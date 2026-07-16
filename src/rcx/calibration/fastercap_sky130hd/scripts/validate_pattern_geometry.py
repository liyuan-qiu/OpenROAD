#!/usr/bin/env python3
"""Validate five-wire source geometry before FasterCap conversion."""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path


WIRE_RE = re.compile(
    r"^WIRE\s+(?P<index>\d+)\s+\S+\s+"
    r"LL\s+(?P<llx>[-+\d.eE]+)\s+(?P<lly>[-+\d.eE]+)\s+"
    r"LR\s+(?P<lrx>[-+\d.eE]+)\s+(?P<lry>[-+\d.eE]+)\s+"
    r"UR\s+(?P<urx>[-+\d.eE]+)\s+(?P<ury>[-+\d.eE]+)\s+"
    r"UL\s+(?P<ulx>[-+\d.eE]+)\s+(?P<uly>[-+\d.eE]+)\s+"
    r"LENGTH\s+(?P<length>[-+\d.eE]+)\s+VOLTAGE\s+(?P<voltage>[-+\d.eE]+)"
)
WINDOW_RE = re.compile(
    r"^WINDOW_BBOX\s+LL\s+(?P<llx>[-+\d.eE]+)\s+\S+\s+"
    r"UR\s+(?P<urx>[-+\d.eE]+)\s+\S+\s+LENGTH\s+(?P<length>[-+\d.eE]+)"
)


@dataclass
class Wire:
    index: int
    llx: float
    lly: float
    lrx: float
    lry: float
    urx: float
    ury: float
    ulx: float
    uly: float
    length: float
    voltage: float

    @property
    def center_x(self) -> float:
        return (self.llx + self.lrx) / 2.0

    @property
    def width(self) -> float:
        return self.lrx - self.llx


def close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def parse_case(path: Path) -> tuple[list[Wire], tuple[float, float, float] | None]:
    wires: list[Wire] = []
    window = None
    for line in path.read_text(errors="replace").splitlines():
        match = WIRE_RE.match(line)
        if match:
            values = match.groupdict()
            wires.append(
                Wire(
                    index=int(values["index"]),
                    **{
                        key: float(value)
                        for key, value in values.items()
                        if key != "index"
                    },
                )
            )
            continue
        match = WINDOW_RE.match(line)
        if match:
            window = tuple(float(match.group(key)) for key in ("llx", "urx", "length"))
    return sorted(wires, key=lambda wire: wire.index), window


def validate_case(
    path: Path, tol: float, family: str = "Over5"
) -> dict[str, object]:
    wires, window = parse_case(path)
    all_wires = wires
    issues: list[str] = []
    max_pair_center_error = 0.0
    victim_center = ""

    if family == "UnderDiag5":
        if len(wires) < 6:
            issues.append(f"wire_count={len(wires)}")
        elif any(not close(wire.voltage, 0.0, tol) for wire in wires[5:]):
            issues.append("diag_voltage_assignment")
        wires = wires[:5]
    elif len(wires) != 5:
        issues.append(f"wire_count={len(wires)}")

    if not issues and [wire.index for wire in wires] != [1, 2, 3, 4, 5]:
        issues.append("wire_indices")
    if not issues:
        victim = wires[2]
        victim_center = victim.center_x
        for left, right in ((wires[0], wires[4]), (wires[1], wires[3])):
            center_error = abs((left.center_x + right.center_x) / 2.0 - victim.center_x)
            max_pair_center_error = max(max_pair_center_error, center_error)
            if center_error > tol:
                issues.append(f"pair_center_{left.index}_{right.index}")
            for field in (
                "width",
                "lly",
                "lry",
                "ury",
                "uly",
                "length",
            ):
                if not close(getattr(left, field), getattr(right, field), tol):
                    issues.append(f"pair_{field}_{left.index}_{right.index}")

        reference = wires[0]
        for wire in wires[1:]:
            for field in ("width", "lly", "lry", "ury", "uly", "length"):
                if not close(getattr(reference, field), getattr(wire, field), tol):
                    issues.append(f"wire_{field}_{wire.index}")

        expected_voltages = [0.0, 0.0, 1.0, 0.0, 0.0]
        if any(
            not close(wire.voltage, expected, tol)
            for wire, expected in zip(wires, expected_voltages)
        ):
            issues.append("voltage_assignment")

        if window is None:
            issues.append("window_missing")
        else:
            window_center = (window[0] + window[1]) / 2.0
            if not close(window_center, victim.center_x, tol):
                issues.append("window_not_centered")
            if not close(window[2], victim.length, tol):
                issues.append("window_length")

    return {
        "case": str(path.parent),
        "wire_count": len(all_wires),
        "victim_center_x": victim_center,
        "max_pair_center_error": max_pair_center_error,
        "status": "PASS" if not issues else "FAIL",
        "issues": ";".join(sorted(set(issues))),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--corner", default="TYP")
    parser.add_argument("--family", default="Over5")
    parser.add_argument("--stack", default="")
    parser.add_argument("--len-mult", type=int, required=True)
    parser.add_argument("--tolerance", type=float, default=1e-9)
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--output-csv", type=Path, required=True)
    args = parser.parse_args()

    root = args.run_dir.resolve()
    family_root = root / args.corner / args.family
    paths = sorted(family_root.rglob("wires"))
    suffix = f"_L{args.len_mult}"
    paths = [path for path in paths if path.parent.name.endswith(suffix)]
    if args.family == "UnderDiag5":
        paths = [path for path in paths if "_S0_L" in path.parent.name]
    if args.stack:
        marker = f"/{args.stack}/"
        paths = [path for path in paths if marker in path.as_posix()]
    if args.max_cases > 0:
        paths = paths[: args.max_cases]
    if not paths:
        raise SystemExit(f"ERROR: no matching wires under {family_root}")

    rows = [validate_case(path, args.tolerance, args.family) for path in paths]
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    failed = [row for row in rows if row["status"] == "FAIL"]
    print(
        f"geometry: total={len(rows)} pass={len(rows) - len(failed)} "
        f"fail={len(failed)} report={args.output_csv}"
    )
    for row in failed[:10]:
        print(f"FAIL {row['case']}: {row['issues']}")
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
