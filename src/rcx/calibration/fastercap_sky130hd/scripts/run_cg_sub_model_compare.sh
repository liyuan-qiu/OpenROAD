#!/usr/bin/env bash
# Build 130.rcx.model.cg_sub (CG = TC - CC - CC2) and plot vs baseline + rules.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

RUN_DIR="${RUN_DIR:-6v2_typ_wirefix}"
PARSE_DIR="${PARSE_DIR:-6v2_typ_wirefix_parse_sym50}"
CAPS_IN="${CAPS_IN:-${FC_DIR}/${PARSE_DIR}/${RUN_DIR}.caps}"
CAPS_CG="${CAPS_CG:-${FC_DIR}/${PARSE_DIR}/${RUN_DIR}.caps.cg_sub}"
MET_CNT="${MET_CNT:-6}"
WIRE="${WIRE:-3}"
RULES="${RULES:-${REPO_ROOT}/flow/platforms/sky130hs/rcx_patterns.rules}"
MODEL_BASE="${MODEL_BASE:-${FC_DIR}/model/130.rcx.model}"
MODEL_CG="${MODEL_CG:-${FC_DIR}/model/130.rcx.model.cg_sub}"
OUT_TAG="${OUT_TAG:-cg_sub_$(date +%Y%m%d)}"
PLOT_DIR="${PLOT_DIR:-${FC_DIR}/model/plots_cg_sub_${OUT_TAG}}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -f "${CAPS_IN}" ]] || die "caps not found: ${CAPS_IN}"
[[ -f "${RULES}" ]] || die "rules not found: ${RULES}"

if [[ -x "${FC_DIR}/scripts/openroad_exec.sh" ]]; then
  OPENROAD="${FC_DIR}/scripts/openroad_exec.sh"
elif [[ -x "${REPO_ROOT}/openroad_run.sh" ]]; then
  OPENROAD="${REPO_ROOT}/openroad_run.sh"
else
  die "openroad not found"
fi

docker_fc="/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fastercap_sky130hd"
RESISTANCE="${FC_DIR}/${RUN_DIR}/resistance.TYP"

echo "==> [1/3] Transform caps: FR = TC - CC - CC2 (wire_${WIRE} only)"
python3 "${FC_DIR}/scripts/transform_caps_cg_sub.py" \
  -in_file "${CAPS_IN}" \
  -out_file "${CAPS_CG}" \
  --wire "${WIRE}"
[[ -s "${CAPS_CG}" ]] || die "empty caps: ${CAPS_CG}"

echo "==> [2/3] Build model -> ${MODEL_CG}"
TCL="${FC_DIR}/model/readCaps_cg_sub.tcl"
{
  echo "init_rcx_model -corner_names \"TYP\" -met_cnt ${MET_CNT}"
  echo "read_rcx_tables -corner TYP -file ${docker_fc}/${PARSE_DIR}/$(basename "${CAPS_CG}")"
  if [[ -f "${RESISTANCE}" ]]; then
    echo "read_rcx_tables -corner TYP -file ${docker_fc}/${RUN_DIR}/resistance.TYP"
  fi
  echo "write_rcx_model -file ${docker_fc}/model/$(basename "${MODEL_CG}")"
} > "${TCL}"

"${OPENROAD}" -exit "${docker_fc}/model/readCaps_cg_sub.tcl" \
  > "${FC_DIR}/model/OUT_cg_sub" 2>&1
[[ -s "${MODEL_CG}" ]] || { tail -40 "${FC_DIR}/model/OUT_cg_sub"; die "model build failed"; }

echo "==> [3/3] Dual plots (rules + baseline + cg_sub)"
[[ -f "${MODEL_BASE}" ]] || die "baseline model missing: ${MODEL_BASE}"

python3 "${FC_DIR}/scripts/plot_rcx_dual_model_vs_rules.py" \
  --model-a "${MODEL_BASE}" \
  --model-b "${MODEL_CG}" \
  --rules "${RULES}" \
  --out-dir "${PLOT_DIR}/strict" \
  --mode strict \
  --label-a "130.rcx.model (FR=TC-CC)" \
  --label-b "130.rcx.model.cg_sub"

python3 "${FC_DIR}/scripts/plot_rcx_dual_model_vs_rules.py" \
  --model-a "${MODEL_BASE}" \
  --model-b "${MODEL_CG}" \
  --rules "${RULES}" \
  --out-dir "${PLOT_DIR}/multiwidth" \
  --mode multiwidth \
  --min-model-widths 1 \
  --label-a "baseline" \
  --label-b "cg_sub"

echo ""
echo "Done."
echo "  caps (cg_sub) : ${CAPS_CG}"
echo "  model (cg_sub): ${MODEL_CG}"
echo "  model (base)  : ${MODEL_BASE}"
echo "  plots         : ${PLOT_DIR}"
