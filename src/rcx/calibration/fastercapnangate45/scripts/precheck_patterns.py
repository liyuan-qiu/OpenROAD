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


@dataclass
class Box:
    kind: str
    name: str
    bbox: Tuple[float, float, float, float, float, float]


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
    parser.add_argument(
        "--family",
        default="",
        help="Only check this family directory, for example Over5",
    )
    parser.add_argument(
        "--stack",
        default="",
        help="Only check this stack directory, for example M1oM0",
    )
    parser.add_argument(
        "--len-mult",
        type=int,
        default=0,
        help="Only check case directories ending in _L<value> (0 means all)",
    )
    parser.add_argument(
        "--fail-on-risk",
        choices=("none", "error", "medium", "high"),
        default="none",
        help="Return nonzero when the selected risk class or worse is present",
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


def parse_geometry_box(line: str) -> Optional[Box]:
    tokens = line.split()
    if len(tokens) < 6 or tokens[0] not in {"C", "D"}:
        return None
    dim_match = re.search(
        r"_W([-+\d.eE]+)_T([-+\d.eE]+)_H([-+\d.eE]+)-",
        tokens[1],
    )
    if dim_match is None:
        return None
    offset = 3 if tokens[0] == "C" else 4
    try:
        width, thickness, height = map(float, dim_match.groups())
        x, y, z = map(float, tokens[offset : offset + 3])
    except (ValueError, IndexError):
        return None
    return Box(
        kind=tokens[0],
        name=tokens[1],
        bbox=(x, x + width, y, y + thickness, z, z + height),
    )


def positive_volume_overlap(
    a: Tuple[float, float, float, float, float, float],
    b: Tuple[float, float, float, float, float, float],
    tol: float,
) -> bool:
    return all(
        min(a[hi], b[hi]) - max(a[lo], b[lo]) > tol
        for lo, hi in ((0, 1), (2, 3), (4, 5))
    )


def count_box_overlaps(
    conductors: List[Box], dielectrics: List[Box], tol: float
) -> Tuple[int, int]:
    metal_dielectric = sum(
        positive_volume_overlap(conductor.bbox, dielectric.bbox, tol)
        for conductor in conductors
        for dielectric in dielectrics
    )
    dielectric_dielectric = sum(
        positive_volume_overlap(a.bbox, b.bbox, tol)
        for index, a in enumerate(dielectrics)
        for b in dielectrics[index + 1 :]
    )
    return metal_dielectric, dielectric_dielectric


def parse_wires_lst(wires_lst: Path) -> Tuple[List[DEntry], List[Box], List[Box], int]:
    name_re = re.compile(r"Dielectrics/dielectric_m(\d+)_(\d+)_.*-(top|bottom)\.txt")
    entries: List[DEntry] = []
    conductors: List[Box] = []
    dielectrics: List[Box] = []
    malformed = 0

    for line in wires_lst.read_text(errors="ignore").splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("C ", "D ")):
            box = parse_geometry_box(stripped)
            if box is None:
                malformed += 1
            elif box.kind == "C":
                conductors.append(box)
            else:
                dielectrics.append(box)
        if not line.lstrip().startswith("D "):
            continue
        m = name_re.search(line)
        bbox = parse_d_bbox(line)
        if m is None or bbox is None:
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
    def deduplicate(boxes: List[Box]) -> List[Box]:
        unique: Dict[Tuple[str, str, Tuple[float, ...]], Box] = {}
        for box in boxes:
            region = re.sub(r"-(?:top|bottom|sides)\.txt$", "", box.name)
            unique[(box.kind, region, box.bbox)] = box
        return list(unique.values())

    return entries, deduplicate(conductors), deduplicate(dielectrics), malformed


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
    metal_inside_dielectric_bbox: int,
    dielectric_dielectric_overlaps: int,
    dup_count: int,
    malformed: int,
) -> str:
    if wires_status != "ok":
        return "error"
    if (
        overlap_candidates > 0
        or dielectric_dielectric_overlaps > 0
    ):
        return "high"
    # Conductors are normally embedded in a dielectric region, so positive
    # solid bounding-box intersection is informational. It does not prove that
    # conductor and dielectric boundary panels overlap.
    if metal_inside_dielectric_bbox > 0 or dup_count > 0 or malformed > 0:
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
    if args.family:
        marker = f"/{args.family}/"
        case_dirs = [p for p in case_dirs if marker in p.as_posix()]
    if args.stack:
        marker = f"/{args.stack}/"
        case_dirs = [p for p in case_dirs if marker in p.as_posix()]
    if args.len_mult:
        suffix = f"_L{args.len_mult}"
        case_dirs = [p for p in case_dirs if p.name.endswith(suffix)]
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
        conductor_boxes = 0
        dielectric_boxes = 0
        metal_inside_dielectric_bbox = 0
        dielectric_dielectric_overlaps = 0

        if wires_status == "ok":
            wires_lst = case_dir / "wires.lst"
            entries, conductors, dielectrics, malformed = parse_wires_lst(wires_lst)
            d_count = len(entries)
            conductor_boxes = len(conductors)
            dielectric_boxes = len(dielectrics)
            overlap_candidates = count_overlap_candidates(entries, args.tolerance)
            (
                metal_inside_dielectric_bbox,
                dielectric_dielectric_overlaps,
            ) = count_box_overlaps(conductors, dielectrics, args.tolerance)
            dup_count = sum(v - 1 for v in Counter(e.raw for e in entries).values() if v > 1)

        risk = classify_risk(
            wires_status,
            overlap_candidates,
            metal_inside_dielectric_bbox,
            dielectric_dielectric_overlaps,
            dup_count,
            malformed,
        )
        risk_counter[risk] += 1

        rows.append(
            {
                "case": rel_case,
                "wires_lst_status": wires_status,
                "d_lines": d_count,
                "conductor_boxes": conductor_boxes,
                "dielectric_boxes": dielectric_boxes,
                "overlap_candidates": overlap_candidates,
                "metal_inside_dielectric_bbox": metal_inside_dielectric_bbox,
                "dielectric_dielectric_overlaps": dielectric_dielectric_overlaps,
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
                "conductor_boxes",
                "dielectric_boxes",
                "overlap_candidates",
                "metal_inside_dielectric_bbox",
                "dielectric_dielectric_overlaps",
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
    severity = {"low": 0, "medium": 1, "high": 2, "error": 3}
    if args.fail_on_risk != "none":
        threshold = severity[args.fail_on_risk]
        failing = sum(
            count
            for risk, count in risk_counter.items()
            if severity.get(risk, 3) >= threshold
        )
        if failing:
            print(
                f"ERROR: precheck gate failed: {failing} case(s) at "
                f"risk>={args.fail_on_risk}"
            )
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
