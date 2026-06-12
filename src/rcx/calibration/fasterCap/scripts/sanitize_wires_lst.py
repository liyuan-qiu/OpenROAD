#!/usr/bin/env python3
"""
Sanitize FasterCap wires.lst by removing known crash-triggering dielectric pairs.

General conservative rule (pattern-derived):
- For dielectric entries in the same metal family (e.g., dielectric_m3_*),
  if layer i "top" and layer i+1 "bottom" share the same X/Z span,
  drop the layer i+1 bottom entry.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List, Optional, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sanitize FasterCap wires.lst in place.")
    parser.add_argument("input", help="Input wires.lst path")
    parser.add_argument("--output", help="Output path (default: overwrite input)")
    parser.add_argument("--backup", action="store_true", help="Write <input>.bak before overwrite")
    return parser.parse_args()


def parse_d_line_bbox(line: str) -> Optional[Tuple[float, float, float, float, float, float]]:
    tokens = line.split()
    if len(tokens) < 10 or tokens[0] != "D":
        return None
    try:
        x1, y1, z1, x2, y2, z2 = map(float, tokens[-7:-1])
    except ValueError:
        return None
    xmin, xmax = (x1, x2) if x1 <= x2 else (x2, x1)
    ymin, ymax = (y1, y2) if y1 <= y2 else (y2, y1)
    zmin, zmax = (z1, z2) if z1 <= z2 else (z2, z1)
    return xmin, xmax, ymin, ymax, zmin, zmax


def approx_eq(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def xz_match(a: Tuple[float, float, float, float, float, float], b: Tuple[float, float, float, float, float, float]) -> bool:
    return (
        approx_eq(a[0], b[0])
        and approx_eq(a[1], b[1])
        and approx_eq(a[4], b[4])
        and approx_eq(a[5], b[5])
    )


def main() -> int:
    args = parse_args()
    in_path = Path(args.input).resolve()
    out_path = Path(args.output).resolve() if args.output else in_path
    if not in_path.exists():
        raise SystemExit(f"ERROR: input not found: {in_path}")

    lines = in_path.read_text().splitlines(keepends=True)

    # Indexed as (metal_id, diel_idx, side, line_idx, bbox)
    entries: List[Tuple[int, int, str, int, Tuple[float, float, float, float, float, float]]] = []
    name_re = re.compile(r"Dielectrics/dielectric_m(\d+)_(\d+)_.*-(top|bottom)\.txt")

    for idx, line in enumerate(lines):
        if not line.lstrip().startswith("D "):
            continue
        m = name_re.search(line)
        if not m:
            continue
        bbox = parse_d_line_bbox(line)
        if bbox is None:
            continue
        metal_id = int(m.group(1))
        diel_idx = int(m.group(2))
        side = m.group(3)
        entries.append((metal_id, diel_idx, side, idx, bbox))

    top_entries: List[Tuple[int, int, int, Tuple[float, float, float, float, float, float]]] = []
    bot_entries: List[Tuple[int, int, int, Tuple[float, float, float, float, float, float]]] = []
    for metal_id, diel_idx, side, idx, bbox in entries:
        if side == "top":
            top_entries.append((metal_id, diel_idx, idx, bbox))
        elif side == "bottom":
            bot_entries.append((metal_id, diel_idx, idx, bbox))

    remove_idx = set()
    for b_metal, b_idx, b_line_idx, b_bbox in bot_entries:
        for t_metal, t_idx, _, t_bbox in top_entries:
            same_family_adjacent = b_metal == t_metal and b_idx == t_idx + 1
            cross_family_boundary = b_metal == t_metal + 1 and b_idx == 1
            # Remove duplicated near-coincident interfaces in either:
            # 1) same-metal dielectric stack adjacency (i top vs i+1 bottom),
            # 2) cross-metal boundary (mX top vs m(X+1)_1 bottom).
            if (same_family_adjacent or cross_family_boundary) and xz_match(b_bbox, t_bbox):
                remove_idx.add(b_line_idx)
                break

    sanitized = [line for idx, line in enumerate(lines) if idx not in remove_idx]

    if args.backup and out_path == in_path:
        backup = in_path.with_suffix(in_path.suffix + ".bak")
        backup.write_text("".join(lines))

    out_path.write_text("".join(sanitized))

    print(f"sanitized: removed={len(remove_idx)} kept={len(sanitized)} total={len(lines)}")
    if remove_idx:
        print("rule: drop dielectric bottom entries paired with adjacent top entries on same X/Z span")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
