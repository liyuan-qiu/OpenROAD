#!/usr/bin/env bash
# Generate 10v2 wire_cnt=5 patterns (M1–M10) with configurable w_list / s_list.
# Aligns with sky130 wirefix + dist2x (see new_rep/docs/nangate45_10m_process_conversion.md §16).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

RUN_DIR="${RUN_DIR:-10v2_typ_wirefix}"
W_LIST="${W_LIST:-1}"
S_LIST="${S_LIST:-1.0 1.5 2.0 3 5 6 7 8 9 10}"
WIRE_CNT="${WIRE_CNT:-5}"
VERSION="${VERSION:-2}"
CORNER="${CORNER:-TYP}"
OPENROAD="${OPENROAD:-${FC_DIR}/scripts/openroad_exec.sh}"

die() { echo "ERROR: $*" >&2; exit 1; }

PROCESS="${FC_DIR}/data/process.TYP"
[[ -f "${PROCESS}" ]] || die "process file missing: ${PROCESS}"
[[ -x "${OPENROAD}" ]] || die "openroad wrapper missing: ${OPENROAD}"

# Docker openroad needs /OpenROAD-flow-scripts/... paths inside Tcl.
FC_ABS="/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fastercapnangate45"
mkdir -p "${FC_DIR}/${RUN_DIR}"

cat > "${FC_DIR}/${RUN_DIR}/tmp_gen_patterns.tcl" <<EOF
cd ${FC_ABS}/${RUN_DIR}
gen_solver_patterns -process_file ${FC_ABS}/data/process.TYP -process_name ${CORNER} \\
  -wire_cnt ${WIRE_CNT} -version ${VERSION} -w_list "${W_LIST}" -s_list "${S_LIST}"
EOF

echo "==> RUN_DIR=${RUN_DIR}"
echo "    w_list='${W_LIST}'  s_list='${S_LIST}'"
echo "    (max spacing mult = last s_list entry)"

"${OPENROAD}" -exit "${FC_ABS}/${RUN_DIR}/tmp_gen_patterns.tcl" \
  > "${FC_DIR}/${RUN_DIR}/${CORNER}.log" 2>&1

grep "Finished .* patterns" "${FC_DIR}/${RUN_DIR}/${CORNER}.log" || {
  tail -30 "${FC_DIR}/${RUN_DIR}/${CORNER}.log" >&2
  die "pattern generation failed"
}

wire_cnt_out="$(find "${FC_DIR}/${RUN_DIR}" -name wires | wc -l | tr -d ' ')"
echo "OK: ${RUN_DIR} -> ${wire_cnt_out} wires files"
