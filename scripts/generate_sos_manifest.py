#!/usr/bin/env python3
"""Generate (or check) the checked-in aircraft federation manifest.

The manifest is a build artifact of ``sos/aircraft_federation.sysml``, not a
hand-maintained file. Regenerate it after changing the federation::

    venv/bin/python scripts/generate_sos_manifest.py

``--check`` exits non-zero when the checked-in file no longer matches what
``pysos-sysml manifest`` would write, which is how the test suite keeps it
honest.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

from pysos_sysml import load_federation, manifest_json

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "sos" / "aircraft_federation.sysml"
DEFAULT_MANIFEST = REPO_ROOT / "manifests" / "aircraft_federation.manifest.json"


def render(source: Path = DEFAULT_SOURCE) -> str:
    """Return the schema-1 manifest text lowered from *source*."""
    return manifest_json(load_federation(source))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Authored federation .sysml file.")
    parser.add_argument("--out", type=Path, default=DEFAULT_MANIFEST, help="Manifest path to write or check.")
    parser.add_argument("--check", action="store_true", help="Fail when --out differs from the generated manifest.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    expected = render(args.source)
    if args.check:
        try:
            actual = args.out.read_text(encoding="utf-8")
        except OSError:
            actual = None
        if actual != expected:
            print(f"stale: {args.out} (regenerate with scripts/generate_sos_manifest.py)", file=sys.stderr)
            if actual is not None:
                diff = difflib.unified_diff(
                    actual.splitlines(keepends=True),
                    expected.splitlines(keepends=True),
                    fromfile=f"{args.out} (checked in)",
                    tofile=f"{args.source} lowering",
                )
                sys.stderr.writelines(list(diff)[:20])
            return 1
        print(f"ok: {args.out} is up to date")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(expected, encoding="utf-8")
    print(f"wrote {args.out} (from {args.source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
