#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from stems_injector_core import build_sidecar, report_to_json


def main() -> int:
    p = argparse.ArgumentParser(description="Build Serato sidecar from stem MP3 files")
    p.add_argument("--base", required=True, help="Base audio file")
    p.add_argument("--vocals", required=True)
    p.add_argument("--bass")
    p.add_argument("--drums")
    p.add_argument("--melody")
    p.add_argument("--instrumental", help="Two-stem mode: maps to drums; bass+melody muted")
    p.add_argument(
        "--two-stem-strategy",
        choices=["compat", "mute"],
        default="compat",
        help="Two-stem behavior: compat=avoid Serato regen, mute=attempt inaudible bass/melody",
    )
    args = p.parse_args()

    two = args.instrumental is not None
    if two:
        if args.bass or args.drums or args.melody:
            raise SystemExit("In two-stem mode, provide only --vocals and --instrumental")
    else:
        if not (args.bass and args.drums and args.melody):
            raise SystemExit("In four-stem mode, provide --vocals --bass --drums --melody")

    report = build_sidecar(
        base_audio=Path(args.base),
        vocals=Path(args.vocals),
        bass=Path(args.bass) if args.bass else None,
        drums=Path(args.drums) if args.drums else None,
        melody=Path(args.melody) if args.melody else None,
        instrumental=Path(args.instrumental) if args.instrumental else None,
        two_stem_strategy=args.two_stem_strategy,
    )
    print(report_to_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
