#!/usr/bin/env python3
"""
Generate OpenRCX FasterCap process.TYP for SkyWater SKY130 (6 routing layers).

Default TECH LEF: **sky130hs** (`sky130_fd_sc_hs.tlef`) — aligns with `rcx_patterns.rules`.

OpenRCX / rcx_patterns.rules numbering:
  M1 = li1, M2 = met1, ..., M6 = met5

TECH LEF supplies WIDTH / SPACING / THICKNESS / RPERSQ in default mode.
Vertical stack / dielectric can be sourced either from:
  - built-in first-pass constants (default), or
  - external ICT file (`--ict`) for conductor bottom-Z / thickness and a
    flattened vertical dielectric profile.

The OpenRCX process format used by this flow writes dielectrics as a cumulative
one-dimensional stack.  ICT conformal sidewall geometry therefore cannot be
represented exactly.  Conformal layers are not promoted to full-plane slabs;
their uncovered vertical intervals inherit the nearest lower non-conformal
bulk dielectric epsilon.

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

# Bottom Z (µm) per routing layer from the SKY130 ICT absolute stack.
# Keep the no-ICT fallback on the same geometry datum as ICT mode; only the
# dielectric approximation and TECH LEF conductor thicknesses differ.
SKY130_BOTTOM_Z: dict[str, float] = {
    "li1": 0.9361,
    "met1": 1.3761,
    "met2": 2.0061,
    "met3": 2.7861,
    "met4": 4.0211,
    "met5": 5.3711,
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
TOP_DIELECTRIC_MARGIN = 1.0  # µm above the highest conductor


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
    conformal: bool

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


def parse_ict_conductors(ict_path: Path) -> dict[str, tuple[float, float]]:
    text = ict_path.read_text(errors="ignore")
    out: dict[str, tuple[float, float]] = {}
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
        t = _first_float(body, r"thickness\s+([\d.]+)", flags=re.IGNORECASE)
        if h is not None and t is not None and t > 0:
            out[lef_name] = (h, t)
    return out


def parse_ict_conductor_bottoms(ict_path: Path) -> dict[str, float]:
    """Compatibility helper for callers that only need conductor bottom-Z."""
    return {name: values[0] for name, values in parse_ict_conductors(ict_path).items()}


def parse_ict_dielectrics(ict_path: Path) -> list[IctDielectric]:
    text = ict_path.read_text(errors="ignore")
    out: list[IctDielectric] = []
    for m in re.finditer(r"dielectric\s+([A-Za-z0-9_]+)\s*\{(.*?)\}", text, re.DOTALL | re.IGNORECASE):
        name = m.group(1)
        body = m.group(2)
        conformal_m = re.search(r"conformal\s+(TRUE|FALSE)", body, re.IGNORECASE)
        conformal = bool(conformal_m and conformal_m.group(1).upper() == "TRUE")
        h = _first_float(body, r"height\s+([\d.]+)", flags=re.IGNORECASE)
        t = _first_float(body, r"thickness\s+([\d.]+)", flags=re.IGNORECASE)
        er = _first_float(body, r"dielectric_constant\s+([\d.]+)", flags=re.IGNORECASE)
        if h is None or t is None or er is None:
            continue
        out.append(
            IctDielectric(
                name=name,
                height=h,
                thickness=t,
                epsilon=er,
                conformal=conformal,
            )
        )
    out.sort(key=lambda d: (d.height, d.conformal, d.name))
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


def build_ict_vertical_slabs(
    layers: list[RoutingLayer],
    diels: list[IctDielectric],
    *,
    top_margin: float = TOP_DIELECTRIC_MARGIN,
) -> tuple[list[IctDielectric], list[str]]:
    """Flatten an ICT stack into contiguous OpenRCX vertical slabs.

    Non-conformal ICT layers are already vertical slabs.  Conformal ICT layers
    describe local side/top expansion around selected conductors and cannot be
    represented by this one-dimensional process stack.  Exclude all conformal
    entries; any resulting vertical interval inherits the nearest lower
    non-conformal bulk dielectric epsilon instead of extending a local high-k
    film across the entire simulation window.

    The downstream UniversalFormat converter uses the slab immediately before
    and after a conductor surface.  Split otherwise-uniform ICT dielectrics at
    every conductor bottom/top so those neighbor lookups are both valid and
    retain the correct epsilon.
    """
    if not diels:
        raise ValueError("ICT contains no dielectric definitions")

    stack_top = max(layer.top_z for layer in layers) + top_margin
    positive = [
        d
        for d in diels
        if not d.conformal and d.thickness > 0 and d.height < stack_top
    ]
    positive.sort(key=lambda d: (d.height, d.conformal, d.name))

    slabs: list[IctDielectric] = []
    skipped = [d.name for d in diels if d.conformal]
    cursor = 0.0
    previous_epsilon = DIEL_BELOW_ER

    for dielectric in positive:
        lo = dielectric.height
        hi = min(dielectric.top, stack_top)
        if hi <= cursor:
            continue
        if lo > cursor + 1e-9:
            slabs.append(
                IctDielectric(
                    name=f"gap_before_{dielectric.name}",
                    height=cursor,
                    thickness=lo - cursor,
                    epsilon=previous_epsilon,
                    conformal=False,
                )
            )
            cursor = lo
        lo = max(lo, cursor)
        if hi <= lo:
            continue
        slabs.append(
            IctDielectric(
                name=dielectric.name,
                height=lo,
                thickness=hi - lo,
                epsilon=dielectric.epsilon,
                conformal=dielectric.conformal,
            )
        )
        cursor = hi
        previous_epsilon = dielectric.epsilon
        if cursor >= stack_top - 1e-9:
            break

    if cursor < stack_top - 1e-9:
        slabs.append(
            IctDielectric(
                name="top_extension",
                height=cursor,
                thickness=stack_top - cursor,
                epsilon=previous_epsilon,
                conformal=False,
            )
        )

    conductor_edges = sorted(
        {
            round(edge, 10)
            for layer in layers
            for edge in (layer.bottom_z, layer.top_z)
            if 0.0 < edge < stack_top
        }
    )
    split_slabs: list[IctDielectric] = []
    for slab in slabs:
        points = [slab.height]
        points.extend(
            edge
            for edge in conductor_edges
            if slab.height + 1e-9 < edge < slab.top - 1e-9
        )
        points.append(slab.top)
        part_count = len(points) - 1
        for part, (lo, hi) in enumerate(zip(points, points[1:]), start=1):
            name = slab.name
            if part_count > 1:
                name = f"{name}_part{part}"
            split_slabs.append(
                IctDielectric(
                    name=name,
                    height=lo,
                    thickness=hi - lo,
                    epsilon=slab.epsilon,
                    conformal=slab.conformal,
                )
            )
    slabs = split_slabs

    total = sum(slab.thickness for slab in slabs)
    if abs(total - stack_top) > 1e-6:
        raise ValueError(
            f"flattened ICT dielectric stack is discontinuous: "
            f"total={total:.6f}, expected={stack_top:.6f}"
        )
    return slabs, skipped


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
) -> list[str]:
    below_er_map = below_er_map or {}
    above_er_map = above_er_map or {}
    lines = [
        "# DIELECTRIC section",
        "# - default: simplified continuous vertical stack",
        "# - split at every conductor bottom/top surface",
        f"# - dielectric top={max(layer.top_z for layer in layers) + TOP_DIELECTRIC_MARGIN:.4f}",
        f"# - highest conductor top={max(layer.top_z for layer in layers):.4f}",
        "",
    ]

    def append_slab(name: str, epsilon: float, thickness: float) -> None:
        if thickness <= 0:
            return
        lines.extend(
            [
                f"DIELECTRIC {name} {{",
                f"        epsilon {epsilon:.3f}",
                f"        thickness {thickness:.4f}",
                "}",
                "",
            ]
        )

    append_slab("substrate_1", substrate_er, layers[0].bottom_z)
    for idx, layer in enumerate(layers):
        metal = layer.rcx_index
        body_er = (
            below_er_map.get(metal, DIEL_BELOW_ER)
            if idx == 0
            else above_er_map.get(metal, DIEL_ABOVE_ER)
        )
        append_slab(f"m{metal}_body", body_er, layer.thickness)

        if idx + 1 == len(layers):
            append_slab(
                f"m{metal}_top_cap",
                above_er_map.get(metal, DIEL_ABOVE_ER),
                TOP_DIELECTRIC_MARGIN,
            )
            continue

        next_layer = layers[idx + 1]
        gap = next_layer.bottom_z - layer.top_z
        if idx == 0:
            lower_th = gap * 0.5
            lower_er = LINT_ER
        else:
            lower_th = gap * 0.15
            lower_er = below_er_map.get(next_layer.rcx_index, DIEL_BELOW_ER)
        upper_th = gap - lower_th
        upper_er = above_er_map.get(next_layer.rcx_index, DIEL_ABOVE_ER)
        append_slab(f"m{metal}_to_m{next_layer.rcx_index}_lower", lower_er, lower_th)
        append_slab(f"m{metal}_to_m{next_layer.rcx_index}_upper", upper_er, upper_th)

    return lines


def emit_ict_dielectrics(
    layers: list[RoutingLayer],
    diels: list[IctDielectric],
) -> list[str]:
    slabs, skipped = build_ict_vertical_slabs(layers, diels)
    stack_top = sum(slab.thickness for slab in slabs)
    metal_top = max(layer.top_z for layer in layers)
    lines = [
        "# DIELECTRIC section",
        "# - ict mode: flattened cumulative vertical stack, split at conductor",
        "#   bottom/top surfaces for UniversalFormat converter compatibility",
        f"# - dielectric top={stack_top:.4f}; highest conductor top={metal_top:.4f}",
    ]
    if skipped:
        lines.append(
            "# - conformal ICT entries omitted from full-plane stack: "
            f"{', '.join(skipped)}"
        )
    lines.append("")
    for index, slab in enumerate(slabs, start=1):
        safe_name = re.sub(r"[^A-Za-z0-9_]", "_", slab.name)
        lines.extend(
            [
                f"DIELECTRIC ict_{index}_{safe_name} {{",
                f"        epsilon {slab.epsilon:.3f}",
                f"        thickness {slab.thickness:.4f}",
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
    diels: list[IctDielectric] = []
    ict_mode = False
    if ict is not None:
        ict_mode = True
        conductors = parse_ict_conductors(ict)
        for i, layer in enumerate(layers):
            if layer.lef_name in conductors:
                bottom_z, thickness = conductors[layer.lef_name]
                layers[i].bottom_z = bottom_z
                layers[i].thickness = thickness
        diels = parse_ict_dielectrics(ict)

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
        "# - ict mode: uses ICT conductor heights/thicknesses and a flattened",
        "#   cumulative ICT dielectric stack",
        "",
    ]
    lines.extend(emit_summary(layers))
    lines.extend(emit_conductors(layers, corner))
    if ict_mode:
        lines.extend(emit_ict_dielectrics(layers, diels))
    else:
        lines.extend(
            emit_dielectrics(
                layers,
                substrate_er=substrate_er,
                below_er_map=below_er_map,
                above_er_map=above_er_map,
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
