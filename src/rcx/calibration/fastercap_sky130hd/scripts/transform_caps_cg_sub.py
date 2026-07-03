#!/usr/bin/env python3
"""
Rewrite .caps FR using substrate-only CG definition (victim wire 3):

  CG = C33 - (|C32| + |C34|) - (|C31| + |C35|)
     = TC - CC - CC2

Only CC/TC/CC2 are read from existing caps lines; FR is replaced before
read_rcx_tables maps FR -> model fringe_/gnd_cap.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

CAPS_RE = re.compile(
    r"^(?P<head>Metal .+? LEN \d+  CC  )"
    r"(?P<cc>[0-9.eE+-]+  FR  )"
    r"(?P<fr>[0-9.eE+-]+  TC  )"
    r"(?P<tc>[0-9.eE+-]+  CC2  )"
    r"(?P<cc2>[0-9.eE+-]+)(?P<tail>  .*?)$"
)


def fmt_ff(val: float) -> str:
    return f"{val:9.6f}"


def transform_line(line: str, wire_only: int | None) -> tuple[str, bool]:
    line = line.rstrip("\n")
    if not line.startswith("Metal "):
        return line, False

    if wire_only is not None and not line.rstrip().endswith(f"/wire_{wire_only}"):
        return line, False

    m = CAPS_RE.match(line)
    if not m:
        return line, False

    cc = float(m.group("cc").split()[0])
    tc = float(m.group("tc").split()[0])
    cc2 = float(m.group("cc2"))
    cg = tc - cc - cc2

    new_line = (
        f"{m.group('head')}{fmt_ff(cc)}  FR  {fmt_ff(cg)}  TC  {fmt_ff(tc)}  "
        f"CC2  {fmt_ff(cc2)}{m.group('tail')}"
    )
    return new_line, True


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Set caps FR = TC - CC - CC2 (CG_sub for wire 3)."
    )
    ap.add_argument("-in_file", required=True, help="Input .caps")
    ap.add_argument("-out_file", required=True, help="Output .caps")
    ap.add_argument(
        "--wire",
        type=int,
        default=3,
        help="Only rewrite lines for this wire index (default: 3)",
    )
    ap.add_argument(
        "--all-wires",
        action="store_true",
        help="Rewrite every caps line (not only --wire)",
    )
    args = ap.parse_args()

    wire_only = None if args.all_wires else args.wire
    in_path = Path(args.in_file)
    out_path = Path(args.out_file)

    changed = 0
    total = 0
    out_lines: list[str] = []
    for raw in in_path.read_text(errors="ignore").splitlines():
        total += 1
        new_line, ok = transform_line(raw, wire_only)
        if ok:
            changed += 1
        out_lines.append(new_line)

    out_path.write_text("\n".join(out_lines) + "\n")
    print(f"input_lines={total}")
    print(f"rewritten={changed}")
    print(f"out_file={out_path}")


if __name__ == "__main__":
    main()
