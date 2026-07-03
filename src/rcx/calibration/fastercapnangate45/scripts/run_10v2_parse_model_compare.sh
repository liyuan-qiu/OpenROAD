#!/usr/bin/env bash
# Parse wires.log -> sym50 caps -> CG(A) + CG(B) models -> rules contrast plots.
#
# CG(A): 130.rcx.model          (FR = TC - CC)
# CG(B): 130.rcx.model.cg_sub    (FR = TC - CC - CC2)
#
# Plots (rules + CG(A) + CG(B) on CG panel):
#   ${PLOT_DIR}/strict/
#   ${PLOT_DIR}/multiwidth/
#   ${PLOT_DIR}/diagunder/
#
# Wirefix example:
#   RUN_DIR=10v2_typ_wirefix \
#   PARSE_DIR=10v2_typ_wirefix_parse_sym50 \
#   OUT_TAG=wirefix_$(date +%Y%m%d) \
#   MET_CNT=10 \
#   ./scripts/run_10v2_parse_model_compare.sh
#
# Re-plot only (caps + models already built):
#   PLOTS_ONLY=1 OUT_TAG=wirefix_$(date +%Y%m%d) \
#   RUN_DIR=10v2_typ_wirefix PARSE_DIR=10v2_typ_wirefix_parse_sym50 \
#   ./scripts/run_10v2_parse_model_compare.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

RUN_DIR="${RUN_DIR:-10v2_typ}"
PARSE_DIR="${PARSE_DIR:-10v2_typ_parse_sym50}"
MET_CNT="${MET_CNT:-10}"
WIRE="${WIRE:-3}"
MAX_ASYM_REL="${MAX_ASYM_REL:-0.5}"
RULES="${RULES:-${REPO_ROOT}/flow/platforms/nangate45/rcx_patterns.rules}"
MODEL="${MODEL:-${FC_DIR}/model/130.rcx.model}"
MODEL_CG="${MODEL_CG:-${FC_DIR}/model/130.rcx.model.cg_sub}"
CAPS_CG="${CAPS_CG:-${FC_DIR}/${PARSE_DIR}/${RUN_DIR}.caps.cg_sub}"
OUT_TAG="${OUT_TAG:-10v2_sym50_$(date +%Y%m%d)}"
PLOT_DIR="${PLOT_DIR:-${FC_DIR}/model/plots_vs_rules_${OUT_TAG}}"
PLOTS_ONLY="${PLOTS_ONLY:-0}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -d "${FC_DIR}/${RUN_DIR}" ]] || die "run dir not found: ${FC_DIR}/${RUN_DIR}"
[[ -f "${RULES}" ]] || die "rules not found: ${RULES}"

if [[ -x "${FC_DIR}/scripts/openroad_exec.sh" ]]; then
  OPENROAD="${FC_DIR}/scripts/openroad_exec.sh"
elif [[ -x "${REPO_ROOT}/openroad_run.sh" ]]; then
  OPENROAD="${REPO_ROOT}/openroad_run.sh"
else
  die "openroad not found"
fi

docker_fc="/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fastercapnangate45"
CAPS="${FC_DIR}/${PARSE_DIR}/${RUN_DIR}.caps"
RESISTANCE="${FC_DIR}/${RUN_DIR}/resistance.TYP"

plot_triple() {
  echo "==> Plot vs rules (strict, rules + CG(A) + CG(B)) -> ${PLOT_DIR}/strict"
  python3 "${FC_DIR}/scripts/plot_rcx_dual_model_vs_rules.py" \
    --model-a "${MODEL}" \
    --model-b "${MODEL_CG}" \
    --rules "${RULES}" \
    --out-dir "${PLOT_DIR}/strict" \
    --mode strict \
    --label-a "CG(A) TC-CC" \
    --label-b "CG(B) TC-CC-CC2"

  echo "==> Plot vs rules (multiwidth, rules + CG(A) + CG(B)) -> ${PLOT_DIR}/multiwidth"
  python3 "${FC_DIR}/scripts/plot_rcx_dual_model_vs_rules.py" \
    --model-a "${MODEL}" \
    --model-b "${MODEL_CG}" \
    --rules "${RULES}" \
    --out-dir "${PLOT_DIR}/multiwidth" \
    --mode multiwidth \
    --min-model-widths 1 \
    --label-a "CG(A)" \
    --label-b "CG(B)"

  echo "==> DIAGUNDER triple plots -> ${PLOT_DIR}/diagunder"
  python3 "${FC_DIR}/scripts/plot_diagunder_vs_rules.py" \
    --model "${MODEL}" \
    --model-b "${MODEL_CG}" \
    --rules "${RULES}" \
    --out-dir "${PLOT_DIR}/diagunder" \
    --model-label "CG(A)" \
    --label-b "CG(B)"
}

if [[ "${PLOTS_ONLY}" == "1" ]]; then
  [[ -s "${MODEL}" ]] || die "CG(A) model missing: ${MODEL}"
  [[ -s "${MODEL_CG}" ]] || die "CG(B) model missing: ${MODEL_CG}"
  echo "==> PLOTS_ONLY: regenerate contrast plots (rules + CG(A) + CG(B))"
  plot_triple
