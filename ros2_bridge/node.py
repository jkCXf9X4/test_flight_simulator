"""ROS 2 bridge runtime for RViz visualization and manual control pass-through."""
from __future__ import annotations

import argparse
import json
import math
import socket
from pathlib import Path

from .common import encode_control_packet, load_local_waypoints, parse_state_packet, resolve_scenario_path


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


def _compute_visual_scales(waypoints: list[dict[str, float]]) -> dict[str, float]:
    target_span_m = 8000.0
    if not waypoints:
        return {
            "mission_span_m": 1000.0,
            "viz_scale": 1.0,
            "route_width_m": 20.0,
            "waypoint_diameter_m": 120.0,
            "label_height_m": 70.0,
            "label_offset_m": 120.0,
            "aircraft_length_m": 180.0,
        }

    xs = [point["x_km"] * 1000.0 for point in waypoints]
    ys = [point["y_km"] * 1000.0 for point in waypoints]
    span_m = max(max(xs) - min(xs), max(ys) - min(ys), 1000.0)
    viz_scale = max(span_m / target_span_m, 1.0)
    route_width_m = 20.0
    waypoint_diameter_m = 120.0
    label_height_m = 70.0
    label_offset_m = waypoint_diameter_m * 0.75
    aircraft_length_m = 180.0

    return {
        "mission_span_m": span_m,
        "viz_scale": viz_scale,
        "route_width_m": route_width_m,
        "waypoint_diameter_m": waypoint_diameter_m,
        "label_height_m": label_height_m,
        "label_offset_m": label_offset_m,
        "aircraft_length_m": aircraft_length_m,
    }


