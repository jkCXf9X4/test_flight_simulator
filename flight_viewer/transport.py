"""UDP transport adapter over :class:`pysos_interop.transport.Channel`.

Socket handling, multicast membership and interface resolution live in the
shared transport.  This module only maps the project ``TransportConfig`` and
the viewer's ``receive`` convention (``None`` on timeout) onto it.
"""

from __future__ import annotations

from pysos_interop.transport import (
    Channel,
    ChannelClosedError,
    ChannelTimeoutError,
    TransportError,
)

from .config import TransportConfig

__all__ = [
    "Channel",
    "ChannelClosedError",
    "ChannelTimeoutError",
    "TransportError",
    "UdpChannel",
    "open_channel",
]


class UdpChannel:
    """A single UDP socket implementing the viewer's channel convention."""

    def __init__(self, cfg: TransportConfig, *, receive: bool) -> None:
        self.cfg = cfg
        self.receiving = receive
        self._channel = Channel(
            cfg.host,
            cfg.port,
            multicast=(cfg.mode == "multicast"),
            bind=receive,
            ttl=cfg.ttl,
            interface=cfg.interface,
        ).open()

    @property
    def local_address(self) -> tuple[str, int] | None:
        sock = getattr(self._channel, "_socket", None)
        return sock.getsockname() if sock is not None else None

    @property
    def local_port(self) -> int | None:
        address = self.local_address
        return address[1] if address else None

    def send(self, data: bytes) -> int:
        return self._channel.send(data)

    def receive(self, timeout: float | None) -> bytes | None:
        try:
            return self._channel.recv(timeout)
        except ChannelTimeoutError:
            return None

    def close(self) -> None:
        self._channel.close()


def open_channel(cfg: TransportConfig, *, receive: bool) -> Channel:
    """Open a unicast or multicast UDP channel following ``cfg``."""

    return UdpChannel(cfg, receive=receive)
