#!/usr/bin/env bash
# Three cumulative gate summaries under REPORT_DIR (gate_L1, gate_L1_L2, gate_L1_L2_L3).
#
# Run after default FasterCap Over5 workflow finishes (all wires.log present):
#   cd tools/OpenROAD/src/rcx/calibration/fastercap_sky130hd
#   REPORT_DIR=workflow_6v2_typ_ict_len10_4/over_default \
#   RUN_DIR=6v2_typ_ict_len10_4 \
#   LEN=10 FAMILY=Over5 \
#   ./scripts/summarize_three_level_gates.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

REPORT_DIR="${REPORT_DIR:-${FC_DIR}/workflow_6v2_typ_ict_len10_4/over_default}"
RUN_DIR="${RUN_DIR:-6v2_typ_ict_len10_4}"
LEN="${LEN:-10}"
FAMILY="${FAMILY:-Over5}"
L1_MAX_LR="${L1_MAX_LR:-0.10}"
L2_MAX_T="${L2_MAX_T:-0.10}"
L3_MAX_REL="${L3_MAX_REL:-0.10}"

if [[ "${REPORT_DIR}" != /* ]]; then
  REPORT_DIR="${FC_DIR}/${REPORT_DIR}"
fi

SKIP_ARGS=()
if [[ -f "${REPORT_DIR}/skipped_preflight.txt" ]]; then
  SKIP_ARGS=(--skip-list "${REPORT_DIR}/skipped_preflight.txt")
fi

exec python3 "${SCRIPT_DIR}/summarize_three_level_gates.py" \
  --report-dir "${REPORT_DIR}" \
  --run-dir "${FC_DIR}/${RUN_DIR}" \
  --len "${LEN}" \
  --family "${FAMILY}" \
  --l1-max-lr "${L1_MAX_LR}" \
  --l2-max-t "${L2_MAX_T}" \
  --l3-max-rel "${L3_MAX_REL}" \
  "${SKIP_ARGS[@]}"
