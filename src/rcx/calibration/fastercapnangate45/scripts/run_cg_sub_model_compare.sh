#!/usr/bin/env bash
# Deprecated wrapper: use run_10v2_parse_model_compare.sh (builds CG(A)+CG(B)+plots).
# Kept for backward compatibility; runs plot-only if caps/models exist, else full pipeline.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RUN_DIR="${RUN_DIR:-10v2_typ_wirefix}"
PARSE_DIR="${PARSE_DIR:-10v2_typ_wirefix_parse_sym50}"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CAPS_IN="${CAPS_IN:-${FC_DIR}/${PARSE_DIR}/${RUN_DIR}.caps}"
MODEL_BASE="${MODEL_BASE:-${FC_DIR}/model/130.rcx.model}"
MODEL_CG="${MODEL_CG:-${FC_DIR}/model/130.rcx.model.cg_sub}"

if [[ -s "${CAPS_IN}" && -s "${MODEL_BASE}" && -s "${MODEL_CG}" ]]; then
  export PLOTS_ONLY=1
else
  export PLOTS_ONLY=0
fi

export RUN_DIR PARSE_DIR
export MODEL="${MODEL_BASE}"
export MODEL_CG
export OUT_TAG="${OUT_TAG:-wirefix_cg_sub_$(date +%Y%m%d)}"
export MET_CNT="${MET_CNT:-10}"

exec "${SCRIPT_DIR}/run_10v2_parse_model_compare.sh"
