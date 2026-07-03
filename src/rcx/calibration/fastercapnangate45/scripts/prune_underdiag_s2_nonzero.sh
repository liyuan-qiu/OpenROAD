#!/usr/bin/env bash
# Remove UnderDiag case dirs where diag spacing s2 != 0 (keep only *_S0_L*).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_DIR="${RUN_DIR:-10v2_typ_wirefix}"
STOP_FC="${STOP_FC:-1}"

cd "${FC_DIR}"
UD="${RUN_DIR}/TYP/UnderDiag5"
[[ -d "${UD}" ]] || { echo "ERROR: missing ${UD}" >&2; exit 1; }

if [[ "${STOP_FC}" == "1" ]] && pgrep -f '[r]un_fasterCap.bash '"${RUN_DIR}" >/dev/null; then
  echo "==> Stopping FasterCap for ${RUN_DIR}"
  pkill -f '[r]un_fasterCap.bash '"${RUN_DIR}" || true
  sleep 2
fi

before=$(find "${UD}" -type d -name 'S*_S*_L*' | wc -l | tr -d ' ')
removed=0
while IFS= read -r d; do
  rm -rf "$d"
  removed=$((removed + 1))
done < <(find "${UD}" -type d -name 'S*_S*_L*' ! -name '*_S0_L*')
after=$(find "${UD}" -type d -name 'S*_S*_L*' | wc -l | tr -d ' ')

echo "==> UnderDiag dirs: ${before} -> ${after} (removed ${removed}, keep s2=0 only)"
echo "    total wires: $(find "${RUN_DIR}" -name wires | wc -l | tr -d ' ')"
