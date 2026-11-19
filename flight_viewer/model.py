"""Neutral entity vocabulary, re-exported from :mod:`pysos_interop`.

The shared model owns ``EntityKey`` and ``EntityState``.  ``EntityState`` is
frozen and carries Z-Y-X Euler attitude in radians plus body-frame angular
velocity, so no project-local entity model remains.
"""

from __future__ import annotations

from pysos_interop.model import EntityKey, EntityState, Vec3

__all__ = ["EntityKey", "EntityState", "Vec3"]
