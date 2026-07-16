#!/usr/bin/env bash
# Generate 6v2 wire_cnt=5 patterns with configurable w_list / s_list.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

RUN_DIR="${RUN_DIR:-6v2_typ_wirefix}"
W_LIST="${W_LIST:-1}"
S_LIST="${S_LIST:-1.0 1.5 2.0 3 5 6 7 8 9 10}"
WIRE_CNT="${WIRE_CNT:-5}"
VERSION="${VERSION:-2}"
LEN="${LEN:-10}"
PROCESS="${PROCESS:-${FC_DIR}/data/process.TYP}"
CORNER="${CORNER:-TYP}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -f "${PROCESS}" ]] || die "process file missing: ${PROCESS}"

FC_ABS="/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fastercap_sky130hd"
PROCESS_REL="${PROCESS#${REPO_ROOT}/}"
[[ "${PROCESS_REL}" != "${PROCESS}" ]] || die "PROCESS must be inside repository: ${PROCESS}"
PROCESS_DOCKER="/OpenROAD-flow-scripts/${PROCESS_REL}"
mkdir -p "${FC_DIR}/${RUN_DIR}"

cat > "${FC_DIR}/${RUN_DIR}/tmp_gen_patterns.tcl" <<EOF
cd ${FC_ABS}/${RUN_DIR}
gen_solver_patterns -process_file ${PROCESS_DOCKER} -process_name ${CORNER} \\
  -wire_cnt ${WIRE_CNT} -version ${VERSION} -len ${LEN} \\
  -w_list "${W_LIST}" -s_list "${S_LIST}"
EOF

echo "==> RUN_DIR=${RUN_DIR}"
echo "    len=${LEN}  w_list='${W_LIST}'  s_list='${S_LIST}'"
echo "    (max spacing mult = last s_list entry)"

docker run --rm -v "${REPO_ROOT}:/OpenROAD-flow-scripts" \
  -w "/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fastercap_sky130hd" \
  openroad-gui:local bash -lc \
  'source /OpenROAD-flow-scripts/env.sh && \
   /OpenROAD-flow-scripts/tools/OpenROAD/build/bin/openroad \
   -exit '"${RUN_DIR}"'/tmp_gen_patterns.tcl' \
  > "${FC_DIR}/${RUN_DIR}/${CORNER}.log" 2>&1

docker run --rm -v "${REPO_ROOT}:/OpenROAD-flow-scripts" \
  openroad-gui:local chown -R "$(id -u):$(id -g)" \
  "/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fastercap_sky130hd/${RUN_DIR}" \
  2>/dev/null || true

grep "Finished .* patterns" "${FC_DIR}/${RUN_DIR}/${CORNER}.log" || {
  tail -30 "${FC_DIR}/${RUN_DIR}/${CORNER}.log" >&2
  die "pattern generation failed"
}

wire_cnt_out="$(find "${FC_DIR}/${RUN_DIR}" -name wires | wc -l | tr -d ' ')"
echo "OK: ${RUN_DIR} -> ${wire_cnt_out} wires files"
