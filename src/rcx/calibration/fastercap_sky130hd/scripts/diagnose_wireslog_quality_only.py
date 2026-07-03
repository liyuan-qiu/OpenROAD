#!/usr/bin/env python3
"""
Classify wires.log quality issues without any rules/model comparison.

Input: symmetry_full.csv from analyze_symmetry_full.py
Output:
  - wireslog_quality_only.csv
  - wireslog_quality_only_summary.md
"""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def _f(v: str, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def classify_asym(v: str) -> str:
    if v in ("", None):
        return "NO_STRONG_PAIR"
    x = _f(v)
    if x < 0.05:
        return "ASYM_GOOD_LT5"
    if x < 0.5:
        return "ASYM_WARN_5_TO_50"
    return "ASYM_BAD_GT50"


def classify_sign(r: dict) -> str:
    flips = int(_f(r.get("sign_flip_pairs", "0")))
    pos_strong = int(_f(r.get("pos_offdiag_strong", "0")))
    if flips > 0 and pos_strong > 0:
        return "SIGN_FLIP_AND_POS_STRONG"
    if flips > 0:
        return "SIGN_FLIP_ONLY"
    if pos_strong > 0:
        return "POS_STRONG_ONLY"
    return "SIGN_OK"


def main() -> None:
    ap = argparse.ArgumentParser(description="Diagnose wires.log issues only")
    ap.add_argument("--input-csv", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument(
        "--pattern-diagnosis-csv",
        default="",
        help="Optional pattern_diagnosis.csv for rules-error impact analysis (matched only)",
    )
    args = ap.parse_args()

    in_csv = Path(args.input_csv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    with in_csv.open(newline="") as f:
        for r in csv.DictReader(f):
            asym_class = classify_asym(r.get("strong_pair_max_signed_rel", ""))
            sign_class = classify_sign(r)

            if int(_f(r.get("parsed_matrix", "0"))) == 0:
                quality = "PARSE_FAIL"
            elif int(_f(r.get("nonconv_1000", "0"))) > 0:
                quality = "NONCONV_1000"
            elif asym_class == "ASYM_BAD_GT50":
                quality = "BAD_ASYM"
            elif sign_class != "SIGN_OK":
                quality = "SIGN_ISSUE"
            elif asym_class == "ASYM_WARN_5_TO_50":
                quality = "WARN_ASYM"
            else:
                quality = "GOOD"

            out = {
                "pattern": r.get("pattern", ""),
                "pattern_type": r.get("pattern_type", ""),
                "parsed_matrix": r.get("parsed_matrix", ""),
                "nonconv_1000": r.get("nonconv_1000", ""),
                "strong_pair_max_signed_rel": r.get("strong_pair_max_signed_rel", ""),
                "strong_asym_class": asym_class,
                "sign_flip_pairs": r.get("sign_flip_pairs", ""),
                "pos_offdiag_strong": r.get("pos_offdiag_strong", ""),
                "sign_class": sign_class,
                "lr_rel_asym": r.get("lr_rel_asym", ""),
                "quality_class": quality,
            }
            rows.append(out)

    out_csv = out_dir / "wireslog_quality_only.csv"
    fields = [
        "pattern",
        "pattern_type",
        "parsed_matrix",
        "nonconv_1000",
        "strong_pair_max_signed_rel",
        "strong_asym_class",
        "sign_flip_pairs",
        "pos_offdiag_strong",
        "sign_class",
        "lr_rel_asym",
        "quality_class",
    ]
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    asym_order = ["ASYM_GOOD_LT5", "ASYM_WARN_5_TO_50", "ASYM_BAD_GT50", "NO_STRONG_PAIR"]
    sign_order = ["SIGN_OK", "POS_STRONG_ONLY", "SIGN_FLIP_ONLY", "SIGN_FLIP_AND_POS_STRONG"]
    type_order = ["Over5", "Under5", "OverUnder5", "UnderDiag5"]
    type_label = {
        "Over5": "Over",
        "Under5": "Under",
        "OverUnder5": "OverUnder",
        "UnderDiag5": "DiagUnder",
    }

    by_asym = Counter(r["strong_asym_class"] for r in rows)
    by_sign = Counter(r["sign_class"] for r in rows)
    by_quality = Counter(r["quality_class"] for r in rows)
    parse_fail = sum(1 for r in rows if int(_f(r.get("parsed_matrix", "0"))) == 0)
    nonconv = sum(1 for r in rows if int(_f(r.get("nonconv_1000", "0"))) > 0)

    def cross_counts(sub_rows: list[dict]) -> dict[str, dict[str, int]]:
        mat: dict[str, dict[str, int]] = {
            a: {s: 0 for s in sign_order} for a in asym_order
        }
        for rr in sub_rows:
            a = rr["strong_asym_class"]
            s = rr["sign_class"]
            if a not in mat:
                continue
            if s not in mat[a]:
                continue
            mat[a][s] += 1
        return mat

    def emit_cross_table(lines: list[str], sub_rows: list[dict], title: str) -> None:
        mat = cross_counts(sub_rows)
        lines += [
            f"### {title}",
            "",
            "| Symmetry \\ Sign | SIGN_OK | POS_STRONG_ONLY | SIGN_FLIP_ONLY | SIGN_FLIP_AND_POS_STRONG | Row total |",
            "|------------------|--------:|----------------:|---------------:|-------------------------:|----------:|",
        ]
        for a in asym_order:
            rsum = sum(mat[a][s] for s in sign_order)
            lines.append(
                f"| {a} | {mat[a]['SIGN_OK']} | {mat[a]['POS_STRONG_ONLY']} | "
                f"{mat[a]['SIGN_FLIP_ONLY']} | {mat[a]['SIGN_FLIP_AND_POS_STRONG']} | {rsum} |"
            )
        col_tot = {s: sum(mat[a][s] for a in asym_order) for s in sign_order}
        total = sum(col_tot.values())
        lines.append(
            f"| **Col total** | **{col_tot['SIGN_OK']}** | **{col_tot['POS_STRONG_ONLY']}** | "
            f"**{col_tot['SIGN_FLIP_ONLY']}** | **{col_tot['SIGN_FLIP_AND_POS_STRONG']}** | **{total}** |"
        )
        lines.append("")

    lines = [
        "# Sky130 wires.log quality diagnosis only",
        "",
        f"- Input rows: **{len(rows)}**",
        "- Scope: asymmetry/sign/convergence from wires.log-derived symmetry CSV only",
        "- No rules/model comparison used",
        "- Dimensions:",
        "  - `Symmetry`: `ASYM_GOOD_LT5` / `ASYM_WARN_5_TO_50` / `ASYM_BAD_GT50` / `NO_STRONG_PAIR`",
        "  - `Sign`: `SIGN_OK` / `POS_STRONG_ONLY` / `SIGN_FLIP_ONLY` / `SIGN_FLIP_AND_POS_STRONG`",
        "",
        "## Data sanity",
        "",
        "| item | count |",
        "|------|------:|",
        f"| parsed_matrix=0 | {parse_fail} |",
        f"| nonconv_1000>0 | {nonconv} |",
        "",
        "## Overall marginal counts",
        "",
        "| Symmetry bucket | count |",
        "|-----------------|------:|",
    ]
    for k in asym_order:
        v = by_asym.get(k, 0)
        lines.append(f"| {k} | {v} |")

    lines += ["", "| Sign bucket | count |", "|-------------|------:|"]
    for k in sign_order:
        v = by_sign.get(k, 0)
        lines.append(f"| {k} | {v} |")

    lines += ["", "| Composite quality_class | count |", "|-------------------------|------:|"]
    for k, v in sorted(by_quality.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| {k} | {v} |")

    lines += ["", "## Symmetry × Sign overlap", ""]
    emit_cross_table(lines, rows, "Overall")

    lines += ["## By topology (Symmetry × Sign)", ""]
    for ptype in type_order:
        sub = [r for r in rows if r["pattern_type"] == ptype]
        emit_cross_table(lines, sub, f"{type_label[ptype]} ({ptype}, n={len(sub)})")

    pd_csv = Path(args.pattern_diagnosis_csv) if args.pattern_diagnosis_csv else None
    if pd_csv and pd_csv.is_file():
        pd_map = {}
        with pd_csv.open(newline="") as f:
            for r in csv.DictReader(f):
                pd_map[r.get("pattern", "")] = r

        joined = []
        for r in rows:
            p = r["pattern"]
            pr = pd_map.get(p)
            if not pr:
                continue
            if pr.get("matched_error") != "1":
                continue
            cc = _f(pr.get("cc_abs_m", ""))
            cg = _f(pr.get("cg_abs_m", ""))
            joined.append(
                {
                    **r,
                    "cc_mae": cc,
                    "cg_mae": cg,
                    "max_mae": max(cc, cg),
                }
            )

        def stat_block(sub: list[dict]) -> dict:
            if not sub:
                return {"n": 0}
            cc = [x["cc_mae"] for x in sub]
            cg = [x["cg_mae"] for x in sub]
            mm = sorted(x["max_mae"] for x in sub)
            p90 = mm[int(0.9 * (len(mm) - 1))]
            return {
                "n": len(sub),
                "cc_mean": statistics.mean(cc),
                "cg_mean": statistics.mean(cg),
                "max_mean": statistics.mean(mm),
                "max_median": statistics.median(mm),
                "max_p90": p90,
            }

        all_m = stat_block(joined)
        good_sign = stat_block(
            [
                x
                for x in joined
                if x["strong_asym_class"] == "ASYM_GOOD_LT5" and x["sign_class"] == "SIGN_OK"
            ]
        )
        by_asym_stats = {a: stat_block([x for x in joined if x["strong_asym_class"] == a]) for a in asym_order}
        by_sign_stats = {s: stat_block([x for x in joined if x["sign_class"] == s]) for s in sign_order}

        def fmt(v: float) -> str:
            return f"{v:.4g}"

        lines += [
            "## Impact on rules error (matched only)",
            "",
            "> Source: join with `pattern_diagnosis.csv`; only rows with `matched_error=1` are included.",
            "",
            f"- matched rows total: **{all_m['n']}**",
            f"- `ASYM_GOOD_LT5 ∩ SIGN_OK` matched rows: **{good_sign['n']}**",
            "",
            "| group | n | cc_mae mean | cg_mae mean | max_mae mean | max_mae median | max_mae p90 |",
            "|------|--:|------------:|------------:|-------------:|---------------:|------------:|",
            f"| ALL matched | {all_m['n']} | {fmt(all_m['cc_mean'])} | {fmt(all_m['cg_mean'])} | {fmt(all_m['max_mean'])} | {fmt(all_m['max_median'])} | {fmt(all_m['max_p90'])} |",
            f"| ASYM_GOOD_LT5 ∩ SIGN_OK | {good_sign['n']} | {fmt(good_sign['cc_mean'])} | {fmt(good_sign['cg_mean'])} | {fmt(good_sign['max_mean'])} | {fmt(good_sign['max_median'])} | {fmt(good_sign['max_p90'])} |",
            "",
            "### By symmetry bucket (matched only)",
            "",
            "| bucket | n | max_mae mean | max_mae p90 |",
            "|--------|--:|-------------:|------------:|",
        ]
        for a in asym_order:
            st = by_asym_stats[a]
            if st["n"] == 0:
                lines.append(f"| {a} | 0 | - | - |")
            else:
                lines.append(f"| {a} | {st['n']} | {fmt(st['max_mean'])} | {fmt(st['max_p90'])} |")

        lines += [
            "",
            "### By sign bucket (matched only)",
            "",
            "| bucket | n | max_mae mean | max_mae p90 |",
            "|--------|--:|-------------:|------------:|",
        ]
        for s in sign_order:
            st = by_sign_stats[s]
            if st["n"] == 0:
                lines.append(f"| {s} | 0 | - | - |")
            else:
                lines.append(f"| {s} | {st['n']} | {fmt(st['max_mean'])} | {fmt(st['max_p90'])} |")

    out_md = out_dir / "wireslog_quality_only_summary.md"
    out_md.write_text("\n".join(lines))

    print(f"Wrote: {out_csv}")
    print(f"Wrote: {out_md}")


if __name__ == "__main__":
    main()
