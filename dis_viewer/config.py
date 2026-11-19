"""Exercise, entity, origin and transport configuration for the DIS viewer."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Tuple

from .model import EntityKey, EntityType


@dataclass(frozen=True)
class Origin:
    """Geodetic origin of the local ENU frame."""

    latitude_deg: float = 0.0
    longitude_deg: float = 0.0
    altitude_m: float = 0.0

    def is_set(self) -> bool:
        return any((self.latitude_deg, self.longitude_deg, self.altitude_m))

    @classmethod
    def from_scenario(cls, path: Path) -> "Origin":
        scenario = json.loads(Path(path).read_text(encoding="utf-8"))
        points = scenario.get("points") or []
        if not points:
            raise ValueError(f"Scenario has no points: {path}")
        first = points[0]
        return cls(
            latitude_deg=float(first["latitude_deg"]),
            longitude_deg=float(first["longitude_deg"]),
            altitude_m=float(first.get("altitude_m", 0.0)),
        )


@dataclass(frozen=True)
class EntityConfig:
    key: EntityKey
    entity_type: EntityType = field(default_factory=EntityType)
    force_id: int = 1
    marking: str = ""

    def resolved_marking(self) -> str:
        return (self.marking or f"AC-{self.key.entity}")[:11]


@dataclass(frozen=True)
class TransportConfig:
    mode: str = "unicast"
    host: str = "127.0.0.1"
    port: int = 3000
    ttl: int = 1
    interface: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("unicast", "multicast"):
            raise ValueError(f"Unknown transport mode: {self.mode}")


@dataclass(frozen=True)
class ExerciseConfig:
    exercise_id: int = 1
    origin: Origin = field(default_factory=Origin)
    entities: Tuple[EntityConfig, ...] = ()
    transport: TransportConfig = field(default_factory=TransportConfig)
    publish_hz: float = 10.0
    heartbeat_s: float = 5.0
    stale_after_s: float = 5.0
    dr_algorithm: int = 4

    def assert_unique_entities(self) -> None:
        keys = [entity.key for entity in self.entities]
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            names = ", ".join(sorted(str(key) for key in duplicates))
            raise ValueError(f"Duplicate entity ids: {names}")


def _exercise_from_dict(data: Dict[str, Any]) -> ExerciseConfig:
    origin_data = data.get("origin") or {}
    transport_data = data.get("transport") or {}
    entities = []
    for item in data.get("entities") or []:
        key_data = item.get("key") or {}
        type_data = item.get("entity_type") or {}
        entities.append(
            EntityConfig(
                key=EntityKey(**key_data),
                entity_type=EntityType(**type_data),
                force_id=int(item.get("force_id", 1)),
                marking=str(item.get("marking", "")),
            )
        )
    config = ExerciseConfig(
        exercise_id=int(data.get("exercise_id", 1)),
        origin=Origin(**origin_data),
        entities=tuple(entities),
        transport=TransportConfig(**transport_data),
        publish_hz=float(data.get("publish_hz", 10.0)),
        heartbeat_s=float(data.get("heartbeat_s", 5.0)),
        stale_after_s=float(data.get("stale_after_s", 5.0)),
        dr_algorithm=int(data.get("dr_algorithm", 4)),
    )
    config.assert_unique_entities()
    return config


def load_exercise(path: Path) -> ExerciseConfig:
    return _exercise_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def save_exercise(path: Path, config: ExerciseConfig) -> None:
    Path(path).write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
