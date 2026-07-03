#!/usr/bin/env python3
"""
Compare NanGate45 DIAGUNDER: FasterCap |C32|+|C34| vs rules col[3].

NanGate45 legacy rules (degenerate 4-column)::

    dist  dist2  col2  col3
    0.065  0     0     0.00271429

**rules CC** = col[3] (0-based).

**FasterCap CC** for UnderDiag5 victim wire (default wire 3):
  CC = |C32| + |C34|  (same as ``fasterCapParse.py`` ``caps[2]`` field)
  normalized per OpenRCX tables:
    CC_norm = CC_fF / (LEN * 1000 * width_um) / 2

Only UnderDiag cases with diag spacing s2=0 (``..._S0_L10``) are kept by
default — matches ``DIAGMODEL ON`` 1D rules axis (victim dist only).

Example::

    python3 plot_nangate45_diagunder_col3_cc.py \\
      --caps 10v2_typ_wirefix_parse_sym50/10v2_typ_wirefix.caps \\
      --rules ../../../../../../flow/platforms/nangate45/rcx_patterns.rules \\
      --out-dir model/plots_diagunder_col3_cc_wirefix
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

METAL_RE = re.compile(r"^Metal\s+(\d+)\s+([A-Z0-9_]+)(?:\s+(.*))?$")
DIST_RE = re.compile(r"^DIST\s+count\s+\d+\s+width\s+([0-9eE+\-.]+)$")
DIAGUNDER_RE = re.compile(r"^DIAGUNDER\s+(\d+)$")
CAPS_DIAG_RE = re.compile(
    r"^Metal\s+(?P<met>\d+)\s+Over\s+\d+\s+DiagUnder\s+(?P<under>\d+)\s+"
    r"Dist\s+(?P<dist>[0-9.]+)\s+Width\s+(?P<width>[0-9.]+)\s+"
    r"LEN\s+(?P<len>\d+)\s+CC\s+(?P<cc>[0-9.eE+-]+)\s+"
    r"FR\s+[0-9.eE+-]+\s+TC\s+[0-9.eE+-]+\s+CC2\s+[0-9.eE+-]+\s+"
    r"DiagDist\s+[0-9.]+\s+DiagWidth\s+[0-9.]+\s+DiagCC\s+[0-9.eE+-]+\s+"
    r"(?P<pattern>TYP/UnderDiag5/[^\s]+/wire_(?P<wire>\d+))\s*$"
)
DIAG_S0_RE = re.compile(r"/S[0-9.eE+\-]+_S0_L")

Key = tuple[int, int, float]  # (metal, under, width)
Point = tuple[float, float]  # (dist, cc_norm)


def width_tag(width: float) -> str:
    return str(width).replace(".", "p")


def wlen(len_mult: int, width_um: float) -> float:
    return len_mult * 1000.0 * width_um


def normalize_cc(cap_fF: float, len_mult: int, width_um: float) -> float:
    return cap_fF / wlen(len_mult, width_um) / 2.0


def parse_nangate45_diagunder_rules_col3(path: Path) -> dict[Key, list[Point]]:
    """Parse DIAGUNDER; CC = col[3] (0-based)."""
    lines = path.read_text(errors="ignore").splitlines()
    data: dict[Key, list[Point]] = {}

    metal: int | None = None
    under: int | None = None
    width: float | None = None
    in_dist = False

    for raw in lines:
        s = raw.strip()
        if not s:
            continue

        m = METAL_RE.match(s)
        if m:
            metal = int(m.group(1))
            family = m.group(2)
            suffix = (m.group(3) or "").strip()
            under = None
            width = None
            in_dist = False
            if family == "DIAGUNDER":
                mm = DIAGUNDER_RE.match(f"{family} {suffix}".strip())
                if mm:
                    under = int(mm.group(1))
            continue

        m = DIST_RE.match(s)
        if m and under is not None and metal is not None:
            width = float(m.group(1))
            in_dist = True
            continue

        if s == "END DIST":
            in_dist = False
            continue

        if not in_dist or metal is None or under is None or width is None:
            continue

        toks = s.split()
        if len(toks) < 4:
            continue
        try:
            dist = float(toks[0])
            cc = float(toks[3])
        except ValueError:
            continue
        key: Key = (metal, under, width)
        data.setdefault(key, []).append((dist, cc))

    for pts in data.values():
        pts.sort(key=lambda x: x[0])
    return data


def parse_caps_diagunder_cc(
    path: Path,
    *,
    wire: int = 3,
    diag_s0_only: bool = True,
) -> dict[Key, list[Point]]:
    """Parse .caps UnderDiag5 lines; CC = |C32|+|C34| from fasterCapParse, wire_N."""
    buckets: dict[Key, dict[float, list[float]]] = defaultdict(lambda: defaultdict(list))

    for line in path.read_text(errors="ignore").splitlines():
        m = CAPS_DIAG_RE.match(line.strip())
        if not m:
            continue
        if int(m.group("wire")) != wire:
            continue
        pattern = m.group("pattern")
        if diag_s0_only and not DIAG_S0_RE.search(pattern):
            continue

        met = int(m.group("met"))
        under = int(m.group("under"))
        dist = float(m.group("dist"))
        width = float(m.group("width"))
        len_mult = int(m.group("len"))
        cc_fF = float(m.group("cc"))
        cc_norm = normalize_cc(cc_fF, len_mult, width)

        key: Key = (met, under, width)
        buckets[key][dist].append(cc_norm)

    data: dict[Key, list[Point]] = {}
    for key, by_dist in buckets.items():
        pts = [(d, sum(vals) / len(vals)) for d, vals in sorted(by_dist.items())]
        data[key] = pts
    return data


def title_key(key: Key) -> str:
    metal, under, width = key
    return f"Metal {metal} DIAGUNDER {under} | width={width:g}"


def fname_key(key: Key) -> str:
    metal, under, width = key
    return f"M{metal}_DIAGUNDER{under}_W{width_tag(width)}.png"


def mae_at_shared_dists(rules_pts: list[Point], fc_pts: list[Point]) -> float | None:
    rmap = {d: v for d, v in rules_pts}
    fmap = {d: v for d, v in fc_pts}
    shared = sorted(set(rmap).intersection(fmap))
    if not shared:
        return None
    return sum(abs(rmap[d] - fmap[d]) for d in shared) / len(shared)


def write_summary_csv(
    path: Path,
    shared_keys: list[Key],
    rules: dict[Key, list[Point]],
    fc: dict[Key, list[Point]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "metal",
                "under",
                "width",
                "rules_cc_col3",
                "fc_cc_mean",
                "fc_cc_min",
                "fc_cc_max",
                "mae_rules_vs_fc_cc",
                "n_dist_shared",
            ]
        )
        for key in shared_keys:
            metal, under, width = key
            rpts = rules[key]
            fpts = fc[key]
            rules_cc = rpts[0][1] if rpts else ""
            vals = [v for _, v in fpts]
            fc_mean = sum(vals) / len(vals) if vals else ""
            fc_min = min(vals) if vals else ""
            fc_max = max(vals) if vals else ""
            mae = mae_at_shared_dists(rpts, fpts)
            shared_n = len(set(d for d, _ in rpts).intersection(d for d, _ in fpts))
            w.writerow(
                [
                    metal,
                    under,
                    width,
                    rules_cc,
                    f"{fc_mean:.6g}",
                    f"{fc_min:.6g}",
                    f"{fc_max:.6g}",
                    f"{mae:.6g}" if mae is not None else "",
                    shared_n,
                ]
            )


def plot_keys(
    rules: dict[Key, list[Point]],
    fc: dict[Key, list[Point]],
    out_dir: Path,
    *,
    fc_label: str,
) -> int:
    shared = sorted(set(rules).intersection(fc))
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for key in shared:
        rpts = rules[key]
        fpts = fc[key]
        if not rpts or not fpts:
            continue

        rd = [x[0] for x in rpts]
        rcc = [x[1] for x in rpts]
        fd = [x[0] for x in fpts]
        fcc = [x[1] for x in fpts]

        fig, ax = plt.subplots(figsize=(8, 5), dpi=130)
        fig.suptitle(title_key(key))
        ax.plot(rd, rcc, "o-", color="C0", label="rules CC = col[3]")
        ax.plot(fd, fcc, "s-", color="C1", label=f"{fc_label} |C32|+|C34|")
        ax.set_xlabel("Dist (victim spacing)")
        ax.set_ylabel("Coupling cap (fF/µm)")
        ax.set_title("DIAGUNDER CC: rules col[3] vs FasterCap lateral CC")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8, loc="best")
        fig.tight_layout(rect=[0, 0, 1, 0.94])
        fig.savefig(out_dir / fname_key(key))
        plt.close(fig)
        n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(
        description="NanGate45 DIAGUNDER: rules col[3] vs FasterCap |C32|+|C34|"
    )
    ap.add_argument("--caps", required=True, help="Parsed .caps (sym50 wirefix output)")
    ap.add_argument("--rules", required=True, help="NanGate45 rcx_patterns.rules")
    ap.add_argument("--out-dir", required=True, help="Output directory for PNG plots")
    ap.add_argument("--summary-csv", help="Optional per-key CSV summary")
    ap.add_argument("--wire", type=int, default=3, help="Victim wire index (default 3)")
    ap.add_argument(
        "--all-diag-spacing",
        action="store_true",
        help="Include all diag s2 spacings (default: only *_S0_L* cases)",
    )
    ap.add_argument("--fc-label", default="FasterCap wire_3")
    args = ap.parse_args()

    rules = parse_nangate45_diagunder_rules_col3(Path(args.rules))
    fc = parse_caps_diagunder_cc(
        Path(args.caps),
        wire=args.wire,
        diag_s0_only=not args.all_diag_spacing,
    )
    shared = sorted(set(rules).intersection(fc))

    n = plot_keys(rules, fc, Path(args.out_dir), fc_label=args.fc_label)

    if args.summary_csv:
        write_summary_csv(Path(args.summary_csv), shared, rules, fc)

    print(f"rules_keys={len(rules)}")
    print(f"fc_keys={len(fc)}")
    print(f"shared_keys={len(shared)}")
    print(f"plots={n}")
    print(f"wire={args.wire}")
    print(f"diag_s0_only={not args.all_diag_spacing}")
    print(f"out_dir={args.out_dir}")
    if args.summary_csv:
        print(f"summary_csv={args.summary_csv}")


if __name__ == "__main__":
    main()
