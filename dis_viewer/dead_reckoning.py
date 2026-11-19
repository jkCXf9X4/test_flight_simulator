"""Dead reckoning re-exported from :mod:`pysos_interop`.

The shared implementation owns DIS algorithms 1 (static), 2 (linear) and 4
(rotating, body-frame velocity) plus the strict staleness predicate.
"""

from __future__ import annotations

from pysos_interop.dead_reckoning import (
    LINEAR,
    ROTATING,
    STATIC,
    SUPPORTED_ALGORITHMS,
    dead_reckon,
    is_stale,
)

__all__ = [
    "LINEAR",
    "ROTATING",
    "STATIC",
    "SUPPORTED_ALGORITHMS",
    "dead_reckon",
    "is_stale",
]
