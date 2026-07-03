#!/usr/bin/env bash
# Run FasterCap only for patterns missing a valid wires.log (no Total time: line).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

RUN_DIR="${RUN_DIR:-6v2_typ_wirefix}"
OUT_TAG="${OUT_TAG:-${RUN_DIR}_fasterCap}"
TIME_LIMIT="${FASTER_CAP_TIME_LIMIT:-1200}"
CHECK_INTERVAL="${FASTER_CAP_CHECK_INTERVAL:-30}"
LOG="${LOG:-${FC_DIR}/typ_fastercap_${RUN_DIR}_missing.log}"

cd "${FC_DIR}"

if pgrep -f '[r]un_fasterCap.bash '"${RUN_DIR}" >/dev/null; then
  echo "ERROR: FasterCap already running for ${RUN_DIR}" >&2
  echo "  pgrep -af 'run_fasterCap.bash ${RUN_DIR}'" >&2
  exit 1
fi

[[ -d "${RUN_DIR}" ]] || { echo "ERROR: missing ${RUN_DIR}" >&2; exit 1; }

total="$(find "${RUN_DIR}" -name wires | wc -l | tr -d ' ')"
missing="$(find "${RUN_DIR}" -name wires | while read -r w; do
  d=$(dirname "$w")
  if [[ ! -s "${d}/wires.log" ]] || ! grep -q 'Total time:' "${d}/wires.log" 2>/dev/null; then
    echo "$d"
  fi
done | wc -l | tr -d ' ')"

echo "==> RUN_DIR=${RUN_DIR}  patterns=${total}  missing valid wires.log=${missing}"
echo "    log: ${LOG}"

export FASTER_CAP_PROFILE="${FASTER_CAP_PROFILE:-optimized}"
export FASTER_CAP_TIME_LIMIT="${TIME_LIMIT}"
export FASTER_CAP_CHECK_INTERVAL="${CHECK_INTERVAL}"

nohup "${FC_DIR}/scripts/run_fasterCap.bash" \
  "${RUN_DIR}" "${OUT_TAG}" \
  standard 20 ALL \
  "${FC_DIR}/scripts/UniversalFormat2FasterCap_923.py" \
  "${FC_DIR}/bin/FasterCap" \
  > "${LOG}" 2>&1 &

echo "Started PID=$!"
echo "Monitor: grep -E 'Running|Completed|Done ' ${LOG} | tail -8"
echo "Count:   find ${RUN_DIR} -name wires.log -size +1k | wc -l"
