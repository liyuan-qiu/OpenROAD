#!/usr/bin/env python3
"""
Plot RCX model vs rules tables for shared pattern keys.

Supported families:
  - OVER <over> UNDER <under>
  - DIAGUNDER <under>
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt

METAL_RE = re.compile(r"^Metal\s+(\d+)\s+([A-Z0-9_]+)(?:\s+(.*))?$")
DIST_RE = re.compile(r"^DIST\s+count\s+\d+\s+width\s+([0-9eE+\-.]+)$")
# Matches either:
#   "OVER 1 UNDER 5"  (full form)
#   "1 UNDER 5"       (suffix after family token "OVER")
OVER_UNDER_RE = re.compile(r"^(?:OVER\s+)?(\d+)\s+UNDER\s+(\d+)$")
OVER_ONLY_RE = re.compile(r"^(\d+)$")
UNDER_ONLY_RE = re.compile(r"^(?:UNDER\s+)?(\d+)$")
DIAGUNDER_RE = re.compile(r"^DIAGUNDER\s+(\d+)$")


def width_tag(width: float) -> str:
    return str(width).replace(".", "p")


FAMILY_SUBDIR = {
    "OVER": "Over",
    "UNDER": "Under",
    "OVER_UNDER": "OverUnder",
    "DIAGUNDER": "DIAGUNDER",
}


def category_subdir(family: str) -> str:
    return FAMILY_SUBDIR.get(family, "Other")


def plot_out_path(out_dir: Path, family: str, filename: str) -> Path:
    path = out_dir / category_subdir(family) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def classify_plot_filename(filename: str) -> str:
    """Classify flat plot filename into Over / Under / OverUnder / DIAGUNDER."""
    if "DIAGUNDER" in filename:
        return "DIAGUNDER"
    if re.search(r"_OVER\d+_UNDER\d+", filename):
        return "OverUnder"
    if re.search(r"_OVER\d+", filename):
        return "Over"
    if re.search(r"_UNDER\d+", filename):
        return "Under"
    return "Other"


def parse_tables(
    path: Path,
    *,
    diagunder_columns: str = "model",
) -> dict[tuple, list[tuple[float, float, float]]]:
    """Parse RCX model or rules tables.

    For non-DIAGUNDER families each DIST row is: dist CC CG [res].

    DIAGUNDER has two on-disk layouts:
      - rules:  dist dist2 CC CG   (dist2 often 0; CC/CG are cols 3-4)
      - model:  dist CC CG res     (OpenRCX writeRC: coupling, fringe, res)
    """
    if diagunder_columns not in {"rules", "model"}:
        raise ValueError(f"diagunder_columns must be 'rules' or 'model', got {diagunder_columns!r}")

    lines = path.read_text(errors="ignore").splitlines()
    data: dict[tuple, list[tuple[float, float, float]]] = {}

    header: tuple | None = None
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
            header = None
            width = None
            in_dist = False

            if family.startswith("OVER") and not family.startswith("OVERUNDER"):
                mm = OVER_UNDER_RE.match(suffix)
                if mm:
                    over = int(mm.group(1))
                    under = int(mm.group(2))
                    header = (metal, "OVER_UNDER", over, under)
                else:
                    mm = OVER_ONLY_RE.match(suffix)
                    if mm:
                        over = int(mm.group(1))
                        header = (metal, "OVER", over)
            elif family.startswith("UNDER") and not family.startswith("DIAGUNDER"):
                mm = UNDER_ONLY_RE.match(suffix)
                if mm:
                    under = int(mm.group(1))
                    header = (metal, "UNDER", under)
            elif family.startswith("DIAGUNDER"):
                mm = DIAGUNDER_RE.match(f"{family} {suffix}".strip())
                if mm:
                    under = int(mm.group(1))
                    header = (metal, "DIAGUNDER", under)
            continue

        m = DIST_RE.match(s)
        if m and header is not None:
            width = float(m.group(1))
            in_dist = True
            continue

        if s == "END DIST":
            in_dist = False
            continue

        if in_dist and header is not None and width is not None:
            toks = s.split()
            try:
                dist = float(toks[0])
                if header[1] == "DIAGUNDER":
                    if diagunder_columns == "rules":
                        if len(toks) < 4:
                            continue
                        cc = float(toks[2])
                        cg = float(toks[3])
                    else:
                        if len(toks) < 3:
                            continue
                        cc = float(toks[1])
                        cg = float(toks[2])
                else:
                    if len(toks) < 3:
                        continue
                    cc = float(toks[1])
                    cg = float(toks[2])
            except ValueError:
                continue
            key = (*header, width)
            data.setdefault(key, []).append((dist, cc, cg))

    for k in data:
        data[k].sort(key=lambda x: x[0])
    return data


def title_of_key(key: tuple) -> str:
    metal = key[0]
    family = key[1]
    if family == "OVER_UNDER":
        _, _, over, under, width = key
        return f"Metal {metal} OVER {over} UNDER {under} | width={width:g}"
    if family == "OVER":
        _, _, over, width = key
        return f"Metal {metal} OVER {over} | width={width:g}"
    if family == "UNDER":
        _, _, under, width = key
        return f"Metal {metal} UNDER {under} | width={width:g}"
    _, _, under, width = key
    return f"Metal {metal} DIAGUNDER {under} | width={width:g}"


def filename_of_key(key: tuple) -> str:
    metal = key[0]
    family = key[1]
    if family == "OVER_UNDER":
        _, _, over, under, width = key
        return f"M{metal}_OVER{over}_UNDER{under}_W{width_tag(width)}.png"
    if family == "OVER":
        _, _, over, width = key
        return f"M{metal}_OVER{over}_W{width_tag(width)}.png"
    if family == "UNDER":
        _, _, under, width = key
        return f"M{metal}_UNDER{under}_W{width_tag(width)}.png"
    _, _, under, width = key
    return f"M{metal}_DIAGUNDER{under}_W{width_tag(width)}.png"


def title_of_header(header: tuple) -> str:
    metal = header[0]
    family = header[1]
    if family == "OVER_UNDER":
        _, _, over, under = header
        return f"Metal {metal} OVER {over} UNDER {under}"
    if family == "OVER":
        _, _, over = header
        return f"Metal {metal} OVER {over}"
    if family == "UNDER":
        _, _, under = header
        return f"Metal {metal} UNDER {under}"
    _, _, under = header
    return f"Metal {metal} DIAGUNDER {under}"


def filename_of_header(header: tuple) -> str:
    metal = header[0]
    family = header[1]
    if family == "OVER_UNDER":
        _, _, over, under = header
        return f"M{metal}_OVER{over}_UNDER{under}_multiwidth.png"
    if family == "OVER":
        _, _, over = header
        return f"M{metal}_OVER{over}_multiwidth.png"
    if family == "UNDER":
        _, _, under = header
        return f"M{metal}_UNDER{under}_multiwidth.png"
    _, _, under = header
    return f"M{metal}_DIAGUNDER{under}_multiwidth.png"


def plot_strict(
    model: dict, rules: dict, out_dir: Path, model_label: str
) -> tuple[int, dict[str, int], int]:
    shared = sorted(set(model).intersection(set(rules)))
    generated = 0
    by_family = {"OVER_UNDER": 0, "OVER": 0, "UNDER": 0, "DIAGUNDER": 0}

    for key in shared:
        mpts = model.get(key, [])
        rpts = rules.get(key, [])
        if not mpts or not rpts:
            continue

        md = [x[0] for x in mpts]
        mcc = [x[1] for x in mpts]
        mcg = [x[2] for x in mpts]
        rd = [x[0] for x in rpts]
        rcc = [x[1] for x in rpts]
        rcg = [x[2] for x in rpts]

        fig, axs = plt.subplots(1, 2, figsize=(12, 5), dpi=130)
        fig.suptitle(title_of_key(key))

        axs[0].plot(rd, rcc, "o-", label="rcx_patterns.rules")
        axs[0].plot(md, mcc, "s-", label=model_label)
        axs[0].set_title("Dist vs CC")
        axs[0].set_xlabel("Dist")
        axs[0].set_ylabel("CC")
        axs[0].grid(True, alpha=0.3)
        axs[0].legend()

        axs[1].plot(rd, rcg, "o-", label="rcx_patterns.rules")
        axs[1].plot(md, mcg, "s-", label=model_label)
        axs[1].set_title("Dist vs CG")
        axs[1].set_xlabel("Dist")
        axs[1].set_ylabel("CG")
        axs[1].grid(True, alpha=0.3)
        axs[1].legend()

        out_png = plot_out_path(out_dir, key[1], filename_of_key(key))
        fig.tight_layout(rect=[0, 0, 1, 0.95])
        fig.savefig(out_png)
        plt.close(fig)
        generated += 1
        by_family[key[1]] = by_family.get(key[1], 0) + 1

    return len(shared), by_family, generated


def plot_multiwidth(
    model: dict,
    rules: dict,
    out_dir: Path,
    min_model_widths: int,
    model_label: str,
) -> tuple[int, dict[str, int], int]:
    # Group by header=(metal,family,over/under...)
    model_by_header: dict[tuple, dict[float, list[tuple[float, float, float]]]] = {}
    rules_by_header: dict[tuple, dict[float, list[tuple[float, float, float]]]] = {}

    for key, pts in model.items():
        header = key[:-1]
        width = key[-1]
        model_by_header.setdefault(header, {})[width] = pts
    for key, pts in rules.items():
        header = key[:-1]
        width = key[-1]
        rules_by_header.setdefault(header, {})[width] = pts

    shared_headers = sorted(set(model_by_header).intersection(set(rules_by_header)))
    generated = 0
    by_family = {"OVER_UNDER": 0, "OVER": 0, "UNDER": 0, "DIAGUNDER": 0}

    for hdr in shared_headers:
        mwidths = sorted(
            [w for w, pts in model_by_header[hdr].items() if len(pts) > 0]
        )
        rwidths = sorted(
            [w for w, pts in rules_by_header[hdr].items() if len(pts) > 0]
        )
        if len(mwidths) < min_model_widths or not rwidths:
            continue

        # rules baseline width: prefer overlap width, otherwise smallest rules width.
        overlap = sorted(set(mwidths).intersection(set(rwidths)))
        rules_w = overlap[0] if overlap else rwidths[0]
        rpts = rules_by_header[hdr][rules_w]
        rd = [x[0] for x in rpts]
        rcc = [x[1] for x in rpts]
        rcg = [x[2] for x in rpts]

        fig, axs = plt.subplots(1, 2, figsize=(12, 5), dpi=130)
        fig.suptitle(
            f"{title_of_header(hdr)} | model widths={len(mwidths)}, rules baseline width={rules_w:g}"
        )

        axs[0].plot(rd, rcc, "o-", linewidth=2.0, label=f"rules w={rules_w:g}")
        axs[1].plot(rd, rcg, "o-", linewidth=2.0, label=f"rules w={rules_w:g}")

        for w in mwidths:
            pts = model_by_header[hdr][w]
            md = [x[0] for x in pts]
            mcc = [x[1] for x in pts]
            mcg = [x[2] for x in pts]
            axs[0].plot(md, mcc, "s-", alpha=0.8, label=f"{model_label} w={w:g}")
            axs[1].plot(md, mcg, "s-", alpha=0.8, label=f"{model_label} w={w:g}")

        axs[0].set_title("Dist vs CC")
        axs[0].set_xlabel("Dist")
        axs[0].set_ylabel("CC")
        axs[0].grid(True, alpha=0.3)
        axs[0].legend(fontsize=8)

        axs[1].set_title("Dist vs CG")
        axs[1].set_xlabel("Dist")
        axs[1].set_ylabel("CG")
        axs[1].grid(True, alpha=0.3)
        axs[1].legend(fontsize=8)

        out_png = plot_out_path(out_dir, hdr[1], filename_of_header(hdr))
        fig.tight_layout(rect=[0, 0, 1, 0.94])
        fig.savefig(out_png)
        plt.close(fig)

        generated += 1
        by_family[hdr[1]] = by_family.get(hdr[1], 0) + 1

    return len(shared_headers), by_family, generated


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot 130.rcx.model vs rcx_patterns.rules.")
    ap.add_argument("--model", required=True, help="Path to 130.rcx.model")
    ap.add_argument("--rules", required=True, help="Path to rcx_patterns.rules")
    ap.add_argument("--out-dir", required=True, help="Output plot directory")
    ap.add_argument(
        "--mode",
        choices=["strict", "multiwidth"],
        default="strict",
        help="strict: exact (pattern,width) match; multiwidth: same pattern with model multi-width overlay",
    )
    ap.add_argument(
        "--model-label",
        default="130.rcx.model",
        help="Legend label for the model curve",
    )
    ap.add_argument(
        "--min-model-widths",
        type=int,
        default=2,
        help="Only for --mode multiwidth: minimum model widths required per pattern",
    )
    args = ap.parse_args()

    model_path = Path(args.model)
    rules_path = Path(args.rules)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    model = parse_tables(model_path, diagunder_columns="model")
    rules = parse_tables(rules_path, diagunder_columns="rules")
    if args.mode == "strict":
        shared_cnt, by_family, generated = plot_strict(
            model, rules, out_dir, args.model_label
        )
    else:
        shared_cnt, by_family, generated = plot_multiwidth(
            model, rules, out_dir, args.min_model_widths, args.model_label
        )

    print(f"mode={args.mode}")
    print(f"shared_keys={shared_cnt}")
    print(f"plots_generated={generated}")
    print(f"over_under_plots={by_family.get('OVER_UNDER', 0)}")
    print(f"over_plots={by_family.get('OVER', 0)}")
    print(f"under_plots={by_family.get('UNDER', 0)}")
    print(f"diagunder_plots={by_family.get('DIAGUNDER', 0)}")
    print(f"out_dir={out_dir}")


if __name__ == "__main__":
    main()
