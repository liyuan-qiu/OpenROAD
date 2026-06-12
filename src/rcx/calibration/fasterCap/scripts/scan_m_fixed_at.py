#!/usr/bin/env python3
"""
Scan FasterCap mesh refinement parameter m with fixed a/t.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


DIM_RE = re.compile(r"^\s*Dimension\s+(\d+)\s+x\s+\d+\s*$", re.IGNORECASE)
NONCONV_RE = re.compile(r"not converging after\s*1000\s*iterations", re.IGNORECASE)
RESID_RE = re.compile(r"(residual|GMRES Iterations:)", re.IGNORECASE)
FLOAT_RE = re.compile(r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")


@dataclass
class RunResult:
    pattern: str
    m: float
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
        if tok:
            vals.append(float(tok))
    if not vals:
        raise ValueError("No numeric values parsed.")
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


def sym_metrics(matrix: list[list[float]]) -> tuple[float, float]:
    n = len(matrix)
    max_abs = 0.0
    max_ref = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            d = abs(matrix[i][j] - matrix[j][i])
            max_abs = max(max_abs, d)
            max_ref = max(max_ref, abs(matrix[i][j]), abs(matrix[j][i]))
    return max_abs, (0.0 if max_ref == 0 else max_abs / max_ref)


def parse_residuals(lines: list[str]) -> list[tuple[int, float]]:
    pts = []
    seq = 0
    for line in lines:
        if not RESID_RE.search(line):
            continue
        fs = FLOAT_RE.findall(line)
        if not fs:
            continue
        seq += 1
        pts.append((seq, float(fs[-1])))
    return pts


def discover_patterns(base_dir: Path, count: int) -> list[Path]:
    pats = sorted([p.parent for p in base_dir.rglob("wires.lst")])
    if not pats:
        raise RuntimeError(f"No patterns with wires.lst in {base_dir}")
    return pats[:count]


def run_one(
    fastercap_bin: Path,
    pattern_dir: Path,
    a: float | None,
    t: float,
    m: float,
    common_args: str,
    timeout_sec: int,
    logs_dir: Path,
) -> tuple[RunResult, list[tuple[int, float]]]:
    slug = str(pattern_dir).replace("/", "__")
    sm = str(m).replace(".", "p")
    a_tag = "noa" if a is None else f"a{str(a).replace('.', 'p')}"
    log_path = logs_dir / f"{slug}_{a_tag}_t{str(t).replace('.', 'p')}_m{sm}.log"
    cmd = [str(fastercap_bin), "-b", "wires.lst", f"-t{t}", f"-m{m}", "-r"]
    if a is not None:
        cmd.append(f"-a{a}")
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
    nonconv = any(NONCONV_RE.search(x) for x in lines)
    residuals = parse_residuals(lines)
    matrix = parse_last_matrix(lines)
    ma, mr = (None, None)
    if matrix is not None:
        ma, mr = sym_metrics(matrix)
    state = "ok" if cp.returncode == 0 else f"failed_{cp.returncode}"
    if nonconv:
        state = "nonconverged_1000"
    res = RunResult(
        pattern=str(pattern_dir),
        m=m,
        rc=cp.returncode,
        state=state,
        not_converged_1000=nonconv,
        residual_count=len(residuals),
        final_residual=(residuals[-1][1] if residuals else None),
        max_asym_abs=ma,
        max_asym_rel=mr,
        log_path=log_path,
    )
    return res, residuals


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan m with fixed a,t.")
    ap.add_argument(
        "--base-dir",
        default="/home/liyuanqiu/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fasterCap/5v2_typ/TYP",
    )
    ap.add_argument(
        "--fastercap-bin",
        default="/home/liyuanqiu/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fasterCap/bin/FasterCap",
    )
    ap.add_argument("--pattern-count", type=int, default=10)
    ap.add_argument("--a", type=float, default=None, help="Auto mode threshold; omit for non-auto mode")
    ap.add_argument("--t", type=float, default=0.1)
    ap.add_argument("--m-values", default="0.2,0.5,1.0,2.0")
    ap.add_argument("--common-args", default="-mc1 -pj -g")
    ap.add_argument("--timeout-sec", type=int, default=1800)
    ap.add_argument(
        "--out-dir",
        default="/home/liyuanqiu/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fasterCap/model/m_scan_a0p1_t0p1",
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

    m_vals = parse_csv_floats(args.m_values)
    patterns = discover_patterns(base_dir, args.pattern_count)
    print(f"Patterns selected: {len(patterns)}")
    print(f"m values: {m_vals}")
    print(f"fixed a={args.a if args.a is not None else 'disabled'}, t={args.t}")

    results: list[RunResult] = []
    residual_rows = []

    for p in patterns:
        for m in m_vals:
            print(f"[RUN] {p.name} m={m}")
            try:
                r, residuals = run_one(
                    fastercap_bin=fastercap_bin,
                    pattern_dir=p,
                    a=args.a,
                    t=args.t,
                    m=m,
                    common_args=args.common_args,
                    timeout_sec=args.timeout_sec,
                    logs_dir=logs_dir,
                )
            except subprocess.TimeoutExpired:
                slug = str(p).replace("/", "__")
                sm = str(m).replace(".", "p")
                lp = logs_dir / f"{slug}_a{str(args.a).replace('.', 'p')}_t{str(args.t).replace('.', 'p')}_m{sm}.log"
                if args.a is None:
                    lp = logs_dir / f"{slug}_noa_t{str(args.t).replace('.', 'p')}_m{sm}.log"
                lp.write_text(f"TIMEOUT after {args.timeout_sec}s\n")
                r = RunResult(
                    pattern=str(p),
                    m=m,
                    rc=124,
                    state="timeout",
                    not_converged_1000=False,
                    residual_count=0,
                    final_residual=None,
                    max_asym_abs=None,
                    max_asym_rel=None,
                    log_path=lp,
                )
                residuals = []
            results.append(r)
            for it, val in residuals:
                residual_rows.append(
                    {"pattern": r.pattern, "m": r.m, "iter": it, "residual": val}
                )

    with (out_dir / "run_summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "pattern",
                "m",
                "state",
                "rc",
                "not_converged_1000",
                "residual_count",
                "final_residual",
                "max_asym_abs",
                "max_asym_rel",
                "log_path",
            ],
        )
        w.writeheader()
        for r in results:
            w.writerow(
                {
                    "pattern": r.pattern,
                    "m": r.m,
                    "state": r.state,
                    "rc": r.rc,
                    "not_converged_1000": int(r.not_converged_1000),
                    "residual_count": r.residual_count,
                    "final_residual": "" if r.final_residual is None else r.final_residual,
                    "max_asym_abs": "" if r.max_asym_abs is None else r.max_asym_abs,
                    "max_asym_rel": "" if r.max_asym_rel is None else r.max_asym_rel,
                    "log_path": str(r.log_path),
                }
            )

    with (out_dir / "residuals.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["pattern", "m", "iter", "residual"])
        w.writeheader()
        w.writerows(residual_rows)

    # Plot 1: mean symmetry vs m
    fig, ax = plt.subplots(figsize=(7, 4.5))
    means = []
    for m in m_vals:
        vals = [r.max_asym_rel for r in results if r.m == m and r.max_asym_rel is not None]
        means.append(float(np.mean(vals)) if vals else np.nan)
    ax.plot(m_vals, means, marker="o")
    ax.set_xlabel("m")
    ax.set_ylabel("mean max relative asymmetry")
    ax.set_title("Symmetry vs m (fixed a,t)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(plots_dir / "symmetry_vs_m.png", dpi=180)
    plt.close(fig)

    # Plot 2: per-pattern residual curves by m
    by_pattern = {}
    for r in results:
        by_pattern.setdefault(r.pattern, []).append(r)
    for pat, runs in by_pattern.items():
        fig, ax = plt.subplots(figsize=(8, 5))
        plotted = 0
        for r in sorted(runs, key=lambda x: x.m):
            pts = [x for x in residual_rows if x["pattern"] == pat and x["m"] == r.m]
            if not pts:
                continue
            ax.plot([x["iter"] for x in pts], [x["residual"] for x in pts], label=f"m={r.m}")
            plotted += 1
        if plotted > 0:
            ax.set_yscale("log")
            ax.set_xlabel("Iteration step")
            ax.set_ylabel("Residual")
            ax.set_title(f"Residual vs step by m\n{pat}")
            ax.grid(True, which="both", alpha=0.3)
            ax.legend()
            fig.tight_layout()
            slug = pat.replace("/", "__")
            fig.savefig(plots_dir / f"residual_by_m_{slug}.png", dpi=180)
        plt.close(fig)

    print(f"Done. Results under: {out_dir}")


if __name__ == "__main__":
    main()
