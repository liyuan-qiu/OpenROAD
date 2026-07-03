#!/usr/bin/env python3
"""
Plot two RCX models + rules: same pattern key, dist on x-axis.

Useful to compare baseline FR (= TC - CC) vs CG_sub (= TC - CC - CC2).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from plot_rcx_model_vs_rules import (
    filename_of_header,
    filename_of_key,
    parse_tables,
    plot_out_path,
    title_of_header,
    title_of_key,
)


def plot_strict_dual(
    model_a: dict,
    model_b: dict,
    rules: dict,
    out_dir: Path,
    label_a: str,
    label_b: str,
) -> tuple[int, int]:
    shared = sorted(set(model_a).intersection(set(model_b)).intersection(set(rules)))
    generated = 0

    for key in shared:
        apts = model_a.get(key, [])
        bpts = model_b.get(key, [])
        rpts = rules.get(key, [])
        if not apts or not bpts or not rpts:
            continue

        rd = [x[0] for x in rpts]
        rcc = [x[1] for x in rpts]
        rcg = [x[2] for x in rpts]

        ad = [x[0] for x in apts]
        acc = [x[1] for x in apts]
        acg = [x[2] for x in apts]

        bd = [x[0] for x in bpts]
        bcc = [x[1] for x in bpts]
        bcg = [x[2] for x in bpts]

        fig, axs = plt.subplots(1, 2, figsize=(13, 5), dpi=130)
        fig.suptitle(
            f"{title_of_key(key)}\n"
            "CG(A)=TC-CC  CG(B)=TC-CC-CC2"
        )

        axs[0].plot(rd, rcc, "o-", linewidth=2.0, label="rules")
        axs[0].plot(ad, acc, "s--", alpha=0.9, label=label_a)
        axs[0].plot(bd, bcc, "^--", alpha=0.9, label=label_b)
        axs[0].set_title("Dist vs CC")
        axs[0].set_xlabel("Dist")
        axs[0].set_ylabel("CC")
        axs[0].grid(True, alpha=0.3)
        axs[0].legend(fontsize=8)

        axs[1].plot(rd, rcg, "o-", linewidth=2.0, label="rules CG")
        axs[1].plot(ad, acg, "s--", alpha=0.9, label=f"{label_a} CG(A)")
        axs[1].plot(bd, bcg, "^-", alpha=0.9, label=f"{label_b} CG(B)")
        axs[1].set_title("Dist vs CG")
        axs[1].set_xlabel("Dist")
        axs[1].set_ylabel("CG")
        axs[1].grid(True, alpha=0.3)
        axs[1].legend(fontsize=8)

        out_png = plot_out_path(out_dir, key[1], filename_of_key(key))
        fig.tight_layout(rect=[0, 0, 1, 0.93])
        fig.savefig(out_png)
        plt.close(fig)
        generated += 1

    return len(shared), generated


def plot_multiwidth_dual(
    model_a: dict,
    model_b: dict,
    rules: dict,
    out_dir: Path,
    label_a: str,
    label_b: str,
    min_model_widths: int,
) -> tuple[int, int]:
    def group_by_header(data: dict) -> dict[tuple, dict[float, list]]:
        out: dict[tuple, dict[float, list]] = {}
        for key, pts in data.items():
            header = key[:-1]
            width = key[-1]
            out.setdefault(header, {})[width] = pts
        return out

    ga = group_by_header(model_a)
    gb = group_by_header(model_b)
    gr = group_by_header(rules)

    shared_headers = sorted(set(ga).intersection(set(gb)).intersection(set(gr)))
    generated = 0

    for hdr in shared_headers:
        aw = sorted(w for w, pts in ga[hdr].items() if pts)
        bw = sorted(w for w, pts in gb[hdr].items() if pts)
        rw = sorted(w for w, pts in gr[hdr].items() if pts)
        if len(aw) < min_model_widths or not rw:
            continue

        overlap = sorted(set(aw).intersection(set(bw)).intersection(set(rw)))
        rules_w = overlap[0] if overlap else rw[0]
        rpts = gr[hdr][rules_w]
        rd = [x[0] for x in rpts]
        rcc = [x[1] for x in rpts]
        rcg = [x[2] for x in rpts]

        fig, axs = plt.subplots(1, 2, figsize=(13, 5), dpi=130)
        fig.suptitle(
            f"{title_of_header(hdr)} | rules w={rules_w:g}\n"
            "CG(A)=TC-CC  CG(B)=TC-CC-CC2"
        )

        axs[0].plot(rd, rcc, "o-", linewidth=2.0, label="rules")
        axs[1].plot(rd, rcg, "o-", linewidth=2.0, label="rules CG")

        for w in sorted(set(aw).intersection(set(bw))):
            apts = ga[hdr][w]
            bpts = gb[hdr][w]
            ad = [x[0] for x in apts]
            acg = [x[2] for x in apts]
            bd = [x[0] for x in bpts]
            bcg = [x[2] for x in bpts]
            axs[0].plot(ad, [x[1] for x in apts], "s--", alpha=0.75, label=f"{label_a} w={w:g}")
            axs[0].plot(bd, [x[1] for x in bpts], "^--", alpha=0.75, label=f"{label_b} w={w:g}")
            axs[1].plot(ad, acg, "s--", alpha=0.75, label=f"{label_a} w={w:g}")
            axs[1].plot(bd, bcg, "^-", alpha=0.75, label=f"{label_b} w={w:g}")

        axs[0].set_title("Dist vs CC")
        axs[0].set_xlabel("Dist")
        axs[0].set_ylabel("CC")
        axs[0].grid(True, alpha=0.3)
        axs[0].legend(fontsize=7)

        axs[1].set_title("Dist vs CG")
        axs[1].set_xlabel("Dist")
        axs[1].set_ylabel("CG")
        axs[1].grid(True, alpha=0.3)
        axs[1].legend(fontsize=7)

        out_png = plot_out_path(out_dir, hdr[1], filename_of_header(hdr))
        fig.tight_layout(rect=[0, 0, 1, 0.92])
        fig.savefig(out_png)
        plt.close(fig)
        generated += 1

    return len(shared_headers), generated


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot two models + rules per pattern/dist.")
    ap.add_argument("--model-a", required=True, help="Baseline model (FR = TC - CC)")
    ap.add_argument("--model-b", required=True, help="CG_sub model (FR = TC - CC - CC2)")
    ap.add_argument("--rules", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--label-a", default="baseline")
    ap.add_argument("--label-b", default="cg_sub")
    ap.add_argument(
        "--mode",
        choices=["strict", "multiwidth"],
        default="strict",
    )
    ap.add_argument("--min-model-widths", type=int, default=1)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ma = parse_tables(Path(args.model_a), diagunder_columns="model")
    mb = parse_tables(Path(args.model_b), diagunder_columns="model")
    rules = parse_tables(Path(args.rules), diagunder_columns="rules")

    if args.mode == "strict":
        shared, generated = plot_strict_dual(
            ma, mb, rules, out_dir, args.label_a, args.label_b
        )
    else:
        shared, generated = plot_multiwidth_dual(
            ma,
            mb,
            rules,
            out_dir,
            args.label_a,
            args.label_b,
            args.min_model_widths,
        )

    print(f"mode={args.mode}")
    print(f"shared_keys={shared}")
    print(f"plots_generated={generated}")
    print(f"out_dir={out_dir}")


if __name__ == "__main__":
    main()
