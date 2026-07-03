#!/usr/bin/env bash
# Rebuild DIAGUNDER sections: col3=CC, col4=CG (CG = TC - CC - CC2 - sum(DiagCC)).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

RUN_DIR="${RUN_DIR:-6v2_typ_wirefix}"
CAPS="${CAPS:-${FC_DIR}/${PARSE_DIR:-6v2_typ_wirefix_parse_sym50}/${RUN_DIR}.caps}"
BASE_MODEL="${BASE_MODEL:-${FC_DIR}/model/130.rcx.model}"
OUT_MODEL="${OUT_MODEL:-${FC_DIR}/model/130.rcx.model.diagunder}"
CG_MODE="${CG_MODE:-full}"
RULES="${RULES:-${REPO_ROOT}/flow/platforms/sky130hs/rcx_patterns.rules}"
OUT_TAG="${OUT_TAG:-diagunder_$(date +%Y%m%d)}"
PLOT_DIR="${PLOT_DIR:-${FC_DIR}/model/plots_diagunder_${OUT_TAG}}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -f "${CAPS}" ]] || die "caps not found: ${CAPS}"
[[ -f "${BASE_MODEL}" ]] || die "base model not found: ${BASE_MODEL}"
[[ -f "${RULES}" ]] || die "rules not found: ${RULES}"
[[ -d "${FC_DIR}/${RUN_DIR}" ]] || die "run dir not found: ${FC_DIR}/${RUN_DIR}"

echo "==> [1/2] Patch DIAGUNDER in model -> ${OUT_MODEL}"
python3 "${FC_DIR}/scripts/build_diagunder_model.py" \
  --caps "${CAPS}" \
  --run-dir "${FC_DIR}/${RUN_DIR}" \
  --base-model "${BASE_MODEL}" \
  --out-model "${OUT_MODEL}" \
  --cg-mode "${CG_MODE}"

echo "==> [2/2] Plot DIAGUNDER vs rules (col3=CC, col4=CG)"
python3 "${FC_DIR}/scripts/plot_diagunder_vs_rules.py" \
  --model "${OUT_MODEL}" \
  --model-b "${BASE_MODEL}" \
  --rules "${RULES}" \
  --out-dir "${PLOT_DIR}" \
  --model-label "130.rcx.model.diagunder" \
  --label-b "130.rcx.model (old)"

echo ""
echo "Done."
echo "  model : ${OUT_MODEL}"
echo "  plots : ${PLOT_DIR}"
