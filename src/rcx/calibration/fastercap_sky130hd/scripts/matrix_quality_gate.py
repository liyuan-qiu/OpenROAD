#!/usr/bin/env python3
"""Shared strict capacitance-matrix quality gate for parse and workflow checks."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
FC_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(FC_DIR.parent / "fastercapnangate45" / "scripts"))

from scan_wires_quality import (  # noqa: E402
    STRONG_TH,
    block_no_m0,
    parse_last_matrix,
    scan_offdiag_positive,
    scan_symmetry,
)


@dataclass(frozen=True)
class GateConfig:
    max_rel: float = 0.10
    min_abs: float = 1e-16
    reject_pos_offdiag: bool = True
    reject_sign_flip: bool = True
    strong_th: float = STRONG_TH


def matrix_max_rel_asym(mat: list[list[float]], min_abs: float = 1e-16) -> float:
    """Full-matrix reciprocity: max |Cij-Cji|/max(|Cij|,|Cji|) for |C|>=min_abs."""
    n = len(mat)
    max_rel = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            a, b = mat[i][j], mat[j][i]
            ref = max(abs(a), abs(b))
            if ref < min_abs:
                continue
            max_rel = max(max_rel, abs(a - b) / ref)
    return max_rel


def evaluate_matrix_quality_gate(
    mat: list[list[float]] | None,
    config: GateConfig | None = None,
) -> tuple[bool, str, dict[str, float | int | bool]]:
    """Return (passed, reason, metrics). reason is 'ok' when passed."""
    cfg = config or GateConfig()
    metrics: dict[str, float | int | bool] = {}
    if not mat:
        return False, "no_matrix", metrics

    max_rel = matrix_max_rel_asym(mat, cfg.min_abs)
    metrics["global_max_rel_asym"] = max_rel

    sym = scan_symmetry(mat, cfg.strong_th)
    off = scan_offdiag_positive(block_no_m0(mat), cfg.strong_th)
    sign_flips = int(sym.get("sign_flip_pairs") or 0)
    pos_offdiag = bool(off.get("pos_offdiag_strong"))
    metrics["sign_flip_pairs"] = sign_flips
    metrics["pos_offdiag_strong"] = int(pos_offdiag)

    failures: list[str] = []
    if max_rel > cfg.max_rel:
        failures.append(f"reciprocity={max_rel:.4g}>{cfg.max_rel:g}")
    if cfg.reject_sign_flip and sign_flips > 0:
        failures.append(f"sign_flip_pairs={sign_flips}")
    if cfg.reject_pos_offdiag and pos_offdiag:
        failures.append("pos_offdiag_strong")

    if failures:
        return False, "; ".join(failures), metrics
    return True, "ok", metrics


def evaluate_log_text(
    text: str,
    config: GateConfig | None = None,
) -> tuple[bool, str, dict[str, float | int | bool]]:
    mat = parse_last_matrix(text.splitlines())
    return evaluate_matrix_quality_gate(mat, config)


def gate_config_from_env(
    *,
    max_rel: float | None = None,
    min_abs: float | None = None,
    reject_pos_offdiag: bool | None = None,
    reject_sign_flip: bool | None = None,
) -> GateConfig:
    return GateConfig(
        max_rel=max_rel if max_rel is not None else 0.10,
        min_abs=min_abs if min_abs is not None else 1e-16,
        reject_pos_offdiag=True if reject_pos_offdiag is None else reject_pos_offdiag,
        reject_sign_flip=True if reject_sign_flip is None else reject_sign_flip,
    )
