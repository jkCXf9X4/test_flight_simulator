"""Per-sample fan-in barrier for the RPR recorder.

RPR carries no timestamp, so every publisher slug owns an independent ordinal
sequence and the recorder stamps sample ``n`` at ``n * sample_period_s``. A
sample is complete only when every expected slug has contributed its ordinal
``n``. If one publisher disappears the barrier must not hold the recording
hostage, so a watchdog flushes the oldest partial sample once it has waited
longer than ``watchdog_s``; entities that never arrived are simply absent, and
the CSV export renders their channels as ``nan``.

The class owns no sockets and no file format: it takes decoded states and a
``write_sample`` callback, which keeps the watchdog testable with a fake clock.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any

DEFAULT_WATCHDOG_S = 2.0


class SampleFanIn:
    """Barrier that flushes complete samples and times out partial ones."""

    def __init__(
        self,
        expected_slugs: Iterable[str],
        write_sample: Callable[[list[Any]], None],
        *,
        sample_period_s: float = 0.1,
        watchdog_s: float = DEFAULT_WATCHDOG_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.expected_slugs = tuple(sorted(set(expected_slugs)))
        self.write_sample = write_sample
        self.sample_period_s = float(sample_period_s)
        self.watchdog_s = float(watchdog_s)
        self.clock = clock
        self.ordinals: dict[str, int] = defaultdict(int)
        self.pending: dict[float, dict[str, Any]] = {}
        self._pending_since: dict[float, float] = {}
        self.samples = 0
        self.complete_samples = 0
        self.partial_samples = 0
        self.flushed_ordinals: list[float] = []

    def observe(self, slug: str, state: Any) -> None:
        """Record one decoded state for *slug* and flush whatever is ready."""

        ordinal = self.ordinals[slug]
        self.ordinals[slug] = ordinal + 1
        timestamp = ordinal * self.sample_period_s
        self.pending.setdefault(timestamp, {})[slug] = state
        self._pending_since.setdefault(timestamp, self.clock())
        self._flush_ready()

    def poll(self) -> None:
        """Apply the watchdog without a new frame (called on receiver timeouts)."""

        self._flush_ready()

    def flush(self) -> None:
        """Flush every remaining sample, complete or partial (end of stream)."""

        self._flush_ready(force=True)

    def _flush_ready(self, *, force: bool = False) -> None:
        while self.pending:
            timestamp = min(self.pending)
            batch = self.pending[timestamp]
            complete = all(slug in batch for slug in self.expected_slugs)
            age = self.clock() - self._pending_since.get(timestamp, self.clock())
            if not force and not complete and age <= self.watchdog_s:
                return
            self.pending.pop(timestamp)
            self._pending_since.pop(timestamp, None)
            ordered = [batch[slug] for slug in self.expected_slugs if slug in batch]
            if not ordered:
                continue
            self.write_sample(ordered)
            self.samples += 1
            self.flushed_ordinals.append(timestamp)
            if complete:
                self.complete_samples += 1
            else:
                self.partial_samples += 1
