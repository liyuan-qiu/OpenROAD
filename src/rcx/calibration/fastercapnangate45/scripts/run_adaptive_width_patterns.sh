#!/usr/bin/env bash
set -euo pipefail

# Adaptive pattern generation helper:
# 1) start with a base width multiplier list
# 2) if width multiplier "4" is required but missing, auto-append "4 5"
# 3) run gen_solver_patterns with the final width/spacing lists
#
# Usage:
#   cd tools/OpenROAD/src/rcx/calibration/fastercapnangate45
#   scripts/run_adaptive_width_patterns.sh
#
# Common overrides:
#   RUN_DIR=5v2_typ_wide scripts/run_adaptive_width_patterns.sh
#   BASE_W_LIST="1 1.5 2" REQUESTED_WIDTH_MULTS="4" scripts/run_adaptive_width_patterns.sh
#   S_LIST="0.5 1 1.5 2 3" OVER_DIST=6 UNDER_DIST=6 scripts/run_adaptive_width_patterns.sh
#   OPENROAD_EXEC=../bin/openroad scripts/run_adaptive_width_patterns.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
cd "${ROOT_DIR}"

RUN_DIR="${RUN_DIR:-5v2_typ}"
PROCESS_FILE="${PROCESS_FILE:-${ROOT_DIR}/data/process.TYP}"
PROCESS_NAME="${PROCESS_NAME:-TYP}"
WIRE_CNT="${WIRE_CNT:-5}"
VERSION="${VERSION:-2}"
LEN="${LEN:-10}"
BASE_W_LIST="${BASE_W_LIST:-1 1.5 2}"
REQUESTED_WIDTH_MULTS="${REQUESTED_WIDTH_MULTS:-}"
S_LIST="${S_LIST:-1 1.5 2 3 5}"
OVER_DIST="${OVER_DIST:-4}"
UNDER_DIST="${UNDER_DIST:-4}"
OPENROAD_EXEC="${OPENROAD_EXEC:-openroad}"
FORCE_APPEND_45="${FORCE_APPEND_45:-0}"

normalize_list() {
  # Keep insertion order, remove duplicates.
  awk '
    {
      for (i = 1; i <= NF; i++) {
        if (!seen[$i]++) {
          out = out (out ? " " : "") $i
        }
      }
    }
    END { print out }
  '
}

contains_word() {
  local list="$1"
  local needle="$2"
  for x in ${list}; do
    if [[ "${x}" == "${needle}" ]]; then
      return 0
    fi
  done
  return 1
}

final_w_list="$(printf '%s\n' "${BASE_W_LIST}" | normalize_list)"

need_add_45=0
if [[ "${FORCE_APPEND_45}" == "1" ]]; then
  need_add_45=1
else
  for req in ${REQUESTED_WIDTH_MULTS}; do
    if [[ "${req}" == "4" ]]; then
      if ! contains_word "${final_w_list}" "4"; then
        need_add_45=1
      fi
    fi
  done
fi

if [[ "${need_add_45}" == "1" ]]; then
  final_w_list="$(printf '%s\n' "${final_w_list} 4 5" | normalize_list)"
fi

echo "== adaptive width pattern generation"
echo "RUN_DIR=${RUN_DIR}"
echo "PROCESS_FILE=${PROCESS_FILE}"
echo "PROCESS_NAME=${PROCESS_NAME}"
echo "WIRE_CNT=${WIRE_CNT} VERSION=${VERSION} LEN=${LEN}"
echo "BASE_W_LIST=${BASE_W_LIST}"
echo "REQUESTED_WIDTH_MULTS=${REQUESTED_WIDTH_MULTS:-<none>}"
echo "FINAL_W_LIST=${final_w_list}"
echo "S_LIST=${S_LIST}"
echo "OVER_DIST=${OVER_DIST} UNDER_DIST=${UNDER_DIST}"
echo "OPENROAD_EXEC=${OPENROAD_EXEC}"

rm -rf "${RUN_DIR}"
mkdir -p "${RUN_DIR}"
cd "${RUN_DIR}"

cat > tmp_gen_patterns_adaptive.tcl <<EOF
gen_solver_patterns -process_file ${PROCESS_FILE} -process_name ${PROCESS_NAME} -wire_cnt ${WIRE_CNT} -version ${VERSION} -len ${LEN} -w_list "${final_w_list}" -s_list "${S_LIST}" -over_dist ${OVER_DIST} -under_dist ${UNDER_DIST}
EOF

"${OPENROAD_EXEC}" < tmp_gen_patterns_adaptive.tcl > "${PROCESS_NAME}.log"

echo "== done"
echo "generated_dir=${ROOT_DIR}/${RUN_DIR}"
echo "tcl=${ROOT_DIR}/${RUN_DIR}/tmp_gen_patterns_adaptive.tcl"
echo "log=${ROOT_DIR}/${RUN_DIR}/${PROCESS_NAME}.log"

