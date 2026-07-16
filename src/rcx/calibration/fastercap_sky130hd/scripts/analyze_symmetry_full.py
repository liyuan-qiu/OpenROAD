#!/usr/bin/env python3
"""Full symmetry analysis for all wirefix wires.log files."""

from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
FC_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(FC_DIR.parent / "fastercapnangate45" / "scripts"))

from scan_wires_quality import STRONG_TH, parse_last_matrix, rel_asym, scan_log  # noqa: E402

from matrix_quality_gate import GateConfig, evaluate_matrix_quality_gate  # noqa: E402

DIM_RE = re.compile(r"^\s*Dimension\s+(\d+)\s+x\s+\d+\s*$", re.I)


def pattern_type(pattern: str) -> str:
    m = re.match(r"TYP/([^/]+)/", pattern)
    return m.group(1) if m else "unknown"


def target_met_from_pattern(pattern: str) -> int | None:
    for pat in (
        r"/M(\d+)oM(\d+)uM(\d+)/",
        r"/M(\d+)oM(\d+)/",
        r"/M(\d+)uM(\d+)/",
        r"/M(\d+)duM(\d+)/",
    ):
        m = re.search(pat, pattern)
        if m:
            return int(m.group(1))
    return None


def parse_last_matrix_with_names(text: str) -> tuple[list[str], list[list[float]]] | None:
    lines = text.splitlines()
    last = None
    i = 0
    while i < len(lines):
        m = DIM_RE.match(lines[i])
        if not m:
            i += 1
            continue
        n = int(m.group(1))
        names: list[str] = []
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
            names.append(toks[0])
            rows.append([float(x) for x in toks[1 : n + 1]])
        if ok and len(rows) == n:
            last = (names, rows)
            i += n + 1
        else:
            i += 1
    return last


def victim_lr_metrics(log_path: Path, root: Path) -> dict[str, str]:
    rel = str(log_path.relative_to(root)).replace("/wires.log", "")
    empty = {
        "lr_status": "empty",
        "c32_fF": "",
        "c34_fF": "",
        "lr_rel_asym": "",
        "cc_fF": "",
        "t32_rel": "",
        "t34_rel": "",
    }
    if log_path.stat().st_size == 0:
        return empty

    parsed = parse_last_matrix_with_names(log_path.read_text(errors="replace"))
    if parsed is None:
        return {**empty, "lr_status": "no_matrix"}

    names, matrix = parsed
    met = target_met_from_pattern("/" + rel + "/")
    if met is None:
        return {**empty, "lr_status": "no_met"}

    target = f"_M{met}_"
    vi = next((i for i, nm in enumerate(names) if target in nm and nm.endswith("_w3")), None)
    c2i = next((i for i, nm in enumerate(names) if target in nm and nm.endswith("_w2")), None)
    c4i = next((i for i, nm in enumerate(names) if target in nm and nm.endswith("_w4")), None)
    if vi is None or c2i is None or c4i is None:
        return {**empty, "lr_status": "no_w3_w2_w4"}

    c32, c34 = matrix[vi][c2i], matrix[vi][c4i]
    c23, c43 = matrix[c2i][vi], matrix[c4i][vi]
    denom = max(abs(c32), abs(c34))
    lr = abs(c32 - c34) / denom if denom else 0.0
    return {
        "lr_status": "ok",
        "c32_fF": f"{c32 * 1e15:.6f}",
        "c34_fF": f"{c34 * 1e15:.6f}",
        "lr_rel_asym": f"{lr:.6f}",
        "cc_fF": f"{-(c32 + c34) * 1e15:.6f}",
        "t32_rel": f"{rel_asym(c32, c23):.6f}",
        "t34_rel": f"{rel_asym(c34, c43):.6f}",
    }


