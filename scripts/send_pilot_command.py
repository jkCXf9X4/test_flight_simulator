#!/usr/bin/env python3
"""Manual pilot input shim for the ROS-free stack.

Sends newline-delimited JSON control packets to the bridge FMU's UDP command
port (default 127.0.0.1:5502), replacing the earlier command subscription. The
packet encoder is reused from ``bridge_contract.common.encode_control_packet``;
that module is pure Python.

Interactive stdin (TTY) accepts one update per line, either ``key=value`` tokens
using the flag names below or a raw JSON object with the packet field names.
Without a TTY, piped lines are applied one per send tick; with no piped lines
the flag values are sent once.
"""

from __future__ import annotations

import argparse
import json
import queue
import shlex
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bridge_contract.common import encode_control_packet  # noqa: E402

ALIASES = {
    "pitch": "stick_pitch_norm",
    "roll": "stick_roll_norm",
    "rudder": "rudder_norm",
    "throttle": "throttle_norm",
    "mode": "mode_switch",
}
FLOAT_FIELDS = {
    "stick_pitch_norm",
    "stick_roll_norm",
    "rudder_norm",
    "throttle_norm",
    "throttle_aux_norm",
}
INT_FIELDS = {"button_mask", "hat_x", "hat_y", "mode_switch", "reserved"}
UNIT_FIELDS = {"stick_pitch_norm", "stick_roll_norm", "rudder_norm"}
THROTTLE_FIELDS = {"throttle_norm", "throttle_aux_norm"}


def _normalise(raw: Dict[str, Any]) -> Dict[str, Any]:
    update: Dict[str, Any] = {}
    for name, value in raw.items():
        field = ALIASES.get(name, name)
        if field in FLOAT_FIELDS:
            number = float(value)
            if field in UNIT_FIELDS and not -1.0 <= number <= 1.0:
                raise ValueError(f"{name} must be in [-1, 1], got {number}")
            if field in THROTTLE_FIELDS and not 0.0 <= number <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {number}")
            update[field] = number
        elif field in INT_FIELDS:
            number = int(value)
            if number < 0:
                raise ValueError(f"{name} must be >= 0, got {number}")
            update[field] = number
        else:
            raise ValueError(f"unknown field {name!r}")
    return update


def parse_update(text: str) -> Dict[str, Any]:
    """Parse one stdin line into a partial control packet."""

    text = text.strip()
    if not text or text.startswith("#"):
        return {}
    if text.startswith("{"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("JSON input must be an object")
        return _normalise(data)
    pairs: Dict[str, str] = {}
    for token in shlex.split(text):
        key, separator, value = token.partition("=")
        if not separator:
            raise ValueError(f"expected key=value, got {token!r}")
        pairs[key] = value
    return _normalise(pairs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send manual pilot control packets to the bridge UDP command port.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5502)
    parser.add_argument("--pitch", type=float, default=0.0, help="stick_pitch_norm, [-1, 1]")
    parser.add_argument("--roll", type=float, default=0.0, help="stick_roll_norm, [-1, 1]")
    parser.add_argument("--rudder", type=float, default=0.0, help="rudder_norm, [-1, 1]")
    parser.add_argument("--throttle", type=float, default=0.6, help="throttle_norm, [0, 1]")
    parser.add_argument("--mode", type=int, default=0, help="mode_switch")
    parser.add_argument("--rate-hz", type=float, default=10.0, help="send rate, default 10")
    parser.add_argument("--duration", type=float, default=0.0, help="seconds, 0 = until Ctrl-C/EOF")
    return parser


def _read_stdin(updates: "queue.Queue[Dict[str, Any]]", eof: threading.Event) -> None:
    try:
        for line in sys.stdin:
            try:
                update = parse_update(line)
            except (ValueError, json.JSONDecodeError) as exc:
                print(f"input ignored: {exc}", file=sys.stderr)
                continue
            if update:
                updates.put(update)
    finally:
        eof.set()


def _read_piped_stdin() -> Tuple[list, bool]:
    updates = []
    for line in sys.stdin:
        try:
            update = parse_update(line)
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"input ignored: {exc}", file=sys.stderr)
            continue
        if update:
            updates.append(update)
    return updates, True


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.rate_hz <= 0.0:
        print("--rate-hz must be positive", file=sys.stderr)
        return 2
    if args.duration < 0.0:
        print("--duration must be >= 0", file=sys.stderr)
        return 2

    try:
        command = _normalise(
            {
                "pitch": args.pitch,
                "roll": args.roll,
                "rudder": args.rudder,
                "throttle": args.throttle,
                "mode": args.mode,
            }
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    interactive = sys.stdin.isatty()
    updates: "queue.Queue[Dict[str, Any]]" = queue.Queue()
    eof = threading.Event()
    piped: list = []

    if interactive:
        print(
            "Interactive pilot input. Lines: pitch= roll= rudder= throttle= mode= (or JSON). "
            "Ctrl-D or Ctrl-C to stop.",
            file=sys.stderr,
        )
        threading.Thread(target=_read_stdin, args=(updates, eof), daemon=True).start()
    else:
        piped, _ = _read_piped_stdin()
        for update in piped:
            updates.put(update)
        eof.set()

    period = 1.0 / args.rate_hz
    started = time.monotonic()
    deadline = started + args.duration if args.duration > 0.0 else None
    sent = 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break
            try:
                update = updates.get_nowait()
            except queue.Empty:
                update = None
            if update:
                command.update(update)
            sock.sendto(encode_control_packet(command), (args.host, args.port))
            sent += 1
            if eof.is_set() and updates.empty():
                break
            target = started + sent * period
            delay = target - time.monotonic()
            if delay > 0.0:
                time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()

    print(f"sent {sent} control packets to {args.host}:{args.port}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
