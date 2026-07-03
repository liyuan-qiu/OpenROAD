#!/usr/bin/env bash
# Progressive FasterCap run for ICT patterns:
# 1) smoke subset
# 2) full ALL on same RUN_DIR (incremental; keeps smoke results)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

RUN_DIR="${RUN_DIR:-6v2_typ_ict_smoke}"
OUT_TAG="${OUT_TAG:-ict_smoke2all_$(date +%Y%m%d_%H%M%S)}"
SMOKE_PATTERN="${SMOKE_PATTERN:-M1oM0}"
STD_NORMAL="${STD_NORMAL:-standard}"
EXT="${EXT:-20}"

TIME_LIMIT="${FASTER_CAP_TIME_LIMIT:-1200}"
CHECK_INTERVAL="${FASTER_CAP_CHECK_INTERVAL:-30}"
PROFILE="${FASTER_CAP_PROFILE:-optimized}"
FORCE="${FASTER_CAP_FORCE_RERUN:-0}"

LOG="${LOG:-${FC_DIR}/typ_fastercap_${OUT_TAG}.log}"

cd "${FC_DIR}"

if pgrep -f "[r]un_fasterCap.bash ${RUN_DIR}" >/dev/null; then
  echo "ERROR: FasterCap already running for ${RUN_DIR}" >&2
  echo "  pgrep -af 'run_fasterCap.bash ${RUN_DIR}'" >&2
  exit 1
fi

[[ -d "${RUN_DIR}" ]] || {
  echo "ERROR: missing ${RUN_DIR}" >&2
  echo "hint: generate patterns first, e.g. RUN_DIR=6v2_typ_ict_smoke via generate_process_sky130hd.sh" >&2
  exit 1
}
[[ -f "${RUN_DIR}/process.out" ]] || { echo "ERROR: missing ${RUN_DIR}/process.out" >&2; exit 1; }
[[ -x "${FC_DIR}/bin/FasterCap" ]] || { echo "ERROR: missing executable ${FC_DIR}/bin/FasterCap" >&2; exit 1; }
[[ -f "${FC_DIR}/scripts/UniversalFormat2FasterCap_923.py" ]] || { echo "ERROR: missing converter script" >&2; exit 1; }

echo "==> Progressive FasterCap for ${RUN_DIR}"
echo "    OUT_TAG=${OUT_TAG}"
echo "    smoke pattern=${SMOKE_PATTERN}"
echo "    log=${LOG}"
echo "    profile=${PROFILE} time_limit=${TIME_LIMIT}s check_interval=${CHECK_INTERVAL}s"

export FASTER_CAP_PROFILE="${PROFILE}"
export FASTER_CAP_TIME_LIMIT="${TIME_LIMIT}"
export FASTER_CAP_CHECK_INTERVAL="${CHECK_INTERVAL}"
export FASTER_CAP_FORCE_RERUN="${FORCE}"

{
  echo "=== [1/2] smoke subset: ${SMOKE_PATTERN} ==="
  bash "${FC_DIR}/scripts/run_fasterCap.bash" \
    "${RUN_DIR}" "${OUT_TAG}_smoke" "${STD_NORMAL}" "${EXT}" "${SMOKE_PATTERN}" \
    "${FC_DIR}/scripts/UniversalFormat2FasterCap_923.py" \
    "${FC_DIR}/bin/FasterCap"

  echo "=== [2/2] full ALL (incremental) ==="
  bash "${FC_DIR}/scripts/run_fasterCap.bash" \
    "${RUN_DIR}" "${OUT_TAG}_all" "${STD_NORMAL}" "${EXT}" "ALL" \
    "${FC_DIR}/scripts/UniversalFormat2FasterCap_923.py" \
    "${FC_DIR}/bin/FasterCap"

  echo "=== DONE ==="
} > "${LOG}" 2>&1

echo "Completed. log: ${LOG}"

