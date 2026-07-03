#!/usr/bin/env python3
"""
Generate OpenRCX FasterCap process.TYP for SkyWater SKY130 (6 routing layers).

Default TECH LEF: **sky130hs** (`sky130_fd_sc_hs.tlef`) — aligns with `rcx_patterns.rules`.

OpenRCX / rcx_patterns.rules numbering:
  M1 = li1, M2 = met1, ..., M6 = met5

TECH LEF supplies WIDTH / SPACING / THICKNESS / RPERSQ.
Vertical stack / dielectric can be sourced either from:
  - built-in first-pass constants (default), or
  - external ICT file (`--ict`) for refined bottom-Z and epsilon profile.

Usage:
  python3 tech_lef_to_process_sky130.py \\
    --tech-lef flow/platforms/sky130hs/lef/sky130_fd_sc_hs.tlef \\
    --all-corners --out-dir data/generated/sky130hs_6m
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

# Bottom Z (µm) per routing layer — SKY130 ICT / cap table (issue #187), HD tlef names.
SKY130_BOTTOM_Z: dict[str, float] = {
    "li1": 0.9361,
    "met1": 1.3761,
    "met2": 1.8710,
    "met3": 2.5710,
    "met4": 3.6710,
    "met5": 5.0710,
}

SKY130_LAYER_ORDER: list[tuple[str, int]] = [
    ("li1", 1),
    ("met1", 2),
    ("met2", 3),
    ("met3", 4),
    ("met4", 5),
    ("met5", 6),
]

# Simplified dielectric slabs (first-pass 2-slab model per metal).
DIEL_BELOW_ER = 3.9
DIEL_ABOVE_ER = 2.9
LINT_ER = 7.3  # li1–met1 inter-level dielectric (LINT)


@dataclass
class RoutingLayer:
    lef_name: str
    rcx_index: int
    width: float
    spacing: float
    thickness: float
    bottom_z: float
    rpersq: float

    @property
    def top_z(self) -> float:
        return self.bottom_z + self.thickness

    @property
    def distance(self) -> float:
        return self.bottom_z

    @property
    def resistivity(self) -> float:
        return self.rpersq * self.thickness


@dataclass
class IctDielectric:
    name: str
    height: float
    thickness: float
    epsilon: float

    @property
    def top(self) -> float:
        return self.height + self.thickness

    def covers(self, z: float) -> bool:
        return self.height <= z <= self.top


def _strip_spacing_table(body: str) -> str:
    return re.sub(r"SPACINGTABLE.*?;", "", body, flags=re.DOTALL)


def _first_float(text: str, pattern: str, flags: int = 0) -> float | None:
    match = re.search(pattern, text, flags)
    return float(match.group(1)) if match else None


def _routing_width(body: str) -> float:
    stripped = _strip_spacing_table(body)
    width = _first_float(stripped, r"^\s*WIDTH\s+([\d.]+)", flags=re.MULTILINE)
    if width is None:
        raise ValueError("missing routing WIDTH")
    return width


def _routing_spacing(body: str, width: float) -> float:
    stripped = _strip_spacing_table(body)
    spacing = _first_float(stripped, r"^\s*SPACING\s+([\d.]+)", flags=re.MULTILINE)
    if spacing is not None:
        return spacing
    table = re.search(r"SPACINGTABLE(.*?);", body, re.DOTALL)
    if table:
        numbers = [float(x) for x in re.findall(r"([\d.]+)", table.group(1))]
        positives = [n for n in numbers if n > 0]
        if positives:
            return min(positives)
    pitch = _first_float(body, r"PITCH\s+([\d.]+)")
    if pitch is not None:
        return max(pitch - width, width)
    raise ValueError("cannot infer spacing")


def parse_sky130_tlef(path: Path) -> list[RoutingLayer]:
    text = path.read_text()
    by_name: dict[str, RoutingLayer] = {}
    for lef_name, rcx_index in SKY130_LAYER_ORDER:
        block = re.search(
            rf"LAYER\s+{lef_name}\s+TYPE\s+ROUTING\s*;(.*?)\s*END\s+{lef_name}",
            text,
            re.DOTALL,
        )
        if not block:
            raise ValueError(f"missing ROUTING layer {lef_name} in {path}")
        body = block.group(1)
        width = _routing_width(body)
        spacing = _routing_spacing(body, width)
        thickness = _first_float(body, r"THICKNESS\s+([\d.]+)")
        if thickness is None:
            raise ValueError(f"{lef_name}: missing THICKNESS")
        rpersq = _first_float(body, r"RESISTANCE\s+RPERSQ\s+([\d.]+)")
        if rpersq is None:
            raise ValueError(f"{lef_name}: missing RPERSQ")
        bottom_z = SKY130_BOTTOM_Z[lef_name]
        by_name[lef_name] = RoutingLayer(
            lef_name=lef_name,
            rcx_index=rcx_index,
            width=width,
            spacing=spacing,
            thickness=thickness,
            bottom_z=bottom_z,
            rpersq=rpersq,
        )
    return [by_name[name] for name, _ in SKY130_LAYER_ORDER]


def parse_ict_conductor_bottoms(ict_path: Path) -> dict[str, float]:
    text = ict_path.read_text(errors="ignore")
    out: dict[str, float] = {}
    for lef_name, _ in SKY130_LAYER_ORDER:
        m = re.search(
            rf"conductor\s+{lef_name}\s*\{{(.*?)\}}",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if not m:
            continue
        body = m.group(1)
        h = _first_float(body, r"height\s+([\d.]+)", flags=re.IGNORECASE)
        if h is not None:
            out[lef_name] = h
    return out


def parse_ict_dielectrics(ict_path: Path) -> list[IctDielectric]:
    text = ict_path.read_text(errors="ignore")
    out: list[IctDielectric] = []
    for m in re.finditer(r"dielectric\s+([A-Za-z0-9_]+)\s*\{(.*?)\}", text, re.DOTALL | re.IGNORECASE):
        name = m.group(1)
        body = m.group(2)
        conformal_m = re.search(r"conformal\s+(TRUE|FALSE)", body, re.IGNORECASE)
        if conformal_m and conformal_m.group(1).upper() == "TRUE":
            # OpenRCX process format here models vertical slabs only.
            continue
        h = _first_float(body, r"height\s+([\d.]+)", flags=re.IGNORECASE)
        t = _first_float(body, r"thickness\s+([\d.]+)", flags=re.IGNORECASE)
        er = _first_float(body, r"dielectric_constant\s+([\d.]+)", flags=re.IGNORECASE)
        if h is None or t is None or er is None or t <= 0:
            continue
        out.append(IctDielectric(name=name, height=h, thickness=t, epsilon=er))
    out.sort(key=lambda d: d.height)
    return out


def _epsilon_at_z(diels: list[IctDielectric], z: float, default_er: float) -> float:
    for d in diels:
        if d.covers(z):
            return d.epsilon
    return default_er


def derive_ict_dielectric_profile(layers: list[RoutingLayer], diels: list[IctDielectric]) -> tuple[float, dict[int, float], dict[int, float]]:
    substrate_eps = DIEL_BELOW_ER
    if diels:
        z0 = layers[0].bottom_z * 0.5
        substrate_eps = _epsilon_at_z(diels, z0, DIEL_BELOW_ER)

    below_er: dict[int, float] = {}
    above_er: dict[int, float] = {}
    for idx, layer in enumerate(layers):
        metal = layer.rcx_index
        if idx == 0:
            low = 0.0
        else:
            low = layers[idx - 1].top_z
        high = layer.bottom_z
        if high <= low:
            below_er[metal] = DIEL_BELOW_ER
        else:
            below_er[metal] = _epsilon_at_z(diels, low + 0.5 * (high - low), DIEL_BELOW_ER)

        top = layer.top_z
        if idx + 1 < len(layers):
            nxt = layers[idx + 1].bottom_z
            if nxt <= top:
                above_er[metal] = DIEL_ABOVE_ER
            else:
                above_er[metal] = _epsilon_at_z(diels, top + 0.5 * (nxt - top), DIEL_ABOVE_ER)
        else:
            above_er[metal] = _epsilon_at_z(diels, top + 0.2, DIEL_ABOVE_ER)
    return substrate_eps, below_er, above_er


def conductor_distance(layers: list[RoutingLayer], index: int) -> float:
    layer = layers[index]
    if index == 0:
        return layer.bottom_z
    prev = layers[index - 1]
    return layer.bottom_z - prev.top_z


def emit_summary(layers: list[RoutingLayer]) -> list[str]:
    lines = [
        "# --- Stack summary (M# = OpenRCX Metal #, lef_name = TECH LEF) ---",
    ]
    for layer in layers:
        dist = conductor_distance(layers, layer.rcx_index - 1)
        lines.append(
            f"# M{layer.rcx_index} ({layer.lef_name}): dist={dist:.4f} t={layer.thickness:.4f} "
            f"w={layer.width:.4f} s={layer.spacing:.4f} "
            f"z=[{layer.bottom_z:.4f},{layer.top_z:.4f}] rho={layer.resistivity:.6f}"
        )
    lines.append("")
    return lines


def emit_conductors(layers: list[RoutingLayer], corner: str) -> list[str]:
    lines = [
        "# CONDUCTOR M1..M6 = li1, met1..met5 (aligns with rcx_patterns LayerCount 6)",
        "",
    ]
    for idx, layer in enumerate(layers):
        dist = conductor_distance(layers, idx)
        lines.append(f"CONDUCTOR M{layer.rcx_index} {{")
        lines.append(f"        distance {dist:.4f}")
        lines.append(f"        thickness {layer.thickness:.4f}")
        lines.append(f"        min_width {layer.width:.4f}")
        lines.append(f"        min_spacing {layer.spacing:.4f}")
        if corner.upper() != "MIN" or layer.rcx_index >= 4:
            lines.append(f"        resistivity {layer.resistivity:.6f}")
        lines.append("}")
    lines.append("")
    return lines


def emit_dielectrics(
    layers: list[RoutingLayer],
    *,
    substrate_er: float = DIEL_BELOW_ER,
    below_er_map: dict[int, float] | None = None,
    above_er_map: dict[int, float] | None = None,
    ict_mode: bool = False,
) -> list[str]:
    below_er_map = below_er_map or {}
    above_er_map = above_er_map or {}
    lines = [
        "# DIELECTRIC section",
        "# - default: simplified 2-slab / metal",
        "# - ict mode: epsilon sampled from non-conformal ICT dielectrics",
        "",
        "DIELECTRIC substrate_1 {",
        f"        epsilon {substrate_er:.3f}",
        f"        thickness {layers[0].bottom_z:.4f}",
        "        next_met 1",
        "}",
        "",
    ]
    for idx, layer in enumerate(layers):
        metal = layer.rcx_index
        gap = conductor_distance(layers, idx)
        if idx == 0:
            below_th = gap * 0.55
            above_th = gap * 0.45
            below_er = below_er_map.get(metal, DIEL_BELOW_ER)
            above_er = above_er_map.get(metal, DIEL_ABOVE_ER)
        elif idx == 1:
            below_th = gap * 0.5
            above_th = gap * 0.5
            if ict_mode:
                below_er = below_er_map.get(metal, DIEL_BELOW_ER)
                above_er = above_er_map.get(metal, DIEL_ABOVE_ER)
            else:
                below_er = LINT_ER
                above_er = DIEL_ABOVE_ER
        else:
            below_th = gap * 0.15
            above_th = max(gap - below_th, 0.05)
            below_er = below_er_map.get(metal, DIEL_BELOW_ER)
            above_er = above_er_map.get(metal, DIEL_ABOVE_ER)

        lines.extend(
            [
                f"DIELECTRIC m{metal}_below {{",
                f"        epsilon {below_er:.3f}",
                f"        thickness {below_th:.4f}",
                f"        next_met {metal}",
                "}",
                "",
                f"DIELECTRIC m{metal}_above {{",
                f"        epsilon {above_er:.3f}",
                f"        thickness {above_th:.4f}",
                f"        met {metal}",
                "}",
                "",
            ]
        )
    lines.extend(
        [
            "DIELECTRIC air_1 {",
            "        epsilon 1.0",
            "        thickness 1.0000",
            "}",
            "",
        ]
    )
    return lines


def build_process_file(tech_lef: Path, corner: str, *, ict: Path | None = None) -> str:
    layers = parse_sky130_tlef(tech_lef)
    if len(layers) != 6:
        raise ValueError(f"expected 6 routing layers, found {len(layers)}")

    substrate_er = DIEL_BELOW_ER
    below_er_map: dict[int, float] = {}
    above_er_map: dict[int, float] = {}
    ict_mode = False
    if ict is not None:
        ict_mode = True
        bottoms = parse_ict_conductor_bottoms(ict)
        for i, layer in enumerate(layers):
            if layer.lef_name in bottoms:
                layers[i].bottom_z = bottoms[layer.lef_name]
        diels = parse_ict_dielectrics(ict)
        substrate_er, below_er_map, above_er_map = derive_ict_dielectric_profile(layers, diels)

    lines = [
        f"# Auto-generated process.{corner} for FasterCap gen_solver_patterns",
        f"# Platform: SkyWater SKY130 ({'HS' if 'sc_hs' in str(tech_lef) else 'HD/HS'})",
        f"# Source TECH_LEF: {tech_lef}",
        f"# Source ICT: {ict if ict is not None else 'N/A (built-in constants)'}",
        "#",
        "# OpenRCX Metal 1..6 = li1, met1..met5",
        "# rcx_patterns.rules LayerCount 6 (use sky130hs rules for HS tlef)",
        "#",
        "# NOTE:",
        "# - default mode: simplified first-pass dielectric stack",
        "# - ict mode: uses ICT conductor heights + non-conformal dielectric eps sampling",
        "",
    ]
    lines.extend(emit_summary(layers))
    lines.extend(emit_conductors(layers, corner))
    lines.extend(
        emit_dielectrics(
            layers,
            substrate_er=substrate_er,
            below_er_map=below_er_map,
            above_er_map=above_er_map,
            ict_mode=ict_mode,
        )
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tech-lef", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--corner", default="TYP")
    parser.add_argument("--all-corners", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=Path("data"))
    parser.add_argument("--ict", type=Path, default=None, help="Optional ICT file for refined stack")
    args = parser.parse_args()

    if args.all_corners:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        for corner in ("TYP", "MIN"):
            content = build_process_file(args.tech_lef, corner, ict=args.ict)
            out_path = args.out_dir / f"process.{corner}"
            out_path.write_text(content)
            print(f"Wrote {out_path} ({len(content.splitlines())} lines)")
        return

    if args.out is None:
        parser.error("--out is required unless --all-corners is set")
    content = build_process_file(args.tech_lef, args.corner, ict=args.ict)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(content)
    print(f"Wrote {args.out} ({len(content.splitlines())} lines)")


if __name__ == "__main__":
    main()
