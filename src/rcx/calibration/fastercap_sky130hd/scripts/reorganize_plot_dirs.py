#!/usr/bin/env python3
"""Move flat plot PNGs into Over / Under / OverUnder / DIAGUNDER subfolders."""

from __future__ import annotations

import argparse
import shutil
from collections import Counter
from pathlib import Path

from plot_rcx_model_vs_rules import classify_plot_filename


def reorganize(mode_dir: Path, dry_run: bool = False) -> Counter:
    counts: Counter = Counter()
    for png in sorted(mode_dir.glob("*.png")):
        sub = classify_plot_filename(png.name)
        dest_dir = mode_dir / sub
        dest = dest_dir / png.name
        if dest.exists() and dest.resolve() == png.resolve():
            continue
        counts[sub] += 1
        if dry_run:
            print(f"  {png.name} -> {sub}/")
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(png), str(dest))
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description="Organize plot PNGs by pattern family.")
    ap.add_argument(
        "plot_root",
        help="Directory containing strict/ and/or multiwidth/ (or a single mode dir)",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.plot_root)
    mode_dirs = []
    for name in ("strict", "multiwidth"):
        d = root / name
        if d.is_dir():
            mode_dirs.append(d)
    if not mode_dirs and any(root.glob("*.png")):
        mode_dirs = [root]

    if not mode_dirs:
        raise SystemExit(f"No plot mode dirs under {root}")

    for mode_dir in mode_dirs:
        print(f"==> {mode_dir}")
        counts = reorganize(mode_dir, dry_run=args.dry_run)
        for sub, n in sorted(counts.items()):
            print(f"    {sub}: {n}")


if __name__ == "__main__":
    main()
