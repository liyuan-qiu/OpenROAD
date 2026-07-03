#!/usr/bin/env bash
# Sky130 DIAGUNDER: wires.log (wire_3) vs rules (dist, 0, CC, CG).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

RUN_DIR="${RUN_DIR:-6v2_typ_wirefix}"
RULES="${RULES:-${REPO_ROOT}/flow/platforms/sky130hs/rcx_patterns.rules}"
OUT_TAG="${OUT_TAG:-wirefix_$(date +%Y%m%d)}"
PLOT_DIR="${PLOT_DIR:-${FC_DIR}/model/plots_diagunder_wires_vs_rules_${OUT_TAG}}"
SUMMARY_CSV="${SUMMARY_CSV:-${PLOT_DIR}/summary.csv}"
CG_MODE="${CG_MODE:-tc_minus_cc}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -d "${FC_DIR}/${RUN_DIR}" ]] || die "run dir not found: ${FC_DIR}/${RUN_DIR}"
[[ -f "${RULES}" ]] || die "rules not found: ${RULES}"

EXTRA=()
[[ "${ALL_DIAG_SPACING:-0}" == "1" ]] && EXTRA+=(--all-diag-spacing)

echo "==> Sky130 DIAGUNDER: wires.log vs rules"
echo "    run   : ${FC_DIR}/${RUN_DIR}"
echo "    rules : ${RULES}"
echo "    cg    : ${CG_MODE}"
echo "    out   : ${PLOT_DIR}"

python3 "${FC_DIR}/scripts/plot_sky130_diagunder_wires_vs_rules.py" \
  --run-dir "${FC_DIR}/${RUN_DIR}" \
  --rules "${RULES}" \
  --out-dir "${PLOT_DIR}" \
  --summary-csv "${SUMMARY_CSV}" \
  --cg-mode "${CG_MODE}" \
  "${EXTRA[@]}"
