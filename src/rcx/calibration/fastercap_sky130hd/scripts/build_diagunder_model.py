#!/usr/bin/env python3
"""
Build / patch DIAGUNDER sections in 130.rcx.model from FasterCap caps + wires.log.

CG (ground / fringe) for victim wire 3:
  CG = C33 - sum(|C3j|) for all wire j != 3 (exclude substrate M0)
     = TC - CC - CC2 - sum(DiagCC)

Rules / model row format (DIAGUNDER):
  dist  dist2  CC  CG
  (1-indexed: col3=CC, col4=CG)

Normalization matches read_rcx_tables:
  per_table = cap_fF / wLen / 2,  wLen = LEN * 1000 * width_um
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from fasterCapParse import (  # noqa: E402
    float_matrix_to_rows,
    getMets,
    matrix_rows_to_float,
    parseMatrixRow,
    symmetrize_off_diagonal_avg,
)

CAPS_DIAG_RE = re.compile(
    r"^Metal\s+(?P<met>\d+)\s+Over\s+\d+\s+DiagUnder\s+(?P<under>\d+)\s+"
    r"Dist\s+(?P<dist>[0-9.]+)\s+Width\s+(?P<width>[0-9.]+)\s+"
    r"LEN\s+(?P<len>\d+)\s+CC\s+(?P<cc>[0-9.eE+-]+)\s+FR\s+(?P<fr>[0-9.eE+-]+)\s+"
    r"TC\s+(?P<tc>[0-9.eE+-]+)\s+CC2\s+(?P<cc2>[0-9.eE+-]+)\s+"
    r"DiagDist\s+[0-9.]+\s+DiagWidth\s+[0-9.]+\s+DiagCC\s+(?P<diagcc>[0-9.eE+-]+)\s+"
    r"(?P<pattern>TYP/UnderDiag5/[^\s]+/wire_3)\s*$"
)

METAL_DIAG_HDR = re.compile(r"^Metal\s+(\d+)\s+DIAGUNDER(?:\s+(\d+))?\s*$")


def wlen(len_mult: int, width_um: float) -> float:
    return len_mult * 1000.0 * width_um


def normalize(cap_fF: float, len_mult: int, width_um: float) -> float:
    return cap_fF / wlen(len_mult, width_um) / 2.0


def count_diag_wires(rows: list[str], met_over: int) -> int:
    tag = f"_M{met_over}_"
    return sum(1 for r in rows if tag in r.split()[0])


def cg_from_wires_log(
    log_path: Path, met_word: str, victim_met: int, cg_mode: str = "full"
) -> tuple[float, float, float] | None:
    """Return (CC_fF, CG_fF, TC_fF). cg_mode: full=|C30|, c=|C30|+sum(diag)."""
    if not log_path.is_file() or log_path.stat().st_size == 0:
        return None

    matrix_rows = [
        ln.strip()
        for ln in log_path.read_text(errors="ignore").splitlines()
        if ln.startswith("g") and "_wire_" in ln
    ]
    if not matrix_rows:
        return None

    mets = getMets(met_word)
    met = int(mets[0])
    met_over = int(mets[2])
    if met != victim_met:
        return None

    names, mat = matrix_rows_to_float(matrix_rows)
    symmetrize_off_diagonal_avg(mat)
    symrows = float_matrix_to_rows(names, mat)
    wire_cnt = sum(1 for n in names if f"_M{met}_" in n)
    diag_cnt = count_diag_wires(symrows, met_over)
    if wire_cnt < 3:
        return None

    row_idx = None
    for i, row in enumerate(symrows):
        caps = parseMatrixRow(row, met, i + 1, wire_cnt, diag_cnt)
        if caps and caps[0] == 3:
            row_idx = i
            break
    if row_idx is None:
        return None

    caps = parseMatrixRow(symrows[row_idx], met, row_idx + 1, wire_cnt, diag_cnt)
    tc_f = caps[1] * 1e15
    cc_f = caps[2] * 1e15
    cc2_f = caps[3] * 1e15
    diag_sum_f = sum(caps[4]) * 1e15

    cap_vals = symrows[row_idx].split()
    ii = row_idx + 1
    c30_f = abs(float(cap_vals[1])) * 1e15

    if cg_mode == "c":
        cg_f = c30_f + diag_sum_f  # |C30| + |C36| + |C37| + ...
    elif cg_mode == "full":
        cg_f = tc_f - cc_f - cc2_f - diag_sum_f  # |C30|
    else:
        raise ValueError(f"unknown cg_mode: {cg_mode}")

    return cc_f, cg_f, tc_f


def cg_from_caps_fallback(
    tc: float, cc: float, cc2: float, diagcc: float, cg_mode: str = "full"
) -> float:
    if cg_mode == "c":
        return tc - cc - cc2
    return tc - cc - cc2 - diagcc


def parse_caps_diag_lines(
    caps_path: Path, run_dir: Path, prefer_wires_log: bool, cg_mode: str = "full"
) -> dict[tuple[int, int, float], list[tuple[float, float, float]]]:
    """key=(metal, under, width) -> sorted list of (dist, cc_norm, cg_norm)."""
    groups: dict[tuple[int, int, float], list[tuple[float, float, float]]] = defaultdict(list)

    for line in caps_path.read_text(errors="ignore").splitlines():
        m = CAPS_DIAG_RE.match(line.strip())
        if not m:
            continue

        met = int(m.group("met"))
        under = int(m.group("under"))
        dist = float(m.group("dist"))
        width = float(m.group("width"))
        len_mult = int(m.group("len"))
        cc_caps = float(m.group("cc"))
        tc = float(m.group("tc"))
        cc2 = float(m.group("cc2"))
        diagcc = float(m.group("diagcc"))
        pattern = m.group("pattern")
        parts = pattern.split("/")
        met_word = parts[2]
        log_path = run_dir / "/".join(parts[:-1]) / "wires.log"
        vals = None
        if prefer_wires_log:
            vals = cg_from_wires_log(log_path, met_word, met, cg_mode)

        if vals is not None:
            cc_f, cg_f, _tc_f = vals
        else:
            cc_f = cc_caps
            cg_f = cg_from_caps_fallback(tc, cc_caps, cc2, diagcc, cg_mode)

        cc_n = normalize(cc_f, len_mult, width)
        cg_n = normalize(cg_f, len_mult, width)
        groups[(met, under, width)].append((dist, cc_n, cg_n))

    for key in groups:
        groups[key].sort(key=lambda x: x[0])
    return groups


def format_section(metal: int, under: int, width: float, rows: list[tuple[float, float, float]]) -> list[str]:
    out = [f"Metal {metal} DIAGUNDER {under}", f"DIST count {len(rows)} width {width:g}"]
    for dist, cc, cg in rows:
        out.append(f"{dist:g} 0 {cc:g} {cg:g}")
    out.append("END DIST")
    return out


def patch_model(base_path: Path, sections: dict[tuple[int, int, float], list[str]]) -> list[str]:
    lines = base_path.read_text(errors="ignore").splitlines()
    out: list[str] = []
    seen: set[tuple[int, int, float]] = set()
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        hm = METAL_DIAG_HDR.match(line.strip())
        if hm and i + 1 < n and lines[i + 1].strip().startswith("DIST count"):
            metal = int(hm.group(1))
            under = int(hm.group(2) or 0)
            wm = re.search(r"width\s+([0-9.eE+-]+)", lines[i + 1])
            width = float(wm.group(1)) if wm else 0.0
            key = (metal, under, width)

            block_start = i
            i += 2
            while i < n and lines[i].strip() != "END DIST":
                i += 1
            block_end = i
            if i < n:
                i += 1

            if key in sections:
                out.extend(sections[key])
                seen.add(key)
            else:
                out.extend(lines[block_start : block_end + 1])
            continue

        out.append(line)
        i += 1

    for key in sorted(set(sections.keys()) - seen):
        out.append("")
        out.extend(sections[key])

    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Patch DIAGUNDER sections with correct CC/CG columns.")
    ap.add_argument("--caps", required=True)
    ap.add_argument("--run-dir", required=True, help="Pattern tree e.g. 6v2_typ_wirefix")
    ap.add_argument("--base-model", required=True)
    ap.add_argument("--out-model", required=True)
    ap.add_argument(
        "--no-wires-log",
        action="store_true",
        help="Use caps DiagCC only (single diag wire) instead of wires.log sum",
    )
    ap.add_argument(
        "--cg-mode",
        choices=["full", "c"],
        default="full",
        help="full: CG=|C30|; c: CG_C=|C30|+sum(diag)=TC-CC-CC2",
    )
    args = ap.parse_args()

    caps_path = Path(args.caps)
    run_dir = Path(args.run_dir)
    base_path = Path(args.base_model)
    out_path = Path(args.out_model)

    groups = parse_caps_diag_lines(
        caps_path, run_dir, prefer_wires_log=not args.no_wires_log, cg_mode=args.cg_mode
    )
    if not groups:
        raise SystemExit("no DiagUnder wire_3 caps lines parsed")

    section_lines: dict[tuple[int, int, float], list[str]] = {}
    for key, rows in groups.items():
        metal, under, width = key
        section_lines[key] = format_section(metal, under, width, rows)

    patched = patch_model(base_path, section_lines)
    out_path.write_text("\n".join(patched) + "\n")

    print(f"diagunder_keys={len(groups)}")
    print(f"dist_points={sum(len(v) for v in groups.values())}")
    print(f"out_model={out_path}")


if __name__ == "__main__":
    main()
