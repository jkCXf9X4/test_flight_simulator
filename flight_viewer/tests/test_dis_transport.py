"""UDP transport tests: unicast always, multicast opt-in."""

from __future__ import annotations

import os
import socket

import pytest

from flight_viewer.config import TransportConfig
from flight_viewer.transport import open_channel


def free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def test_unicast_loopback_round_trip():
    port = free_udp_port()
    receiver = open_channel(
        TransportConfig(mode="unicast", host="127.0.0.1", port=port),
        receive=True,
    )
    sender = open_channel(
        TransportConfig(mode="unicast", host="127.0.0.1", port=port),
        receive=False,
    )
    try:
        payload = b"\x07\x01\x01\x01entity-state-test"
        assert sender.send(payload) == len(payload)
        assert receiver.receive(2.0) == payload
        assert receiver.receive(0.05) is None
    finally:
        sender.close()
        receiver.close()


@pytest.mark.network
@pytest.mark.skipif(
    os.environ.get("DIS_NETWORK_TESTS") != "1",
    reason="set DIS_NETWORK_TESTS=1 to run multicast tests",
)
def test_multicast_loopback_round_trip():
    group = "239.255.42.99"
    port = free_udp_port()
    cfg = TransportConfig(mode="multicast", host=group, port=port, ttl=1)
    receiver = open_channel(cfg, receive=True)
    sender = open_channel(cfg, receive=False)
    try:
        payload = b"multicast-entity-state"
        assert sender.send(payload) == len(payload)
        assert receiver.receive(2.0) == payload
    finally:
        sender.close()
        receiver.close()
