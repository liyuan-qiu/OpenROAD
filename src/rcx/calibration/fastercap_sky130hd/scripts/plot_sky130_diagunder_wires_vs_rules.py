#!/usr/bin/env python3
"""
Sky130 DIAGUNDER: contrast FasterCap wires.log vs rcx_patterns.rules.

Rules row format (Sky130)::

    dist  0  CC  CG
          ↑     ↑   ↑
        col0  col2 col3  (0-based; col1 is dist2 placeholder)

From wires.log (UnderDiag5, victim wire 3, symmetrized matrix):
  CC = |C32| + |C34|
  CG modes (--cg-mode):
    tc_minus_cc      : TC - CC  (default; matches fasterCapParse FR basis)
    tc_minus_cc_cc2  : TC - CC - CC2
    full             : |C30| = TC - CC - CC2 - sum(diag)
    c                : |C30| + sum(diag) = TC - CC - CC2

Normalization: cap_fF / (LEN * 1000 * width_um) / 2

Default: only ``*_S0_L*`` cases (diag s2=0, matches DIAGMODEL ON).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from fasterCapParse import (  # noqa: E402
    getMets,
    getWS,
    matrix_rows_to_float,
    parseMatrixRow,
    symmetrize_off_diagonal_avg,
    float_matrix_to_rows,
)
from plot_diagunder_vs_rules import parse_diagunder, plot_out_path  # noqa: E402

METAL_DIAG_HDR = re.compile(r"^Metal\s+(\d+)\s+DIAGUNDER(?:\s+(\d+))?\s*$")
DIAG_S0_RE = re.compile(r"/S[0-9.eE+\-]+_S0_L")

Key = tuple[int, int, float]  # (metal, under, width)
Point3 = tuple[float, float, float]  # (dist, cc, cg)


def width_tag(width: float) -> str:
    return str(width).replace(".", "p")


def wlen(len_mult: int, width_um: float) -> float:
    return len_mult * 1000.0 * width_um


def normalize(cap_fF: float, len_mult: int, width_um: float) -> float:
    return cap_fF / wlen(len_mult, width_um) / 2.0


def count_diag_wires(rows: list[str], met_over: int) -> int:
    tag = f"_M{met_over}_"
    return sum(1 for r in rows if tag in r.split()[0])


def cg_from_caps(
    tc_f: float,
    cc_f: float,
    cc2_f: float,
    diag_sum_f: float,
    *,
    cg_mode: str,
) -> float:
    if cg_mode == "tc_minus_cc":
        return tc_f - cc_f
    if cg_mode == "tc_minus_cc_cc2":
        return tc_f - cc_f - cc2_f
    if cg_mode == "c":
        return tc_f - cc_f - cc2_f
    if cg_mode == "full":
        return tc_f - cc_f - cc2_f - diag_sum_f
    raise ValueError(f"unknown cg_mode: {cg_mode!r}")


def extract_wire3_from_log(
    log_path: Path,
    *,
    met_word: str,
    victim_met: int,
    cg_mode: str,
) -> tuple[float, float, float] | None:
    """Return (CC_fF, CG_fF, TC_fF) for victim wire 3."""
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
    cg_f = cg_from_caps(tc_f, cc_f, cc2_f, diag_sum_f, cg_mode=cg_mode)
    return cc_f, cg_f, tc_f


def parse_log_path(log_path: Path, run_dir: Path) -> dict | None:
    """Parse UnderDiag5 case path: TYP/UnderDiag5/M1duM2/W.../S..._L10/wires.log."""
    try:
        rel = log_path.relative_to(run_dir)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 6 or parts[1] != "UnderDiag5":
        return None

    met_word = parts[2]
    wpart = parts[3]
    spart = parts[4]

    mets = getMets(met_word)
    if int(mets[3]) == 0:
        return None

    victim_met = int(mets[0])
    under_met = int(mets[2])
    width_um = getWS(wpart, "W", 0)
    dist = getWS(spart, "S", 0)
    if "L" not in spart:
        return None
    len_mult = int(spart.split("L")[1])

    return {
        "met_word": met_word,
        "victim_met": victim_met,
        "under": under_met,
        "width_um": width_um,
        "dist": dist,
        "len_mult": len_mult,
        "rel": str(rel),
    }


def collect_wires_log_diagunder(
    run_dir: Path,
    *,
    wire: int = 3,
    diag_s0_only: bool = True,
    cg_mode: str = "tc_minus_cc",
    skip_cases: set[str] | None = None,
    stack: str = "",
    len_mult: int | None = None,
) -> dict[Key, list[Point3]]:
    if wire != 3:
        raise ValueError("only victim wire 3 is supported for UnderDiag5")

    buckets: dict[Key, dict[float, list[Point3]]] = defaultdict(lambda: defaultdict(list))

    for log_path in sorted(run_dir.rglob("wires.log")):
        if log_path.stat().st_size == 0:
            continue
        rel = str(log_path.relative_to(run_dir))
        if "UnderDiag5" not in rel:
            continue
        case = str(log_path.parent.relative_to(run_dir))
        if skip_cases and case in skip_cases:
            continue
        if stack and f"/{stack}/" not in f"/{rel}":
            continue
        if diag_s0_only and not DIAG_S0_RE.search(rel):
            continue

        meta = parse_log_path(log_path, run_dir)
        if meta is None:
            continue
        if len_mult is not None and meta["len_mult"] != len_mult:
            continue

        vals = extract_wire3_from_log(
            log_path,
            met_word=meta["met_word"],
            victim_met=meta["victim_met"],
            cg_mode=cg_mode,
        )
        if vals is None:
            continue

        cc_f, cg_f, _tc_f = vals
        cc_n = normalize(cc_f, meta["len_mult"], meta["width_um"])
        cg_n = normalize(cg_f, meta["len_mult"], meta["width_um"])
        key: Key = (meta["victim_met"], meta["under"], meta["width_um"])
        buckets[key][meta["dist"]].append((meta["dist"], cc_n, cg_n))

    data: dict[Key, list[Point3]] = {}
    for key, by_dist in buckets.items():
        pts = []
        for dist in sorted(by_dist):
            group = by_dist[dist]
            cc_m = sum(p[1] for p in group) / len(group)
            cg_m = sum(p[2] for p in group) / len(group)
            pts.append((dist, cc_m, cg_m))
        data[key] = pts
    return data


def title_key(key: Key) -> str:
    metal, under, width = key
    return f"Metal {metal} DIAGUNDER {under} | width={width:g}"


def fname_key(key: Key) -> str:
    metal, under, width = key
    return f"M{metal}_DIAGUNDER{under}_W{width_tag(width)}.png"


def mae_shared(
    rules: list[Point3], fc: list[Point3], *, col: int
) -> tuple[float | None, int]:
    rmap = {d: p[col] for d, p in ((x[0], x) for x in rules)}
    fmap = {d: p[col] for d, p in ((x[0], x) for x in fc)}
    shared = sorted(set(rmap).intersection(fmap))
    if not shared:
        return None, 0
    mae = sum(abs(rmap[d] - fmap[d]) for d in shared) / len(shared)
    return mae, len(shared)


def plot_vs_rules(
    rules: dict[Key, list[Point3]],
    fc: dict[Key, list[Point3]],
    out_dir: Path,
    *,
    fc_label: str,
) -> int:
    shared = sorted(set(rules).intersection(fc))
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for key in shared:
        rpts = rules[key]
        fpts = fc[key]
        if not rpts or not fpts:
            continue

        rd = [x[0] for x in rpts]
        rcc = [x[1] for x in rpts]
        rcg = [x[2] for x in rpts]
        fd = [x[0] for x in fpts]
        fcc = [x[1] for x in fpts]
        fcg = [x[2] for x in fpts]

        fig, axs = plt.subplots(1, 2, figsize=(12, 5), dpi=130)
        fig.suptitle(title_key(key))

        axs[0].plot(rd, rcc, "o-", label="rules CC (col2)")
        axs[0].plot(fd, fcc, "s-", label=f"{fc_label} |C32|+|C34|")
        axs[0].set_title("Dist vs CC")
        axs[0].set_xlabel("Dist")
        axs[0].grid(True, alpha=0.3)
        axs[0].legend(fontsize=8)

        axs[1].plot(rd, rcg, "o-", label="rules CG (col3)")
        axs[1].plot(fd, fcg, "s-", label=f"{fc_label} CG")
        axs[1].set_title("Dist vs CG")
        axs[1].set_xlabel("Dist")
        axs[1].grid(True, alpha=0.3)
        axs[1].legend(fontsize=8)

        fig.tight_layout(rect=[0, 0, 1, 0.94])
        fig.savefig(plot_out_path(out_dir, "DIAGUNDER", fname_key(key)))
        plt.close(fig)
        n += 1
    return n


def write_summary(
    path: Path,
    shared: list[Key],
    rules: dict[Key, list[Point3]],
    fc: dict[Key, list[Point3]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "metal",
                "under",
                "width",
                "mae_cc",
                "mae_cg",
                "n_dist_shared",
                "rules_cc_at_min_dist",
                "fc_cc_at_min_dist",
            ]
        )
        for key in shared:
            metal, under, width = key
            mae_cc, n = mae_shared(rules[key], fc[key], col=1)
            mae_cg, _ = mae_shared(rules[key], fc[key], col=2)
            r0 = min(rules[key], key=lambda x: x[0])
            f0 = min(fc[key], key=lambda x: x[0])
            w.writerow(
                [
                    metal,
                    under,
                    width,
                    f"{mae_cc:.6g}" if mae_cc is not None else "",
                    f"{mae_cg:.6g}" if mae_cg is not None else "",
                    n,
                    f"{r0[1]:.6g}",
                    f"{f0[1]:.6g}",
                ]
            )


def main() -> None:
    ap = argparse.ArgumentParser(description="Sky130 DIAGUNDER wires.log vs rules")
    ap.add_argument("--run-dir", required=True, help="FasterCap run root (e.g. 6v2_typ_wirefix)")
    ap.add_argument("--rules", required=True, help="sky130hs rcx_patterns.rules")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--summary-csv")
    ap.add_argument("--cg-mode", default="tc_minus_cc", choices=[
        "tc_minus_cc",
        "tc_minus_cc_cc2",
        "full",
        "c",
    ])
    ap.add_argument("--all-diag-spacing", action="store_true")
    ap.add_argument("--fc-label", default="wires.log wire_3")
    ap.add_argument("--skip-list")
    ap.add_argument("--stack", default="")
    ap.add_argument("--len-mult", type=int)
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    rules = parse_diagunder(Path(args.rules))
    skip_cases: set[str] = set()
    if args.skip_list:
        skip_cases = {
            line.strip().removeprefix("./")
            for line in Path(args.skip_list).read_text(errors="replace").splitlines()
            if line.strip()
        }
    fc = collect_wires_log_diagunder(
        run_dir,
        diag_s0_only=not args.all_diag_spacing,
        cg_mode=args.cg_mode,
        skip_cases=skip_cases,
        stack=args.stack,
        len_mult=args.len_mult,
    )
    shared = sorted(set(rules).intersection(fc))
    n = plot_vs_rules(rules, fc, Path(args.out_dir), fc_label=args.fc_label)

    if args.summary_csv:
        write_summary(Path(args.summary_csv), shared, rules, fc)

    print(f"rules_keys={len(rules)}")
    print(f"wires_keys={len(fc)}")
    print(f"shared_keys={len(shared)}")
    print(f"plots={n}")
    print(f"cg_mode={args.cg_mode}")
    print(f"diag_s0_only={not args.all_diag_spacing}")
    print(f"out_dir={args.out_dir}")
    if args.summary_csv:
        print(f"summary_csv={args.summary_csv}")


if __name__ == "__main__":
    main()
