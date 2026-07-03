#!/usr/bin/env bash
# Partial model vs rules during 6v2_typ_fasterCap (nangate45 doc §6.3).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

export RUN_DIR="${RUN_DIR:-6v2_typ}"
export RULES="${RULES:-${REPO_ROOT}/flow/platforms/sky130hs/rcx_patterns.rules}"
export MET_CNT="${MET_CNT:-6}"
export WIRE="${WIRE:-3}"
export OUT_TAG="${OUT_TAG:-partial_6v2_$(date +%Y%m%d)}"
export MODEL_BASENAME="${MODEL_BASENAME:-130.rcx.model.${OUT_TAG}}"

exec "${FC_DIR}/scripts/compare_partial_model_vs_rules.sh" "$@"
