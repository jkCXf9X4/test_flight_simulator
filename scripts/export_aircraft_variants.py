#!/usr/bin/env python3
"""Export one aircraft SSP per participant variant from the SysML model.

Each variant in ``sos/aircraft_federation.sysml`` is a composition root that
inherits the shared ``AircraftModel`` graph. This script resolves that model's
import roots, builds the variant SSP with ``pyssp_sysml2.generate_ssp``, and
checks that the archive really carries the SSD and its parameter sets before
reporting success.

The output is one archive per variant, so downstream steps select a variant by
path instead of injecting its parameters into ``command`` argv::

    build/ssp/variants/<Variant>.ssp

Use ``--allow-missing-fmus`` while the built FMUs are not yet available. A
missing declared FMU still yields a design archive, but ``--no-validate-fmus``
additionally skips the interface check against ``modelDescription.xml``.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

import pyfmi_rpr
import pysos_sysml
import pyssp_sysml2
from pyssp_sysml_definitions import core_definitions

REPO_ROOT = Path(__file__).resolve().parents[1]
PARTICIPANTS_MODEL = REPO_ROOT / "sos" / "aircraft_federation.sysml"
AIRPLANE_ROOT = REPO_ROOT / "3rd_party" / "airplane"
AIRCRAFT_ARCHITECTURE = AIRPLANE_ROOT / "architecture" / "aircraft.sysml"
DEFAULT_VARIANTS = ("RedInterceptor", "RedStriker", "BlueCas", "BlueBaseline")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / "ssp" / "variants"
DEFAULT_STAGE_DIR = DEFAULT_OUTPUT_DIR / ".fmu-root"
SSD_ENTRY = "SystemStructure.ssd"
PARAMETER_SET_PREFIX = "resources/parameter_sets/"
#: ``pyssp_sysml2`` indexes array parameters from zero by default; the built
#: FMUs expose ``waypointX_km[1..10]``, so the export must match them.
PARAMETER_BASE_INDEX = 1


class ExportError(RuntimeError):
    """A variant SSP was not produced or is missing required entries."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--variant",
        action="append",
        dest="variants",
        metavar="NAME",
        help=(
            "variant composition to export; repeat for several "
            f"(default: {', '.join(DEFAULT_VARIANTS)})"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"directory for the per-variant archives (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--fmu-root",
        type=Path,
        default=None,
        help=(
            "root for relative fmu_meta.source paths; by default a staged root "
            "under build/ssp/variants/.fmu-root resolves both "
            "build/fmus/<Name>.fmu and the bare RprEntity.fmu source"
        ),
    )
    parser.add_argument(
        "--allow-missing-fmus",
        action="store_true",
        help="export a declared FMU that is absent instead of failing",
    )
    parser.add_argument(
        "--no-validate-fmus",
        action="store_true",
        help="skip the modelDescription.xml interface check",
    )
    return parser.parse_args(argv)


def resolve_path(path: Path) -> Path:
    """Resolve a repo-relative CLI path against the repository root."""
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def stage_fmu_root(
    airplane_root: Path = AIRPLANE_ROOT,
    stage_dir: Path = DEFAULT_STAGE_DIR,
) -> Path:
    """Build one root that satisfies every ``fmu_meta.source`` in the model.

    The airplane components name ``build/fmus/<Name>.fmu``, while ``pyfmi_rpr``
    owns the bare ``RprEntity.fmu`` source (see its example contract). Keeping
    those paths unchanged, the staged root links ``build/`` to the airplane
    build tree and exposes every built FMU by basename.
    """
    fmu_dir = airplane_root / "build" / "fmus"
    if not fmu_dir.is_dir():
        raise ExportError(f"{fmu_dir}: built FMU directory does not exist")

    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    (stage_dir / "build").symlink_to(airplane_root / "build", target_is_directory=True)

    built = sorted(fmu_dir.glob("*.fmu"))
    if not built:
        raise ExportError(f"{fmu_dir}: no *.fmu files")
    for fmu in built:
        (stage_dir / fmu.name).symlink_to(fmu)
    return stage_dir


def resolve_includes() -> tuple[Path, ...]:
    """Import roots required by ``sos/aircraft_federation.sysml``."""
    return (
        AIRCRAFT_ARCHITECTURE,
        core_definitions(),
        pyfmi_rpr.rpr_entity(),
        pysos_sysml.sos_definitions(),
    )


def count_parameter_sets(archive: Path) -> int:
    """Verify *archive* is a complete SSP and return its parameter-set count."""
    try:
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise ExportError(f"{archive}: not a readable SSP archive: {exc}") from exc

    if SSD_ENTRY not in names:
        raise ExportError(f"{archive}: missing {SSD_ENTRY}")

    parameter_sets = [
        name
        for name in names
        if name.startswith(PARAMETER_SET_PREFIX) and name.endswith(".ssv")
    ]
    if not parameter_sets:
        raise ExportError(f"{archive}: no {PARAMETER_SET_PREFIX}*.ssv parameter sets")
    return len(parameter_sets)


def export_variant(variant: str, args: argparse.Namespace) -> Path:
    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{variant}.ssp"
    fmu_root = resolve_path(args.fmu_root) if args.fmu_root else stage_fmu_root()

    pyssp_sysml2.generate_ssp(
        PARTICIPANTS_MODEL,
        output,
        variant,
        includes=resolve_includes(),
        fmu_root=fmu_root,
        validate_fmus=not args.no_validate_fmus,
        allow_missing_fmus=args.allow_missing_fmus,
        base_index=PARAMETER_BASE_INDEX,
    )
    return output


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    variants = list(args.variants) if args.variants else list(DEFAULT_VARIANTS)

    failed = False
    for variant in variants:
        try:
            output = export_variant(variant, args)
            parameter_sets = count_parameter_sets(output)
        except Exception as exc:  # noqa: BLE001 - one report line per variant
            print(f"export failed for {variant}: {exc}", file=sys.stderr)
            failed = True
            continue
        print(
            f"exported {variant} -> {output} ({parameter_sets} parameter sets)",
            flush=True,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
