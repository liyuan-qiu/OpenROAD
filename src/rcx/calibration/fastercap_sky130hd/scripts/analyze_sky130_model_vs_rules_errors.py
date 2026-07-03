#!/usr/bin/env python3
"""
Summarize Sky130 FasterCap model vs rules errors for Over / Under / OverUnder.

Outputs:
  - per_dist_points.csv   : every shared (key, dist) with CC/CG abs & rel error
  - by_family.csv         : MAE / bias by topology family
  - by_metal.csv
  - by_dist_bin.csv       : error vs dist bucket
  - worst_keys.csv        : highest CG MAE keys
  - summary.md            : human-readable report

Excludes DIAGUNDER (use plot_sky130_diagunder_wires_vs_rules.py).
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

from plot_rcx_model_vs_rules import parse_tables

FAMILIES = ("OVER", "UNDER", "OVER_UNDER")
EPS = 1e-15


def key_fields(key: tuple) -> dict:
    metal = key[0]
    family = key[1]
    out: dict = {"metal": metal, "family": family}
    if family == "OVER_UNDER":
        _, _, over, under, width = key
        out.update(over=over, under=under, width=width, context=under)
    elif family == "OVER":
        _, _, over, width = key
        out.update(over=over, under=0, width=width, context=over)
    elif family == "UNDER":
        _, _, under, width = key
        out.update(over=0, under=under, width=width, context=under)
    else:
        out.update(over=0, under=0, width=0.0, context=0)
    return out


def dist_bin(dist: float) -> str:
    if dist <= 0:
        return "0"
    if dist < 0.2:
        return "(0,0.2)"
    if dist < 0.5:
        return "[0.2,0.5)"
    if dist < 1.0:
        return "[0.5,1.0)"
    if dist < 1.5:
        return "[1.0,1.5)"
    return ">=1.5"


def _interp_rules_at_dist(
    rules_pts: list[tuple[float, float, float]],
    dist: float,
    *,
    allow_extrapolation: bool,
) -> dict | None:
    if not rules_pts:
        return None
    rs = sorted(rules_pts, key=lambda x: x[0])
    ds = [x[0] for x in rs]
    i = bisect.bisect_left(ds, dist)

    if i < len(ds) and ds[i] == dist:
        d, cc, cg = rs[i]
        return {
            "rules_cc": cc,
            "rules_cg": cg,
            "dist_match_type": "exact",
            "rules_dist_lo": d,
            "rules_dist_hi": d,
            "rules_cc_lo": cc,
            "rules_cc_hi": cc,
            "rules_cg_lo": cg,
            "rules_cg_hi": cg,
        }

    if i == 0:
        if not allow_extrapolation:
            return None
        d0, cc0, cg0 = rs[0]
        return {
            "rules_cc": cc0,
            "rules_cg": cg0,
            "dist_match_type": "extrap_low_nearest",
            "rules_dist_lo": d0,
            "rules_dist_hi": d0,
            "rules_cc_lo": cc0,
            "rules_cc_hi": cc0,
            "rules_cg_lo": cg0,
            "rules_cg_hi": cg0,
        }

    if i >= len(ds):
        if not allow_extrapolation:
            return None
        d1, cc1, cg1 = rs[-1]
        return {
            "rules_cc": cc1,
            "rules_cg": cg1,
            "dist_match_type": "extrap_high_nearest",
            "rules_dist_lo": d1,
            "rules_dist_hi": d1,
            "rules_cc_lo": cc1,
            "rules_cc_hi": cc1,
            "rules_cg_lo": cg1,
            "rules_cg_hi": cg1,
        }

    d0, cc0, cg0 = rs[i - 1]
    d1, cc1, cg1 = rs[i]
    if d1 == d0:
        cc_i = cc0
        cg_i = cg0
    else:
        t = (dist - d0) / (d1 - d0)
        cc_i = cc0 + t * (cc1 - cc0)
        cg_i = cg0 + t * (cg1 - cg0)
    return {
        "rules_cc": cc_i,
        "rules_cg": cg_i,
        "dist_match_type": "interp",
        "rules_dist_lo": d0,
        "rules_dist_hi": d1,
        "rules_cc_lo": cc0,
        "rules_cc_hi": cc1,
        "rules_cg_lo": cg0,
        "rules_cg_hi": cg1,
    }


def match_points(
    model_pts: list[tuple[float, float, float]],
    rules_pts: list[tuple[float, float, float]],
    *,
    dist_match_mode: str = "strict",
    allow_extrapolation: bool = False,
) -> list[dict]:
    rows = []
    if dist_match_mode == "strict":
        rmap = {d: (cc, cg) for d, cc, cg in rules_pts}
        mmap = {d: (cc, cg) for d, cc, cg in model_pts}
        shared = sorted(set(rmap).intersection(mmap))
        for d in shared:
            mcc, mcg = mmap[d]
            rcc, rcg = rmap[d]
            rows.append(
                {
                    "dist": d,
                    "model_cc": mcc,
                    "rules_cc": rcc,
                    "model_cg": mcg,
                    "rules_cg": rcg,
                    "cc_abs": mcc - rcc,
                    "cg_abs": mcg - rcg,
                    "cc_abs_m": abs(mcc - rcc),
                    "cg_abs_m": abs(mcg - rcg),
                    "cc_rel": abs(mcc - rcc) / max(abs(rcc), EPS),
                    "cg_rel": abs(mcg - rcg) / max(abs(rcg), EPS),
                    "dist_match_type": "exact",
                    "rules_dist_lo": d,
                    "rules_dist_hi": d,
                    "rules_cc_lo": rcc,
                    "rules_cc_hi": rcc,
                    "rules_cg_lo": rcg,
                    "rules_cg_hi": rcg,
                    "rules_cc_span_abs": 0.0,
                    "rules_cg_span_abs": 0.0,
                    "dist_gap_to_lo": 0.0,
                    "dist_gap_to_hi": 0.0,
                }
            )
        return rows

    for d, mcc, mcg in sorted(model_pts, key=lambda x: x[0]):
        rv = _interp_rules_at_dist(rules_pts, d, allow_extrapolation=allow_extrapolation)
        if rv is None:
            continue
        rcc = rv["rules_cc"]
        rcg = rv["rules_cg"]
        dlo = rv["rules_dist_lo"]
        dhi = rv["rules_dist_hi"]
        rows.append(
            {
                "dist": d,
                "model_cc": mcc,
                "rules_cc": rcc,
                "model_cg": mcg,
                "rules_cg": rcg,
                "cc_abs": mcc - rcc,
                "cg_abs": mcg - rcg,
                "cc_abs_m": abs(mcc - rcc),
                "cg_abs_m": abs(mcg - rcg),
                "cc_rel": abs(mcc - rcc) / max(abs(rcc), EPS),
                "cg_rel": abs(mcg - rcg) / max(abs(rcg), EPS),
                "dist_match_type": rv["dist_match_type"],
                "rules_dist_lo": dlo,
                "rules_dist_hi": dhi,
                "rules_cc_lo": rv["rules_cc_lo"],
                "rules_cc_hi": rv["rules_cc_hi"],
                "rules_cg_lo": rv["rules_cg_lo"],
                "rules_cg_hi": rv["rules_cg_hi"],
                "rules_cc_span_abs": abs(rv["rules_cc_hi"] - rv["rules_cc_lo"]),
                "rules_cg_span_abs": abs(rv["rules_cg_hi"] - rv["rules_cg_lo"]),
                "dist_gap_to_lo": abs(d - dlo),
                "dist_gap_to_hi": abs(d - dhi),
            }
        )
    return rows


def agg_stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0, "mean": "", "median": "", "p90": ""}
    s = sorted(vals)
    p90 = s[int(0.9 * (len(s) - 1))]
    return {
        "n": len(vals),
        "mean": statistics.mean(vals),
        "median": statistics.median(vals),
        "p90": p90,
    }


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def plot_error_vs_dist(points: list[dict], out_path: Path, *, yfield: str, title: str) -> None:
    by_family: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for p in points:
        by_family[p["family"]].append((p["dist"], p[yfield]))

    fig, ax = plt.subplots(figsize=(9, 5), dpi=130)
    for fam in FAMILIES:
        pts = by_family.get(fam, [])
        if not pts:
            continue
        pts.sort()
        ax.plot([x[0] for x in pts], [x[1] for x in pts], ".", alpha=0.35, label=fam, markersize=4)

    # binned median trend (all families)
    bins: dict[float, list[float]] = defaultdict(list)
    for p in points:
        bins[round(p["dist"], 4)].append(p[yfield])
    bd = sorted(bins)
    med = [statistics.median(bins[d]) for d in bd]
    ax.plot(bd, med, "k-o", linewidth=1.5, markersize=3, label="median@dist")

    ax.axhline(0, color="gray", linewidth=0.8, linestyle="--")
    ax.set_xlabel("Dist")
    ax.set_ylabel(yfield)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def build_report(
    points: list[dict],
    *,
    model_path: str,
    rules_path: str,
    dist_match_mode: str,
    allow_extrapolation: bool,
) -> str:
    lines = [
        "# Sky130 model vs rules — Over / Under / OverUnder error summary",
        "",
        f"- Model: `{model_path}`",
        f"- Rules: `{rules_path}`",
        f"- Points (after dist match): **{len(points)}**",
        f"- Dist match mode: **{dist_match_mode}** (allow_extrapolation={allow_extrapolation})",
        "",
    ]

    if points:
        by_mt = defaultdict(int)
        for p in points:
            by_mt[p.get("dist_match_type", "unknown")] += 1
        lines.append("## Dist match type counts")
        lines.append("")
        for k in sorted(by_mt):
            lines.append(f"- {k}: **{by_mt[k]}**")
        lines.append("")

        # Overall matched-point stats (exact + interp [+ extrapolation if enabled]).
        cc_mae_all = agg_stats([p["cc_abs_m"] for p in points])
        cg_mae_all = agg_stats([p["cg_abs_m"] for p in points])
        cc_span_all = agg_stats([p["rules_cc_span_abs"] for p in points])
        cg_span_all = agg_stats([p["rules_cg_span_abs"] for p in points])
        dlo_all = agg_stats([p["dist_gap_to_lo"] for p in points])
        dhi_all = agg_stats([p["dist_gap_to_hi"] for p in points])
        lines += [
            "## All-matched error vs rules",
            "",
            f"All matched points: **{len(points)}**",
            "",
            "| metric | mean | median | p90 |",
            "|--------|------|--------|-----|",
            f"| CC abs error | {cc_mae_all['mean']:.4g} | {cc_mae_all['median']:.4g} | {cc_mae_all['p90']:.4g} |",
            f"| CG abs error | {cg_mae_all['mean']:.4g} | {cg_mae_all['median']:.4g} | {cg_mae_all['p90']:.4g} |",
            f"| rules CC span | {cc_span_all['mean']:.4g} | {cc_span_all['median']:.4g} | {cc_span_all['p90']:.4g} |",
            f"| rules CG span | {cg_span_all['mean']:.4g} | {cg_span_all['median']:.4g} | {cg_span_all['p90']:.4g} |",
            f"| dist gap to lo | {dlo_all['mean']:.4g} | {dlo_all['median']:.4g} | {dlo_all['p90']:.4g} |",
            f"| dist gap to hi | {dhi_all['mean']:.4g} | {dhi_all['median']:.4g} | {dhi_all['p90']:.4g} |",
            "",
        ]

        interp_pts = [p for p in points if p.get("dist_match_type") == "interp"]
        if interp_pts:
            cc_mae = agg_stats([p["cc_abs_m"] for p in interp_pts])
            cg_mae = agg_stats([p["cg_abs_m"] for p in interp_pts])
            cc_span = agg_stats([p["rules_cc_span_abs"] for p in interp_pts])
            cg_span = agg_stats([p["rules_cg_span_abs"] for p in interp_pts])
            dlo = agg_stats([p["dist_gap_to_lo"] for p in interp_pts])
            dhi = agg_stats([p["dist_gap_to_hi"] for p in interp_pts])
            lines += [
                "## Interp-only error vs rules span",
                "",
                f"Interp points: **{len(interp_pts)}**",
                "",
                "| metric | mean | median | p90 |",
                "|--------|------|--------|-----|",
                f"| CC abs error | {cc_mae['mean']:.4g} | {cc_mae['median']:.4g} | {cc_mae['p90']:.4g} |",
                f"| CG abs error | {cg_mae['mean']:.4g} | {cg_mae['median']:.4g} | {cg_mae['p90']:.4g} |",
                f"| rules CC span | {cc_span['mean']:.4g} | {cc_span['median']:.4g} | {cc_span['p90']:.4g} |",
                f"| rules CG span | {cg_span['mean']:.4g} | {cg_span['median']:.4g} | {cg_span['p90']:.4g} |",
                f"| dist gap to lo | {dlo['mean']:.4g} | {dlo['median']:.4g} | {dlo['p90']:.4g} |",
                f"| dist gap to hi | {dhi['mean']:.4g} | {dhi['median']:.4g} | {dhi['p90']:.4g} |",
                "",
            ]

    for fam in FAMILIES:
        sub = [p for p in points if p["family"] == fam]
        if not sub:
            continue
        cc = agg_stats([p["cc_abs_m"] for p in sub])
        cg = agg_stats([p["cg_abs_m"] for p in sub])
        cc_bias = statistics.mean([p["cc_abs"] for p in sub])
        cg_bias = statistics.mean([p["cg_abs"] for p in sub])
        lines += [
            f"## {fam}",
            f"- CC MAE mean={cc['mean']:.4g}, median={cc['median']:.4g}, p90={cc['p90']:.4g}; "
            f"mean bias(model-rules)={cc_bias:+.4g}",
            f"- CG MAE mean={cg['mean']:.4g}, median={cg['median']:.4g}, p90={cg['p90']:.4g}; "
            f"mean bias={cg_bias:+.4g}",
            "",
        ]

    lines.append("## Error vs dist (CG MAE by dist bin)")
    lines.append("")
    lines.append("| dist bin | n | CG MAE mean | CG bias mean | CC MAE mean |")
    lines.append("|----------|---|-------------|--------------|-------------|")
    bin_groups: dict[str, list[dict]] = defaultdict(list)
    for p in points:
        bin_groups[dist_bin(p["dist"])].append(p)
    bin_order = ["0", "(0,0.2)", "[0.2,0.5)", "[0.5,1.0)", "[1.0,1.5)", ">=1.5"]
    for b in bin_order:
        g = bin_groups.get(b, [])
        if not g:
            continue
        cg_m = statistics.mean([x["cg_abs_m"] for x in g])
        cg_b = statistics.mean([x["cg_abs"] for x in g])
        cc_m = statistics.mean([x["cc_abs_m"] for x in g])
        lines.append(f"| {b} | {len(g)} | {cg_m:.4g} | {cg_b:+.4g} | {cc_m:.4g} |")
    lines.append("")

    lines.append("## Error vs metal (CG)")
    lines.append("")
    lines.append("| metal | n | CG MAE mean | CG bias | CC MAE mean |")
    lines.append("|-------|---|-------------|---------|-------------|")
    by_m: dict[int, list[dict]] = defaultdict(list)
    for p in points:
        by_m[p["metal"]].append(p)
    for m in sorted(by_m):
        g = by_m[m]
        lines.append(
            f"| M{m} | {len(g)} | "
            f"{statistics.mean([x['cg_abs_m'] for x in g]):.4g} | "
            f"{statistics.mean([x['cg_abs'] for x in g]):+.4g} | "
            f"{statistics.mean([x['cc_abs_m'] for x in g]):.4g} |"
        )
    lines.append("")

    # dist trend: correlation of dist with signed CG error
    if len(points) >= 3:
        ds = [p["dist"] for p in points]
        cg_err = [p["cg_abs"] for p in points]
        mean_d = statistics.mean(ds)
        mean_e = statistics.mean(cg_err)
        num = sum((d - mean_d) * (e - mean_e) for d, e in zip(ds, cg_err))
        den_d = math.sqrt(sum((d - mean_d) ** 2 for d in ds))
        den_e = math.sqrt(sum((e - mean_e) ** 2 for e in cg_err))
        corr = num / (den_d * den_e) if den_d and den_e else 0.0
        lines += [
            "## Dist correlation",
            f"- Pearson(dist, CG signed error) = **{corr:.3f}** "
            f"(positive ⇒ model CG rises with dist vs rules)",
            "",
        ]

    lines.append("## Interpretation notes")
    lines.append("")
    lines.append(
        "- CC and CG MAE are usually **same order of magnitude** across Over/Under/OverUnder "
        "when rules CG is not a flat placeholder."
    )
    lines.append(
        "- **Small dist** often has larger **relative** error (rules CG/CC near zero in denominator)."
    )
    lines.append(
        "- Systematic **positive CG bias** (model > rules) usually indicates process/stack mismatch "
        "or normalization grid differences, not a single pattern bug."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze Sky130 O/U/OU model vs rules errors")
    ap.add_argument("--model", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument(
        "--dist-match-mode",
        choices=["strict", "interp"],
        default="strict",
        help="strict: only exact shared dist; interp: compare model dist against interpolated rules",
    )
    ap.add_argument(
        "--allow-extrapolation",
        action="store_true",
        help="with --dist-match-mode interp, allow nearest-end extrapolation for out-of-range model dist",
    )
    args = ap.parse_args()

    model = parse_tables(Path(args.model), diagunder_columns="model")
    rules = parse_tables(Path(args.rules), diagunder_columns="rules")

    points: list[dict] = []
    key_rows: list[dict] = []

    for key in sorted(set(model).intersection(rules)):
        meta = key_fields(key)
        if meta["family"] not in FAMILIES:
            continue
        matched = match_points(
            model[key],
            rules[key],
            dist_match_mode=args.dist_match_mode,
            allow_extrapolation=args.allow_extrapolation,
        )
        if not matched:
            continue
        for row in matched:
            rec = {**meta, **row}
            points.append(rec)

        cc_mae = statistics.mean([r["cc_abs_m"] for r in matched])
        cg_mae = statistics.mean([r["cg_abs_m"] for r in matched])
        key_rows.append(
            {
                **meta,
                "n_dist": len(matched),
                "cc_mae": cc_mae,
                "cg_mae": cg_mae,
                "cc_bias": statistics.mean([r["cc_abs"] for r in matched]),
                "cg_bias": statistics.mean([r["cg_abs"] for r in matched]),
            }
        )

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    pt_fields = [
        "metal", "family", "over", "under", "width", "context", "dist",
        "model_cc", "rules_cc", "model_cg", "rules_cg",
        "cc_abs", "cg_abs", "cc_abs_m", "cg_abs_m", "cc_rel", "cg_rel",
        "dist_match_type", "rules_dist_lo", "rules_dist_hi",
        "rules_cc_lo", "rules_cc_hi", "rules_cg_lo", "rules_cg_hi",
        "rules_cc_span_abs", "rules_cg_span_abs", "dist_gap_to_lo", "dist_gap_to_hi",
    ]
    write_csv(out / "per_dist_points.csv", pt_fields, points)

    # by family
    fam_rows = []
    for fam in FAMILIES:
        sub = [p for p in points if p["family"] == fam]
        if not sub:
            continue
        fam_rows.append(
            {
                "family": fam,
                "n_points": len(sub),
                "cc_mae_mean": statistics.mean([p["cc_abs_m"] for p in sub]),
                "cg_mae_mean": statistics.mean([p["cg_abs_m"] for p in sub]),
                "cc_bias_mean": statistics.mean([p["cc_abs"] for p in sub]),
                "cg_bias_mean": statistics.mean([p["cg_abs"] for p in sub]),
                "cc_rel_median": statistics.median([p["cc_rel"] for p in sub]),
                "cg_rel_median": statistics.median([p["cg_rel"] for p in sub]),
            }
        )
    write_csv(
        out / "by_family.csv",
        list(fam_rows[0].keys()) if fam_rows else ["family"],
        fam_rows,
    )

    # by metal
    by_m: dict[int, list[dict]] = defaultdict(list)
    for p in points:
        by_m[p["metal"]].append(p)
    metal_rows = []
    for m in sorted(by_m):
        g = by_m[m]
        metal_rows.append(
            {
                "metal": m,
                "n_points": len(g),
                "cc_mae_mean": statistics.mean([x["cc_abs_m"] for x in g]),
                "cg_mae_mean": statistics.mean([x["cg_abs_m"] for x in g]),
                "cc_bias_mean": statistics.mean([x["cc_abs"] for x in g]),
                "cg_bias_mean": statistics.mean([x["cg_abs"] for x in g]),
            }
        )
    write_csv(out / "by_metal.csv", list(metal_rows[0].keys()) if metal_rows else ["metal"], metal_rows)

    # by dist bin
    bin_groups: dict[str, list[dict]] = defaultdict(list)
    for p in points:
        bin_groups[dist_bin(p["dist"])].append(p)
    bin_rows = []
    for b in ["0", "(0,0.2)", "[0.2,0.5)", "[0.5,1.0)", "[1.0,1.5)", ">=1.5"]:
        g = bin_groups.get(b, [])
        if not g:
            continue
        bin_rows.append(
            {
                "dist_bin": b,
                "n_points": len(g),
                "cc_mae_mean": statistics.mean([x["cc_abs_m"] for x in g]),
                "cg_mae_mean": statistics.mean([x["cg_abs_m"] for x in g]),
                "cc_bias_mean": statistics.mean([x["cc_abs"] for x in g]),
                "cg_bias_mean": statistics.mean([x["cg_abs"] for x in g]),
            }
        )
    write_csv(out / "by_dist_bin.csv", list(bin_rows[0].keys()) if bin_rows else ["dist_bin"], bin_rows)

    worst = sorted(key_rows, key=lambda r: r["cg_mae"], reverse=True)[:20]
    write_csv(
        out / "worst_keys_cg.csv",
        list(worst[0].keys()) if worst else ["metal"],
        worst,
    )

    report = build_report(
        points,
        model_path=args.model,
        rules_path=args.rules,
        dist_match_mode=args.dist_match_mode,
        allow_extrapolation=args.allow_extrapolation,
    )
    (out / "summary.md").write_text(report)

    plot_error_vs_dist(
        points,
        out / "cg_signed_error_vs_dist.png",
        yfield="cg_abs",
        title="CG signed error (model - rules) vs dist",
    )
    plot_error_vs_dist(
        points,
        out / "cg_abs_error_vs_dist.png",
        yfield="cg_abs_m",
        title="CG |error| vs dist",
    )
    plot_error_vs_dist(
        points,
        out / "cc_abs_error_vs_dist.png",
        yfield="cc_abs_m",
        title="CC |error| vs dist",
    )

    print(f"points={len(points)}")
    print(f"keys={len(key_rows)}")
    print(f"out_dir={out}")
    print(f"report={out / 'summary.md'}")


if __name__ == "__main__":
    main()
