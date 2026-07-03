#!/usr/bin/env python3
"""Convert FasterCap pattern 'wires' file into Quantus-ready DEF/V/SDC.

This creates a tiny top-level design with two pins per extracted wire:
- <net>_A at y=0
- <net>_B at y=L

and one routed segment on the corresponding metal layer.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


WIRE_RE = re.compile(
    r"^WIRE\s+(\d+)\s+(\S+)\s+LL\s+([-\d.]+)\s+([-\d.]+)\s+LR\s+([-\d.]+)\s+([-\d.]+)\s+UR\s+([-\d.]+)\s+([-\d.]+)\s+UL\s+([-\d.]+)\s+([-\d.]+)\s+LENGTH\s+([-\d.]+)"
)
LAYER_RE = re.compile(r"^M(\d+)_")


@dataclass
class Wire:
    idx: int
    layer_num: int
    layer_name: str
    x_center: float
    width: float
    length: float


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--wires-file", help="Path to one pattern wires file")
    p.add_argument("--out-dir", help="Output benchmark directory for single conversion")
    p.add_argument("--design-name", default="pattern_qts", help="Design/top name (single mode)")
    p.add_argument(
        "--patterns-root",
        help="Pattern root dir containing many case dirs (each with a wires file)",
    )
    p.add_argument(
        "--case-list",
        help="Optional text file: one relative case path per line (under patterns-root)",
    )
    p.add_argument(
        "--batch-out-root",
        help="Output root for batch conversion; each case gets one subdir",
    )
    p.add_argument("--dbu", type=int, default=1000, help="DEF DBU per micron")
    return p.parse_args()


def to_dbu(v: float, dbu: int) -> int:
    return int(round(v * dbu))


def parse_wires(path: Path) -> list[Wire]:
    wires: list[Wire] = []
    for line in path.read_text(errors="ignore").splitlines():
        m = WIRE_RE.match(line.strip())
        if not m:
            continue
        idx = int(m.group(1))
        token = m.group(2)
        llx = float(m.group(3))
        lrx = float(m.group(5))
        length = float(m.group(11))
        layer_m = LAYER_RE.match(token)
        if not layer_m:
            continue
        layer_num = int(layer_m.group(1))
        layer_name = f"metal{layer_num}"
        x_center = (llx + lrx) / 2.0
        width = abs(lrx - llx)
        wires.append(
            Wire(
                idx=idx,
                layer_num=layer_num,
                layer_name=layer_name,
                x_center=x_center,
                width=width,
                length=length,
            )
        )
    return wires


def write_verilog(out_dir: Path, design: str, wires: list[Wire]) -> None:
    ports: list[str] = []
    lines = [f"module {design}("]
    for w in wires:
        ports.extend([f"n{w.idx}_A", f"n{w.idx}_B"])
    lines.append("  " + ", ".join(ports))
    lines.append(");")
    for p in ports:
        lines.append(f"  inout {p};")
    for w in wires:
        lines.append(f"  wire n{w.idx};")
        lines.append(f"  assign n{w.idx}_A = n{w.idx};")
        lines.append(f"  assign n{w.idx}_B = n{w.idx};")
    lines.append("endmodule")
    (out_dir / f"{design}.v").write_text("\n".join(lines) + "\n")


def write_sdc(out_dir: Path, design: str) -> None:
    sdc = [
        "# Minimal SDC for Quantus extraction-only benchmark",
        f"current_design {design}",
    ]
    (out_dir / f"{design}.sdc").write_text("\n".join(sdc) + "\n")


def write_def(out_dir: Path, design: str, wires: list[Wire], dbu: int) -> None:
    if not wires:
        raise SystemExit("No WIRE entries parsed from wires file.")

    max_len = max(w.length for w in wires)
    min_x = min(w.x_center - w.width / 2.0 for w in wires) - 1.0
    max_x = max(w.x_center + w.width / 2.0 for w in wires) + 1.0

    die_x1 = to_dbu(min_x, dbu)
    die_y1 = 0
    die_x2 = to_dbu(max_x, dbu)
    die_y2 = to_dbu(max_len + 1.0, dbu)

    pins = []
    for w in wires:
        x = to_dbu(w.x_center, dbu)
        y0 = 0
        y1 = to_dbu(w.length, dbu)
        pins.append((f"n{w.idx}_A", f"n{w.idx}", w.layer_name, x, y0))
        pins.append((f"n{w.idx}_B", f"n{w.idx}", w.layer_name, x, y1))

    lines = [
        "VERSION 5.8 ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        f"DESIGN {design} ;",
        f"UNITS DISTANCE MICRONS {dbu} ;",
        f"DIEAREA ( {die_x1} {die_y1} ) ( {die_x2} {die_y2} ) ;",
        f"PINS {len(pins)} ;",
    ]
    for name, net, layer, x, y in pins:
        lines.extend(
            [
                f"- {name} + NET {net}",
                "  + DIRECTION INOUT + USE SIGNAL",
                f"  + LAYER {layer} ( -10 -10 ) ( 10 10 )",
                f"  + PLACED ( {x} {y} ) N ;",
            ]
        )
    lines.append("END PINS")

    lines.append(f"NETS {len(wires)} ;")
    for w in wires:
        x = to_dbu(w.x_center, dbu)
        y0 = 0
        y1 = to_dbu(w.length, dbu)
        lines.extend(
            [
                f"- n{w.idx} ( PIN n{w.idx}_A ) ( PIN n{w.idx}_B )",
                f"  + ROUTED {w.layer_name} ( {x} {y0} ) ( {x} {y1} ) ;",
            ]
        )
    lines.append("END NETS")
    lines.append("END DESIGN")

    (out_dir / f"{design}.def").write_text("\n".join(lines) + "\n")


def main() -> int:
    args = parse_args()
    single_mode = bool(args.wires_file or args.out_dir)
    batch_mode = bool(args.patterns_root or args.batch_out_root or args.case_list)

    if single_mode and batch_mode:
        raise SystemExit("Use either single mode or batch mode, not both.")

    if single_mode:
        if not args.wires_file or not args.out_dir:
            raise SystemExit("--wires-file and --out-dir are required in single mode.")
        wires_file = Path(args.wires_file).resolve()
        out_dir = Path(args.out_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        wires = parse_wires(wires_file)
        write_verilog(out_dir, args.design_name, wires)
        write_sdc(out_dir, args.design_name)
        write_def(out_dir, args.design_name, wires, args.dbu)

        print(f"wires_file={wires_file}")
        print(f"out_dir={out_dir}")
        print(f"design={args.design_name}")
        print(f"wires_parsed={len(wires)}")
        print(f"def={out_dir / (args.design_name + '.def')}")
        print(f"verilog={out_dir / (args.design_name + '.v')}")
        print(f"sdc={out_dir / (args.design_name + '.sdc')}")
        return 0

    if not args.patterns_root or not args.batch_out_root:
        raise SystemExit(
            "Batch mode requires --patterns-root and --batch-out-root "
            "(optionally --case-list)."
        )

    patterns_root = Path(args.patterns_root).resolve()
    batch_out_root = Path(args.batch_out_root).resolve()
    batch_out_root.mkdir(parents=True, exist_ok=True)

    if args.case_list:
        cases = []
        for raw in Path(args.case_list).read_text().splitlines():
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            cases.append(s)
    else:
        cases = sorted(str(p.parent.relative_to(patterns_root)) for p in patterns_root.rglob("wires"))

    ok = 0
    fail = 0
    for rel_case in cases:
        wires_file = patterns_root / rel_case / "wires"
        if not wires_file.exists():
            fail += 1
            print(f"missing_wires,{rel_case}")
            continue
        safe_name = re.sub(r"[^a-zA-Z0-9_]+", "_", rel_case).strip("_")
        design = f"pat_{safe_name}"
        out_dir = batch_out_root / safe_name
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            wires = parse_wires(wires_file)
            write_verilog(out_dir, design, wires)
            write_sdc(out_dir, design)
            write_def(out_dir, design, wires, args.dbu)
            ok += 1
            print(f"ok,{rel_case},{out_dir}")
        except Exception as exc:  # pylint: disable=broad-except
            fail += 1
            print(f"fail,{rel_case},{exc}")

    print(f"batch_done,ok={ok},fail={fail},out_root={batch_out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

