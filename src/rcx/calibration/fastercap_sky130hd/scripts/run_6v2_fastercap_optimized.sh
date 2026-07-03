#!/usr/bin/env bash
# Start 6v2_typ FasterCap with the same optimized profile as nangate45 §12
# (see new_rep/docs/nangate45_10m_process_conversion.md §12.1).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

TIME_LIMIT="${FASTER_CAP_TIME_LIMIT:-1200}"
CHECK_INTERVAL="${FASTER_CAP_CHECK_INTERVAL:-30}"
LOG="${FC_DIR}/typ_fastercap_run.log"
FORCE="${FASTER_CAP_FORCE_RERUN:-0}"

cd "${FC_DIR}"

if pgrep -f '[r]un_fasterCap.bash 6v2_typ' >/dev/null; then
  echo "ERROR: 6v2_typ FasterCap already running. Stop it first:" >&2
  echo "  pkill -f 'run_fasterCap.bash 6v2_typ'" >&2
  exit 1
fi

[[ -d 6v2_typ ]] || { echo "ERROR: missing 6v2_typ; run: make 6v2_typ" >&2; exit 1; }
[[ -f data/process.TYP ]] || { echo "ERROR: missing data/process.TYP; run: make process_6m" >&2; exit 1; }

if [[ "${FORCE}" == "1" ]]; then
  echo "==> FASTER_CAP_FORCE_RERUN=1: deleting all non-empty wires.log"
  find 6v2_typ -name wires.log -size +0c -delete
fi

echo "==> FasterCap optimized (nangate45 §12.1): -g -ps128 -t1e-2 -d2.0 -m0.05 -mc0.5 -r"
echo "    TIME_LIMIT=${TIME_LIMIT}s  CHECK_INTERVAL=${CHECK_INTERVAL}s"
echo "    log: ${LOG}"

export FASTER_CAP_PROFILE=optimized
export FASTER_CAP_TIME_LIMIT="${TIME_LIMIT}"
export FASTER_CAP_CHECK_INTERVAL="${CHECK_INTERVAL}"

nohup make 6v2_typ_fasterCap > "${LOG}" 2>&1 &
echo "Started PID=$!"
echo "Monitor: ./scripts/monitor_10v2_fastercap.sh 6v2_typ"
echo "Verify:  grep '^Command:' ${LOG} | head -1"
