"""ROS 2 bridge runtime for RViz visualization and manual control pass-through."""
from __future__ import annotations

import argparse
import json
import math
import socket
from pathlib import Path

from .common import encode_control_packet, load_local_waypoints, parse_state_packet


def _quaternion_from_euler(roll: float, pitch: float, yaw: float) -> tuple[float, float, float, float]:
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--state-port", type=int, default=5501)
    parser.add_argument("--command-port", type=int, default=5502)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--poll-hz", type=float, default=20.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        import rclpy
        from geometry_msgs.msg import Point, PoseStamped, TransformStamped
        from nav_msgs.msg import Path as PathMsg
        from std_msgs.msg import String
        from tf2_ros import TransformBroadcaster
        from visualization_msgs.msg import Marker, MarkerArray
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(f"ROS 2 Python dependencies are required to run the RViz sidecar: {exc}")

    args = parse_args(argv)
    waypoints = load_local_waypoints(args.scenario)

    rclpy.init(args=None)
    node = rclpy.create_node("test_flight_simulator_ros2_bridge")
    broadcaster = TransformBroadcaster(node)
    pose_pub = node.create_publisher(PoseStamped, "aircraft/pose", 10)
    path_pub = node.create_publisher(PathMsg, "aircraft/path", 10)
    markers_pub = node.create_publisher(MarkerArray, "mission/waypoints", 10)
    status_pub = node.create_publisher(String, "mission/status", 10)

    command_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    state_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    state_socket.bind((args.host, args.state_port))
    state_socket.setblocking(False)

    path_msg = PathMsg()
    path_msg.header.frame_id = "map"

    def publish_static_markers(active_index: int) -> None:
        marker_array = MarkerArray()

        route = Marker()
        route.header.frame_id = "map"
        route.header.stamp = node.get_clock().now().to_msg()
        route.ns = "route"
        route.id = 0
        route.type = Marker.LINE_STRIP
        route.action = Marker.ADD
        route.scale.x = 50.0
        route.color.a = 1.0
        route.color.r = 0.2
        route.color.g = 0.7
        route.color.b = 1.0
        for point in waypoints:
            p = Point()
            p.x = point["x_km"] * 1000.0
            p.y = point["y_km"] * 1000.0
            p.z = point["z_km"] * 1000.0
            route.points.append(p)
        marker_array.markers.append(route)

        for idx, point in enumerate(waypoints):
            marker = Marker()
            marker.header.frame_id = "map"
            marker.header.stamp = route.header.stamp
            marker.ns = "waypoints"
            marker.id = idx + 1
            marker.type = Marker.SPHERE
            marker.action = Marker.ADD
            marker.pose.position.x = point["x_km"] * 1000.0
            marker.pose.position.y = point["y_km"] * 1000.0
            marker.pose.position.z = point["z_km"] * 1000.0
            marker.scale.x = 180.0
            marker.scale.y = 180.0
            marker.scale.z = 180.0
            marker.color.a = 0.95
            if idx + 1 == active_index:
                marker.color.r = 1.0
                marker.color.g = 0.35
                marker.color.b = 0.2
            elif idx + 1 < active_index:
                marker.color.r = 0.4
                marker.color.g = 0.4
                marker.color.b = 0.4
            else:
                marker.color.r = 0.3
                marker.color.g = 0.9
                marker.color.b = 0.4
            marker_array.markers.append(marker)

            label = Marker()
            label.header.frame_id = "map"
            label.header.stamp = route.header.stamp
            label.ns = "waypoint_labels"
            label.id = 1000 + idx
            label.type = Marker.TEXT_VIEW_FACING
            label.action = Marker.ADD
            label.pose.position.x = marker.pose.position.x
            label.pose.position.y = marker.pose.position.y
            label.pose.position.z = marker.pose.position.z + 120.0
            label.scale.z = 120.0
            label.color.a = 1.0
            label.color.r = 1.0
            label.color.g = 1.0
            label.color.b = 1.0
            label.text = f"WP {idx}"
            marker_array.markers.append(label)

        markers_pub.publish(marker_array)

    def command_callback(msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError as exc:
            node.get_logger().warning(f"Ignoring malformed /pilot_command_json payload: {exc}")
            return
        command_socket.sendto(encode_control_packet(payload), (args.host, args.command_port))

    node.create_subscription(String, "pilot_command_json", command_callback, 10)

    latest_active_index = 0
    publish_static_markers(latest_active_index)

    def poll_bridge() -> None:
        nonlocal latest_active_index
        try:
            payload, _ = state_socket.recvfrom(4096)
        except BlockingIOError:
            return

        packet = parse_state_packet(payload.decode("utf-8"))
        latest_active_index = packet["mission_status"]["waypoint_index"]
        publish_static_markers(latest_active_index)

        now = node.get_clock().now().to_msg()
        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = now
        pose.pose.position.x = packet["state_m"]["x"]
        pose.pose.position.y = packet["state_m"]["y"]
        pose.pose.position.z = packet["state_m"]["z"]
        qx, qy, qz, qw = _quaternion_from_euler(
            math.radians(packet["orientation_deg"]["roll"]),
            math.radians(packet["orientation_deg"]["pitch"]),
            math.radians(packet["orientation_deg"]["yaw"]),
        )
        pose.pose.orientation.x = qx
        pose.pose.orientation.y = qy
        pose.pose.orientation.z = qz
        pose.pose.orientation.w = qw
        pose_pub.publish(pose)

        path_msg.header.stamp = now
        path_msg.poses.append(pose)
        path_pub.publish(path_msg)

        transform = TransformStamped()
        transform.header.frame_id = "map"
        transform.child_frame_id = "base_link"
        transform.header.stamp = now
        transform.transform.translation.x = pose.pose.position.x
        transform.transform.translation.y = pose.pose.position.y
        transform.transform.translation.z = pose.pose.position.z
        transform.transform.rotation = pose.pose.orientation
        broadcaster.sendTransform(transform)

        camera = TransformStamped()
        camera.header.frame_id = "base_link"
        camera.child_frame_id = "camera_link"
        camera.header.stamp = now
        camera.transform.translation.x = 25.0
        camera.transform.translation.y = 0.0
        camera.transform.translation.z = 4.0
        camera.transform.rotation.w = 1.0
        broadcaster.sendTransform(camera)

        status = String()
        status.data = json.dumps(packet["mission_status"], separators=(",", ":"))
        status_pub.publish(status)

    node.create_timer(max(1.0 / args.poll_hz, 0.01), poll_bridge)
    try:
        rclpy.spin(node)
    finally:  # pragma: no branch
        state_socket.close()
        command_socket.close()
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
