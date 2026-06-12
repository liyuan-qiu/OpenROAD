#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
import statistics
import subprocess
from pathlib import Path


DIM_RE = re.compile(r"^\s*Dimension\s+(\d+)\s+x\s+\d+\s*$", re.IGNORECASE)
OUTER_RE = re.compile(r"Iteration number\s*#(\d+)", re.IGNORECASE)
GMRES_RE = re.compile(r"GMRES Iterations:\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")
NONCONV_RE = re.compile(r"not converging after\s*1000\s*iterations", re.IGNORECASE)
PANEL_RE = re.compile(r"panel distance too small", re.IGNORECASE)


def parse_last_matrix(lines: list[str]) -> list[list[float]] | None:
    last = None
    i = 0
    while i < len(lines):
        m = DIM_RE.match(lines[i])
        if not m:
            i += 1
            continue
        n = int(m.group(1))
        rows = []
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
            continue
        i += 1
    return last


def symmetry_metrics(matrix: list[list[float]]) -> tuple[float, float]:
    n = len(matrix)
    max_abs = 0.0
    max_ref = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            d = abs(matrix[i][j] - matrix[j][i])
            max_abs = max(max_abs, d)
            max_ref = max(max_ref, abs(matrix[i][j]), abs(matrix[j][i]))
    max_rel = 0.0 if max_ref == 0.0 else max_abs / max_ref
    return max_abs, max_rel


def main() -> None:
    typ_root = Path(
        "/home/liyuanqiu/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fasterCap/5v2_typ/TYP"
    )
    fastercap = Path(
        "/home/liyuanqiu/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fasterCap/bin/FasterCap"
    )
    out_dir = Path(
        "/home/liyuanqiu/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fasterCap/model/typ542_ps128_g_a0p1_t0p1_to180"
    )
    logs_dir = out_dir / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    patterns = sorted([p.parent for p in typ_root.rglob("wires.lst")])
    rows = []

    for idx, pat in enumerate(patterns, 1):
        cmd = [
            str(fastercap),
            "-b",
            "wires.lst",
            "-g",
            "-ps128",
            "-a0.1",
            "-t0.1",
            "-r",
        ]
        slug = str(pat).replace("/", "__")
        log_path = logs_dir / f"{slug}.log"

        try:
            cp = subprocess.run(
                cmd,
                cwd=pat,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=180,
                check=False,
            )
            text = cp.stdout
            log_path.write_text(text)
            state = "ok" if cp.returncode == 0 else f"failed_{cp.returncode}"
        except subprocess.TimeoutExpired:
            text = "TIMEOUT after 180s\n"
            log_path.write_text(text)
            state = "timeout"

        outer_idxs = [int(m.group(1)) for m in OUTER_RE.finditer(text)]
        outer_iter_count = max(outer_idxs) + 1 if outer_idxs else ""
        gmres_vals = [float(m.group(1)) for m in GMRES_RE.finditer(text)]
        gmres_max = max(gmres_vals) if gmres_vals else ""
        gmres_lines_count = len(gmres_vals)
        nonconv = bool(NONCONV_RE.search(text))
        panel_hits = len(PANEL_RE.findall(text))
        lines = text.splitlines()
        matrix = parse_last_matrix(lines)
        asym_abs = ""
        asym_rel = ""
        if matrix is not None:
            asym_abs, asym_rel = symmetry_metrics(matrix)

        if nonconv:
            state = "nonconv1000"

        rows.append(
            {
                "run_idx": idx,
                "pattern": str(pat.relative_to(typ_root)),
                "state": state,
                "not_converged_1000": int(nonconv),
                "panel_too_small_hits": panel_hits,
                "outer_iteration_count": outer_iter_count,
                "gmres_max_first_value": gmres_max,
                "gmres_lines_count": gmres_lines_count,
                "max_asym_abs": asym_abs,
                "max_asym_rel": asym_rel,
                "log_file": str(log_path),
            }
        )
        if idx % 25 == 0:
            print(f"progress {idx}/{len(patterns)}")

    csv_path = out_dir / "typ542_results.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    rel_vals = [float(r["max_asym_rel"]) for r in rows if r["max_asym_rel"] != ""]
    outer_vals = [int(r["outer_iteration_count"]) for r in rows if r["outer_iteration_count"] != ""]
    gmmax_vals = [float(r["gmres_max_first_value"]) for r in rows if r["gmres_max_first_value"] != ""]
    gmlines_vals = [int(r["gmres_lines_count"]) for r in rows if r["gmres_lines_count"] != ""]

    summary_path = out_dir / "summary.txt"
    with summary_path.open("w") as f:
        f.write(f"total_patterns={len(rows)}\n")
        for s in ("ok", "timeout", "nonconv1000"):
            f.write(f"{s}={sum(1 for r in rows if r['state']==s)}\n")
        if rel_vals:
            f.write(f"asym_rel_mean={statistics.mean(rel_vals)}\n")
            f.write(f"asym_rel_median={statistics.median(rel_vals)}\n")
            f.write(f"asym_rel_le_1e-2={sum(1 for x in rel_vals if x <= 1e-2)}\n")
            f.write(f"asym_rel_le_5e-2={sum(1 for x in rel_vals if x <= 5e-2)}\n")
        if outer_vals:
            f.write(f"outer_iter_mean={statistics.mean(outer_vals)}\n")
            f.write(f"outer_iter_median={statistics.median(outer_vals)}\n")
            f.write(f"outer_iter_max={max(outer_vals)}\n")
        if gmmax_vals:
            f.write(f"gmres_max_first_mean={statistics.mean(gmmax_vals)}\n")
            f.write(f"gmres_max_first_median={statistics.median(gmmax_vals)}\n")
            f.write(f"gmres_max_first_max={max(gmmax_vals)}\n")
        if gmlines_vals:
            f.write(f"gmres_lines_mean={statistics.mean(gmlines_vals)}\n")
            f.write(f"gmres_lines_median={statistics.median(gmlines_vals)}\n")
            f.write(f"gmres_lines_max={max(gmlines_vals)}\n")

    print(f"DONE csv={csv_path}")
    print(f"DONE summary={summary_path}")


if __name__ == "__main__":
    main()
