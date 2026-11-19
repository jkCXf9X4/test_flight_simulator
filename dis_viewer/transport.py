"""UDP transport for DIS datagrams (unicast and multicast)."""

from __future__ import annotations

import socket
import struct
from typing import Protocol, runtime_checkable

from .config import TransportConfig


@runtime_checkable
class Channel(Protocol):
    def send(self, data: bytes) -> int:
        """Send one datagram and return the number of bytes sent."""

    def receive(self, timeout: float | None) -> bytes | None:
        """Receive one datagram, returning ``None`` on timeout."""

    def close(self) -> None:
        """Release the underlying socket."""


SIOCGIFADDR = 0x8915


def _interface_address(interface: str) -> str:
    """Resolve a configured interface name or address to an IPv4 address."""

    try:
        socket.inet_aton(interface)
        return interface
    except OSError:
        pass

    try:
        socket.if_nametoindex(interface)
    except OSError:
        pass
    else:
        try:
            import fcntl

            request = struct.pack("256s", interface.encode("ascii")[:15])
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                response = fcntl.ioctl(sock.fileno(), SIOCGIFADDR, request)
            return socket.inet_ntoa(response[20:24])
        except (OSError, ImportError, UnicodeEncodeError) as exc:
            raise OSError(
                f"Cannot determine the address of multicast interface {interface!r}"
            ) from exc

    try:
        return socket.gethostbyname(interface)
    except OSError as exc:
        raise OSError(f"Cannot resolve multicast interface {interface!r}") from exc


class UdpChannel:
    """A single bound/unbound UDP socket implementing :class:`Channel`."""

    def __init__(self, cfg: TransportConfig, *, receive: bool) -> None:
        self.cfg = cfg
        self.receiving = receive
        self._socket: socket.socket | None = None
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if cfg.mode == "multicast":
                self._configure_multicast(sock, receive)
            elif receive:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind((cfg.host, cfg.port))
                except OSError as exc:
                    raise OSError(
                        f"Failed to bind unicast channel to "
                        f"{cfg.host}:{cfg.port}: {exc}"
                    ) from exc
            self._socket = sock
        except OSError:
            sock.close()
            raise
        except BaseException:
            sock.close()
            raise

    def _configure_multicast(self, sock: socket.socket, receive: bool) -> None:
        cfg = self.cfg
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, int(cfg.ttl))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        except OSError as exc:
            raise OSError(
                f"Failed to configure multicast options for {cfg.host}:{cfg.port}: "
                f"{exc}"
            ) from exc

        interface_address = "0.0.0.0"
        if cfg.interface:
            try:
                interface_address = _interface_address(cfg.interface)
            except OSError as exc:
                raise OSError(
                    f"Failed to resolve multicast interface {cfg.interface!r}: {exc}"
                ) from exc
            try:
                sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_MULTICAST_IF,
                    socket.inet_aton(interface_address),
                )
            except OSError as exc:
                raise OSError(
                    f"Failed to set multicast interface {cfg.interface!r}: {exc}"
                ) from exc

        if not receive:
            return

        try:
            sock.bind(("", cfg.port))
        except OSError as exc:
            raise OSError(
                f"Failed to bind multicast channel to port {cfg.port}: {exc}"
            ) from exc

        membership = struct.pack(
            "4s4s",
            socket.inet_aton(cfg.host),
            socket.inet_aton(interface_address),
        )
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        except OSError as exc:
            raise OSError(
                f"Failed to join multicast group {cfg.host} on "
                f"{cfg.interface or 'default interface'}: {exc}"
            ) from exc

    @property
    def local_address(self) -> tuple[str, int] | None:
        if self._socket is None:
            return None
        return self._socket.getsockname()

    @property
    def local_port(self) -> int | None:
        address = self.local_address
        return address[1] if address else None

    def send(self, data: bytes) -> int:
        if self._socket is None:
            raise OSError("Channel is closed")
        return self._socket.sendto(bytes(data), (self.cfg.host, self.cfg.port))

    def receive(self, timeout: float | None) -> bytes | None:
        if self._socket is None:
            raise OSError("Channel is closed")
        self._socket.settimeout(timeout)
        try:
            data, _ = self._socket.recvfrom(65535)
            return data
        except (socket.timeout, BlockingIOError, TimeoutError):
            return None

    def close(self) -> None:
        sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()


def open_channel(cfg: TransportConfig, *, receive: bool) -> Channel:
    """Open a unicast or multicast UDP channel following ``cfg``."""

    return UdpChannel(cfg, receive=receive)
