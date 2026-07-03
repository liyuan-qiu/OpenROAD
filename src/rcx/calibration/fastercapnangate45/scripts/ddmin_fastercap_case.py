#!/usr/bin/env python3
"""
Delta-debug FasterCap geometry to isolate a minimal failing subset.

Given a failing wires.lst, this script repeatedly removes chunks of geometry
entries and re-runs FasterCap to find a smaller input that still reproduces
the same failure class (default: exit code 133 / assert-trap).
"""

from __future__ import annotations

import argparse
import math
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple


@dataclass
class RunResult:
    state: str
    return_code: int
    run_id: int
    kept_count: int
    log_path: Path
    wires_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delta-debug FasterCap failures for one case directory.")
    parser.add_argument("case_dir", help="Pattern case directory containing wires.lst")
    parser.add_argument("fastercap_exec", help="Path to FasterCap executable")
    parser.add_argument("--timeout", type=int, default=60, help="Per-run timeout in seconds")
    parser.add_argument("--extra-args", default="", help="Extra FasterCap arguments (quoted string)")
    parser.add_argument("--use-g", action="store_true", help="Include -g")
    parser.add_argument("--use-ap", action="store_true", help="Include -ap")
    parser.add_argument("--target-state", default="failed_133", help="Failure class to preserve")
    parser.add_argument("--max-runs", type=int, default=80, help="Stop after this many runs")
    parser.add_argument("--keep-prefixes", default="C ,D ", help="Comma-separated line prefixes considered geometry candidates")
    return parser.parse_args()


def is_candidate(line: str, prefixes: Sequence[str]) -> bool:
    stripped = line.lstrip()
    return any(stripped.startswith(prefix) for prefix in prefixes)


def classify_state(return_code: int) -> str:
    if return_code < 0:
        # subprocess returns negative signal number when terminated by signal.
        sig = -return_code
        return f"failed_{128 + sig}"
    if return_code == 0:
        return "ok"
    if return_code in (9, 137):
        return "killed"
    return f"failed_{return_code}"


def chunkify(items: Sequence[int], parts: int) -> List[List[int]]:
    if not items:
        return []
    chunk_size = int(math.ceil(len(items) / float(parts)))
    return [list(items[i : i + chunk_size]) for i in range(0, len(items), chunk_size)]


def build_wires_content(all_lines: Sequence[str], keep_set: Set[int], candidate_idx: Set[int]) -> str:
    out: List[str] = []
    for idx, line in enumerate(all_lines):
        if idx in candidate_idx and idx not in keep_set:
            continue
        out.append(line)
    return "".join(out)


def run_fastercap(
    *,
    case_dir: Path,
    fastercap_exec: Path,
    timeout_s: int,
    extra_args: Sequence[str],
    use_g: bool,
    use_ap: bool,
    run_id: int,
    content: str,
) -> RunResult:
    runs_dir = case_dir / "ddmin_runs"
    runs_dir.mkdir(exist_ok=True)
    # Keep temporary wires files in case_dir so relative geometry paths
    # (e.g., Wires/*.txt) resolve exactly like the original wires.lst.
    wires_path = case_dir / f"wires_ddmin_run_{run_id:04d}.lst"
    log_path = runs_dir / f"run_{run_id:04d}.log"
    wires_path.write_text(content)

    cmd = [str(fastercap_exec), "-b", str(wires_path)]
    if use_g:
        cmd.append("-g")
    if use_ap:
        cmd.append("-ap")
    cmd.extend(extra_args)

    with log_path.open("w") as logf:
        try:
            completed = subprocess.run(
                cmd,
                cwd=case_dir,
                stdout=logf,
                stderr=subprocess.STDOUT,
                timeout=timeout_s,
                check=False,
            )
            rc = completed.returncode
        except subprocess.TimeoutExpired:
            rc = 137

    state = classify_state(rc)
    kept_count = sum(1 for line in content.splitlines() if line.lstrip().startswith(("C ", "D ")))
    return RunResult(state=state, return_code=rc, run_id=run_id, kept_count=kept_count, log_path=log_path, wires_path=wires_path)


