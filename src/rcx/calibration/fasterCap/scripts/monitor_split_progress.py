#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BucketSpec:
    name: str
    list_file: str
    unresolved_check: str
    rerun_log: str
    done_marker: str


def read_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text(errors="ignore").splitlines() if ln.strip()]


def is_unresolved(log_path: Path, mode: str, nonconv_re: re.Pattern[str]) -> bool:
    if not log_path.exists():
        return True
    text = log_path.read_text(errors="ignore")
    if mode == "empty":
        return not text.strip()
    if mode == "nonconverge_133":
        return bool(nonconv_re.search(text))
    if mode == "nonterminal":
        if not text.strip():
            return True
        if nonconv_re.search(text):
            return False
        if re.search(r"Total allocated memory:\s*\d+", text, re.I):
            return False
        return True
    return True


def count_attempts(log_path: Path, done_marker_re: re.Pattern[str]) -> int:
    if not log_path.exists():
        return 0
    return sum(1 for ln in log_path.read_text(errors="ignore").splitlines() if done_marker_re.search(ln))


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor rerun progress for split buckets.")
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Path to run dir, e.g. .../5v2_typ_widened",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    nonconv133_re = re.compile(r"not converging after\s*1000\s*iterations", re.I)

    specs = [
        BucketSpec(
            name="unknown_empty",
            list_file="split_v2_unknown_empty.list",
            unresolved_check="empty",
            rerun_log="fasterCap_rerun_empty_abs.log",
            done_marker=r"Completed$",
        ),
        BucketSpec(
            name="nonconverge_133",
            list_file="split_v2_nonconverge_133.list",
            unresolved_check="nonconverge_133",
            rerun_log="fasterCap_rerun_nonconverge.log",
            done_marker=r"Completed\(nonconverge rerun\)$",
        ),
        BucketSpec(
            name="unknown_no_terminal",
            list_file="split_v2_unknown_no_terminal_marker.list",
            unresolved_check="nonterminal",
            rerun_log="fasterCap_rerun_unknown_noterm.log",
            done_marker=r"Completed\(unknown-noterm rerun\)$",
        ),
    ]

    print(f"run_dir={run_dir}")
    for spec in specs:
        dirs = read_list(run_dir / spec.list_file)
        unresolved = 0
        for d in dirs:
            unresolved += int(
                is_unresolved(run_dir / d / "wires.log", spec.unresolved_check, nonconv133_re)
            )
        resolved = len(dirs) - unresolved
        attempts = count_attempts(run_dir / spec.rerun_log, re.compile(spec.done_marker))
        print(
            f"{spec.name}: total={len(dirs)} attempts={attempts} "
            f"resolved={resolved} unresolved={unresolved}"
        )


if __name__ == "__main__":
    main()

