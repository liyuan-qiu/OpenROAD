#!/usr/bin/env bash
# Generate SKY130 HS 6-metal process.TYP / process.MIN from TECH LEF + stack table.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

TECH_LEF="${TECH_LEF:-${REPO_ROOT}/flow/platforms/sky130hs/lef/sky130_fd_sc_hs.tlef}"
ICT_FILE="${ICT_FILE:-}"
DATA_DIR="${DATA_DIR:-${FC_DIR}/data}"
GEN_DIR="${GEN_DIR:-${DATA_DIR}/generated/sky130hs_6m}"
INSTALL="${INSTALL:-1}"
VALIDATE="${VALIDATE:-1}"
RUN_DIR="${RUN_DIR:-6v2_typ_smoke}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -f "${TECH_LEF}" ]] || die "TECH_LEF not found: ${TECH_LEF}"

mkdir -p "${GEN_DIR}"

echo "==> [1/4] Generate process.TYP / process.MIN (SKY130 HS, 6 metals)"
ICT_ARGS=()
if [[ -n "${ICT_FILE}" ]]; then
  [[ -f "${ICT_FILE}" ]] || die "ICT_FILE not found: ${ICT_FILE}"
  ICT_ARGS+=(--ict "${ICT_FILE}")
  echo "    Using ICT: ${ICT_FILE}"
fi

python3 "${SCRIPT_DIR}/tech_lef_to_process_sky130.py" \
  --tech-lef "${TECH_LEF}" \
  --all-corners \
  --out-dir "${GEN_DIR}" \
  "${ICT_ARGS[@]}"

if [[ "${INSTALL}" == "1" ]]; then
  echo "==> [2/4] Install to ${DATA_DIR}"
  cp -a "${GEN_DIR}/process.TYP" "${DATA_DIR}/process.TYP"
  cp -a "${GEN_DIR}/process.MIN" "${DATA_DIR}/process.MIN"
else
  echo "==> [2/4] Skip install (INSTALL=0)"
fi

echo "==> [3/4] Sanity checks"
grep -c '^CONDUCTOR M' "${DATA_DIR}/process.TYP" | awk \
  '{ if ($1==6) print "    OK: 6 CONDUCTOR entries"; else { print "    FAIL: expected 6, got " $1; exit 1 } }'
grep '^CONDUCTOR M' "${DATA_DIR}/process.TYP" | head -6
grep -c '^DIELECTRIC ' "${DATA_DIR}/process.TYP" | awk '{ print "    INFO: " $1 " DIELECTRIC entries" }'

if [[ "${VALIDATE}" == "1" ]]; then
  echo "==> [4/4] Smoke: gen_solver_patterns -> ${RUN_DIR}"
  rm -rf "${FC_DIR}/${RUN_DIR}"
  (
    cd "${FC_DIR}"
    ./scripts/gen_patterns.bash "${RUN_DIR}" ./scripts/openroad_exec.sh \
      "${DATA_DIR}/process.TYP" TYP 5 2
  ) || die "gen_solver_patterns smoke failed"
  pattern_cnt="$(find "${FC_DIR}/${RUN_DIR}" -name wires 2>/dev/null | wc -l | tr -d ' ')"
  echo "    OK: ${pattern_cnt} wires files"
  find "${FC_DIR}/${RUN_DIR}" -type d -name 'M6oM*' 2>/dev/null | head -3 || true
else
  echo "==> [4/4] Skip validation (VALIDATE=0)"
fi

echo "Done."
