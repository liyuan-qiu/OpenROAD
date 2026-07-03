#!/usr/bin/env bash
# Parse completed wires.log -> partial caps -> partial model -> plot vs rules.
# Run anytime during 10v2_typ_fasterCap to early-check calibration quality.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

RUN_DIR="${RUN_DIR:-10v2_typ}"
RULES="${RULES:-${REPO_ROOT}/flow/platforms/nangate45/rcx_patterns.rules}"
MET_CNT="${MET_CNT:-10}"
WIRE="${WIRE:-3}"
MODE="${MODE:-strict}"   # strict | multiwidth
MIN_LOG_BYTES="${MIN_LOG_BYTES:-1000}"
MAX_ASYM_REL="${MAX_ASYM_REL:-}"   # set e.g. 0.5 with SYMMETRIZE=1
SYMMETRIZE="${SYMMETRIZE:-0}"
OUT_TAG="${OUT_TAG:-partial_$(date +%Y%m%d)}"
MODEL_BASENAME="${MODEL_BASENAME:-130.rcx.model.${OUT_TAG}}"

WORK="${WORK:-${FC_DIR}/${OUT_TAG}_compare}"
PARSE_DIR="${WORK}/parse"
MODEL_DIR="${WORK}/model"
PLOT_DIR_STRICT="${WORK}/plots_strict"
PLOT_DIR_MULTI="${WORK}/plots_multiwidth"
CAPS="${PARSE_DIR}/${RUN_DIR}.caps"
MODEL="${MODEL_DIR}/${MODEL_BASENAME}"
RESISTANCE="${FC_DIR}/${RUN_DIR}/resistance.TYP"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -d "${FC_DIR}/${RUN_DIR}" ]] || die "run dir not found: ${FC_DIR}/${RUN_DIR}"
[[ -f "${RULES}" ]] || die "rules not found: ${RULES}"
[[ -f "${FC_DIR}/scripts/fasterCapParse.py" ]] || die "missing fasterCapParse.py"
[[ -f "${FC_DIR}/scripts/plot_rcx_model_vs_rules.py" ]] || die "missing plot script"

if [[ -x "${FC_DIR}/scripts/openroad_exec.sh" ]]; then
  OPENROAD="${FC_DIR}/scripts/openroad_exec.sh"
elif [[ -x "${FC_DIR}/bin/openroad" ]] && "${FC_DIR}/bin/openroad" -version >/dev/null 2>&1; then
  OPENROAD="${FC_DIR}/bin/openroad"
elif [[ -x "${REPO_ROOT}/openroad_run.sh" ]]; then
  OPENROAD="${REPO_ROOT}/openroad_run.sh"
else
  die "openroad not found"
fi

mkdir -p "${PARSE_DIR}" "${MODEL_DIR}" "${PLOT_DIR_STRICT}" "${PLOT_DIR_MULTI}"
cd "${PARSE_DIR}"

echo "==> [1/4] Collect completed wires.log (min ${MIN_LOG_BYTES} bytes)"
find "${FC_DIR}/${RUN_DIR}" -name wires.log -size +"${MIN_LOG_BYTES}"c | sort > sorted.input.list
log_cnt="$(wc -l < sorted.input.list | tr -d ' ')"
echo "    wires.log count: ${log_cnt}"
[[ "${log_cnt}" -gt 0 ]] || die "no completed wires.log yet; wait for fasterCap"

echo "==> [2/4] Parse -> ${CAPS}"
parse_args=(-in_list_file sorted.input.list -wire "${WIRE}" -out_file "${RUN_DIR}.caps")
if [[ "${SYMMETRIZE}" == "1" ]]; then
  parse_args+=(--symmetrize-avg)
  if [[ -n "${MAX_ASYM_REL}" ]]; then
    parse_args+=(--max-asym-rel "${MAX_ASYM_REL}")
  fi
fi
python3 "${FC_DIR}/scripts/fasterCapParse.py" \
  "${parse_args[@]}" > OUT 2>&1
[[ -s "${CAPS}" ]] || die "caps file empty: ${CAPS}"
echo "    caps size: $(wc -c < "${CAPS}") bytes"

echo "==> [3/4] Build partial model -> ${MODEL}"
docker_fc="/OpenROAD-flow-scripts/${FC_DIR#${REPO_ROOT}/}"
tcl="${MODEL_DIR}/readCaps.partial.tcl"
{
  echo "init_rcx_model -corner_names \"TYP\" -met_cnt ${MET_CNT}"
  echo "read_rcx_tables -corner TYP -file ${docker_fc}/${OUT_TAG}_compare/parse/${RUN_DIR}.caps"
  if [[ -f "${RESISTANCE}" ]]; then
    echo "read_rcx_tables -corner TYP -file ${docker_fc}/${RUN_DIR}/resistance.TYP"
  fi
  echo "write_rcx_model -file ${docker_fc}/${OUT_TAG}_compare/model/${MODEL_BASENAME}"
} > "${tcl}"

if [[ "${OPENROAD}" == *openroad_run.sh* ]] || [[ "${OPENROAD}" == *openroad_exec.sh* ]]; then
  "${OPENROAD}" -exit "${docker_fc}/${OUT_TAG}_compare/model/readCaps.partial.tcl" > "${MODEL_DIR}/OUT" 2>&1
else
  "${OPENROAD}" -exit "${tcl}" > "${MODEL_DIR}/OUT" 2>&1
fi
[[ -s "${MODEL}" ]] || { tail -30 "${MODEL_DIR}/OUT" >&2; die "model build failed"; }
echo "    model size: $(wc -c < "${MODEL}") bytes"

echo "==> [4/5] Plot model vs rules (strict) -> ${PLOT_DIR_STRICT}"
python3 "${FC_DIR}/scripts/plot_rcx_model_vs_rules.py" \
  --model "${MODEL}" \
  --rules "${RULES}" \
  --out-dir "${PLOT_DIR_STRICT}" \
  --mode strict \
  --model-label "${MODEL_BASENAME}"

echo "==> [5/5] Plot model vs rules (multiwidth) -> ${PLOT_DIR_MULTI}"
python3 "${FC_DIR}/scripts/plot_rcx_model_vs_rules.py" \
  --model "${MODEL}" \
  --rules "${RULES}" \
  --out-dir "${PLOT_DIR_MULTI}" \
  --mode multiwidth \
  --min-model-widths 1 \
  --model-label "${MODEL_BASENAME}"

echo ""
echo "Done."
echo "  wires.log used : ${log_cnt}"
echo "  partial model  : ${MODEL}"
echo "  plots strict   : ${PLOT_DIR_STRICT}"
echo "  plots multiw   : ${PLOT_DIR_MULTI}"
echo "  sample list    : ${PARSE_DIR}/sorted.input.list"
ls "${PLOT_DIR_STRICT}"/*.png 2>/dev/null | head -5 || echo "  (no shared-key strict plots yet)"
ls "${PLOT_DIR_MULTI}"/*.png 2>/dev/null | head -5 || echo "  (no shared-key multiwidth plots yet)"