def _scale_position(point_m: dict[str, float], visual_scales: dict[str, float]) -> tuple[float, float, float]:
    scale = visual_scales["viz_scale"]
    return (
        point_m["x"] / scale,
        point_m["y"] / scale,
        point_m["z"] / scale,
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
        from rclpy.executors import ExternalShutdownException
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from geometry_msgs.msg import Point, PoseStamped, TransformStamped
        from nav_msgs.msg import Path as PathMsg
        from std_msgs.msg import String
        from tf2_ros import TransformBroadcaster
        from visualization_msgs.msg import Marker, MarkerArray
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(f"ROS 2 Python dependencies are required to run the RViz sidecar: {exc}")

    args = parse_args(argv)
    args.scenario = resolve_scenario_path(args.scenario)
    waypoints = load_local_waypoints(args.scenario)
    visual_scales = _compute_visual_scales(waypoints)

    rclpy.init(args=None)
    node = rclpy.create_node("test_flight_simulator_ros2_bridge")
    broadcaster = TransformBroadcaster(node)
    latched_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    pose_pub = node.create_publisher(PoseStamped, "aircraft/pose", latched_qos)
    path_pub = node.create_publisher(PathMsg, "aircraft/path", latched_qos)
    markers_pub = node.create_publisher(MarkerArray, "mission/waypoints", latched_qos)
    aircraft_marker_pub = node.create_publisher(Marker, "aircraft/marker", latched_qos)
    status_pub = node.create_publisher(String, "mission/status", latched_qos)

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
        route.scale.x = visual_scales["route_width_m"]
        route.color.a = 1.0
        route.color.r = 0.2
        route.color.g = 0.7
        route.color.b = 1.0
        for point in waypoints:
            p = Point()
            p.x, p.y, p.z = _scale_position(
                {
                    "x": point["x_km"] * 1000.0,
                    "y": point["y_km"] * 1000.0,
                    "z": point["z_km"] * 1000.0,
                },
                visual_scales,
            )
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
            marker.pose.position.x, marker.pose.position.y, marker.pose.position.z = _scale_position(
                {
                    "x": point["x_km"] * 1000.0,
                    "y": point["y_km"] * 1000.0,
                    "z": point["z_km"] * 1000.0,
                },
                visual_scales,
            )
            marker.scale.x = visual_scales["waypoint_diameter_m"]
            marker.scale.y = visual_scales["waypoint_diameter_m"]
            marker.scale.z = visual_scales["waypoint_diameter_m"]
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
            label.pose.position.z = marker.pose.position.z + visual_scales["label_offset_m"]
            label.scale.z = visual_scales["label_height_m"]
            label.color.a = 1.0
            label.color.r = 1.0
            label.color.g = 1.0
            label.color.b = 1.0
            label.text = f"WP {idx}"
            marker_array.markers.append(label)

        markers_pub.publish(marker_array)

    def publish_aircraft_marker(pose: PoseStamped) -> None:
        marker = Marker()
        marker.header.frame_id = "map"
        marker.header.stamp = pose.header.stamp
        marker.ns = "aircraft"
        marker.id = 0
        marker.type = Marker.ARROW
        marker.action = Marker.ADD
        marker.pose = pose.pose
        arrow_length_m = visual_scales["aircraft_length_m"]
        marker.scale.x = arrow_length_m
        marker.scale.y = arrow_length_m * 0.18
        marker.scale.z = arrow_length_m * 0.18
        marker.color.a = 0.95
        marker.color.r = 1.0
        marker.color.g = 0.82
        marker.color.b = 0.15
        aircraft_marker_pub.publish(marker)

    def publish_pose_and_tf(pose: PoseStamped) -> None:
        pose_pub.publish(pose)
        publish_aircraft_marker(pose)

        transform = TransformStamped()
        transform.header.frame_id = "map"
        transform.child_frame_id = "base_link"
        transform.header.stamp = pose.header.stamp
        transform.transform.translation.x = pose.pose.position.x
        transform.transform.translation.y = pose.pose.position.y
        transform.transform.translation.z = pose.pose.position.z
        transform.transform.rotation = pose.pose.orientation
        broadcaster.sendTransform(transform)

        camera = TransformStamped()
        camera.header.frame_id = "base_link"
        camera.child_frame_id = "camera_link"
        camera.header.stamp = pose.header.stamp
        camera.transform.translation.x = 25.0
        camera.transform.translation.y = 0.0
        camera.transform.translation.z = 4.0
        camera.transform.rotation.w = 1.0
        broadcaster.sendTransform(camera)

    def publish_initial_state() -> None:
        now = node.get_clock().now().to_msg()
        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = now
        if waypoints:
            pose.pose.position.x, pose.pose.position.y, pose.pose.position.z = _scale_position(
                {
                    "x": waypoints[0]["x_km"] * 1000.0,
                    "y": waypoints[0]["y_km"] * 1000.0,
                    "z": waypoints[0]["z_km"] * 1000.0,
                },
                visual_scales,
            )
        pose.pose.orientation.w = 1.0
        publish_pose_and_tf(pose)

        path_msg.header.stamp = now
        path_msg.poses = [pose]
        path_pub.publish(path_msg)

        status = String()
        status.data = json.dumps(
            {
                "waypoint_index": 0,
                "total_waypoints": max(len(waypoints) - 1, 0),
                "distance_to_waypoint_km": 0.0,
                "arrived": False,
                "complete": False,
            },
            separators=(",", ":"),
        )
        status_pub.publish(status)

    def command_callback(msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError as exc:
            node.get_logger().warning(f"Ignoring malformed /pilot_command_json payload: {exc}")
            return
        command_socket.sendto(encode_control_packet(payload), (args.host, args.command_port))

    node.create_subscription(String, "pilot_command_json", command_callback, 10)

    latest_active_index = 0
    latest_pose: PoseStamped | None = None
    latest_status_payload = {
        "waypoint_index": 0,
        "total_waypoints": max(len(waypoints) - 1, 0),
        "distance_to_waypoint_km": 0.0,
        "arrived": False,
        "complete": False,
    }
    publish_static_markers(latest_active_index)
    publish_initial_state()
    if path_msg.poses:
        latest_pose = path_msg.poses[-1]

    def republish_static_state() -> None:
        publish_static_markers(latest_active_index)
        if latest_pose is not None:
            publish_pose_and_tf(latest_pose)
            path_msg.header.stamp = node.get_clock().now().to_msg()
            path_pub.publish(path_msg)
        status = String()
        status.data = json.dumps(latest_status_payload, separators=(",", ":"))
        status_pub.publish(status)

    def poll_bridge() -> None:
        nonlocal latest_active_index, latest_pose, latest_status_payload
        try:
            payload, _ = state_socket.recvfrom(4096)
        except BlockingIOError:
            return

        packet = parse_state_packet(payload.decode("utf-8"))
        latest_active_index = packet["mission_status"]["waypoint_index"]
        latest_status_payload = packet["mission_status"]
        publish_static_markers(latest_active_index)

        now = node.get_clock().now().to_msg()
        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = now
        pose.pose.position.x, pose.pose.position.y, pose.pose.position.z = _scale_position(packet["state_m"], visual_scales)
        qx, qy, qz, qw = _quaternion_from_euler(
            math.radians(packet["orientation_deg"]["roll"]),
            math.radians(packet["orientation_deg"]["pitch"]),
            math.radians(packet["orientation_deg"]["yaw"]),
        )
        pose.pose.orientation.x = qx
        pose.pose.orientation.y = qy
        pose.pose.orientation.z = qz
        pose.pose.orientation.w = qw
        latest_pose = pose
        publish_pose_and_tf(pose)

        path_msg.header.stamp = now
        path_msg.poses.append(pose)
        path_pub.publish(path_msg)

        status = String()
        status.data = json.dumps(latest_status_payload, separators=(",", ":"))
        status_pub.publish(status)

    node.create_timer(max(1.0 / args.poll_hz, 0.01), poll_bridge)
    node.create_timer(1.0, republish_static_state)
    try:
        rclpy.spin(node)
    except ExternalShutdownException:
        pass
    finally:  # pragma: no branch
        state_socket.close()
        command_socket.close()
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
