#!/usr/bin/env python3
"""Scan wires.log files for convergence, symmetry, and off-diagonal sign quality."""

from __future__ import annotations

import argparse
import csv
import re
import statistics
from pathlib import Path

DIM_RE = re.compile(r"^\s*Dimension\s+(\d+)\s+x\s+\d+\s*$", re.IGNORECASE)
PAT_NONCONV1000 = re.compile(r"not converging after\s*1000\s*iterations", re.I)
PAT_NONCONV_ANY = re.compile(r"not converging", re.I)
PAT_KILLED = re.compile(r"killed|Second Limit exceeded|timeout|timed out", re.I)
PAT_RESID_FAIL = re.compile(
    r"norm of the residual is\s+([\d.]+),\s*while targeting\s+([\d.]+)", re.I
)
PAT_FROB = re.compile(r"Weighted Frobenius", re.I)
PAT_CAP_MATRIX = re.compile(r"Capacitance matrix is:", re.I)
PAT_MEMORY = re.compile(r"Total allocated memory", re.I)
STRONG_TH = 1e-16


def parse_last_matrix(lines: list[str]) -> list[list[float]] | None:
    last = None
    i = 0
    while i < len(lines):
        m = DIM_RE.match(lines[i])
        if not m:
            i += 1
            continue
        n = int(m.group(1))
        rows: list[list[float]] = []
        ok = True
        for k in range(1, n + 1):
            if i + k >= len(lines):
                ok = False
                break
            toks = lines[i + k].split()
            if len(toks) < n + 1:
                ok = False
                break
            try:
                rows.append([float(x) for x in toks[1 : n + 1]])
            except ValueError:
                ok = False
                break
        if ok and len(rows) == n:
            last = rows
            i += n + 1
        else:
            i += 1
    return last


def block_no_m0(mat: list[list[float]]) -> list[list[float]]:
    if len(mat) <= 1:
        return mat
    return [row[1:] for row in mat[1:]]


def rel_asym(cij: float, cji: float) -> float:
    denom = max(abs(cij), abs(cji))
    if denom == 0.0:
        return 0.0
    return abs(cij - cji) / denom


def signed_rel_asym(cij: float, cji: float) -> float:
    denom = max(abs(cij), abs(cji))
    if denom == 0.0:
        return 0.0
    return (cij - cji) / denom


def scan_offdiag_positive(mat: list[list[float]], strong_th: float) -> dict:
    n = len(mat)
    all_pairs: list[tuple[float, float, float, bool]] = []
    for i in range(n):
        for j in range(i + 1, n):
            cij, cji = mat[i][j], mat[j][i]
            mag = max(abs(cij), abs(cji))
            if cij > 0 or cji > 0:
                strong = mag >= strong_th
                all_pairs.append((cij, cji, mag, strong))

    strong_pairs = [p for p in all_pairs if p[3]]
    both = sum(1 for cij, cji, _, _ in strong_pairs if cij > 0 and cji > 0)
    one = sum(1 for cij, cji, _, _ in strong_pairs if (cij > 0) ^ (cji > 0))

    def max_pos(pairs: list[tuple[float, float, float, bool]]) -> float:
        if not pairs:
            return 0.0
        return max(max(cij, cji) for cij, cji, _, _ in pairs)

    return {
        "pos_offdiag_all": int(len(all_pairs) > 0),
        "pos_offdiag_strong": int(len(strong_pairs) > 0),
        "pos_strong_pairs": len(strong_pairs),
        "pos_strong_max": max_pos(strong_pairs),
        "pos_both_sides_strong": both,
        "pos_one_side_strong": one,
        "pos_all_pairs": len(all_pairs),
        "pos_all_max": max_pos(all_pairs),
    }


def scan_symmetry(mat: list[list[float]], strong_th: float) -> dict:
    n = len(mat)
    global_max = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            global_max = max(global_max, rel_asym(mat[i][j], mat[j][i]))

    blk = block_no_m0(mat)
    bn = len(blk)
    block_max = 0.0
    signed_rels: list[float] = []
    mag_rels: list[float] = []
    sign_flips = 0

    for i in range(bn):
        for j in range(i + 1, bn):
            cij, cji = blk[i][j], blk[j][i]
            block_max = max(block_max, rel_asym(cij, cji))
            mag = max(abs(cij), abs(cji))
            if mag < strong_th:
                continue
            signed_rels.append(abs(signed_rel_asym(cij, cji)))
            mag_rels.append(rel_asym(cij, cji))
            if (cij > 0) ^ (cji > 0):
                sign_flips += 1

    return {
        "global_max_rel_asym": global_max,
        "block_noM0_max_rel_asym": block_max,
        "strong_pair_max_signed_rel": max(signed_rels) if signed_rels else "",
        "strong_pair_max_mag_rel": max(mag_rels) if mag_rels else "",
        "strong_pair_median_signed_rel": statistics.median(signed_rels) if signed_rels else "",
        "strong_pair_count": len(signed_rels),
        "sign_flip_pairs": sign_flips,
    }


