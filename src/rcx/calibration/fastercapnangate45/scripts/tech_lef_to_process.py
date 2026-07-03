#!/usr/bin/env python3
"""
Generate OpenRCX FasterCap process.TYP from NanGate45 TECH_LEF + ITF.

TECH_LEF supplies routing geometry (WIDTH/SPACING/THICKNESS/HEIGHT/RPERSQ).
ITF supplies dielectric stack (ER + thickness between metals).

Usage:
  python3 tech_lef_to_process.py \
    --tech-lef flow/platforms/nangate45/lef/NangateOpenCellLibrary.tech.lef \
    --itf flow/PDK/NanGate45-Synopsys-Enablement-main/NanGate45/tlup/NangateOpenCellLibrary.itf \
    --out data/process.TYP.nangate45_10m \
    --corner TYP
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RoutingLayer:
    name: str
    width: float
    spacing: float
    thickness: float
    height: float
    rpersq: float

    @property
    def index(self) -> int:
        return int(self.name.replace("metal", ""))

    @property
    def resistivity(self) -> float:
        return self.rpersq * self.thickness


@dataclass
class DielectricLayer:
    name: str
    thickness: float
    epsilon: float


@dataclass
class ConductorLayer:
    name: str
    thickness: float
    wmin: float
    smin: float
    rpsq: float


def parse_tech_lef(path: Path) -> list[RoutingLayer]:
    text = path.read_text()
    layers: list[RoutingLayer] = []
    for block in re.finditer(
        r"LAYER\s+(metal\d+)\s+TYPE\s+ROUTING\s*;(.*?)\s*END\s+\1",
        text,
        re.DOTALL,
    ):
        name = block.group(1)
        body = block.group(2)
        width = _routing_width(body)
        spacing = _routing_spacing(body, width)
        thickness = _require_float(body, r"THICKNESS\s+([\d.]+)", name, "THICKNESS")
        height = _require_float(body, r"HEIGHT\s+([\d.]+)", name, "HEIGHT")
        rpersq = _require_float(body, r"RESISTANCE\s+RPERSQ\s+([\d.]+)", name, "RPERSQ")
        layers.append(
            RoutingLayer(
                name=name,
                width=width,
                spacing=spacing,
                thickness=thickness,
                height=height,
                rpersq=rpersq,
            )
        )
    layers.sort(key=lambda layer: layer.index)
    return layers


def parse_itf(path: Path) -> tuple[list[DielectricLayer], list[ConductorLayer]]:
    dielectrics: list[DielectricLayer] = []
    conductors: list[ConductorLayer] = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("$"):
            continue
        diel = re.match(
            r"DIELECTRIC\s+(\S+)\s*\{\s*THICKNESS=([\d.]+)\s+ER=([\d.]+)\s*\}",
            line,
        )
        if diel:
            dielectrics.append(
                DielectricLayer(diel.group(1), float(diel.group(2)), float(diel.group(3)))
            )
            continue
        cond = re.match(
            r"CONDUCTOR\s+(\S+)\s*\{\s*THICKNESS=([\d.]+)\s+WMIN=([\d.]+)\s+SMIN=([\d.]+)\s+RPSQ=([\d.]+)\s*\}",
            line,
        )
        if cond:
            conductors.append(
                ConductorLayer(
                    cond.group(1),
                    float(cond.group(2)),
                    float(cond.group(3)),
                    float(cond.group(4)),
                    float(cond.group(5)),
                )
            )
    return dielectrics, conductors


def _first_float(text: str, pattern: str, flags: int = 0) -> float | None:
    match = re.search(pattern, text, flags)
    return float(match.group(1)) if match else None


def _require_float(text: str, pattern: str, layer: str, field: str) -> float:
    value = _first_float(text, pattern)
    if value is None:
        raise ValueError(f"{layer}: missing {field}")
    return value


def _strip_spacing_table(body: str) -> str:
    return re.sub(r"SPACINGTABLE.*?;", "", body, flags=re.DOTALL)


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
    return _pitch_minus_width(stripped, width)


def _pitch_minus_width(body: str, width: float | None) -> float:
    pitch = _first_float(body, r"PITCH\s+([\d.]+)")
    if pitch is not None and width is not None:
        return max(pitch - width, width or 0.0)
    raise ValueError("cannot infer spacing")


def conductor_distance(layers: list[RoutingLayer], index: int) -> float:
    layer = layers[index]
    if index == 0:
        return layer.height
    prev = layers[index - 1]
    return layer.height - (prev.height + prev.thickness)


def metal_dielectrics_from_itf(
    dielectrics: list[DielectricLayer],
) -> dict[int, tuple[DielectricLayer | None, DielectricLayer | None]]:
    by_metal: dict[int, tuple[DielectricLayer | None, DielectricLayer | None]] = {}
    for diel in dielectrics:
        match = re.fullmatch(r"metal(\d+)_diel2?", diel.name)
        if not match:
            continue
        metal = int(match.group(1))
        below, above = by_metal.get(metal, (None, None))
        if diel.name.endswith("_diel2"):
            above = diel
        else:
            below = diel
        by_metal[metal] = (below, above)
    return by_metal


def emit_conductors(layers: list[RoutingLayer], corner: str) -> list[str]:
    lines = [
        "# CONDUCTOR section generated from TECH_LEF routing layers (metal1-metal10)",
        "# distance = gap from previous metal top to current metal bottom (HEIGHT-based)",
        "# resistivity = RPERSQ * THICKNESS (TYP: all metals; MIN: M6-M10 only, per legacy 7m flow)",
        "",
    ]
    for idx, layer in enumerate(layers):
        dist = conductor_distance(layers, idx)
        lines.append(f"CONDUCTOR M{layer.index} {{")
        lines.append(f"        distance {dist:.4f}")
        lines.append(f"        thickness {layer.thickness:.4f}")
        lines.append(f"        min_width {layer.width:.4f}")
        lines.append(f"        min_spacing {layer.spacing:.4f}")
        if _emit_resistivity(corner, layer.index):
            lines.append(f"        resistivity {layer.resistivity:.6f}")
        lines.append("}")
    lines.append("")
    return lines


def _emit_resistivity(corner: str, metal_index: int) -> bool:
    if corner.upper() == "MIN":
        return metal_index >= 6
    return True


def emit_dielectrics(
    layers: list[RoutingLayer],
    diel_map: dict[int, tuple[DielectricLayer | None, DielectricLayer | None]],
    include_substrate: bool,
    substrate: DielectricLayer | None,
) -> list[str]:
    lines = [
        "# DIELECTRIC section generated from ITF (2 slabs per metal: below/above)",
        "# next_met N = below metal N; met N = above metal N",
        "",
    ]
    if include_substrate and substrate is not None:
        lines.extend(
            [
                "DIELECTRIC substrate_1 {",
                f"        epsilon {substrate.epsilon:.1f}",
                f"        thickness {substrate.thickness:.4f}",
                "        next_met 1",
                "}",
                "",
            ]
        )

    for layer in layers:
        metal = layer.index
        below, above = diel_map.get(metal, (None, None))
        if below is not None:
            lines.extend(
                [
                    f"DIELECTRIC m{metal}_below {{",
                    f"        epsilon {below.epsilon:.1f}",
                    f"        thickness {below.thickness:.4f}",
                    f"        next_met {metal}",
                    "}",
                    "",
                ]
            )
        if above is not None:
            lines.extend(
                [
                    f"DIELECTRIC m{metal}_above {{",
                    f"        epsilon {above.epsilon:.1f}",
                    f"        thickness {above.thickness:.4f}",
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


def emit_summary(layers: list[RoutingLayer]) -> list[str]:
    lines = ["# --- LEF-derived summary ---"]
    for idx, layer in enumerate(layers):
        dist = conductor_distance(layers, idx)
        top = layer.height + layer.thickness
        lines.append(
            f"# M{layer.index}: dist={dist:.4f} t={layer.thickness:.4f} "
            f"w={layer.width:.4f} s={layer.spacing:.4f} "
            f"z=[{layer.height:.4f},{top:.4f}] rho={layer.resistivity:.6f}"
        )
    lines.append("")
    return lines


def build_process_file(
    tech_lef: Path,
    itf: Path | None,
    corner: str,
    include_substrate: bool,
) -> str:
    layers = parse_tech_lef(tech_lef)
    if len(layers) != 10:
        raise ValueError(f"expected 10 routing metals, found {len(layers)}")

    lines = [
        f"# Auto-generated process.{corner} for FasterCap gen_solver_patterns",
        f"# Source TECH_LEF: {tech_lef}",
        f"# Source ITF: {itf if itf else 'N/A'}",
        "#",
        "# NOTE:",
        "# - TECH_LEF cannot describe full 3D dielectric segmentation alone.",
        "# - ITF gives a simpler 2-slab-per-metal stack (good first pass).",
        "# - Existing data/process.TYP uses 7 abstract metals (M6M/M7M) with",
        "#   hand-tuned multi-segment dielectrics; replace only after validation.",
        "",
    ]
    lines.extend(emit_summary(layers))
    lines.extend(emit_conductors(layers, corner))

    if itf is not None:
        dielectrics, _ = parse_itf(itf)
        diel_map = metal_dielectrics_from_itf(dielectrics)
        substrate = next((d for d in dielectrics if d.name == "field_base_diel"), None)
        lines.extend(emit_dielectrics(layers, diel_map, include_substrate, substrate))

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tech-lef", type=Path, required=True)
    parser.add_argument("--itf", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--corner", default="TYP")
    parser.add_argument(
        "--include-substrate",
        action="store_true",
        default=True,
        help="include field_base_diel below M1 (required for UniversalFormat2FasterCap index alignment)",
    )
    parser.add_argument(
        "--no-substrate",
        action="store_true",
        help="omit substrate slab (breaks FasterCap converter unless processDielectrics[0] is reserved)",
    )
    parser.add_argument(
        "--all-corners",
        action="store_true",
        help="write process.TYP and process.MIN into --out-dir",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="output directory when --all-corners is set",
    )
    args = parser.parse_args()

    if args.no_substrate:
        include_substrate = False
    else:
        include_substrate = args.include_substrate

    if args.all_corners:
        out_dir = args.out_dir or Path("data")
        out_dir.mkdir(parents=True, exist_ok=True)
        for corner in ("TYP", "MIN"):
            content = build_process_file(
                args.tech_lef,
                args.itf,
                corner,
                include_substrate,
            )
            out_path = out_dir / f"process.{corner}"
            out_path.write_text(content)
            print(f"Wrote {out_path} ({len(content.splitlines())} lines)")
        return

    if args.out is None:
        parser.error("--out is required unless --all-corners is set")

    content = build_process_file(
        args.tech_lef,
        args.itf,
        args.corner,
        include_substrate,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(content)
    print(f"Wrote {args.out} ({len(content.splitlines())} lines)")


if __name__ == "__main__":
    main()
