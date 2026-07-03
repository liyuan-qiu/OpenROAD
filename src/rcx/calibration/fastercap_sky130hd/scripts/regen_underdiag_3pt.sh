#!/usr/bin/env bash
# Regenerate UnderDiag with 3-point diag s2 (see extSolverGen.cpp).
# Removes stale UnderDiag5 dirs (old 11-point s2 sweep) then full pattern gen.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

RUN_DIR="${RUN_DIR:-6v2_typ_wirefix}"
S_LIST="${S_LIST:-1.0 1.5 2.0 3 5 6 7 8 9 10}"
STOP_FC="${STOP_FC:-1}"

cd "${FC_DIR}"

if [[ "${STOP_FC}" == "1" ]] && pgrep -f '[r]un_fasterCap.bash '"${RUN_DIR}" >/dev/null; then
  echo "==> Stopping FasterCap for ${RUN_DIR}"
  pkill -f '[r]un_fasterCap.bash '"${RUN_DIR}" || true
  sleep 2
fi

echo "==> Removing ${RUN_DIR}/TYP/UnderDiag5 (stale s2 dirs)"
rm -rf "${RUN_DIR}/TYP/UnderDiag5"

echo "==> Regenerating all patterns (expect 960 wires, UnderDiag 420)"
RUN_DIR="${RUN_DIR}" S_LIST="${S_LIST}" "${SCRIPT_DIR}/gen_6v2_typ_patterns.sh"

find "${RUN_DIR}/TYP/UnderDiag5" -name wires | wc -l | xargs -I{} echo "    UnderDiag5 wires: {}"
find "${RUN_DIR}" -name wires | wc -l | xargs -I{} echo "    total wires: {}"

echo ""
echo "Next: ./scripts/run_missing_fastercap.sh"
