#!/usr/bin/env python3
"""
Sweep FasterCap across a/t combinations on multiple patterns.

Outputs:
  - run_summary.csv: one row per (pattern, a, t)
  - residuals.csv: per-iteration residual samples
  - plots/*.png: residual curves and symmetry visualizations
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np


DIM_RE = re.compile(r"^\s*Dimension\s+(\d+)\s+x\s+\d+\s*$", re.IGNORECASE)
NONCONV_RE = re.compile(r"not converging after\s*1000\s*iterations", re.IGNORECASE)
RESID_RE = re.compile(r"(residual|GMRES Iterations:)", re.IGNORECASE)
FLOAT_RE = re.compile(r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")
INT_RE = re.compile(r"\b(\d+)\b")


@dataclass
class RunResult:
    pattern: str
    a: float
    t: float
    rc: int
    state: str
    not_converged_1000: bool
    residual_count: int
    final_residual: float | None
    max_asym_abs: float | None
    max_asym_rel: float | None
    log_path: Path


def parse_csv_floats(text: str) -> list[float]:
    vals = []
    for tok in text.split(","):
        tok = tok.strip()
        if not tok:
            continue
        vals.append(float(tok))
    if not vals:
        raise ValueError("No numeric values parsed from CSV string.")
    return vals


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
                vals = [float(x) for x in toks[1 : n + 1]]
            except ValueError:
                ok = False
                break
            rows.append(vals)
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


def parse_residuals(lines: Iterable[str]) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    seq = 0
    for line in lines:
        if not RESID_RE.search(line):
            continue
        floats = FLOAT_RE.findall(line)
        if not floats:
            continue
        residual = float(floats[-1])
        # FasterCap logs often print per-step info in "GMRES Iterations: ..."
        # where the first integer is not a strict step counter. Use sequence id.
        seq += 1
        it = seq
        out.append((it, residual))
    return out


def discover_patterns(base_dir: Path, limit: int) -> list[Path]:
    candidates = []
    for p in sorted(base_dir.rglob("wires.lst")):
        if p.is_file():
            candidates.append(p.parent)
    if not candidates:
        raise RuntimeError(f"No pattern dirs with wires.lst found under {base_dir}")
    return candidates[:limit]


def run_one(
    fastercap_bin: Path,
    pattern_dir: Path,
    a: float,
    t: float,
    common_args: str,
    timeout_sec: int,
    out_dir: Path,
) -> tuple[RunResult, list[tuple[int, float]]]:
    safe_a = str(a).replace(".", "p")
    safe_t = str(t).replace(".", "p")
    pattern_slug = str(pattern_dir).replace("/", "__")
    log_path = out_dir / f"{pattern_slug}_a{safe_a}_t{safe_t}.log"

    cmd = [str(fastercap_bin), "-b", "wires.lst", f"-a{a}", f"-t{t}", "-r"]
    if common_args.strip():
        cmd.extend(common_args.strip().split())

    cp = subprocess.run(
        cmd,
        cwd=pattern_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    log_path.write_text(cp.stdout)

    lines = cp.stdout.splitlines()
    nonconv = any(NONCONV_RE.search(ln) for ln in lines)
    residuals = parse_residuals(lines)
    matrix = parse_last_matrix(lines)
    max_abs, max_rel = (None, None)
    if matrix is not None:
        max_abs, max_rel = symmetry_metrics(matrix)

    state = "ok" if cp.returncode == 0 else f"failed_{cp.returncode}"
    if nonconv:
        state = "nonconverged_1000"

    result = RunResult(
        pattern=str(pattern_dir),
        a=a,
        t=t,
        rc=cp.returncode,
        state=state,
        not_converged_1000=nonconv,
        residual_count=len(residuals),
        final_residual=(residuals[-1][1] if residuals else None),
        max_asym_abs=max_abs,
        max_asym_rel=max_rel,
        log_path=log_path,
    )
    return result, residuals


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def plot_per_pattern(
    out_plots: Path,
    pattern: str,
    runs: list[RunResult],
    residual_rows: list[dict],
) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    ax_res, ax_sym = axes

    legend_count = 0
    for r in runs:
        pts = [
            x for x in residual_rows if x["pattern"] == pattern and x["a"] == r.a and x["t"] == r.t
        ]
        if not pts:
            continue
        xs = [p["iter"] for p in pts]
        ys = [p["residual"] for p in pts]
        ax_res.plot(xs, ys, marker=".", linewidth=1, label=f"a={r.a}, t={r.t}")
        legend_count += 1

    ax_res.set_yscale("log")
    ax_res.set_xlabel("Iteration")
    ax_res.set_ylabel("Residual")
    ax_res.set_title("GMRES residual by iteration")
    ax_res.grid(True, which="both", alpha=0.3)
    if legend_count > 0:
        ax_res.legend(fontsize=7)

    labels = [f"a={r.a}\nt={r.t}" for r in runs]
    vals = [np.nan if r.max_asym_rel is None else r.max_asym_rel for r in runs]
    ax_sym.bar(range(len(vals)), vals)
    ax_sym.set_xticks(range(len(vals)))
    ax_sym.set_xticklabels(labels, rotation=70, fontsize=7)
    ax_sym.set_ylabel("max relative asymmetry")
    ax_sym.set_title("Symmetry metric per run")
    ax_sym.grid(True, axis="y", alpha=0.3)

    fig.suptitle(pattern)
    fig.tight_layout()
    safe_name = pattern.replace("/", "__")
    fig.savefig(out_plots / f"pattern_{safe_name}.png", dpi=170)
    plt.close(fig)


def plot_global_heatmap(out_plots: Path, runs: list[RunResult], a_vals: list[float], t_vals: list[float]) -> None:
    data = np.full((len(a_vals), len(t_vals)), np.nan)
    for i, a in enumerate(a_vals):
        for j, t in enumerate(t_vals):
            vals = [r.max_asym_rel for r in runs if r.a == a and r.t == t and r.max_asym_rel is not None]
            if vals:
                data[i, j] = float(np.mean(vals))

    fig, ax = plt.subplots(figsize=(7, 5))
    im = ax.imshow(data, aspect="auto")
    ax.set_xticks(range(len(t_vals)))
    ax.set_xticklabels([str(v) for v in t_vals])
    ax.set_yticks(range(len(a_vals)))
    ax.set_yticklabels([str(v) for v in a_vals])
    ax.set_xlabel("t (GMRES tolerance)")
    ax.set_ylabel("a (relative error target)")
    ax.set_title("Mean max relative asymmetry (across patterns)")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("max|Aij-Aji| / max|Aij|")
    fig.tight_layout()
    fig.savefig(out_plots / "symmetry_heatmap_mean.png", dpi=170)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Sweep FasterCap a/t and visualize convergence + symmetry.")
    ap.add_argument(
        "--base-dir",
        default="/home/liyuanqiu/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fasterCap/5v2_typ/TYP",
        help="Root directory containing pattern subdirs with wires.lst",
    )
    ap.add_argument(
        "--fastercap-bin",
        default="/home/liyuanqiu/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fasterCap/bin/FasterCap",
        help="Path to FasterCap binary",
    )
    ap.add_argument("--a-values", default="0.2,0.1,0.05", help="CSV list, e.g. 0.2,0.1,0.05")
    ap.add_argument("--t-values", default="0.1,0.05", help="CSV list, e.g. 0.1,0.05")
    ap.add_argument("--pattern-count", type=int, default=10, help="How many patterns to scan")
    ap.add_argument(
        "--start-run-index",
        type=int,
        default=1,
        help="1-based global run index to start from (for resume), default=1",
    )
    ap.add_argument(
        "--end-run-index",
        type=int,
        default=0,
        help="1-based global run index to stop at (0 means run all)",
    )
    ap.add_argument(
        "--common-args",
        default="-m0.5 -mc1 -pj -g",
        help="Extra FasterCap arguments applied to every run",
    )
    ap.add_argument("--timeout-sec", type=int, default=600, help="Per-run timeout")
    ap.add_argument(
        "--out-dir",
        default="/home/liyuanqiu/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fasterCap/model/at_scan_results",
        help="Output directory",
    )
    ap.add_argument(
        "--pattern-file",
        default="",
        help="Optional file listing pattern directories (one absolute or relative path per line)",
    )
    args = ap.parse_args()

    base_dir = Path(args.base_dir).resolve()
    fastercap_bin = Path(args.fastercap_bin).resolve()
    out_dir = Path(args.out_dir).resolve()
    logs_dir = out_dir / "logs"
    plots_dir = out_dir / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    a_vals = parse_csv_floats(args.a_values)
    t_vals = parse_csv_floats(args.t_values)

    if args.pattern_file:
        pattern_dirs = []
        for raw in Path(args.pattern_file).read_text().splitlines():
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            p = Path(s)
            if not p.is_absolute():
                p = base_dir / s
            pattern_dirs.append(p.resolve())
        pattern_dirs = pattern_dirs[: args.pattern_count]
    else:
        pattern_dirs = discover_patterns(base_dir, args.pattern_count)

    print(f"Patterns selected: {len(pattern_dirs)}")
    for p in pattern_dirs:
        print(f"  - {p}")
    print(f"a values: {a_vals}")
    print(f"t values: {t_vals}")

    all_runs: list[RunResult] = []
    residual_rows: list[dict] = []
    run_idx = 0
    for pdir in pattern_dirs:
        for a in a_vals:
            for t in t_vals:
                run_idx += 1
                if run_idx < args.start_run_index:
                    continue
                if args.end_run_index > 0 and run_idx > args.end_run_index:
                    break
                print(f"[RUN] {pdir.name} a={a} t={t}")
                try:
                    rr, residuals = run_one(
                        fastercap_bin=fastercap_bin,
                        pattern_dir=pdir,
                        a=a,
                        t=t,
                        common_args=args.common_args,
                        timeout_sec=args.timeout_sec,
                        out_dir=logs_dir,
                    )
                except subprocess.TimeoutExpired:
                    pattern_slug = str(pdir).replace("/", "__")
                    log_path = logs_dir / (
                        f"{pattern_slug}_a{str(a).replace('.', 'p')}_t{str(t).replace('.', 'p')}.log"
                    )
                    log_path.write_text(f"TIMEOUT after {args.timeout_sec}s\n")
                    rr = RunResult(
                        pattern=str(pdir),
                        a=a,
                        t=t,
                        rc=124,
                        state="timeout",
                        not_converged_1000=False,
                        residual_count=0,
                        final_residual=None,
                        max_asym_abs=None,
                        max_asym_rel=None,
                        log_path=log_path,
                    )
                    residuals = []
                all_runs.append(rr)
                for it, res in residuals:
                    residual_rows.append(
                        {
                            "pattern": rr.pattern,
                            "a": rr.a,
                            "t": rr.t,
                            "iter": it,
                            "residual": res,
                        }
                    )
            if args.end_run_index > 0 and run_idx >= args.end_run_index:
                break
        if args.end_run_index > 0 and run_idx >= args.end_run_index:
            break

    summary_rows = [
        {
            "pattern": r.pattern,
            "a": r.a,
            "t": r.t,
            "rc": r.rc,
            "state": r.state,
            "not_converged_1000": int(r.not_converged_1000),
            "residual_count": r.residual_count,
            "final_residual": "" if r.final_residual is None else r.final_residual,
            "max_asym_abs": "" if r.max_asym_abs is None else r.max_asym_abs,
            "max_asym_rel": "" if r.max_asym_rel is None else r.max_asym_rel,
            "log_path": str(r.log_path),
        }
        for r in all_runs
    ]
    write_csv(
        out_dir / "run_summary.csv",
        summary_rows,
        [
            "pattern",
            "a",
            "t",
            "rc",
            "state",
            "not_converged_1000",
            "residual_count",
            "final_residual",
            "max_asym_abs",
            "max_asym_rel",
            "log_path",
        ],
    )
    write_csv(out_dir / "residuals.csv", residual_rows, ["pattern", "a", "t", "iter", "residual"])

    by_pattern: dict[str, list[RunResult]] = {}
    for r in all_runs:
        by_pattern.setdefault(r.pattern, []).append(r)
    for pattern, runs in by_pattern.items():
        plot_per_pattern(plots_dir, pattern, runs, residual_rows)

    plot_global_heatmap(plots_dir, all_runs, a_vals, t_vals)

    ok_cnt = sum(1 for r in all_runs if r.state == "ok")
    nonconv_cnt = sum(1 for r in all_runs if r.not_converged_1000)
    with (out_dir / "README.txt").open("w") as f:
        f.write("a/t scan complete\n")
        f.write(f"patterns={len(pattern_dirs)}\n")
        f.write(f"runs={len(all_runs)}\n")
        f.write(f"ok_runs={ok_cnt}\n")
        f.write(f"not_converged_1000_runs={nonconv_cnt}\n")
        f.write("Artifacts:\n")
        f.write("  run_summary.csv\n")
        f.write("  residuals.csv\n")
        f.write("  plots/pattern_*.png\n")
        f.write("  plots/symmetry_heatmap_mean.png\n")

    print(f"Done. Results under: {out_dir}")


if __name__ == "__main__":
    main()
