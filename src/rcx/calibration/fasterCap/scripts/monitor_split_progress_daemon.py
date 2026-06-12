#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import time
from datetime import datetime
from pathlib import Path


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


def count_attempts(log_path: Path, done_marker: re.Pattern[str]) -> int:
    if not log_path.exists():
        return 0
    return sum(1 for ln in log_path.read_text(errors="ignore").splitlines() if done_marker.search(ln))


def collect(run_dir: Path) -> list[dict]:
    nonconv133_re = re.compile(r"not converging after\s*1000\s*iterations", re.I)
    specs = [
        {
            "name": "unknown_empty",
            "list_file": "split_v2_unknown_empty.list",
            "mode": "empty",
            "rerun_log": "fasterCap_rerun_empty_abs.log",
            "done_marker": re.compile(r"Completed$"),
        },
        {
            "name": "nonconverge_133",
            "list_file": "split_v2_nonconverge_133.list",
            "mode": "nonconverge_133",
            "rerun_log": "fasterCap_rerun_nonconverge_sanitize.log",
            "done_marker": re.compile(r"Completed\(nonconverge rerun\)$"),
        },
        {
            "name": "unknown_no_terminal",
            "list_file": "split_v2_unknown_no_terminal_marker.list",
            "mode": "nonterminal",
            "rerun_log": "fasterCap_rerun_unknown_noterm.log",
            "done_marker": re.compile(r"Completed\(unknown-noterm rerun\)$"),
        },
    ]

    rows = []
    for s in specs:
        dirs = read_list(run_dir / s["list_file"])
        unresolved = 0
        for d in dirs:
            unresolved += int(is_unresolved(run_dir / d / "wires.log", s["mode"], nonconv133_re))
        resolved = len(dirs) - unresolved
        attempts = count_attempts(run_dir / s["rerun_log"], s["done_marker"])
        rows.append(
            {
                "bucket": s["name"],
                "total": len(dirs),
                "attempts": attempts,
                "resolved": resolved,
                "unresolved": unresolved,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Record split progress every N minutes.")
    parser.add_argument("--run-dir", required=True, help="Path to 5v2_typ_widened directory.")
    parser.add_argument("--out", default="split_progress_10m.tsv", help="Output TSV file path.")
    parser.add_argument("--interval-sec", type=int, default=600, help="Sampling interval in seconds.")
    parser.add_argument(
        "--iterations",
        type=int,
        default=0,
        help="Number of samples to take; 0 means infinite loop.",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not out_path.exists():
        out_path.write_text(
            "timestamp\tbucket\ttotal\tattempts\tresolved\tunresolved\n",
            encoding="utf-8",
        )

    count = 0
    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = collect(run_dir)
        with out_path.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(
                    f"{now}\t{r['bucket']}\t{r['total']}\t{r['attempts']}\t{r['resolved']}\t{r['unresolved']}\n"
                )
        print(f"[{now}] progress sampled -> {out_path}")
        for r in rows:
            print(
                f"  {r['bucket']}: total={r['total']} attempts={r['attempts']} "
                f"resolved={r['resolved']} unresolved={r['unresolved']}"
            )

        count += 1
        if args.iterations > 0 and count >= args.iterations:
            break
        time.sleep(args.interval_sec)


if __name__ == "__main__":
    main()