def pct(vals: list[float], p: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    return s[min(int(p * len(s)), len(s) - 1)]


def _truthy(val) -> bool:
    return str(val) in ("1", "True", "true")


def stat_block(subset: list[dict], label: str) -> list[str]:
    lines = [f"\n=== {label} (n={len(subset)}) ==="]
    parsed = [r for r in subset if _truthy(r["parsed_matrix"])]
    strong = [
        float(r["strong_pair_max_signed_rel"])
        for r in parsed
        if r["strong_pair_max_signed_rel"] not in ("", None)
    ]
    block = [
        float(r["block_noM0_max_rel_asym"])
        for r in parsed
        if r["block_noM0_max_rel_asym"]
    ]
    global_a = [
        float(r["global_max_rel_asym"])
        for r in parsed
        if r["global_max_rel_asym"]
    ]
    lr_ok = [float(r["lr_rel_asym"]) for r in subset if r.get("lr_status") == "ok"]
    t32 = [float(r["t32_rel"]) for r in subset if r.get("lr_status") == "ok" and r["t32_rel"]]
    t34 = [float(r["t34_rel"]) for r in subset if r.get("lr_status") == "ok" and r["t34_rel"]]

    lines.append(f"  parsed_matrix: {len(parsed)}")
    lines.append(f"  nonconv_1000: {sum(1 for r in subset if _truthy(r['nonconv_1000']))}")
    lines.append(
        f"  pos_offdiag_strong: {sum(1 for r in parsed if _truthy(r.get('pos_offdiag_strong')))}"
    )

    if strong:
        lines.append("  强耦合 max signed rel asym (|C|>=1e-16, C_ij vs C_ji):")
        lines.append(
            f"    n={len(strong)}  p50={pct(strong, 0.5) * 100:.2f}%"
            f"  p95={pct(strong, 0.95) * 100:.2f}%  max={max(strong) * 100:.2f}%"
        )
        for th in (0.01, 0.05, 0.10, 0.50, 1.00):
            c = sum(1 for x in strong if x < th)
            lines.append(f"    < {th * 100:.0f}%: {c}/{len(strong)} ({100 * c / len(strong):.1f}%)")
        lines.append(
            f"  sign_flip_pairs>0: {sum(1 for r in parsed if r['sign_flip_pairs'] and int(r['sign_flip_pairs']) > 0)}"
        )
        worst = sorted(
            parsed,
            key=lambda r: float(r["strong_pair_max_signed_rel"] or 0),
            reverse=True,
        )[:5]
        lines.append("  worst 5 strong_pair_max_signed_rel:")
        for r in worst:
            lines.append(
                f"    {float(r['strong_pair_max_signed_rel']) * 100:.1f}%  {r['pattern']}"
            )

    if block:
        lines.append("  导体块 block_noM0 max rel asym (含弱耦合):")
        lines.append(
            f"    p50={pct(block, 0.5) * 100:.2f}%"
            f"  p95={pct(block, 0.95) * 100:.2f}%  max={max(block) * 100:.2f}%"
        )
        lines.append(f"    >50%: {sum(1 for x in block if x > 0.5)}/{len(block)}")

    if global_a:
        lines.append("  全矩阵 global max rel asym (含 M0):")
        lines.append(
            f"    p50={pct(global_a, 0.5) * 100:.2f}%"
            f"  p95={pct(global_a, 0.95) * 100:.2f}%  max={max(global_a) * 100:.2f}%"
        )

    if lr_ok:
        lines.append("  C32 vs C34 左右几何对称 (victim w3, 同层 w2/w4):")
        lines.append(
            f"    n={len(lr_ok)}  p50={pct(lr_ok, 0.5) * 100:.2f}%"
            f"  p95={pct(lr_ok, 0.95) * 100:.2f}%  max={max(lr_ok) * 100:.2f}%"
        )
        for th in (0.05, 0.10, 0.50):
            c = sum(1 for x in lr_ok if x < th)
            lines.append(f"    < {th * 100:.0f}%: {c}/{len(lr_ok)} ({100 * c / len(lr_ok):.1f}%)")

    if t32:
        lines.append("  互易性 C32 vs C23 / C34 vs C43:")
        lines.append(
            f"    t32 p50={pct(t32, 0.5) * 100:.2f}%  p95={pct(t32, 0.95) * 100:.2f}%  max={max(t32) * 100:.2f}%"
        )
        lines.append(
            f"    t34 p50={pct(t34, 0.5) * 100:.2f}%  p95={pct(t34, 0.95) * 100:.2f}%  max={max(t34) * 100:.2f}%"
        )

    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze FasterCap matrix and victim symmetry")
    ap.add_argument("--root", type=Path, default=FC_DIR / "6v2_typ_wirefix")
    ap.add_argument("--out-prefix", type=Path, default=FC_DIR / "6v2_typ_wirefix")
    ap.add_argument(
        "--only-pattern-type",
        choices=("Over5", "OverUnder5", "Under5", "UnderDiag5"),
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Fail unless all matrices parse with no sign flips and symmetry <= --max-rel",
    )
    ap.add_argument("--max-rel", type=float, default=0.10)
    ap.add_argument(
        "--reject-pos-offdiag",
        action="store_true",
        default=True,
        help="Strict gate: reject strong positive off-diagonal (default: on)",
    )
    ap.add_argument(
        "--no-reject-pos-offdiag",
        action="store_false",
        dest="reject_pos_offdiag",
        help="Disable positive off-diagonal rejection in strict gate",
    )
    ap.add_argument(
        "--reject-sign-flip",
        action="store_true",
        default=True,
        help="Strict gate: reject sign-flip reciprocal pairs (default: on)",
    )
    ap.add_argument(
        "--no-reject-sign-flip",
        action="store_false",
        dest="reject_sign_flip",
        help="Disable sign-flip rejection in strict gate",
    )
    ap.add_argument(
        "--rules-summary",
        type=Path,
        help="Append an existing FasterCap-vs-rules Markdown summary",
    )
    ap.add_argument(
        "--skip-list",
        type=Path,
        help="Optional case paths relative to --root, one per line",
    )
    args = ap.parse_args()

    root = args.root.resolve()
    out_csv = Path(f"{args.out_prefix}_symmetry_full.csv")
    out_sum = Path(f"{args.out_prefix}_symmetry_summary.txt")

    logs = sorted(p for p in root.rglob("wires.log") if p.stat().st_size > 0)
    if args.skip_list and args.skip_list.is_file():
        skipped = {
            line.strip().removeprefix("./")
            for line in args.skip_list.read_text(errors="replace").splitlines()
            if line.strip()
        }
        logs = [
            path
            for path in logs
            if str(path.parent.relative_to(root)).removeprefix("./") not in skipped
        ]
    if args.only_pattern_type:
        marker = f"/{args.only_pattern_type}/"
        logs = [p for p in logs if marker in p.as_posix()]
    if not logs:
        raise SystemExit(f"No non-empty wires.log files under {root}")
    print(f"Analyzing {len(logs)} wires.log ...")

    rows: list[dict] = []
    for log in logs:
        base = scan_log(log, root, STRONG_TH)
        base["pattern_type"] = pattern_type(base["pattern"])
        base.update(victim_lr_metrics(log, root))
        rows.append(base)

    fieldnames = list(rows[0].keys())
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    summary = [
        "Sky130 FasterCap 对称性分析",
        f"Dataset: {root}",
        f"CSV: {out_csv}",
        f"Total non-empty wires.log: {len(rows)}",
    ]
    summary.extend(stat_block(rows, "ALL"))
    for ptype in ("Over5", "OverUnder5", "Under5", "UnderDiag5"):
        summary.extend(stat_block([r for r in rows if r["pattern_type"] == ptype], ptype))

    by_dim: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if _truthy(r["parsed_matrix"]) and r["strong_pair_max_signed_rel"] not in ("", None):
            by_dim[r["dim"]].append(float(r["strong_pair_max_signed_rel"]))
    summary.append("\n=== 按矩阵 dim 的 strong_pair max rel asym median ===")
    for dim in sorted(by_dim, key=lambda x: int(x)):
        vals = by_dim[dim]
        summary.append(f"  dim{dim}: n={len(vals)}  median={statistics.median(vals) * 100:.2f}%")

    # sym50 gate overlap
    skipped_patterns: set[str] = set()
    skip_file = Path(f"{args.out_prefix}_parse_sym50") / "skipped_asymmetry"
    if skip_file.exists():
        for line in skip_file.read_text().splitlines():
            path = line.split(" rel=")[0].strip()
            if "/6v2_typ_wirefix/" in path:
                rel = path.split("/6v2_typ_wirefix/", 1)[1].replace("/wires.log", "")
                skipped_patterns.add(rel)

    summary.append("\n=== sym50 parse 门槛 (block_noM0 asym > 50%) ===")
    summary.append(f"  skipped in parse: {len(skipped_patterns)}")
    in_caps = [r for r in rows if r["pattern"] not in skipped_patterns]
    strong_caps = [
        float(r["strong_pair_max_signed_rel"])
        for r in in_caps
        if r["strong_pair_max_signed_rel"] not in ("", None)
    ]
    if strong_caps:
        summary.append(f"  in caps subset strong asym p50: {pct(strong_caps, 0.5) * 100:.2f}%")
        summary.append(f"  in caps subset strong asym >50%: {sum(1 for x in strong_caps if x > 0.5)}")

    text = "\n".join(summary) + "\n"
    if args.rules_summary:
        if not args.rules_summary.is_file():
            raise SystemExit(f"Rules summary not found: {args.rules_summary}")
        text += "\n=== rcx_patterns.rules 对比 ===\n\n"
        text += args.rules_summary.read_text()
        if not text.endswith("\n"):
            text += "\n"
    out_sum.write_text(text)
    print(text)
    print(f"Wrote {out_csv}")
    print(f"Wrote {out_sum}")

    if args.check:
        gate_cfg = GateConfig(
            max_rel=args.max_rel,
            reject_pos_offdiag=args.reject_pos_offdiag,
            reject_sign_flip=args.reject_sign_flip,
        )
        parsed = [r for r in rows if _truthy(r["parsed_matrix"])]
        lr = [
            float(r["lr_rel_asym"])
            for r in parsed
            if r.get("lr_status") == "ok" and r["lr_rel_asym"] not in ("", None)
        ]
        failures = []
        strict_failures = []
        if len(parsed) != len(rows):
            failures.append(f"parsed {len(parsed)}/{len(rows)} matrices")

        for log in logs:
            mat = parse_last_matrix(log.read_text(errors="replace").splitlines())
            ok, reason, _metrics = evaluate_matrix_quality_gate(mat, gate_cfg)
            if not ok:
                rel = str(log.relative_to(root)).replace("/wires.log", "")
                strict_failures.append(f"{rel}: {reason}")

        if strict_failures:
            failures.append(
                f"strict gate failed on {len(strict_failures)}/{len(logs)} matrices"
            )
            for entry in strict_failures[:10]:
                failures.append(f"  {entry}")
            if len(strict_failures) > 10:
                failures.append(f"  ... and {len(strict_failures) - 10} more")

        if lr and max(lr) > args.max_rel:
            failures.append(f"max C32/C34 asymmetry {max(lr):.2%} > {args.max_rel:.2%}")

        passed = len(logs) - len(strict_failures)
        print(
            f"Strict gate (max_rel={args.max_rel:.2%}, "
            f"pos_offdiag={'on' if args.reject_pos_offdiag else 'off'}, "
            f"sign_flip={'on' if args.reject_sign_flip else 'off'}): "
            f"pass {passed}/{len(logs)}"
        )

        if failures:
            raise SystemExit("Symmetry check FAILED: " + "; ".join(failures[:3]))
        print(
            f"Symmetry check PASSED: {len(rows)} matrices, "
            f"C32/C34 max={max(lr, default=0):.2%}"
        )


if __name__ == "__main__":
    main()