else
  echo "==> [1/6] Parse ${RUN_DIR} (symmetrize Cij/Cji avg, skip if asym>${MAX_ASYM_REL})"
  rm -rf "${FC_DIR}/${PARSE_DIR}"
  mkdir -p "${FC_DIR}/${PARSE_DIR}"
  cd "${FC_DIR}/${PARSE_DIR}"

  find "${FC_DIR}/${RUN_DIR}" -name wires.log -size +0c | sort > sorted.input.list
  log_cnt="$(wc -l < sorted.input.list | tr -d ' ')"
  echo "    wires.log count: ${log_cnt}"

  python3 "${FC_DIR}/scripts/fasterCapParse.py" \
    -in_list_file sorted.input.list \
    -wire "${WIRE}" \
    --symmetrize-avg \
    --max-asym-rel "${MAX_ASYM_REL}" \
    -out_file "${RUN_DIR}.caps" > OUT 2>&1

  [[ -s "${CAPS}" ]] || { tail -30 OUT; die "caps empty: ${CAPS}"; }
  echo "    caps: $(wc -l < "${CAPS}") lines, $(wc -c < "${CAPS}") bytes"
  echo "    skipped_asymmetry: $(wc -l < skipped_asymmetry 2>/dev/null || echo 0)"

  echo "==> [2/6] Build CG(A) model -> ${MODEL}"
  mkdir -p "$(dirname "${MODEL}")"
  if [[ -f "${MODEL}" ]]; then
    cp -a "${MODEL}" "${MODEL}.bak.$(date +%Y%m%d_%H%M%S)"
  fi

  TCL="${FC_DIR}/model/readCaps_10v2_sym.tcl"
  {
    echo "init_rcx_model -corner_names \"TYP\" -met_cnt ${MET_CNT}"
    echo "read_rcx_tables -corner TYP -file ${docker_fc}/${PARSE_DIR}/${RUN_DIR}.caps"
    if [[ -f "${RESISTANCE}" ]]; then
      echo "read_rcx_tables -corner TYP -file ${docker_fc}/${RUN_DIR}/resistance.TYP"
    fi
    echo "write_rcx_model -file ${docker_fc}/model/130.rcx.model"
  } > "${TCL}"

  "${OPENROAD}" -exit "${docker_fc}/model/readCaps_10v2_sym.tcl" > "${FC_DIR}/model/OUT_10v2_sym" 2>&1
  [[ -s "${MODEL}" ]] || { tail -40 "${FC_DIR}/model/OUT_10v2_sym"; die "CG(A) model build failed"; }
  echo "    CG(A) model size: $(wc -c < "${MODEL}") bytes"

  echo "==> [3/6] Build CG(B) caps + model -> ${MODEL_CG}"
  python3 "${FC_DIR}/scripts/transform_caps_cg_sub.py" \
    -in_file "${CAPS}" \
    -out_file "${CAPS_CG}" \
    --wire "${WIRE}"
  [[ -s "${CAPS_CG}" ]] || die "empty caps: ${CAPS_CG}"

  TCL_CG="${FC_DIR}/model/readCaps_cg_sub.tcl"
  {
    echo "init_rcx_model -corner_names \"TYP\" -met_cnt ${MET_CNT}"
    echo "read_rcx_tables -corner TYP -file ${docker_fc}/${PARSE_DIR}/$(basename "${CAPS_CG}")"
    if [[ -f "${RESISTANCE}" ]]; then
      echo "read_rcx_tables -corner TYP -file ${docker_fc}/${RUN_DIR}/resistance.TYP"
    fi
    echo "write_rcx_model -file ${docker_fc}/model/$(basename "${MODEL_CG}")"
  } > "${TCL_CG}"

  "${OPENROAD}" -exit "${docker_fc}/model/readCaps_cg_sub.tcl" > "${FC_DIR}/model/OUT_cg_sub" 2>&1
  [[ -s "${MODEL_CG}" ]] || { tail -40 "${FC_DIR}/model/OUT_cg_sub"; die "CG(B) model build failed"; }
  echo "    CG(B) model size: $(wc -c < "${MODEL_CG}") bytes"

  echo "==> [4/6] strict + [5/6] multiwidth + [6/6] diagunder plots"
  plot_triple
fi

plot_cnt="$(find "${PLOT_DIR}" -name '*.png' 2>/dev/null | wc -l | tr -d ' ')"

echo ""
echo "Done."
echo "  parse dir     : ${FC_DIR}/${PARSE_DIR}"
echo "  caps (CG(A))  : ${CAPS}"
echo "  caps (CG(B))  : ${CAPS_CG}"
echo "  skipped asym  : ${FC_DIR}/${PARSE_DIR}/skipped_asymmetry"
echo "  model CG(A)   : ${MODEL}   (FR = TC - CC)"
echo "  model CG(B)   : ${MODEL_CG}   (FR = TC - CC - CC2)"
echo "  plots         : ${PLOT_DIR}  (${plot_cnt} png, rules + CG(A) + CG(B))"
echo "    strict/     : ${PLOT_DIR}/strict/"
echo "    multiwidth/ : ${PLOT_DIR}/multiwidth/"
echo "    diagunder/  : ${PLOT_DIR}/diagunder/"
