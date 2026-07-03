#!/usr/bin/env python3
"""
Diagnose Sky130 wirefix patterns following the suggested triage order:
1) Is pattern included in caps (sym50 gate)?
2) If not, is it skipped by asymmetry gate?
3) If included and family is O/U/OU, does it match model-vs-rules points?
4) If matched, classify error severity with asymmetry context.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

FAMILY_MAP = {
    "Over5": "OVER",
    "Under5": "UNDER",
    "OverUnder5": "OVER_UNDER",
    "UnderDiag5": "DIAGUNDER",
}


def _f(v: str, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def parse_pattern(pattern: str) -> dict:
    # Example: TYP/Over5/M1oM0/W0.17_W0.17/S0.17_S0.17_L10
    m = re.match(
        r"^TYP/(?P<ptype>[^/]+)/(?P<stack>M[^/]+)/W(?P<w1>[\d.]+)_[^/]+/S(?P<s1>[\d.]+)_[^/]+_L(?P<len>\d+)$",
        pattern,
    )
    if not m:
        return {
            "pattern": pattern,
            "pattern_type": "UNKNOWN",
            "family_eval": "UNKNOWN",
            "metal": "",
            "over": "",
            "under": "",
            "width": "",
            "dist": "",
            "len_mult": "",
        }

    ptype = m.group("ptype")
    stack = m.group("stack")
    width = _f(m.group("w1"))
    dist = _f(m.group("s1"))
    len_mult = int(m.group("len"))

    metal = 0
    over = 0
    under = 0
    if ptype == "Over5":
        mm = re.match(r"M(\d+)oM(\d+)$", stack)
        if mm:
            metal, over = int(mm.group(1)), int(mm.group(2))
    elif ptype == "Under5":
        mm = re.match(r"M(\d+)uM(\d+)$", stack)
        if mm:
            metal, under = int(mm.group(1)), int(mm.group(2))
    elif ptype == "OverUnder5":
        mm = re.match(r"M(\d+)oM(\d+)uM(\d+)$", stack)
        if mm:
            metal, over, under = int(mm.group(1)), int(mm.group(2)), int(mm.group(3))
    elif ptype == "UnderDiag5":
        mm = re.match(r"M(\d+)duM(\d+)$", stack)
        if mm:
            metal, under = int(mm.group(1)), int(mm.group(2))

    return {
        "pattern": pattern,
        "pattern_type": ptype,
        "family_eval": FAMILY_MAP.get(ptype, "UNKNOWN"),
        "metal": metal,
        "over": over,
        "under": under,
        "width": width,
        "dist": dist,
        "len_mult": len_mult,
    }


def load_caps_patterns(caps_path: Path) -> set[str]:
    out: set[str] = set()
    for ln in caps_path.read_text(errors="ignore").splitlines():
        toks = ln.split()
        if not toks:
            continue
        tail = toks[-1]
        if "/wire_3" in tail:
            out.add(tail.rsplit("/wire_3", 1)[0])
    return out


def load_skipped_patterns(skipped_path: Path, run_root: Path) -> set[str]:
    out: set[str] = set()
    if not skipped_path.is_file():
        return out
    prefix = str(run_root.resolve()) + "/"
    for ln in skipped_path.read_text(errors="ignore").splitlines():
        s = ln.strip()
        if not s:
            continue
        path_part = s.split(" rel=", 1)[0].strip()
        if path_part.endswith("/wires.log"):
            path_part = path_part[: -len("/wires.log")]
        if path_part.startswith(prefix):
            path_part = path_part[len(prefix) :]
        out.add(path_part)
    return out


def kf(x: float) -> str:
    return f"{x:.4f}"


def make_diag(row: dict) -> tuple[str, str]:
    fam = row["family_eval"]
    in_caps = row["in_caps"] == "1"
    skipped = row["skipped_asym"] == "1"
    asym = _f(row["strong_pair_max_signed_rel"])
    has_err = row["matched_error"] == "1"
    cc_mae = _f(row["cc_abs_m"])
    cg_mae = _f(row["cg_abs_m"])

    if not in_caps:
        if skipped:
            return (
                "NO_CAPS_ASYM_GATE",
                "sym50 gate: strong asym > 50%, skipped before caps/model",
            )
        return ("NO_CAPS_OTHER", "not in caps subset; check empty/invalid wires.log or parse input")

    if fam == "DIAGUNDER":
        return ("DIAGUNDER_SCOPE_OUT", "excluded from O/U/OU error table; use diagunder-specific compare")

    if fam not in {"OVER", "UNDER", "OVER_UNDER"}:
        return ("UNSUPPORTED_FAMILY", "unknown pattern family")

    if not has_err:
        return ("NO_RULES_MATCH", "in caps but no strict key+dist match in per_dist_points")

    if asym > 0.5:
        return ("IN_CAPS_HIGH_ASYM", "matched but asym unexpectedly high; inspect parser thresholds/data mix")

    max_mae = max(cc_mae, cg_mae)
    if max_mae <= 2e-5:
        return ("MATCH_GOOD", "small abs error; model/rules closely aligned at this point")
    if max_mae <= 5e-5:
        return ("MATCH_MEDIUM_GAP", "moderate gap; likely stack/grid/definition drift, not parse failure")
    return ("MATCH_LARGE_GAP", "large gap with low asym; likely process stack / CG definition mismatch")


def main() -> None:
    ap = argparse.ArgumentParser(description="Per-pattern diagnosis for Sky130 wirefix")
    ap.add_argument("--symmetry-csv", required=True)
    ap.add_argument("--caps", required=True)
    ap.add_argument("--skipped-asym", required=True)
    ap.add_argument("--per-dist", required=True)
    ap.add_argument("--run-root", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    sym_csv = Path(args.symmetry_csv)
    caps_path = Path(args.caps)
    skipped_path = Path(args.skipped_asym)
    per_dist_path = Path(args.per_dist)
    run_root = Path(args.run_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    caps_patterns = load_caps_patterns(caps_path)
    skipped_patterns = load_skipped_patterns(skipped_path, run_root)

    err_map: dict[tuple, dict] = {}
    with per_dist_path.open(newline="") as f:
        for r in csv.DictReader(f):
            key = (
                int(r["metal"]),
                r["family"],
                int(r["over"]),
                int(r["under"]),
                kf(_f(r["width"])),
                kf(_f(r["dist"])),
            )
            err_map[key] = r

    rows = []
    with sym_csv.open(newline="") as f:
        for r in csv.DictReader(f):
            pattern = r["pattern"]
            meta = parse_pattern(pattern)
            in_caps = pattern in caps_patterns
            skipped = pattern in skipped_patterns

            out = {
                **meta,
                "in_caps": "1" if in_caps else "0",
                "skipped_asym": "1" if skipped else "0",
                "nonconv_1000": r.get("nonconv_1000", ""),
                "strong_pair_max_signed_rel": r.get("strong_pair_max_signed_rel", ""),
                "lr_rel_asym": r.get("lr_rel_asym", ""),
                "matched_error": "0",
                "cc_abs": "",
                "cg_abs": "",
                "cc_abs_m": "",
                "cg_abs_m": "",
            }

            if meta["family_eval"] in {"OVER", "UNDER", "OVER_UNDER"}:
                ekey = (
                    int(meta["metal"] or 0),
                    meta["family_eval"],
                    int(meta["over"] or 0),
                    int(meta["under"] or 0),
                    kf(_f(str(meta["width"]))),
                    kf(_f(str(meta["dist"]))),
                )
                em = err_map.get(ekey)
                if em is not None:
                    out["matched_error"] = "1"
                    out["cc_abs"] = em.get("cc_abs", "")
                    out["cg_abs"] = em.get("cg_abs", "")
                    out["cc_abs_m"] = em.get("cc_abs_m", "")
                    out["cg_abs_m"] = em.get("cg_abs_m", "")

            code, note = make_diag(out)
            out["diagnosis_code"] = code
            out["diagnosis_note"] = note
            rows.append(out)

    fieldnames = [
        "pattern",
        "pattern_type",
        "family_eval",
        "metal",
        "over",
        "under",
        "width",
        "dist",
        "len_mult",
        "in_caps",
        "skipped_asym",
        "nonconv_1000",
        "strong_pair_max_signed_rel",
        "lr_rel_asym",
        "matched_error",
        "cc_abs",
        "cg_abs",
        "cc_abs_m",
        "cg_abs_m",
        "diagnosis_code",
        "diagnosis_note",
    ]
    out_csv = out_dir / "pattern_diagnosis.csv"
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    by_code = Counter(r["diagnosis_code"] for r in rows)
    by_type = defaultdict(Counter)
    for r in rows:
        by_type[r["pattern_type"]][r["diagnosis_code"]] += 1

    # representative high-error rows with low asym and valid matches
    reps = [
        r
        for r in rows
        if r["matched_error"] == "1"
        and _f(r["strong_pair_max_signed_rel"]) <= 0.5
        and r["diagnosis_code"] in {"MATCH_MEDIUM_GAP", "MATCH_LARGE_GAP"}
    ]
    reps.sort(key=lambda x: max(_f(x["cc_abs_m"]), _f(x["cg_abs_m"])), reverse=True)
    reps = reps[:15]

    md_lines = [
        "# Sky130 per-pattern diagnosis",
        "",
        f"- Input symmetry rows: **{len(rows)}**",
        f"- In caps: **{sum(1 for r in rows if r['in_caps'] == '1')}**",
        f"- Skipped by asym gate file: **{sum(1 for r in rows if r['skipped_asym'] == '1')}**",
        "",
        "## Diagnosis code counts",
        "",
        "| code | count |",
        "|------|------:|",
    ]
    for code, cnt in sorted(by_code.items(), key=lambda x: (-x[1], x[0])):
        md_lines.append(f"| {code} | {cnt} |")

    md_lines += ["", "## By pattern type", ""]
    for ptype in sorted(by_type):
        md_lines.append(f"### {ptype}")
        md_lines.append("")
        md_lines.append("| code | count |")
        md_lines.append("|------|------:|")
        for code, cnt in sorted(by_type[ptype].items(), key=lambda x: (-x[1], x[0])):
            md_lines.append(f"| {code} | {cnt} |")
        md_lines.append("")

    md_lines += [
        "## Representative medium/large gaps (low asym, matched)",
        "",
        "| pattern | asym | cc_mae | cg_mae | code |",
        "|---------|-----:|-------:|-------:|------|",
    ]
    for r in reps:
        md_lines.append(
            f"| `{r['pattern']}` | {_f(r['strong_pair_max_signed_rel']):.3f} | "
            f"{_f(r['cc_abs_m']):.4g} | {_f(r['cg_abs_m']):.4g} | {r['diagnosis_code']} |"
        )

    out_md = out_dir / "pattern_diagnosis_summary.md"
    out_md.write_text("\n".join(md_lines))

    print(f"Wrote: {out_csv}")
    print(f"Wrote: {out_md}")


if __name__ == "__main__":
    main()
