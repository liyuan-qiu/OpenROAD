#!/usr/bin/env bash
# Parse 6v2_typ wires.log -> sym50 caps -> model -> plots vs sky130 rules.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

RUN_DIR="${RUN_DIR:-6v2_typ}"
PARSE_DIR="${PARSE_DIR:-6v2_typ_parse_sym50}"
MET_CNT="${MET_CNT:-6}"
WIRE="${WIRE:-3}"
MAX_ASYM_REL="${MAX_ASYM_REL:-0.5}"
RULES="${RULES:-${REPO_ROOT}/flow/platforms/sky130hs/rcx_patterns.rules}"
MODEL="${MODEL:-${FC_DIR}/model/130.rcx.model}"
OUT_TAG="${OUT_TAG:-6v2_sym50_$(date +%Y%m%d)}"
PLOT_DIR="${PLOT_DIR:-${FC_DIR}/model/plots_vs_rules_${OUT_TAG}}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -d "${FC_DIR}/${RUN_DIR}" ]] || die "run dir not found: ${FC_DIR}/${RUN_DIR}"
[[ -f "${RULES}" ]] || die "rules not found: ${RULES}"

if [[ -x "${FC_DIR}/scripts/openroad_exec.sh" ]]; then
  OPENROAD="${FC_DIR}/scripts/openroad_exec.sh"
elif [[ -x "${REPO_ROOT}/openroad_run.sh" ]]; then
  OPENROAD="${REPO_ROOT}/openroad_run.sh"
else
  die "openroad not found; run make setup_links first"
fi

docker_fc="/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fastercap_sky130hd"
CAPS="${FC_DIR}/${PARSE_DIR}/${RUN_DIR}.caps"
RESISTANCE="${FC_DIR}/${RUN_DIR}/resistance.TYP"

echo "==> [1/4] Parse ${RUN_DIR} (symmetrize, skip asym>${MAX_ASYM_REL})"
rm -rf "${FC_DIR}/${PARSE_DIR}"
mkdir -p "${FC_DIR}/${PARSE_DIR}"
cd "${FC_DIR}/${PARSE_DIR}"

find "${FC_DIR}/${RUN_DIR}" -name wires.log -size +0c | sort > sorted.input.list
log_cnt="$(wc -l < sorted.input.list | tr -d ' ')"
echo "    wires.log count: ${log_cnt}"
[[ "${log_cnt}" -gt 0 ]] || die "no wires.log; run make 6v2_typ_fasterCap first"

python3 "${FC_DIR}/scripts/fasterCapParse.py" \
  -in_list_file sorted.input.list \
  -wire "${WIRE}" \
  --symmetrize-avg \
  --max-asym-rel "${MAX_ASYM_REL}" \
  -out_file "${RUN_DIR}.caps" > OUT 2>&1

[[ -s "${CAPS}" ]] || { tail -30 OUT; die "caps empty: ${CAPS}"; }
echo "    caps: $(wc -l < "${CAPS}") lines"

echo "==> [2/4] Build model -> ${MODEL}"
mkdir -p "$(dirname "${MODEL}")"
if [[ -f "${MODEL}" ]]; then
  cp -a "${MODEL}" "${MODEL}.bak.$(date +%Y%m%d_%H%M%S)"
fi

TCL="${FC_DIR}/model/readCaps_6v2_sym.tcl"
{
  echo "init_rcx_model -corner_names \"TYP\" -met_cnt ${MET_CNT}"
  echo "read_rcx_tables -corner TYP -file ${docker_fc}/${PARSE_DIR}/${RUN_DIR}.caps"
  if [[ -f "${RESISTANCE}" ]]; then
    echo "read_rcx_tables -corner TYP -file ${docker_fc}/${RUN_DIR}/resistance.TYP"
  fi
  echo "write_rcx_model -file ${docker_fc}/model/130.rcx.model"
} > "${TCL}"

"${OPENROAD}" -exit "${docker_fc}/model/readCaps_6v2_sym.tcl" > "${FC_DIR}/model/OUT_6v2_sym" 2>&1
[[ -s "${MODEL}" ]] || { tail -40 "${FC_DIR}/model/OUT_6v2_sym"; die "model build failed"; }

echo "==> [3/4] Plot vs rules (strict)"
python3 "${FC_DIR}/scripts/plot_rcx_model_vs_rules.py" \
  --model "${MODEL}" \
  --rules "${RULES}" \
  --out-dir "${PLOT_DIR}/strict" \
  --mode strict \
  --model-label "130.rcx.model.6v2"

echo "==> [4/4] Plot vs rules (multiwidth)"
python3 "${FC_DIR}/scripts/plot_rcx_model_vs_rules.py" \
  --model "${MODEL}" \
  --rules "${RULES}" \
  --out-dir "${PLOT_DIR}/multiwidth" \
  --mode multiwidth \
  --min-model-widths 1 \
  --model-label "130.rcx.model.6v2"

echo ""
echo "Done."
echo "  caps   : ${CAPS}"
echo "  model  : ${MODEL}"
echo "  plots  : ${PLOT_DIR}"
