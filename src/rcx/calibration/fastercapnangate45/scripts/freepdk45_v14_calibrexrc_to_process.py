#!/usr/bin/env python3
"""
Generate OpenRCX process.TYP / process.MIN from FreePDK45-v1.4 calibrexRC profile.

Input:
  - calibrexRC.rul (contains a commented stack profile block)
  - optional rules.txt (used to patch obvious outliers, e.g. metal1 spacing)

Output:
  - process.TYP
  - process.MIN
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Metal:
    idx: int
    height: float
    thickness: float
    wmin: float
    smin: float
    rpsq: float | None = None

    @property
    def name(self) -> str:
        return f"M{self.idx}"

    @property
    def resistivity(self) -> float | None:
        if self.rpsq is None:
            return None
        return self.rpsq * self.thickness


@dataclass
class Dielectric:
    name: str
    thickness: float
    er: float


def parse_calibrexrc(path: Path) -> tuple[dict[int, Metal], dict[str, Dielectric]]:
    text = path.read_text(errors="ignore")
    lines = text.splitlines()

    metals: dict[int, Metal] = {}
    diels: dict[str, Dielectric] = {}

    z_pat = re.compile(r"//\s*---\s*([0-9.]+)")
    c_pat = re.compile(
        r"//\s*\|\s*(metal(\d+))\s+C\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)"
    )
    d_pat = re.compile(r"//\s*\|\s*([A-Za-z0-9_]+)\s+D\s+([0-9.]+)\s+([0-9.]+)")

    for i, ln in enumerate(lines):
        mc = c_pat.search(ln)
        if mc:
            idx = int(mc.group(2))
            t = float(mc.group(3))
            w = float(mc.group(4))
            s = float(mc.group(5))

            z_top = z_bot = None
            for j in range(i - 1, max(-1, i - 8), -1):
                mz = z_pat.search(lines[j])
                if mz:
                    z_top = float(mz.group(1))
                    break
            for j in range(i + 1, min(len(lines), i + 8)):
                mz = z_pat.search(lines[j])
                if mz:
                    z_bot = float(mz.group(1))
                    break
            if z_top is None or z_bot is None:
                raise ValueError(f"Cannot infer z for metal{idx} from calibrexRC profile")
            h = min(z_top, z_bot)
            metals[idx] = Metal(idx=idx, height=h, thickness=t, wmin=w, smin=s)
            continue

        md = d_pat.search(ln)
        if md:
            name = md.group(1)
            t = float(md.group(2))
            er = float(md.group(3))
            diels[name] = Dielectric(name=name, thickness=t, er=er)

    if len(metals) < 10:
        raise ValueError(f"Expected >=10 metals in calibrexRC profile, got {len(metals)}")

    return metals, diels


def patch_with_rules_txt(metals: dict[int, Metal], rules_txt: Path | None) -> None:
    if rules_txt is None or not rules_txt.exists():
        return
    txt = rules_txt.read_text(errors="ignore")
    # Example line: Metal1.2 drc min spacing sep metal1 0.065 <
    rule_pat = re.compile(
        r"Metal(\d+)\.\d+\s+drc\s+min\s+(width|spacing)\s+\S+\s+metal\d+\s+([0-9.]+)"
    )
    width_map: dict[int, float] = {}
    spacing_map: dict[int, float] = {}
    for m in rule_pat.finditer(txt):
        idx = int(m.group(1))
        kind = m.group(2)
        val = float(m.group(3))
        if kind == "width":
            width_map[idx] = val
        else:
            spacing_map[idx] = val

    for idx, metal in metals.items():
        # Patch only if clearly out-of-family (e.g. 0.650 instead of 0.065)
        if idx in width_map and metal.wmin > 5.0 * width_map[idx]:
            metal.wmin = width_map[idx]
        if idx in spacing_map and metal.smin > 5.0 * spacing_map[idx]:
            metal.smin = spacing_map[idx]


def assign_rpsq_from_nangate_itf(
    metals: dict[int, Metal], itf: Path | None, fallback_rpsq: float = 0.25
) -> None:
    # FreePDK calibrexRC profile comment block does not carry RPSQ directly.
    # To keep extraction flow operational and comparable, optionally borrow
    # per-layer RPSQ from Nangate ITF. If unavailable, use a conservative fallback.
    rpsq_map: dict[int, float] = {}
    if itf and itf.exists():
        for ln in itf.read_text(errors="ignore").splitlines():
            m = re.match(
                r"\s*CONDUCTOR\s+metal(\d+)\s*\{[^}]*RPSQ=([0-9.]+)\s*\}",
                ln,
            )
            if m:
                rpsq_map[int(m.group(1))] = float(m.group(2))
    for idx, metal in metals.items():
        metal.rpsq = rpsq_map.get(idx, fallback_rpsq)


def conductor_distance(metals: dict[int, Metal], idx: int) -> float:
    if idx == 1:
        return metals[idx].height
    prev = metals[idx - 1]
    curr = metals[idx]
    return curr.height - (prev.height + prev.thickness)


def emit_process(
    metals: dict[int, Metal],
    diels: dict[str, Dielectric],
    corner: str,
    source_calibrexrc: Path,
    source_rules: Path | None,
    source_rpsq: Path | None,
) -> str:
    out: list[str] = []
    out.append(f"# Auto-generated process.{corner} from FreePDK45-v1.4 calibrexRC")
    out.append(f"# Source calibrexRC: {source_calibrexrc}")
    out.append(f"# Source rules.txt: {source_rules if source_rules else 'N/A'}")
    out.append(f"# Source RPSQ ITF: {source_rpsq if source_rpsq else 'N/A (fallback)'}")
    out.append(
        "# NOTE: generated for isolated pattern/FasterCap rerun; does not overwrite baseline process.*"
    )
    out.append("")

    for idx in range(1, 11):
        m = metals[idx]
        out.append(f"CONDUCTOR M{idx} {{")
        out.append(f"        distance {conductor_distance(metals, idx):.4f}")
        out.append(f"        thickness {m.thickness:.4f}")
        out.append(f"        min_width {m.wmin:.4f}")
        out.append(f"        min_spacing {m.smin:.4f}")
        if corner == "TYP" or idx >= 6:
            rho = m.resistivity if m.resistivity is not None else 0.0
            out.append(f"        resistivity {rho:.6f}")
        out.append("}")
    out.append("")

    # Keep dielectric naming aligned with existing converter expectations.
    # Use single slab per metal (metalN_diel) when diel2 is unavailable.
    if "field_base_diel" in diels:
        d = diels["field_base_diel"]
        out.extend(
            [
                "DIELECTRIC substrate_1 {",
                f"        epsilon {d.er:.1f}",
                f"        thickness {d.thickness:.4f}",
                "        next_met 1",
                "}",
                "",
            ]
        )

    for idx in range(1, 11):
        key = f"metal{idx}_diel"
        if key in diels:
            d = diels[key]
            out.extend(
                [
                    f"DIELECTRIC m{idx}_below {{",
                    f"        epsilon {d.er:.1f}",
                    f"        thickness {d.thickness:.4f}",
                    f"        next_met {idx}",
                    "}",
                    "",
                ]
            )

    out.extend(
        [
            "DIELECTRIC air_1 {",
            "        epsilon 1.0",
            "        thickness 1.0000",
            "}",
            "",
        ]
    )
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--calibrexrc", type=Path, required=True)
    ap.add_argument("--rules-txt", type=Path, default=None)
    ap.add_argument("--rpsq-itf", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    metals, diels = parse_calibrexrc(args.calibrexrc)
    patch_with_rules_txt(metals, args.rules_txt)
    assign_rpsq_from_nangate_itf(metals, args.rpsq_itf)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for corner in ("TYP", "MIN"):
        content = emit_process(
            metals=metals,
            diels=diels,
            corner=corner,
            source_calibrexrc=args.calibrexrc,
            source_rules=args.rules_txt,
            source_rpsq=args.rpsq_itf,
        )
        out = args.out_dir / f"process.{corner}"
        out.write_text(content)
        print(f"Wrote {out}")


if __name__ == "__main__":
    main()
