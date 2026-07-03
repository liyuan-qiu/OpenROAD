#!/usr/bin/env bash
# Compare NanGate45 DIAGUNDER: rules col[3] vs FasterCap |C32|+|C34| (wire_3).
#
# Example (wirefix):
#   RUN_DIR=10v2_typ_wirefix \
#   PARSE_DIR=10v2_typ_wirefix_parse_sym50 \
#   OUT_TAG=wirefix_$(date +%Y%m%d) \
#   ./scripts/run_nangate45_diagunder_col3_compare.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

RUN_DIR="${RUN_DIR:-10v2_typ_wirefix}"
PARSE_DIR="${PARSE_DIR:-10v2_typ_wirefix_parse_sym50}"
WIRE="${WIRE:-3}"
RULES="${RULES:-${REPO_ROOT}/flow/platforms/nangate45/rcx_patterns.rules}"
CAPS="${CAPS:-${FC_DIR}/${PARSE_DIR}/${RUN_DIR}.caps}"
OUT_TAG="${OUT_TAG:-col3_$(date +%Y%m%d)}"
PLOT_DIR="${PLOT_DIR:-${FC_DIR}/model/plots_diagunder_col3_cc_${OUT_TAG}}"
SUMMARY_CSV="${SUMMARY_CSV:-${PLOT_DIR}/summary.csv}"
FC_LABEL="${FC_LABEL:-FasterCap wire_${WIRE}}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -f "${RULES}" ]] || die "rules not found: ${RULES}"
[[ -s "${CAPS}" ]] || die "caps not found or empty: ${CAPS}"

EXTRA_ARGS=()
if [[ "${ALL_DIAG_SPACING:-0}" == "1" ]]; then
  EXTRA_ARGS+=(--all-diag-spacing)
fi

echo "==> NanGate45 DIAGUNDER: rules col[3] vs FasterCap |C32|+|C34|"
echo "    rules : ${RULES}"
echo "    caps  : ${CAPS}"
echo "    wire  : ${WIRE}"
echo "    out   : ${PLOT_DIR}"

python3 "${FC_DIR}/scripts/plot_nangate45_diagunder_col3_cc.py" \
  --caps "${CAPS}" \
  --rules "${RULES}" \
  --out-dir "${PLOT_DIR}" \
  --summary-csv "${SUMMARY_CSV}" \
  --wire "${WIRE}" \
  --fc-label "${FC_LABEL}" \
  "${EXTRA_ARGS[@]}"
