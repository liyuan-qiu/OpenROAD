#!/usr/bin/env python3
"""Generate extended rerun pattern list from empty-bin risks.

This script starts from empty table entries in model risk CSV and maps them to
likely pattern families. Compared with strict one-to-one mapping, it expands
the selection to include more width/spacing variants in the same relation,
which improves chances of filling WIDTH/DIST buckets.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path


W_RE = re.compile(r"/W([0-9.]+)_W?([0-9.]+)/")
S_RE = re.compile(r"/S([0-9.]+)_S?([0-9.]+)_")


@dataclass(frozen=True)
class Case:
    relpath: str
    family: str
    relation: str
    w1: str
    w2: str
    s1: str
    s2: str


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".", help="fasterCap root directory")
    p.add_argument("--run-dir", default="5v2_typ/TYP", help="pattern case root")
    p.add_argument(
        "--risk-csv",
        default="model/130_rcx_risks.csv",
        help="risk CSV from check_rcx_model_risks.py",
    )
    p.add_argument(
        "--out-list",
        default="rerun_extended_candidates.list",
        help="output rerun list path (relative to root)",
    )
    p.add_argument(
        "--out-meta",
        default="rerun_extended_candidates.meta.csv",
        help="output mapping meta CSV (relative to root)",
    )
    p.add_argument(
        "--base-results-csv",
        default="rerun_missing_priority_results.csv",
        help="existing run results, used to avoid already-ok cases",
    )
    return p.parse_args()


def load_cases(root: Path, run_dir: str) -> list[Case]:
    cases: list[Case] = []
    base = root / run_dir
    for w in base.rglob("wires"):
        rel = w.parent.relative_to(root / "5v2_typ")
        rel_s = str(rel)
        parts = rel_s.split("/")
        if len(parts) < 5:
            continue
        family = parts[1]
        relation = parts[2]
        mw = W_RE.search("/" + rel_s + "/")
        ms = S_RE.search("/" + rel_s + "/")
        if not mw:
            continue
        s1 = ms.group(1) if ms else ""
        s2 = ms.group(2) if ms else ""
        cases.append(
            Case(
                relpath=rel_s,
                family=family,
                relation=relation,
                w1=mw.group(1),
                w2=mw.group(2),
                s1=s1,
                s2=s2,
            )
        )
    return cases


def relation_patterns(metal: str, model_type: str, suffix: str) -> list[str]:
    m = f"M{metal}"
    pats: list[str] = []
    s = suffix.strip()
    if model_type == "OVER0":
        pats.append(f"TYP/Over5/{m}oM0/*")
    elif model_type == "OVER1":
        pats.append(f"TYP/Over5/{m}oM1/*")
    elif model_type == "RESOVER":
        if s and s.lstrip("-").isdigit():
            pats.append(f"TYP/Over5/{m}oM{s}/*")
    elif model_type == "OVER":
        m2 = re.match(r"^(\d+)\s+UNDER\s+(\d+)$", s)
        if m2:
            over_m, under_m = m2.groups()
            pats.append(f"TYP/OverUnder5/{m}oM{over_m}uM{under_m}/*")
        elif s and s.lstrip("-").isdigit():
            pats.append(f"TYP/Over5/{m}oM{s}/*")
    elif model_type in ("UNDER", "UNDER0", "UNDER1"):
        if s and s.lstrip("-").isdigit():
            pats.append(f"TYP/Under5/{m}uM{s}/*")
            pats.append(f"TYP/OverUnder5/{m}oM*uM{s}/*")
    elif model_type == "DIAGUNDER":
        if s and s.lstrip("-").isdigit():
            pats.append(f"TYP/UnderDiag5/{m}duM{s}/*")
    elif model_type.startswith("OVERUNDER"):
        pats.append(f"TYP/OverUnder5/{m}oM*uM*/*")
    return pats


def matches(case: Case, patterns: list[str], dist_width: str) -> bool:
    if patterns and not any(fnmatch.fnmatch(case.relpath, p) for p in patterns):
        return False
    if dist_width and dist_width not in (case.w1, case.w2):
        return False
    return True


def load_ok_cases(root: Path, csv_path: str) -> set[str]:
    out: set[str] = set()
    p = root / csv_path
    if not p.exists():
        return out
    with p.open() as f:
        for r in csv.DictReader(f):
            if (r.get("state") or "").strip() == "ok":
                c = (r.get("case") or "").strip()
                if c:
                    out.add(c)
    return out


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    cases = load_cases(root, args.run_dir)
    ok_cases = load_ok_cases(root, args.base_results_csv)

    by_relation: dict[tuple[str, str], list[Case]] = {}
    for c in cases:
        by_relation.setdefault((c.family, c.relation), []).append(c)

    picked: set[str] = set()
    meta_rows: list[dict[str, str]] = []

    with (root / args.risk_csv).open() as f:
        for r in csv.DictReader(f):
            if r.get("category") not in ("empty_width_table", "empty_dist_table"):
                continue
            metal = (r.get("metal") or "").strip()
            model_type = (r.get("model_type") or "").strip()
            suffix = (r.get("model_suffix") or "").strip()
            dist_width = (r.get("dist_width") or "").strip()
            if not metal:
                continue

            pats = relation_patterns(metal, model_type, suffix)
            direct = [c for c in cases if matches(c, pats, dist_width)]

            # Expansion: for direct hits, include all width/spacing variants in the
            # same family+relation; this is the "more likely bins" extension.
            expanded: set[str] = set()
            for c in direct:
                for x in by_relation.get((c.family, c.relation), []):
                    expanded.add(x.relpath)

            # Keep only non-ok cases for rerun list.
            rerun = sorted(x for x in expanded if x not in ok_cases)
            picked.update(rerun)

            meta_rows.append(
                {
                    "line": r.get("line", ""),
                    "category": r.get("category", ""),
                    "metal": metal,
                    "model_type": model_type,
                    "model_suffix": suffix,
                    "dist_width": dist_width,
                    "pattern_globs": "|".join(pats),
                    "direct_hits": str(len(direct)),
                    "expanded_hits": str(len(expanded)),
                    "rerun_candidates": str(len(rerun)),
                    "sample_rerun": "|".join(rerun[:8]),
                }
            )

    out_list = root / args.out_list
    out_meta = root / args.out_meta
    out_list.write_text("".join(f"{x}\n" for x in sorted(picked)))
    if meta_rows:
        with out_meta.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(meta_rows[0].keys()))
            w.writeheader()
            w.writerows(meta_rows)
    else:
        out_meta.write_text("line,category,metal,model_type,model_suffix,dist_width,pattern_globs,direct_hits,expanded_hits,rerun_candidates,sample_rerun\n")

    print(f"cases_total={len(cases)}")
    print(f"rerun_candidates={len(picked)}")
    print(f"out_list={out_list}")
    print(f"out_meta={out_meta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