def scan_log(log_path: Path, root: Path, strong_th: float) -> dict:
    rel = str(log_path.relative_to(root)).replace("/wires.log", "")
    text = log_path.read_text(errors="replace")
    lines = text.splitlines()

    nonconv1000 = int(any(PAT_NONCONV1000.search(ln) for ln in lines))
    nonconv_any = int(any(PAT_NONCONV_ANY.search(ln) for ln in lines))
    killed = int(any(PAT_KILLED.search(ln) for ln in lines))
    has_cap = int(any(PAT_CAP_MATRIX.search(ln) for ln in lines))
    has_frob = int(any(PAT_FROB.search(ln) for ln in lines))
    has_mem = int(any(PAT_MEMORY.search(ln) for ln in lines))

    resid_over = ""
    for ln in lines:
        m = PAT_RESID_FAIL.search(ln)
        if m:
            resid_over = f"{float(m.group(1)) / float(m.group(2)):.2f}"

    mat = parse_last_matrix(lines)
    row: dict = {
        "pattern": rel,
        "nonconv_1000": nonconv1000,
        "nonconv_any": nonconv_any,
        "killed": killed,
        "has_cap_matrix": has_cap,
        "has_frobenius": has_frob,
        "has_memory_marker": has_mem,
        "parsed_matrix": int(mat is not None),
        "dim": len(mat) if mat else "",
        "resid_over_target": resid_over,
    }

    if mat is None:
        row.update(
            {
                "global_max_rel_asym": "",
                "block_noM0_max_rel_asym": "",
                "strong_pair_max_signed_rel": "",
                "strong_pair_max_mag_rel": "",
                "strong_pair_median_signed_rel": "",
                "strong_pair_count": "",
                "sign_flip_pairs": "",
                "pos_offdiag_all": "",
                "pos_offdiag_strong": "",
                "pos_strong_pairs": "",
                "pos_strong_max": "",
                "pos_both_sides_strong": "",
                "pos_one_side_strong": "",
                "pos_all_pairs": "",
                "pos_all_max": "",
            }
        )
        return row

    row.update(scan_symmetry(mat, strong_th))
    row.update(scan_offdiag_positive(block_no_m0(mat), strong_th))
    return row


FIELDNAMES = [
    "pattern",
    "nonconv_1000",
    "nonconv_any",
    "killed",
    "has_cap_matrix",
    "has_frobenius",
    "has_memory_marker",
    "parsed_matrix",
    "dim",
    "global_max_rel_asym",
    "block_noM0_max_rel_asym",
    "strong_pair_max_signed_rel",
    "strong_pair_max_mag_rel",
    "strong_pair_median_signed_rel",
    "strong_pair_count",
    "sign_flip_pairs",
    "resid_over_target",
    "pos_offdiag_all",
    "pos_offdiag_strong",
    "pos_strong_pairs",
    "pos_strong_max",
    "pos_both_sides_strong",
    "pos_one_side_strong",
    "pos_all_pairs",
    "pos_all_max",
]


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan wires.log quality metrics.")
    ap.add_argument(
        "--root",
        default="10v2_typ",
        help="Root directory containing pattern subdirs with wires.log",
    )
    ap.add_argument(
        "--out",
        default="10v2_typ_analysis_wires_quality.csv",
        help="Output CSV path",
    )
    ap.add_argument(
        "--strong-th",
        type=float,
        default=STRONG_TH,
        help="Strong coupling threshold in Farads (default 1e-16)",
    )
    args = ap.parse_args()

    root = Path(args.root).resolve()
    logs = sorted(p for p in root.rglob("wires.log") if p.stat().st_size > 0)
    rows = [scan_log(p, root, args.strong_th) for p in logs]

    out = Path(args.out).resolve()
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)

    strong_pos = sum(1 for r in rows if r.get("pos_offdiag_strong") == 1)
    print(f"Scanned {len(rows)} wires.log -> {out}")
    print(f"strong positive off-diagonal matrices: {strong_pos}/{len(rows)}")


if __name__ == "__main__":
    main()
