"""Neutral entity state shared by DIS sources, sinks and the viewer."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Tuple

Vec3 = Tuple[float, float, float]

PLATFORM_KIND = 1
AIR_DOMAIN = 2


@dataclass(frozen=True, order=True)
class EntityKey:
    """DIS entity identity: site, application, entity (16-bit each)."""

    site: int = 1
    application: int = 1
    entity: int = 1

    @property
    def slug(self) -> str:
        return f"{self.site}_{self.application}_{self.entity}"

    def __str__(self) -> str:
        return f"{self.site}:{self.application}:{self.entity}"


@dataclass(frozen=True)
class EntityType:
    """DIS entity type, seven fields in wire order."""

    kind: int = PLATFORM_KIND
    domain: int = AIR_DOMAIN
    country: int = 0
    category: int = 1
    subcategory: int = 0
    specific: int = 0
    extra: int = 0

    def as_tuple(self) -> Tuple[int, int, int, int, int, int, int]:
        return (
            self.kind,
            self.domain,
            self.country,
            self.category,
            self.subcategory,
            self.specific,
            self.extra,
        )


@dataclass
class EntityState:
    """Viewer-side entity state in local ENU metres.

    ``orientation_deg`` is ``(roll, pitch, yaw)`` in degrees.
    ``angular_velocity_rps`` is the rate of change of those roll/pitch/yaw Euler
    angles in radians per second.  It is a local-frame approximation: each rate
    is applied to its own Euler angle rather than composed as an exact
    body-frame rotation, which is adequate for the small angles seen between
    telemetry packets.
    """

    key: EntityKey
    t_s: float
    position_enu_m: Vec3 = (0.0, 0.0, 0.0)
    orientation_deg: Vec3 = (0.0, 0.0, 0.0)
    velocity_enu_mps: Vec3 = (0.0, 0.0, 0.0)
    angular_velocity_rps: Vec3 = (0.0, 0.0, 0.0)
    entity_type: EntityType = field(default_factory=EntityType)
    force_id: int = 1
    marking: str = ""
    stale: bool = False

    def copy_with(self, **changes) -> "EntityState":
        return replace(self, **changes)
