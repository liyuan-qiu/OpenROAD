#!/usr/bin/env bash
# Start 10v2 wirefix FasterCap with optimized profile (§12.1).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

RUN_DIR="${RUN_DIR:-10v2_typ_wirefix}"
FC_TAG="${FC_TAG:-${RUN_DIR}_fasterCap}"
TIME_LIMIT="${FASTER_CAP_TIME_LIMIT:-1200}"
CHECK_INTERVAL="${FASTER_CAP_CHECK_INTERVAL:-30}"
LOG="${FC_DIR}/typ_fastercap_${RUN_DIR}_run.log"
FORCE="${FASTER_CAP_FORCE_RERUN:-0}"

cd "${FC_DIR}"

if pgrep -f "[r]un_fasterCap.bash ${RUN_DIR}" >/dev/null; then
  echo "ERROR: ${RUN_DIR} FasterCap already running. Stop it first:" >&2
  echo "  pkill -f 'run_fasterCap.bash ${RUN_DIR}'" >&2
  exit 1
fi

[[ -d "${RUN_DIR}" ]] || { echo "ERROR: missing ${RUN_DIR}; run gen_10v2_typ_patterns.sh" >&2; exit 1; }
[[ -f data/process.TYP ]] || { echo "ERROR: missing data/process.TYP; run: make process_10m" >&2; exit 1; }

if [[ "${FORCE}" == "1" ]]; then
  echo "==> FASTER_CAP_FORCE_RERUN=1: deleting all non-empty wires.log"
  find "${RUN_DIR}" -name wires.log -size +0c -delete
fi

echo "==> FasterCap optimized: -g -ps128 -t1e-2 -d2.0 -m0.05 -mc0.5 -r"
echo "    RUN_DIR=${RUN_DIR}  TIME_LIMIT=${TIME_LIMIT}s  log=${LOG}"

export FASTER_CAP_PROFILE=optimized
export FASTER_CAP_TIME_LIMIT="${TIME_LIMIT}"
export FASTER_CAP_CHECK_INTERVAL="${CHECK_INTERVAL}"

nohup "${FC_DIR}/scripts/run_fasterCap.bash" "${RUN_DIR}" "${FC_TAG}" \
  standard 20 ALL \
  "${FC_DIR}/scripts/UniversalFormat2FasterCap_923.py" \
  "${FC_DIR}/bin/FasterCap" \
  > "${LOG}" 2>&1 &
echo "Started PID=$!"
echo "Monitor: ./scripts/monitor_10v2_fastercap.sh ${RUN_DIR}"
