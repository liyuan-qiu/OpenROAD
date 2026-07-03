#!/usr/bin/env bash
# Isolated rerun using FreePDK45-v1.4-derived process parameters.
# This script NEVER overwrites existing pattern trees or wires.log outputs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

# Inputs
FREEPDK_ROOT="${FREEPDK_ROOT:-${REPO_ROOT}/flow/PDK/freepdk45-v14/_tmp_extract/FreePDK45}"
CALIBREXRC="${CALIBREXRC:-${FREEPDK_ROOT}/ncsu_basekit/techfile/calibre/calibrexRC.rul}"
RULES_TXT="${RULES_TXT:-${FREEPDK_ROOT}/ncsu_basekit/techfile/rules.txt}"
RPSQ_ITF="${RPSQ_ITF:-${REPO_ROOT}/flow/PDK/NanGate45-Synopsys-Enablement-main/NanGate45/tlup/NangateOpenCellLibrary.itf}"

# Isolated output names
RUN_TAG="${RUN_TAG:-freepdk45v14_$(date +%Y%m%d_%H%M%S)}"
RUN_DIR="${RUN_DIR:-10v2_typ_${RUN_TAG}}"
OUT_PREFIX="${OUT_PREFIX:-${RUN_DIR}_fasterCap}"
PROC_DIR="${PROC_DIR:-${FC_DIR}/data/generated/freepdk45_v14/${RUN_TAG}}"
PROC_TYP="${PROC_DIR}/process.TYP"

# Solver knobs
FASTER_CAP_PROFILE="${FASTER_CAP_PROFILE:-optimized}"
FASTER_CAP_TIME_LIMIT="${FASTER_CAP_TIME_LIMIT:-1200}"
FASTER_CAP_CHECK_INTERVAL="${FASTER_CAP_CHECK_INTERVAL:-30}"
EXT="${EXT:-20}"
PATTERN_FILTER="${PATTERN_FILTER:-ALL}"
FORCE="${FORCE:-0}"
STOP_AFTER_PATTERNS="${STOP_AFTER_PATTERNS:-0}"

die() { echo "ERROR: $*" >&2; exit 1; }

extract_freepdk_if_needed() {
  if [[ -f "${CALIBREXRC}" ]]; then
    return
  fi
  local tarball="${REPO_ROOT}/flow/PDK/freepdk45-v14/ncsu-FreePDK45-1.4.tar.gz"
  [[ -f "${tarball}" ]] || die "Missing ${CALIBREXRC} and tarball ${tarball}"
  echo "==> Extract FreePDK45-v1.4 into _tmp_extract"
  mkdir -p "${REPO_ROOT}/flow/PDK/freepdk45-v14/_tmp_extract"
  tar -xf "${tarball}" -C "${REPO_ROOT}/flow/PDK/freepdk45-v14/_tmp_extract"
  [[ -f "${CALIBREXRC}" ]] || die "calibrexRC still missing after extract: ${CALIBREXRC}"
}

assert_non_overwrite() {
  if [[ "${FORCE}" != "1" ]]; then
    [[ ! -e "${FC_DIR}/${RUN_DIR}" ]] || die "RUN_DIR exists: ${FC_DIR}/${RUN_DIR} (set FORCE=1 to replace)"
    # run_fasterCap writes to out_dir = ${OUT_PREFIX}.standard.${EXT}.${EXT}.0.${PATTERN_FILTER}
    local out_dir="${FC_DIR}/${OUT_PREFIX}.standard.${EXT}.${EXT}.0.${PATTERN_FILTER}"
    [[ ! -e "${out_dir}" ]] || die "OUT dir exists: ${out_dir} (set FORCE=1 to replace)"
  fi
}

echo "==> [0/4] Preconditions"
extract_freepdk_if_needed
[[ -f "${CALIBREXRC}" ]] || die "Missing calibrexRC: ${CALIBREXRC}"
[[ -f "${RULES_TXT}" ]] || die "Missing rules.txt: ${RULES_TXT}"
[[ -f "${RPSQ_ITF}" ]] || die "Missing ITF for RPSQ seed: ${RPSQ_ITF}"
[[ -x "${FC_DIR}/bin/FasterCap" ]] || die "Missing FasterCap binary: ${FC_DIR}/bin/FasterCap"
[[ -x "${SCRIPT_DIR}/gen_patterns.bash" ]] || die "Missing script: gen_patterns.bash"
[[ -x "${SCRIPT_DIR}/run_fasterCap.bash" ]] || die "Missing script: run_fasterCap.bash"
assert_non_overwrite

echo "==> [1/4] Generate isolated process.{TYP,MIN}"
python3 "${SCRIPT_DIR}/freepdk45_v14_calibrexrc_to_process.py" \
  --calibrexrc "${CALIBREXRC}" \
  --rules-txt "${RULES_TXT}" \
  --rpsq-itf "${RPSQ_ITF}" \
  --out-dir "${PROC_DIR}"

echo "==> [2/4] Generate isolated patterns (${RUN_DIR})"
(
  cd "${FC_DIR}"
  if [[ "${FORCE}" == "1" ]]; then
    rm -rf "${RUN_DIR}"
  fi
  "${SCRIPT_DIR}/gen_patterns.bash" "${RUN_DIR}" "${SCRIPT_DIR}/openroad_exec.sh" "${PROC_TYP}" TYP 5 2
)

echo "==> [3/4] Run FasterCap on isolated patterns"
if [[ "${STOP_AFTER_PATTERNS}" == "1" ]]; then
  echo "STOP_AFTER_PATTERNS=1, skip FasterCap run."
  echo "RUN_DIR     : ${FC_DIR}/${RUN_DIR}"
  echo "PROCESS_DIR : ${PROC_DIR}"
  echo "No existing patterns/wires.log were modified."
  exit 0
fi
(
  cd "${FC_DIR}"
  if [[ "${FORCE}" == "1" ]]; then
    rm -rf "${OUT_PREFIX}.standard.${EXT}.${EXT}.0.${PATTERN_FILTER}"
  fi
  FASTER_CAP_PROFILE="${FASTER_CAP_PROFILE}" \
  FASTER_CAP_TIME_LIMIT="${FASTER_CAP_TIME_LIMIT}" \
  FASTER_CAP_CHECK_INTERVAL="${FASTER_CAP_CHECK_INTERVAL}" \
  "${SCRIPT_DIR}/run_fasterCap.bash" \
    "${RUN_DIR}" "${OUT_PREFIX}" standard "${EXT}" "${PATTERN_FILTER}" \
    "${SCRIPT_DIR}/UniversalFormat2FasterCap_923.py" "${FC_DIR}/bin/FasterCap"
)

echo "==> [4/4] Done (isolated outputs only)"
echo "RUN_DIR     : ${FC_DIR}/${RUN_DIR}"
echo "OUT_PREFIX  : ${FC_DIR}/${OUT_PREFIX}.standard.${EXT}.${EXT}.0.${PATTERN_FILTER}"
echo "PROCESS_DIR : ${PROC_DIR}"
echo "No existing patterns/wires.log were modified."
