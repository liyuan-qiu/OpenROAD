#!/usr/bin/env python3
"""Compare FasterCap caps from wires.log.panel74 vs wires.log.panel79 side-by-side."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import re
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def load_fastercap_parse(fc_dir: Path):
    mod_path = fc_dir / "scripts" / "fasterCapParse.py"
    spec = importlib.util.spec_from_file_location("fasterCapParse", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def panel_count(log_path: Path) -> int | None:
    for line in log_path.read_text(errors="replace").splitlines():
        if "Number of input panels:" in line and "conductors" in line:
            m = re.search(r"panels: (\d+)", line)
            if m:
                return int(m.group(1))
    return None


def parse_wire_caps(fcp, log_path: Path, wire: int) -> dict[str, dict]:
    """Return {full_net_name: {tc, cc, fr, cc2}} for target wire rows."""
    import io

    out = io.StringIO()
    warn = io.StringIO()
    empty = io.StringIO()
    stats = io.StringIO()
    ret = fcp.readFasterCapOutPutLog(
        str(log_path),
        out,
        warn,
        empty,
        stats,
        dbg=0,
        symmetrize_avg=True,
    )
    if ret[0] != 1:
        return {}

    rows: dict[str, dict] = {}
    for line in out.getvalue().splitlines():
        if f"wire_{wire}" not in line:
            continue
        m = re.search(
            r"CC\s+([\d.e+-]+)\s+FR\s+([\d.e+-]+)\s+TC\s+([\d.e+-]+)\s+CC2\s+([\d.e+-]+)\s+(\S+wire_\d+)",
            line,
        )
        if not m:
            continue
        key = m.group(5).strip()
        cc, fr, tc, cc2 = (float(m.group(i)) for i in range(1, 5))
        rows[key] = {"cc": cc, "fr": fr, "tc": tc, "cc2": cc2, "cg": tc - cc - cc2}
    return rows


def ratio_bin(dist: float) -> float:
    edges = [
        (0.21, 0.5),
        (0.30, 1),
        (0.43, 2),
        (0.68, 3),
        (0.94, 4),
        (1.15, 5),
        (1.36, 6),
        (1.70, 7),
        (2.04, 8),
        (2.38, 9),
        (2.72, 10),
    ]
    for hi, rb in edges:
        if dist <= hi + 1e-9:
            return rb
    return dist


def rel_err(a: float, b: float) -> float:
    den = max(abs(a), abs(b), 1e-30)
    return abs(a - b) / den


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fc-dir", type=Path, required=True)
    ap.add_argument("--run-dir", default="6v2_typ_ict_smoke")
    ap.add_argument("--case-list", type=Path, default=None)
    ap.add_argument("--wire", type=int, default=3)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    fc_dir = args.fc_dir.resolve()
    run_root = fc_dir / args.run_dir
    case_list = args.case_list or (run_root / "panel79_rerun_case_list.txt")
    out_dir = args.out_dir or (
        fc_dir / "model" / f"panel74_vs_panel79_{datetime.now():%Y%m%d}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    fcp = load_fastercap_parse(fc_dir)
    cases = [ln.strip() for ln in case_list.read_text().splitlines() if ln.strip()]

    per_case: list[dict] = []
    missing = 0
    for rel in cases:
        d = run_root / rel
        p74 = d / "wires.log.panel74"
        p79 = d / "wires.log.panel79"
        if not p74.is_file() or not p79.is_file():
            missing += 1
            continue
        caps74 = parse_wire_caps(fcp, p74, args.wire)
        caps79 = parse_wire_caps(fcp, p79, args.wire)
        pan74 = panel_count(p74)
        pan79 = panel_count(p79)

        sm = re.search(r"S(\d+\.?\d*)_", rel)
        dist = float(sm.group(1)) if sm else 0.0
        rb = ratio_bin(dist)
        family = rel.split("/")[2] if len(rel.split("/")) > 2 else "?"

        for key in sorted(set(caps74) | set(caps79)):
            c74 = caps74.get(key)
            c79 = caps79.get(key)
            if not c74 or not c79:
                continue
            row = {
                "case": rel,
                "family": family,
                "dist": dist,
                "ratio_bin": rb,
                "panel74": pan74,
                "panel79": pan79,
                "net": key,
                "tc74": c74["tc"],
                "tc79": c79["tc"],
                "cc74": c74["cc"],
                "cc79": c79["cc"],
                "cg74": c74["cg"],
                "cg79": c79["cg"],
                "tc_rel_err": rel_err(c74["tc"], c79["tc"]),
                "cc_rel_err": rel_err(c74["cc"], c79["cc"]),
                "cg_rel_err": rel_err(c74["cg"], c79["cg"]),
            }
            per_case.append(row)

    csv_path = out_dir / "per_case_wire3.tsv"
    fields = list(per_case[0].keys()) if per_case else []
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
        w.writeheader()
        w.writerows(per_case)

    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for r in per_case:
        by_key[(r["family"], r["ratio_bin"], r["panel74"], r["panel79"])].append(r)

    summary_lines = [
        "# Panel74 vs Panel79 FasterCap comparison",
        "",
        f"- Run dir: `{args.run_dir}`",
        f"- Cases in list: {len(cases)}",
        f"- Compared wire_{args.wire} rows: {len(per_case)}",
        f"- Missing panel74/panel79 pair: {missing}",
        "",
        "## By family / ratio_bin / panel transition",
        "",
        "| family | ratio_bin | panel74 | panel79 | n | CC rel err (med) | CG rel err (med) | TC rel err (med) |",
        "|--------|-----------|---------|---------|---|------------------|------------------|------------------|",
    ]

    agg_path = out_dir / "by_family_ratio_bin.tsv"
    agg_rows = []
    for (fam, rb, p74, p79), rows in sorted(by_key.items()):
        cc_med = statistics.median(r["cc_rel_err"] for r in rows)
        cg_med = statistics.median(r["cg_rel_err"] for r in rows)
        tc_med = statistics.median(r["tc_rel_err"] for r in rows)
        agg_rows.append(
            {
                "family": fam,
                "ratio_bin": rb,
                "panel74": p74,
                "panel79": p79,
                "n": len(rows),
                "cc_rel_err_med": cc_med,
                "cg_rel_err_med": cg_med,
                "tc_rel_err_med": tc_med,
            }
        )
        summary_lines.append(
            f"| {fam} | {rb} | {p74} | {p79} | {len(rows)} | "
            f"{cc_med:.4g} | {cg_med:.4g} | {tc_med:.4g} |"
        )

    with agg_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(agg_rows[0].keys()) if agg_rows else [], delimiter="\t")
        if agg_rows:
            w.writeheader()
            w.writerows(agg_rows)

    m1 = [r for r in per_case if "M1oM0" in r["case"]]
    if m1:
        summary_lines += ["", "## M1oM0 detail (wire_3)", ""]
        summary_lines.append(
            "| dist | ratio_bin | panel74→79 | CC74 | CC79 | CC rel | CG74 | CG79 | CG rel |"
        )
        summary_lines.append("|------|-----------|------------|------|------|--------|------|------|--------|")
        for r in sorted(m1, key=lambda x: x["dist"]):
            summary_lines.append(
                f"| {r['dist']} | {r['ratio_bin']} | {r['panel74']}→{r['panel79']} | "
                f"{r['cc74']:.6f} | {r['cc79']:.6f} | {r['cc_rel_err']:.4g} | "
                f"{r['cg74']:.6f} | {r['cg79']:.6f} | {r['cg_rel_err']:.4g} |"
            )

    (out_dir / "summary.md").write_text("\n".join(summary_lines) + "\n")
    print(f"Wrote {csv_path}")
    print(f"Wrote {agg_path}")
    print(f"Wrote {out_dir / 'summary.md'}")


if __name__ == "__main__":
    main()
