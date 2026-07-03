#!/usr/bin/env python3
"""Plot DIAGUNDER only: rules col3=CC, col4=CG (dist on x-axis)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt

from plot_rcx_model_vs_rules import plot_out_path

METAL_DIAG_HDR = re.compile(r"^Metal\s+(\d+)\s+DIAGUNDER(?:\s+(\d+))?\s*$")
DIST_HDR = re.compile(r"^DIST\s+count\s+\d+\s+width\s+([0-9.eE+-]+)")


def width_tag(width: float) -> str:
    return str(width).replace(".", "p")


def parse_diagunder(path: Path) -> dict[tuple, list[tuple[float, float, float]]]:
    data: dict[tuple, list[tuple[float, float, float]]] = {}
    lines = path.read_text(errors="ignore").splitlines()
    metal = under = None
    width = None
    in_dist = False

    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        hm = METAL_DIAG_HDR.match(s)
        if hm:
            metal = int(hm.group(1))
            under = int(hm.group(2) or 0)
            width = None
            in_dist = False
            continue
        dm = DIST_HDR.match(s)
        if dm and metal is not None:
            width = float(dm.group(1))
            in_dist = True
            continue
        if s == "END DIST":
            in_dist = False
            continue
        if in_dist and metal is not None and width is not None:
            toks = s.split()
            if len(toks) < 4:
                continue
            try:
                dist = float(toks[0])
                cc = float(toks[2])
                cg = float(toks[3])
            except ValueError:
                continue
            key = (metal, under, width)
            data.setdefault(key, []).append((dist, cc, cg))

    for k in data:
        data[k].sort(key=lambda x: x[0])
    return data


def title_key(key: tuple) -> str:
    metal, under, width = key
    return f"Metal {metal} DIAGUNDER {under} | width={width:g}"


def fname_key(key: tuple) -> str:
    metal, under, width = key
    return f"M{metal}_DIAGUNDER{under}_W{width_tag(width)}.png"


def plot(
    model_a: dict,
    model_b: dict | None,
    rules: dict,
    out_dir: Path,
    label_a: str,
    label_b: str | None,
) -> int:
    if model_b is not None:
        shared = sorted(set(model_a).intersection(set(model_b)).intersection(set(rules)))
    else:
        shared = sorted(set(model_a).intersection(set(rules)))

    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for key in shared:
        rpts = rules[key]
        apts = model_a[key]
        if not rpts or not apts:
            continue

        rd = [x[0] for x in rpts]
        rcc = [x[1] for x in rpts]
        rcg = [x[2] for x in rpts]
        ad = [x[0] for x in apts]
        acc = [x[1] for x in apts]
        acg = [x[2] for x in apts]

        fig, axs = plt.subplots(1, 2, figsize=(12, 5), dpi=130)
        fig.suptitle(title_key(key))

        axs[0].plot(rd, rcc, "o-", label="rules")
        axs[0].plot(ad, acc, "s-", label=label_a)
        if model_b and key in model_b:
            bpts = model_b[key]
            axs[0].plot([x[0] for x in bpts], [x[1] for x in bpts], "^-", label=label_b)
        axs[0].set_title("Dist vs CC (col3)")
        axs[0].set_xlabel("Dist")
        axs[0].grid(True, alpha=0.3)
        axs[0].legend(fontsize=8)

        axs[1].plot(rd, rcg, "o-", label="rules")
        axs[1].plot(ad, acg, "s-", label=label_a)
        if model_b and key in model_b:
            bpts = model_b[key]
            axs[1].plot([x[0] for x in bpts], [x[2] for x in bpts], "^-", label=label_b)
        axs[1].set_title("Dist vs CG (col4)")
        axs[1].set_xlabel("Dist")
        axs[1].grid(True, alpha=0.3)
        axs[1].legend(fontsize=8)

        fig.tight_layout(rect=[0, 0, 1, 0.94])
        fig.savefig(plot_out_path(out_dir, "DIAGUNDER", fname_key(key)))
        plt.close(fig)
        n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--model-label", default="model")
    ap.add_argument("--model-b", help="Optional second model (e.g. baseline)")
    ap.add_argument("--label-b", default="baseline")
    args = ap.parse_args()

    ma = parse_diagunder(Path(args.model))
    mr = parse_diagunder(Path(args.rules))
    mb = parse_diagunder(Path(args.model_b)) if args.model_b else None

    n = plot(ma, mb, mr, Path(args.out_dir), args.model_label, args.label_b if mb else None)
    print(f"shared_keys={len(set(ma).intersection(mr))}")
    print(f"plots={n}")
    print(f"out_dir={args.out_dir}")


if __name__ == "__main__":
    main()