def ddmin(
    *,
    all_lines: Sequence[str],
    candidate_indices: Sequence[int],
    target_state: str,
    runner,
    max_runs: int,
    report_lines: List[str],
) -> Tuple[List[int], int]:
    current = list(candidate_indices)
    tested: Dict[Tuple[int, ...], RunResult] = {}
    run_counter = 0

    candidate_set = set(candidate_indices)

    def eval_subset(keep_indices: Sequence[int], reason: str) -> RunResult:
        nonlocal run_counter
        key = tuple(sorted(keep_indices))
        if key in tested:
            return tested[key]
        run_counter += 1
        keep_set = set(keep_indices)
        content = build_wires_content(all_lines, keep_set, candidate_set)
        result: RunResult = runner(run_counter, content)
        tested[key] = result
        report_lines.append(
            f"{run_counter:03d},{reason},{len(keep_indices)},{result.state},{result.return_code},{result.wires_path.name},{result.log_path.name}"
        )
        return result

    baseline = eval_subset(current, "baseline")
    if baseline.state != target_state:
        raise RuntimeError(
            f"Baseline is {baseline.state} not target {target_state}; cannot delta-debug this failure class."
        )

    n = 2
    while len(current) >= 2 and run_counter < max_runs:
        chunks = chunkify(current, n)
        reduced = False

        for idx, chunk in enumerate(chunks):
            if run_counter >= max_runs:
                break
            result = eval_subset(chunk, f"subset_{n}_{idx}")
            if result.state == target_state:
                current = chunk
                n = 2
                reduced = True
                break

        if reduced:
            continue

        for idx, chunk in enumerate(chunks):
            if run_counter >= max_runs:
                break
            chunk_set = set(chunk)
            complement = [x for x in current if x not in chunk_set]
            if not complement:
                continue
            result = eval_subset(complement, f"complement_{n}_{idx}")
            if result.state == target_state:
                current = complement
                n = max(n - 1, 2)
                reduced = True
                break

        if reduced:
            continue

        if n >= len(current):
            break
        n = min(len(current), n * 2)

    return current, run_counter


def main() -> int:
    args = parse_args()
    case_dir = Path(args.case_dir).resolve()
    fastercap_exec = Path(args.fastercap_exec).resolve()

    if not case_dir.is_dir():
        raise SystemExit(f"ERROR: case_dir not found: {case_dir}")
    if not fastercap_exec.exists():
        raise SystemExit(f"ERROR: fastercap executable not found: {fastercap_exec}")

    wires_lst = case_dir / "wires.lst"
    if not wires_lst.is_file():
        raise SystemExit(f"ERROR: wires.lst not found in {case_dir}")

    all_lines = wires_lst.read_text().splitlines(keepends=True)
    prefixes = [p for p in (x.strip() for x in args.keep_prefixes.split(",")) if p]

    candidate_indices = [idx for idx, line in enumerate(all_lines) if is_candidate(line, prefixes)]
    if not candidate_indices:
        raise SystemExit("ERROR: no candidate geometry lines matched --keep-prefixes")

    extra_args = shlex.split(args.extra_args) if args.extra_args else []
    report_lines: List[str] = ["run,reason,kept_geometry,state,return_code,wires_file,log_file"]

    def runner(run_id: int, content: str) -> RunResult:
        return run_fastercap(
            case_dir=case_dir,
            fastercap_exec=fastercap_exec,
            timeout_s=args.timeout,
            extra_args=extra_args,
            use_g=args.use_g,
            use_ap=args.use_ap,
            run_id=run_id,
            content=content,
        )

    minimal_keep, runs = ddmin(
        all_lines=all_lines,
        candidate_indices=candidate_indices,
        target_state=args.target_state,
        runner=runner,
        max_runs=args.max_runs,
        report_lines=report_lines,
    )

    candidate_set = set(candidate_indices)
    min_content = build_wires_content(all_lines, set(minimal_keep), candidate_set)
    min_file = case_dir / "wires_min_fail.lst"
    min_file.write_text(min_content)

    report_file = case_dir / "ddmin_report.csv"
    report_file.write_text("\n".join(report_lines) + "\n")

    summary = case_dir / "ddmin_summary.txt"
    summary.write_text(
        "\n".join(
            [
                f"case_dir={case_dir}",
                f"target_state={args.target_state}",
                f"total_candidate_geometry={len(candidate_indices)}",
                f"minimal_candidate_geometry={len(minimal_keep)}",
                f"runs_used={runs}",
                f"use_g={int(args.use_g)}",
                f"use_ap={int(args.use_ap)}",
                f"extra_args={args.extra_args}",
                f"wires_min_fail={min_file}",
                f"report_csv={report_file}",
                f"runs_dir={case_dir / 'ddmin_runs'}",
            ]
        )
        + "\n"
    )

    print(f"ddmin done: {len(candidate_indices)} -> {len(minimal_keep)} geometry lines")
    print(f"summary: {summary}")
    print(f"report : {report_file}")
    print(f"input  : {min_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
