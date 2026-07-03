#!/usr/bin/env bash
set -euo pipefail

# Re-run the 10 known failing Over5 cases with conservative options:
#   - accuracy: -a0.1
#   - no '-g' flag
# This script does NOT touch other completed cases.
#
# Outputs:
#   - rerun_over5_status.csv
#   - rerun_over5_success.list
#   - rerun_over5_failed.list
#
# Usage:
#   cd /home/liyuanqiu/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fastercapnangate45
#   scripts/rerun_failed_over5_cases.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
TYP_DIR="${ROOT_DIR}/5v2_typ"
BIN="${ROOT_DIR}/bin/FasterCap"
STATUS_CSV="${ROOT_DIR}/rerun_over5_status.csv"
SUCCESS_LIST="${ROOT_DIR}/rerun_over5_success.list"
FAILED_LIST="${ROOT_DIR}/rerun_over5_failed.list"

if [[ ! -x "${BIN}" ]]; then
  echo "Error: FasterCap binary not found/executable: ${BIN}" >&2
  exit 1
fi

declare -a CASES=(
  "TYP/Over5/M3oM2/W0.14_W0.14/S0.14_S0.14_L10"
  "TYP/Over5/M3oM2/W0.14_W0.14/S0.21_S0.21_L10"
  "TYP/Over5/M3oM2/W0.14_W0.14/S0.28_S0.28_L10"
  "TYP/Over5/M3oM2/W0.14_W0.14/S0.42_S0.42_L10"
  "TYP/Over5/M3oM2/W0.14_W0.14/S0.7_S0.7_L10"
  "TYP/Over5/M4oM2/W0.14_W0.14/S0.14_S0.14_L10"
  "TYP/Over5/M4oM2/W0.14_W0.14/S0.21_S0.21_L10"
  "TYP/Over5/M4oM2/W0.14_W0.14/S0.28_S0.28_L10"
  "TYP/Over5/M4oM2/W0.14_W0.14/S0.42_S0.42_L10"
  "TYP/Over5/M4oM2/W0.14_W0.14/S0.7_S0.7_L10"
)

echo "case,exit_code,wires_log_bytes,result" > "${STATUS_CSV}"
: > "${SUCCESS_LIST}"
: > "${FAILED_LIST}"

echo "Re-running ${#CASES[@]} cases with: ${BIN} -b wires.lst -a0.1"

for rel in "${CASES[@]}"; do
  case_dir="${TYP_DIR}/${rel}"
  if [[ ! -d "${case_dir}" ]]; then
    echo "${rel},NA,NA,missing_case_dir" | tee -a "${STATUS_CSV}"
    echo "${rel}" >> "${FAILED_LIST}"
    continue
  fi
  if [[ ! -f "${case_dir}/wires.lst" ]]; then
    echo "${rel},NA,NA,missing_wires_lst" | tee -a "${STATUS_CSV}"
    echo "${rel}" >> "${FAILED_LIST}"
    continue
  fi

  (
    cd "${case_dir}"
    rm -f wires.log
    set +e
    "${BIN}" -b wires.lst -a0.1 > wires.log 2>&1
    ec=$?
    set -e
    bytes=0
    if [[ -f wires.log ]]; then
      bytes=$(wc -c < wires.log | tr -d ' ')
    fi

    if [[ "${ec}" -eq 0 && "${bytes}" -gt 0 ]]; then
      result="ok"
    else
      result="failed"
    fi

    echo "${rel},${ec},${bytes},${result}" >> "${STATUS_CSV}"
    if [[ "${result}" == "ok" ]]; then
      echo "${rel}" >> "${SUCCESS_LIST}"
    else
      echo "${rel}" >> "${FAILED_LIST}"
    fi
  )
done

ok_cnt=$(wc -l < "${SUCCESS_LIST}" | tr -d ' ')
fail_cnt=$(wc -l < "${FAILED_LIST}" | tr -d ' ')

echo
echo "Done."
echo "Success: ${ok_cnt}"
echo "Failed : ${fail_cnt}"
echo "Status : ${STATUS_CSV}"
echo "OK list: ${SUCCESS_LIST}"
echo "NG list: ${FAILED_LIST}"
