#!/usr/bin/env python3
"""Plot DIAGUNDER only: rules col3=CC, col4=CG (dist on x-axis)."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from plot_rcx_model_vs_rules import parse_tables, plot_out_path


def width_tag(width: float) -> str:
    return str(width).replace(".", "p")


def _diagunder_items(path: Path, *, diagunder_columns: str) -> dict[tuple, list]:
    out: dict[tuple, list] = {}
    for key, pts in parse_tables(path, diagunder_columns=diagunder_columns).items():
        if len(key) == 4 and key[1] == "DIAGUNDER":
            metal, _, under, width = key
            out[(metal, under, width)] = pts
    return out


def parse_diagunder_rules(path: Path) -> dict[tuple, list[tuple[float, float, float]]]:
    """rules: dist dist2 CC CG → key (metal, under, width)."""
    return _diagunder_items(path, diagunder_columns="rules")


def parse_diagunder_model(path: Path) -> dict[tuple, list[tuple[float, float, float]]]:
    """model: dist CC CG res → key (metal, under, width)."""
    return _diagunder_items(path, diagunder_columns="model")


def parse_diagunder(path: Path, *, source: str = "rules") -> dict[tuple, list[tuple[float, float, float]]]:
    if source == "rules":
        return parse_diagunder_rules(path)
    if source == "model":
        return parse_diagunder_model(path)
    raise ValueError(f"source must be 'rules' or 'model', got {source!r}")


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

        axs[1].plot(rd, rcg, "o-", label="rules CG")
        axs[1].plot(ad, acg, "s-", label=f"{label_a} CG(A)")
        if model_b and key in model_b:
            bpts = model_b[key]
            axs[1].plot([x[0] for x in bpts], [x[2] for x in bpts], "^-", label=f"{label_b} CG(B)")
        axs[1].set_title("Dist vs CG")
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

    ma = parse_diagunder_model(Path(args.model))
    mr = parse_diagunder_rules(Path(args.rules))
    mb = parse_diagunder_model(Path(args.model_b)) if args.model_b else None

    n = plot(ma, mb, mr, Path(args.out_dir), args.model_label, args.label_b if mb else None)
    print(f"shared_keys={len(set(ma).intersection(mr))}")
    print(f"plots={n}")
    print(f"out_dir={args.out_dir}")


if __name__ == "__main__":
    main()
