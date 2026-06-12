#!/usr/bin/env python3
"""
Find nets that exist in DEF routing but are missing in SPEF *D_NET entries.

This helps localize areas where RC extraction/lookup coverage may be missing.
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


COORD_RE = re.compile(r"\(\s*(-?\d+)\s+(-?\d+)\s*\)")
DEF_NET_START_RE = re.compile(r"^\s*-\s+(\S+)")
DEF_NETS_BEGIN_RE = re.compile(r"^\s*NETS\s+\d+\s*;")
SPEF_DNET_RE = re.compile(r"^\*D_NET\s+(\S+)")
SPEF_NAMEMAP_RE = re.compile(r"^\*(\d+)\s+(.+?)\s*$")


@dataclass
class DefNet:
    name: str
    block_lines: List[str] = field(default_factory=list)
    routed_lines: List[str] = field(default_factory=list)
    is_power_ground: bool = False

    def bbox(self) -> Optional[Tuple[int, int, int, int]]:
        coords: List[Tuple[int, int]] = []
        for line in self.routed_lines:
            for m in COORD_RE.finditer(line):
                coords.append((int(m.group(1)), int(m.group(2))))
        if not coords:
            return None
        xs = [x for x, _ in coords]
        ys = [y for _, y in coords]
        return (min(xs), min(ys), max(xs), max(ys))


def normalize_name(name: str) -> str:
    s = name.strip().strip('"')
    # Convert escaped SPEF/DEF names to canonical names.
    # Example: ctrl\.state\.out\[1\] -> ctrl.state.out[1]
    # Keep hierarchical slash after unescaping as-is.
    s = re.sub(r'\\(.)', r'\1', s)
    if s.startswith("\\"):  # defensive for odd leading escapes
        s = s[1:]
    return s


def parse_spef_nets(path: Path) -> Set[str]:
    name_map: Dict[str, str] = {}
    spef_nets: Set[str] = set()
    in_name_map = False

    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.startswith("*NAME_MAP"):
            in_name_map = True
            continue

        if in_name_map:
            m_map = SPEF_NAMEMAP_RE.match(line)
            if m_map:
                name_map[f"*{m_map.group(1)}"] = normalize_name(m_map.group(2))
                continue
            if line.startswith("*"):
                in_name_map = False

        m_dnet = SPEF_DNET_RE.match(line)
        if m_dnet:
            net_tok = m_dnet.group(1)
            mapped = name_map.get(net_tok, net_tok)
            spef_nets.add(normalize_name(mapped))

    return spef_nets


def parse_def_nets(path: Path) -> Dict[str, DefNet]:
    nets: Dict[str, DefNet] = {}
    in_nets = False
    curr: Optional[DefNet] = None

    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()

        if not in_nets and DEF_NETS_BEGIN_RE.match(stripped):
            in_nets = True
            continue
        if in_nets and stripped.startswith("END NETS"):
            break
        if not in_nets:
            continue

        m_start = DEF_NET_START_RE.match(line)
        if m_start:
            if curr is not None:
                nets[curr.name] = curr
            curr = DefNet(name=normalize_name(m_start.group(1)))

        if curr is None:
            continue

        curr.block_lines.append(stripped)
        if " + USE POWER" in line or " + USE GROUND" in line:
            curr.is_power_ground = True
        if "+ ROUTED" in line or stripped.startswith("NEW "):
            curr.routed_lines.append(stripped)

    if curr is not None:
        nets[curr.name] = curr

    return nets


def write_csv(out_csv: Path, rows: List[Dict[str, str]]) -> None:
    fields = [
        "net_name",
        "missing_in_spef",
        "is_power_ground",
        "has_routed_segment",
        "bbox_llx",
        "bbox_lly",
        "bbox_urx",
        "bbox_ury",
        "route_excerpt",
    ]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Report DEF nets that have routing but are missing from SPEF *D_NET "
            "and localize approximate DEF bbox."
        )
    )
    ap.add_argument("--def-file", required=True, help="Path to DEF file")
    ap.add_argument("--spef-file", required=True, help="Path to SPEF file")
    ap.add_argument(
        "--out-csv",
        default="missing_rc_nets_with_def_context.csv",
        help="Output CSV path",
    )
    ap.add_argument(
        "--include-power-ground",
        action="store_true",
        help="Include POWER/GROUND nets in report",
    )
    args = ap.parse_args()

    def_file = Path(args.def_file)
    spef_file = Path(args.spef_file)
    out_csv = Path(args.out_csv)

    def_nets = parse_def_nets(def_file)
    spef_nets = parse_spef_nets(spef_file)

    rows: List[Dict[str, str]] = []
    routed_count = 0
    for net in def_nets.values():
        if net.routed_lines:
            routed_count += 1
        if not args.include_power_ground and net.is_power_ground:
            continue
        if not net.routed_lines:
            continue
        if net.name in spef_nets:
            continue

        b = net.bbox()
        excerpt = " | ".join(net.routed_lines[:5])
        rows.append(
            {
                "net_name": net.name,
                "missing_in_spef": "1",
                "is_power_ground": "1" if net.is_power_ground else "0",
                "has_routed_segment": "1",
                "bbox_llx": "" if b is None else str(b[0]),
                "bbox_lly": "" if b is None else str(b[1]),
                "bbox_urx": "" if b is None else str(b[2]),
                "bbox_ury": "" if b is None else str(b[3]),
                "route_excerpt": excerpt,
            }
        )

    write_csv(out_csv, rows)

    print(f"DEF nets parsed      : {len(def_nets)}")
    print(f"DEF routed nets      : {routed_count}")
    print(f"SPEF *D_NET nets     : {len(spef_nets)}")
    print(f"Missing routed nets  : {len(rows)}")
    print(f"Output CSV           : {out_csv}")


if __name__ == "__main__":
    main()
