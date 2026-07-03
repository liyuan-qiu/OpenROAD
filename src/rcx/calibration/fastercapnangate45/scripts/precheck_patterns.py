#!/usr/bin/env python3
"""
Pre-run geometry precheck for FasterCap calibration patterns.

What this script does:
1) Enumerate pattern cases under <run_dir>/<corner>/... that contain "wires".
2) Generate/refresh wires.lst using UniversalFormat2FasterCap_923.py.
3) Scan wires.lst for potential pathological dielectric interface pairs:
   - same-metal adjacency: mX_i_top vs mX_(i+1)_bottom
   - cross-metal boundary: mX_*_top vs m(X+1)_1_bottom
   where X/Z spans overlap (within tolerance).
4) Emit a CSV report with per-case risk markers.

This is intended as a lightweight pre-screen before launching large batch runs.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class DEntry:
    metal_id: int
    diel_idx: int
    side: str
    bbox: Tuple[float, float, float, float, float, float]
    raw: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Precheck FasterCap pattern geometries before batch solve."
    )
    parser.add_argument(
        "--run-dir",
        default="5v2_typ",
        help="Pattern root directory (default: 5v2_typ)",
    )
    parser.add_argument(
        "--corner",
        default="TYP",
        help="Corner subdirectory under run-dir (default: TYP)",
    )
    parser.add_argument(
        "--converter",
        default="scripts/UniversalFormat2FasterCap_923.py",
        help="Path to converter script",
    )
    parser.add_argument(
        "--process-out",
        default=None,
        help="Path to process.out (default: <run-dir>/process.out)",
    )
    parser.add_argument(
        "--std-normal",
        default="standard",
        choices=["standard", "normalized"],
        help="Converter mode (default: standard)",
    )
    parser.add_argument(
        "--ext",
        type=float,
        default=20.0,
        help="Simulation window extension value for x/y (default: 20)",
    )
    parser.add_argument(
        "--z-ext",
        type=float,
        default=0.0,
        help="Simulation window extension value for z (default: 0)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1e-9,
        help="Coordinate compare tolerance (default: 1e-9)",
    )
    parser.add_argument(
        "--output-csv",
        default="precheck_pathology_report.csv",
        help="Output CSV path (default: precheck_pathology_report.csv)",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=0,
        help="Limit number of cases for quick dry run (0 means all)",
    )
    return parser.parse_args()


def approx_eq(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def xz_match(
    a: Tuple[float, float, float, float, float, float],
    b: Tuple[float, float, float, float, float, float],
    tol: float,
) -> bool:
    # bbox is (xmin, xmax, ymin, ymax, zmin, zmax)
    return (
        approx_eq(a[0], b[0], tol)
        and approx_eq(a[1], b[1], tol)
        and approx_eq(a[4], b[4], tol)
        and approx_eq(a[5], b[5], tol)
    )


def parse_d_bbox(line: str) -> Optional[Tuple[float, float, float, float, float, float]]:
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


def find_case_dirs(run_dir: Path, corner: str) -> List[Path]:
    corner_dir = run_dir / corner
    if not corner_dir.is_dir():
        return []
    cases: List[Path] = []
    for wires in corner_dir.rglob("wires"):
        if wires.is_file():
            cases.append(wires.parent)
    return sorted(cases)


def build_wires_lst(
    case_dir: Path,
    converter: Path,
    process_out: Path,
    std_normal: str,
    ext: float,
    z_ext: float,
) -> str:
    cmd = [
        "python3",
        str(converter),
        str(process_out),
        "./",
        "./",
        std_normal,
        "-sim_window_ext",
        f"{-ext}",
        f"{-z_ext}",
        f"{-ext}",
        f"{ext}",
        f"{z_ext}",
        f"{ext}",
    ]
    result = subprocess.run(
        cmd,
        cwd=case_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return f"converter_failed_{result.returncode}"
    wires_lst = case_dir / "wires.lst"
    if not wires_lst.exists():
        return "wires_lst_missing"
    if wires_lst.stat().st_size == 0:
        return "wires_lst_empty"
    return "ok"


def parse_wires_lst(wires_lst: Path) -> Tuple[List[DEntry], int]:
    name_re = re.compile(r"Dielectrics/dielectric_m(\d+)_(\d+)_.*-(top|bottom)\.txt")
    entries: List[DEntry] = []
    malformed = 0

    for line in wires_lst.read_text(errors="ignore").splitlines():
        if not line.lstrip().startswith("D "):
            continue
        m = name_re.search(line)
        bbox = parse_d_bbox(line)
        if m is None or bbox is None:
            malformed += 1
            continue
        entries.append(
            DEntry(
                metal_id=int(m.group(1)),
                diel_idx=int(m.group(2)),
                side=m.group(3),
                bbox=bbox,
                raw=line.strip(),
            )
        )
    return entries, malformed


def count_overlap_candidates(entries: Iterable[DEntry], tol: float) -> int:
    tops = [e for e in entries if e.side == "top"]
    bots = [e for e in entries if e.side == "bottom"]
    count = 0

    for b in bots:
        for t in tops:
            same_family_adjacent = b.metal_id == t.metal_id and b.diel_idx == t.diel_idx + 1
            cross_family_boundary = b.metal_id == t.metal_id + 1 and b.diel_idx == 1
            if (same_family_adjacent or cross_family_boundary) and xz_match(b.bbox, t.bbox, tol):
                count += 1
                break
    return count


def classify_risk(
    wires_status: str,
    overlap_candidates: int,
    dup_count: int,
    malformed: int,
) -> str:
    if wires_status != "ok":
        return "error"
    if overlap_candidates > 0:
        return "high"
    if dup_count > 0 or malformed > 0:
        return "medium"
    return "low"


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    run_dir = (root / args.run_dir).resolve()
    converter = (root / args.converter).resolve()
    process_out = (
        (root / args.process_out).resolve()
        if args.process_out
        else (run_dir / "process.out").resolve()
    )
    output_csv = (root / args.output_csv).resolve()

    if not run_dir.is_dir():
        raise SystemExit(f"ERROR: run-dir not found: {run_dir}")
    if not converter.is_file():
        raise SystemExit(f"ERROR: converter not found: {converter}")
    if not process_out.is_file():
        raise SystemExit(f"ERROR: process.out not found: {process_out}")

    case_dirs = find_case_dirs(run_dir, args.corner)
    if not case_dirs:
        raise SystemExit(f"ERROR: no cases found under {run_dir / args.corner}")
    if args.max_cases > 0:
        case_dirs = case_dirs[: args.max_cases]

    rows: List[Dict[str, object]] = []
    risk_counter: Counter[str] = Counter()

    for case_dir in case_dirs:
        rel_case = case_dir.relative_to(run_dir).as_posix()
        wires_status = build_wires_lst(
            case_dir=case_dir,
            converter=converter,
            process_out=process_out,
            std_normal=args.std_normal,
            ext=args.ext,
            z_ext=args.z_ext,
        )

        overlap_candidates = 0
        dup_count = 0
        malformed = 0
        d_count = 0

        if wires_status == "ok":
            wires_lst = case_dir / "wires.lst"
            entries, malformed = parse_wires_lst(wires_lst)
            d_count = len(entries)
            overlap_candidates = count_overlap_candidates(entries, args.tolerance)
            dup_count = sum(v - 1 for v in Counter(e.raw for e in entries).values() if v > 1)

        risk = classify_risk(wires_status, overlap_candidates, dup_count, malformed)
        risk_counter[risk] += 1

        rows.append(
            {
                "case": rel_case,
                "wires_lst_status": wires_status,
                "d_lines": d_count,
                "overlap_candidates": overlap_candidates,
                "exact_duplicate_d": dup_count,
                "malformed_d": malformed,
                "risk": risk,
            }
        )

    with output_csv.open("w", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "case",
                "wires_lst_status",
                "d_lines",
                "overlap_candidates",
                "exact_duplicate_d",
                "malformed_d",
                "risk",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote: {output_csv}")
    print(
        "summary: total={total} high={high} medium={medium} low={low} error={error}".format(
            total=len(rows),
            high=risk_counter.get("high", 0),
            medium=risk_counter.get("medium", 0),
            low=risk_counter.get("low", 0),
            error=risk_counter.get("error", 0),
        )
    )
    print("tip: prioritize 'risk=high' cases for sanitize/dry-run first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
