#!/usr/bin/env bash
# Summarize Nangate45 Over/Under/OverUnder model vs rules errors.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

MODEL="${MODEL:-${FC_DIR}/model/130.rcx.model}"
RULES="${RULES:-${REPO_ROOT}/flow/platforms/nangate45/rcx_patterns.rules}"
OUT_TAG="${OUT_TAG:-wirefix_$(date +%Y%m%d)}"
OUT_DIR="${OUT_DIR:-${FC_DIR}/model/error_analysis_${OUT_TAG}}"
DIST_MATCH_MODE="${DIST_MATCH_MODE:-strict}"    # strict | interp
ALLOW_EXTRAPOLATION="${ALLOW_EXTRAPOLATION:-0}" # 1 to enable with interp

EXTRA_ARGS=()
if [[ "${DIST_MATCH_MODE}" == "interp" ]]; then
  EXTRA_ARGS+=(--dist-match-mode interp)
  if [[ "${ALLOW_EXTRAPOLATION}" == "1" ]]; then
    EXTRA_ARGS+=(--allow-extrapolation)
  fi
fi

python3 "${FC_DIR}/scripts/analyze_nangate45_model_vs_rules_errors.py" \
  --model "${MODEL}" \
  --rules "${RULES}" \
  --out-dir "${OUT_DIR}" \
  "${EXTRA_ARGS[@]}"

echo "==> Nangate45 O/U/OU error analysis -> ${OUT_DIR}"

