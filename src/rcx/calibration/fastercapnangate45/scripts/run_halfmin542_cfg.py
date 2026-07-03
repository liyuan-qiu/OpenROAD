#!/usr/bin/env python3
"""
Run FasterCap on newly added half-min-width patterns only.

Input list defaults to:
  5v2_typ_widened/halfmin_added_patterns.list

Flow per pattern:
  1) Convert wires -> wires.lst
  2) Run FasterCap with fixed knobs:
     -g -ps128 -t1e-2 -d2.0 -m0.05 -mc0.5 -r
  3) Write wires.log back to pattern directory
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import time
from pathlib import Path


def run_one(
    pattern_dir: Path,
    process_out: Path,
    converter: Path,
    fastercap: Path,
    timeout_sec: int,
) -> tuple[str, float]:
    # 1) Universal format -> FasterCap input.
    conv_cmd = [
        "python3",
        str(converter),
        str(process_out),
        "./",
        "./",
        "standard",
        "-sim_window_ext",
        "-15",
        "-0",
        "-15",
        "15",
        "0",
        "15",
    ]
    conv = subprocess.run(
        conv_cmd,
        cwd=pattern_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    (pattern_dir / "wireDielGeomGen.log").write_text(conv.stdout)
    if conv.returncode != 0:
        return (f"convert_failed_{conv.returncode}", 0.0)

    # 2) FasterCap run with requested knobs.
    fc_cmd = [
        str(fastercap),
        "-b",
        "wires.lst",
        "-g",
        "-ps128",
        "-t1e-2",
        "-d2.0",
        "-m0.05",
        "-mc0.5",
        "-r",
    ]
    t0 = time.time()
    try:
        cp = subprocess.run(
            fc_cmd,
            cwd=pattern_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        (pattern_dir / "wires.log").write_text(cp.stdout)
        runtime = time.time() - t0
        if cp.returncode == 0:
            return ("ok", runtime)
        return (f"failed_{cp.returncode}", runtime)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + "\nTIMEOUT\n"
        (pattern_dir / "wires.log").write_text(out)
        runtime = time.time() - t0
        return ("timeout", runtime)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run half-min 542 patterns with fixed knobs")
    ap.add_argument(
        "--root",
        default="/home/liyuanqiu/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fastercapnangate45/5v2_typ_widened",
        help="Root directory containing TYP and process.out",
    )
    ap.add_argument(
        "--list-file",
        default="halfmin_added_patterns.list",
        help="Pattern list file relative to --root",
    )
    ap.add_argument(
        "--fastercap",
        default="/home/liyuanqiu/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fastercapnangate45/bin/FasterCap",
    )
    ap.add_argument(
        "--converter",
        default="/home/liyuanqiu/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fastercapnangate45/scripts/UniversalFormat2FasterCap_923.py",
    )
    ap.add_argument("--timeout-sec", type=int, default=180)
    ap.add_argument(
        "--out-csv",
        default="halfmin_added_run_results.csv",
        help="CSV path relative to --root",
    )
    args = ap.parse_args()

    root = Path(args.root)
    list_file = root / args.list_file
    process_out = root / "process.out"
    fastercap = Path(args.fastercap)
    converter = Path(args.converter)
    out_csv = root / args.out_csv

    patterns = [
        line.strip()
        for line in list_file.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    rows: list[dict[str, str]] = []
    t_all = time.time()
    for i, rel in enumerate(patterns, 1):
        pdir = root / "TYP" / rel
        print(f"[{i}/{len(patterns)}] {rel}")
        state, runtime = run_one(
            pattern_dir=pdir,
            process_out=process_out,
            converter=converter,
            fastercap=fastercap,
            timeout_sec=args.timeout_sec,
        )
        rows.append(
            {
                "idx": str(i),
                "pattern": rel,
                "state": state,
                "runtime_sec": f"{runtime:.3f}",
            }
        )
        if i % 25 == 0:
            print(f"progress {i}/{len(patterns)}")

    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["idx", "pattern", "state", "runtime_sec"])
        w.writeheader()
        w.writerows(rows)

    from collections import Counter

    c = Counter(r["state"] for r in rows)
    print("DONE")
    print(f"total={len(rows)} elapsed_sec={time.time()-t_all:.2f}")
    for k in sorted(c):
        print(f"{k}={c[k]}")
    print(f"csv={out_csv}")


if __name__ == "__main__":
    main()
