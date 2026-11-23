#!/usr/bin/env python3
"""Lower the entity plane with its SysML include roots resolved.

The entity plane (``sos/aircraft_federation.sysml``) imports the real aircraft
architecture (``Aircraft``) and the shared SoS vocabulary (``PysosSoS``).
``pysos-sysml`` deliberately resolves only the roots it is given, so this thin
wrapper supplies them, exactly as ``scripts/sos_model.py`` does for the system
plane, and keeps the lowering command one line.

The lowered artifact is the schema-1 manifest owned by ``pysos_coordinate``.
The aircraft composition itself is not lowered: it is a model-time assertion
that every entity is an ``AircraftModel``, and ``scripts/sos_model.py`` checks
that assertion against the system plane.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import pyfmi_rpr
from pysos_sysml import FederationDef, SysMLError, load_federation, manifest_json
from pysos_sysml.manifest import check
from pyssp_sysml_definitions import core_definitions

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

DEFAULT_MODEL = REPO_ROOT / "sos" / "aircraft_federation.sysml"
DEFAULT_MANIFEST = REPO_ROOT / "manifests" / "aircraft_federation.manifest.json"
AIRCRAFT_ARCHITECTURE = REPO_ROOT / "3rd_party" / "airplane" / "architecture" / "aircraft.sysml"


def include_roots() -> tuple[Path, ...]:
    """Roots the entity plane imports: the aircraft and the shared vocabulary.

    ``pysos_sysml`` always adds its own bundled ``PysosSoS`` root, so only the
    architecture's imports (``PysspCore``, ``RprEntity``) are supplied here.
    """
    return (AIRCRAFT_ARCHITECTURE, core_definitions(), pyfmi_rpr.rpr_entity())


def load_entity_model(path: Path | str = DEFAULT_MODEL) -> FederationDef:
    return load_federation(path, includes=include_roots())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="entity-manifest",
        description="Lower the SoS entity plane, resolving its SysML include roots.",
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=f"write the manifest here (default: stdout; --check defaults to {DEFAULT_MANIFEST.name})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify --output is the current lowering; exit 1 on drift",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.check:
            target = args.output or DEFAULT_MANIFEST
            if check(args.model, target, includes=include_roots()):
                print(f"ok: {target} is up to date")
                return 0
            print(f"drift: {target} is not up to date", file=sys.stderr)
            return 1
        text = manifest_json(load_entity_model(args.model))
    except SysMLError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
