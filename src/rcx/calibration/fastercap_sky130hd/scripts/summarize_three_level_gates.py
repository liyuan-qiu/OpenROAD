#!/usr/bin/env python3
"""Summarize Over5 FasterCap results under three cumulative quality gates.

Level 1 — C32 vs C34 local symmetry (lr_rel_asym)
Level 2 — + t32/t34 pairwise reciprocity
Level 3 — + full-matrix strict gate (global reciprocity, sign flip, pos offdiag)

Each level writes a subfolder under --report-dir with parse, compare, and error stats.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
FC_DIR = SCRIPT_DIR.parent
REPO_ROOT = FC_DIR.parents[5]

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(FC_DIR.parent / "fastercapnangate45" / "scripts"))

from matrix_quality_gate import GateConfig, evaluate_matrix_quality_gate  # noqa: E402
from scan_wires_quality import parse_last_matrix  # noqa: E402


@dataclass(frozen=True)
class LevelSpec:
    slug: str
    title: str
    description: str


LEVELS = (
    LevelSpec(
        "gate_L1",
        "限制 1：C32 ≈ C34",
        "lr_rel_asym = |C32−C34|/max(|C32|,|C34|) on victim w3",
    ),
    LevelSpec(
        "gate_L1_L2",
        "限制 1 + 2：+ t32/t34 互易性",
        "t32 = rel(C32,C23), t34 = rel(C34,C43)",
    ),
    LevelSpec(
        "gate_L1_L2_L3",
        "限制 1 + 2 + 3：+ 全矩阵 strict gate",
        "global_max_rel_asym + reject sign_flip + reject pos_offdiag_strong",
    ),
)


def _float(row: dict, key: str) -> float | None:
    val = row.get(key)
    if val in ("", None):
        return None
    return float(val)


def passes_l1(row: dict, max_lr: float) -> tuple[bool, str]:
    if row.get("lr_status") != "ok":
        return False, f"lr_status={row.get('lr_status')}"
    lr = _float(row, "lr_rel_asym")
    if lr is None:
        return False, "missing_lr"
    if lr > max_lr:
        return False, f"lr_rel={lr:.4g}>{max_lr:g}"
    return True, "ok"


def passes_l2(row: dict, max_t: float) -> tuple[bool, str]:
    t32 = _float(row, "t32_rel")
    t34 = _float(row, "t34_rel")
    if t32 is None or t34 is None:
        return False, "missing_t32_t34"
    if t32 > max_t:
        return False, f"t32={t32:.4g}>{max_t:g}"
    if t34 > max_t:
        return False, f"t34={t34:.4g}>{max_t:g}"
    return True, "ok"


def passes_l3(mat, gate_cfg: GateConfig) -> tuple[bool, str]:
    ok, reason, _ = evaluate_matrix_quality_gate(mat, gate_cfg)
    return ok, reason


def case_rel_path(pattern: str) -> str:
    prefix = "TYP/"
    if pattern.startswith(prefix):
        return pattern[len(prefix) :]
    return pattern


def pattern_from_case_rel(rel: str) -> str:
    return rel if rel.startswith("TYP/") else f"TYP/{rel}"


def is_default_wires_log(log_path: Path) -> bool:
    if not log_path.is_file() or log_path.stat().st_size == 0:
        return False
    text = log_path.read_text(errors="replace")[:1200]
    return (
        "GMRES tolerance (-t): 0.005" in text
        and "Mesh relative refinement value (-m): 0.05" not in text
    )


def collect_default_case_patterns(
    run_dir: Path,
    family: str,
    *,
    first_n: int | None = None,
) -> list[str]:
    """Sorted FasterCap case order; return patterns with default-profile wires.log."""
    wires = sorted(
        p
        for p in run_dir.rglob("wires")
        if f"/{family}/" in p.as_posix()
    )
    patterns: list[str] = []
    for wire in wires:
        log = wire.parent / "wires.log"
        if not is_default_wires_log(log):
            continue
        rel = wire.parent.relative_to(run_dir)
        patterns.append(f"TYP/{rel.as_posix()}")
        if first_n is not None and len(patterns) >= first_n:
            break
    return patterns


def load_case_filter(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    allowed: set[str] = set()
    for line in path.read_text(errors="replace").splitlines():
        item = line.strip().removeprefix("./")
        if not item:
            continue
        allowed.add(item)
        allowed.add(case_rel_path(item))
        allowed.add(pattern_from_case_rel(item))
    return allowed


def row_in_case_filter(row: dict, allowed: set[str] | None) -> bool:
    if allowed is None:
        return True
    pattern = row["pattern"]
    rel = case_rel_path(pattern)
    return pattern in allowed or rel in allowed


def load_symmetry_csv(path: Path) -> list[dict]:
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def ensure_symmetry_csv(
    run_dir: Path,
    family: str,
    out_prefix: Path,
    skip_list: Path | None,
) -> Path:
    csv_path = Path(f"{out_prefix}_symmetry_full.csv")
    if csv_path.is_file():
        return csv_path
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "analyze_symmetry_full.py"),
        "--root",
        str(run_dir),
        "--out-prefix",
        str(out_prefix),
        "--only-pattern-type",
        family,
    ]
    if skip_list and skip_list.is_file():
        cmd.extend(["--skip-list", str(skip_list)])
    subprocess.run(cmd, check=True)
    return csv_path


def build_pass_sets(
    rows: list[dict],
    logs_by_pattern: dict[str, Path],
    *,
    l1_max: float,
    l2_max: float,
    gate_cfg: GateConfig,
) -> dict[str, tuple[set[str], list[dict]]]:
    """Return {slug: (passed_case_relpaths, skip_rows)} for each cumulative level."""
    results: dict[str, tuple[set[str], list[dict]]] = {}
    passed_l1: set[str] = set()
    passed_l2: set[str] = set()
    passed_l3: set[str] = set()
    skips: dict[str, list[dict]] = {level.slug: [] for level in LEVELS}

    for row in rows:
        pattern = row["pattern"]
        rel = case_rel_path(pattern)
        log_path = logs_by_pattern.get(pattern)
        if log_path is None:
            for level in LEVELS:
                skips[level.slug].append(
                    {"case": rel, "reason": "missing_wires.log", "level_failed": "L0"}
                )
            continue

        ok1, r1 = passes_l1(row, l1_max)
        if not ok1:
            for level in LEVELS:
                skips[level.slug].append(
                    {"case": rel, "reason": r1, "level_failed": "L1"}
                )
            continue
        passed_l1.add(rel)

        ok2, r2 = passes_l2(row, l2_max)
        if not ok2:
            skips["gate_L1_L2"].append({"case": rel, "reason": r2, "level_failed": "L2"})
            skips["gate_L1_L2_L3"].append({"case": rel, "reason": r2, "level_failed": "L2"})
            continue
        passed_l2.add(rel)

        mat = parse_last_matrix(log_path.read_text(errors="replace").splitlines())
        ok3, r3 = passes_l3(mat, gate_cfg)
        if not ok3:
            skips["gate_L1_L2_L3"].append({"case": rel, "reason": r3, "level_failed": "L3"})
            continue
        passed_l3.add(rel)

    results["gate_L1"] = (passed_l1, skips["gate_L1"])
    results["gate_L1_L2"] = (passed_l2, skips["gate_L1_L2"])
    results["gate_L1_L2_L3"] = (passed_l3, skips["gate_L1_L2_L3"])
    return results


def stack_from_case(rel: str) -> str:
    # TYP/Over5/M1oM0/W0.17_W0.17/S0.17_S0.17_L10 -> M1oM0
    parts = rel.split("/")
    return parts[1] if len(parts) > 1 else "unknown"


def run_parse_compare_error(
    *,
    level_dir: Path,
    passed: set[str],
    run_dir: Path,
    len_mult: int,
    family: str,
    rules: Path,
    compare_script: Path,
    error_script: Path,
    compare_timeout: int = 120,
    parse_timeout: int = 300,
    no_plots: bool = False,
    skip_error_analysis: bool = False,
) -> dict:
    parse_dir = level_dir / "parse"
    compare_dir = level_dir / "compare_rules"
    error_dir = level_dir / "error_analysis"
    parse_dir.mkdir(parents=True, exist_ok=True)
    compare_dir.mkdir(parents=True, exist_ok=True)
    error_dir.mkdir(parents=True, exist_ok=True)

    by_stack: dict[str, list[Path]] = defaultdict(list)
    for rel in sorted(passed):
        log = run_dir / "TYP" / rel / "wires.log"
        if log.is_file() and log.stat().st_size > 0:
            by_stack[stack_from_case(rel)].append(log)

    parsed_stacks: list[str] = []
    failed_parse: list[str] = []
    sub_env = {**os.environ, "MPLBACKEND": "Agg"}
    for stack_name, logs in sorted(by_stack.items()):
        if not logs:
            continue
        input_list = parse_dir / f"{stack_name}.input.list"
        input_list.write_text("".join(f"{p}\n" for p in logs))
        caps = parse_dir / f"{stack_name}.caps"
        parse_skip = parse_dir / f"{stack_name}.parse_skipped"
        if parse_skip.is_file():
            failed_parse.append(stack_name)
            continue
        if caps.is_file() and caps.stat().st_size > 0:
            parsed_stacks.append(stack_name)
            continue
        cmd = [
            sys.executable,
            str(FC_DIR / "scripts" / "fasterCapParse.py"),
            "-in_list_file",
            str(input_list),
            "-wire",
            "3",
            "--symmetrize-avg",
            "-out_file",
            str(caps),
            "-len_meta_file",
            str(parse_dir / f"{stack_name}.len_meta.csv"),
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=parse_dir,
                capture_output=True,
                text=True,
                timeout=parse_timeout,
                env=sub_env,
            )
        except subprocess.TimeoutExpired:
            parse_skip.write_text(f"parse timeout after {parse_timeout}s\n", encoding="utf-8")
            failed_parse.append(stack_name)
            continue
        (parse_dir / f"{stack_name}.parse.out").write_text(proc.stdout + proc.stderr)
        if caps.is_file() and caps.stat().st_size > 0:
            parsed_stacks.append(stack_name)
        else:
            reason = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
            parse_skip.write_text(reason + "\n", encoding="utf-8")
            failed_parse.append(stack_name)

    compared = 0
    total_points = 0
    failed_compare: list[str] = []
    for stack_name in parsed_stacks:
        out = compare_dir / stack_name
        tsv = out / "fastercap_vs_rules.tsv"
        compare_skip = out / ".compare_skipped"
        if compare_skip.is_file():
            failed_compare.append(stack_name)
            continue
        if tsv.is_file() and tsv.stat().st_size > 0:
            compared += 1
            with tsv.open(newline="") as stream:
                total_points += sum(1 for _ in csv.DictReader(stream))
            continue
        compare_cmd = [
            sys.executable,
            str(compare_script),
            "--caps",
            str(parse_dir / f"{stack_name}.caps"),
            "--rules",
            str(rules),
            "--wire",
            "3",
            "--pattern-label",
            stack_name,
            "--out-dir",
            str(out),
        ]
        if no_plots:
            compare_cmd.append("--no-plot")
        try:
            proc = subprocess.run(
                compare_cmd,
                capture_output=True,
                text=True,
                timeout=compare_timeout,
                env=sub_env,
            )
        except subprocess.TimeoutExpired:
            out.mkdir(parents=True, exist_ok=True)
            compare_skip.write_text(
                f"compare timeout after {compare_timeout}s\n", encoding="utf-8"
            )
            failed_compare.append(stack_name)
            print(f"    SKIP compare {stack_name}: timeout", flush=True)
            continue
        (parse_dir / f"{stack_name}.compare.out").write_text(proc.stdout + proc.stderr)
        if proc.returncode == 0 and tsv.is_file() and tsv.stat().st_size > 0:
            compared += 1
            with tsv.open(newline="") as stream:
                total_points += sum(1 for _ in csv.DictReader(stream))
        else:
            out.mkdir(parents=True, exist_ok=True)
            reason = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
            compare_skip.write_text(reason + "\n", encoding="utf-8")
            failed_compare.append(stack_name)
            print(f"    SKIP compare {stack_name}: {reason.splitlines()[0]}", flush=True)

    if failed_parse:
        (level_dir / "failed_parse_stacks.txt").write_text(
            "".join(f"{name}\n" for name in failed_parse), encoding="utf-8"
        )
    if failed_compare:
        (level_dir / "failed_compare_stacks.txt").write_text(
            "".join(f"{name}\n" for name in failed_compare), encoding="utf-8"
        )

    family_label = {"Over5": "OVER", "Under5": "UNDER", "OverUnder5": "OVER_UNDER"}.get(
        family, "OVER"
    )
    if compared > 0 and not skip_error_analysis:
        error_cmd = [
            sys.executable,
            str(error_script),
            "--compare-dir",
            str(compare_dir),
            "--out-dir",
            str(error_dir),
            "--len-mult",
            str(len_mult),
            "--rules",
            str(rules),
            "--ratio-tag",
            f"sky130_fastercap_len{len_mult}",
            "--platform-name",
            "SKY130",
            "--expected-patterns",
            str(compared),
            "--family",
            family_label,
            "--cg-mode",
            "a",
        ]
        if no_plots:
            error_cmd.append("--no-plot")
        try:
            subprocess.run(
                error_cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=max(compare_timeout * 4, 300),
                env=sub_env,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            (error_dir / "error_analysis_skipped.txt").write_text(
                f"{exc}\n", encoding="utf-8"
            )
            print(f"    WARN error_analysis skipped: {exc}", flush=True)

    return {
        "passed_cases": len(passed),
        "parsed_stacks": len(parsed_stacks),
        "compared_stacks": compared,
        "compare_points": total_points,
        "failed_parse_stacks": len(failed_parse),
        "failed_compare_stacks": len(failed_compare),
        "error_summary": error_dir / "summary.md",
    }


def write_level_summary(
    level_dir: Path,
    spec: LevelSpec,
    *,
    total: int,
    passed: set[str],
    skipped: list[dict],
    thresholds: dict,
    run_stats: dict,
) -> None:
    lines = [
        f"# {spec.title}",
        "",
        spec.description,
        "",
        "## 阈值",
        "",
        f"- L1 max lr_rel_asym (C32 vs C34): **{thresholds['l1_max']:.2%}**",
    ]
    if spec.slug != "gate_L1":
        lines.append(f"- L2 max t32/t34 reciprocity: **{thresholds['l2_max']:.2%}**")
    if spec.slug == "gate_L1_L2_L3":
        lines.append(
            f"- L3 global_max_rel_asym: **≤ {thresholds['l3_max']:.2%}**"
            f"  sign_flip=reject  pos_offdiag=reject"
        )
    lines.extend(
        [
            "",
            "## 通过数量",
            "",
            f"| 指标 | 数量 |",
            f"|------|------|",
            f"| 总 case（有 wires.log） | {total} |",
            f"| **通过本层 gate** | **{len(passed)}** |",
            f"| 跳过 | {len(skipped)} |",
            f"| 通过率 | {100 * len(passed) / total:.1f}% |" if total else "",
            f"| parse stack 数 | {run_stats['parsed_stacks']} |",
            f"| compare stack 数 | {run_stats['compared_stacks']} |",
            f"| parse 失败 stack | {run_stats.get('failed_parse_stacks', 0)} |",
            f"| compare 失败 stack | {run_stats.get('failed_compare_stacks', 0)} |",
            f"| rules 对比 dist 点数 | {run_stats['compare_points']} |",
            "",
        ]
    )
    if run_stats["error_summary"].is_file():
        lines.extend(["## Error vs golden rules", ""])
        lines.append(run_stats["error_summary"].read_text(errors="replace"))
    if skipped:
        lines.extend(["", "## 跳过原因统计", ""])
        by_reason: dict[str, int] = defaultdict(int)
        for row in skipped:
            by_reason[row["reason"].split(";")[0]] += 1
        for reason, count in sorted(by_reason.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- `{reason}`: {count}")
    level_dir.joinpath("summary.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report-dir", type=Path, required=True)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--len", type=int, default=10)
    ap.add_argument("--family", default="Over5")
    ap.add_argument("--l1-max-lr", type=float, default=0.10)
    ap.add_argument("--l2-max-t", type=float, default=0.10)
    ap.add_argument("--l3-max-rel", type=float, default=0.10)
    ap.add_argument(
        "--rules",
        type=Path,
        default=REPO_ROOT / "flow/platforms/sky130hs/rcx_patterns.rules",
    )
    ap.add_argument(
        "--skip-list",
        type=Path,
        help="Optional preflight/solver skip list relative to run-dir",
    )
    ap.add_argument(
        "--case-list",
        type=Path,
        help="Only analyze these cases (TYP/Over5/... or Over5/... one per line)",
    )
    ap.add_argument(
        "--only-default-profile",
        action="store_true",
        help="Only include wires.log with default FasterCap header (-g -ap -a0.01)",
    )
    ap.add_argument(
        "--first-n-cases",
        type=int,
        help="With --only-default-profile, take first N cases in runner sort order",
    )
    ap.add_argument(
        "--title-suffix",
        default="",
        help="Extra note in summary markdown (e.g. 'first 40 default cases')",
    )
    ap.add_argument(
        "--compare-timeout",
        type=int,
        default=120,
        help="Per-stack compare timeout in seconds; failures are skipped",
    )
    ap.add_argument(
        "--parse-timeout",
        type=int,
        default=300,
        help="Per-stack parse timeout in seconds; failures are skipped",
    )
    ap.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip matplotlib plots in compare/error_analysis (faster)",
    )
    ap.add_argument(
        "--skip-error-analysis",
        action="store_true",
        help="Skip aggregate error_analysis stage",
    )
    args = ap.parse_args()

    report_dir = args.report_dir.resolve()
    run_dir = args.run_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    case_filter = load_case_filter(args.case_list)
    if args.only_default_profile:
        patterns = collect_default_case_patterns(
            run_dir, args.family, first_n=args.first_n_cases
        )
        auto_filter: set[str] = set()
        for pattern in patterns:
            auto_filter.add(pattern)
            auto_filter.add(case_rel_path(pattern))
        case_filter = auto_filter if case_filter is None else (case_filter & auto_filter)

    sym_prefix = report_dir / "symmetry_default"
    if case_filter is not None:
        sym_prefix = report_dir / "symmetry_subset"
        subset_list = report_dir / "analyzed_cases.txt"
        subset_patterns = sorted(
            {
                pattern_from_case_rel(x)
                if not x.startswith("TYP/")
                else x
                for x in case_filter
                if x.startswith("TYP/") or x.startswith(f"{args.family}/")
            }
        )
        subset_list.write_text("".join(f"{p}\n" for p in subset_patterns))

    csv_path = ensure_symmetry_csv(
        run_dir, args.family, sym_prefix, args.skip_list
    )
    rows = load_symmetry_csv(csv_path)
    rows = [r for r in rows if r.get("pattern_type") == args.family]
    if case_filter is not None:
        rows = [r for r in rows if row_in_case_filter(r, case_filter)]
    total = len(rows)
    if total == 0:
        raise SystemExit("No cases left after case filter")

    logs_by_pattern = {r["pattern"]: run_dir / r["pattern"] / "wires.log" for r in rows}
    gate_cfg = GateConfig(
        max_rel=args.l3_max_rel,
        reject_pos_offdiag=True,
        reject_sign_flip=True,
    )
    thresholds = {
        "l1_max": args.l1_max_lr,
        "l2_max": args.l2_max_t,
        "l3_max": args.l3_max_rel,
    }
    pass_sets = build_pass_sets(
        rows,
        logs_by_pattern,
        l1_max=args.l1_max_lr,
        l2_max=args.l2_max_t,
        gate_cfg=gate_cfg,
    )

    compare_script = REPO_ROOT / "bench_wires_nangate45_20260710/compare_fastercap_caps_vs_rules.py"
    error_script = REPO_ROOT / "bench_wires_nangate45_20260710/analyze_fastercap_vs_rules_errors.py"

    master_lines = [
        "# 三层 gate 汇总 — default FasterCap Over5",
        "",
        f"- Run: `{run_dir}`",
        f"- Report: `{report_dir}`",
        f"- Symmetry CSV: `{csv_path}`",
        f"- **Scope: {total} case(s)**"
        + (f" — {args.title_suffix}" if args.title_suffix else ""),
        "",
        "## 阈值",
        "",
        f"1. **L1** C32≈C34: lr_rel_asym ≤ {args.l1_max_lr:.2%}",
        f"2. **L2** + t32/t34 ≤ {args.l2_max_t:.2%}",
        f"3. **L3** + global reciprocity ≤ {args.l3_max_rel:.2%}, no sign_flip, no pos_offdiag_strong",
        "",
        "## 各层通过数",
        "",
        "| 文件夹 | 限制 | 通过 case | 通过率 | compare 点数 |",
        "|--------|------|-----------|--------|--------------|",
    ]

    for spec in LEVELS:
        passed, skipped = pass_sets[spec.slug]
        level_dir = report_dir / spec.slug
        level_dir.mkdir(parents=True, exist_ok=True)

        (level_dir / "passed_cases.txt").write_text(
            "".join(f"{c}\n" for c in sorted(passed))
        )
        with (level_dir / "skipped_cases.tsv").open("w", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=["case", "reason", "level_failed"]
            )
            writer.writeheader()
            writer.writerows(skipped)

        passed_rows = [r for r in rows if case_rel_path(r["pattern"]) in passed]
        if passed_rows:
            with (level_dir / "symmetry_passed.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(passed_rows[0].keys()))
                writer.writeheader()
                writer.writerows(passed_rows)

        print(f"==> {spec.slug}: {len(passed)}/{total} passed, running parse/compare/error...")
        run_stats = run_parse_compare_error(
            level_dir=level_dir,
            passed=passed,
            run_dir=run_dir,
            len_mult=args.len,
            family=args.family,
            rules=args.rules.resolve(),
            compare_script=compare_script,
            error_script=error_script,
            compare_timeout=args.compare_timeout,
            parse_timeout=args.parse_timeout,
            no_plots=args.no_plots,
            skip_error_analysis=args.skip_error_analysis,
        )
        write_level_summary(
            level_dir,
            spec,
            total=total,
            passed=passed,
            skipped=skipped,
            thresholds=thresholds,
            run_stats=run_stats,
        )
        rate = 100 * len(passed) / total if total else 0.0
        master_lines.append(
            f"| `{spec.slug}/` | {spec.title} | **{len(passed)}** | {rate:.1f}% | {run_stats['compare_points']} |"
        )
        print(f"    stacks compared={run_stats['compared_stacks']} points={run_stats['compare_points']}")

    master_lines.extend(
        [
            "",
            "各层详情见子目录 `summary.md`、`compare_rules/`、`error_analysis/`。",
            "",
        ]
    )
    (report_dir / "three_level_gates_summary.md").write_text(
        "\n".join(master_lines) + "\n"
    )
    print(f"Wrote {report_dir / 'three_level_gates_summary.md'}")


if __name__ == "__main__":
    main()
