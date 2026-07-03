#!/usr/bin/env bash
# Generate NanGate45 10-metal process.TYP / process.MIN from TECH_LEF + ITF.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

TECH_LEF="${TECH_LEF:-${REPO_ROOT}/flow/platforms/nangate45/lef/NangateOpenCellLibrary.tech.lef}"
ITF="${ITF:-${REPO_ROOT}/flow/PDK/NanGate45-Synopsys-Enablement-main/NanGate45/tlup/NangateOpenCellLibrary.itf}"
DATA_DIR="${DATA_DIR:-${FC_DIR}/data}"
ARCHIVE_DIR="${ARCHIVE_DIR:-${DATA_DIR}/archive/7m_abstract}"
GEN_DIR="${GEN_DIR:-${DATA_DIR}/generated/nangate45_10m}"
INSTALL="${INSTALL:-1}"
VALIDATE="${VALIDATE:-1}"
RUN_DIR="${RUN_DIR:-10v2_typ_smoke}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -f "${TECH_LEF}" ]] || die "TECH_LEF not found: ${TECH_LEF}"
[[ -f "${ITF}" ]] || die "ITF not found: ${ITF}"

mkdir -p "${GEN_DIR}" "${ARCHIVE_DIR}"

echo "==> [1/5] Generate process.TYP / process.MIN (TECH_LEF + ITF)"
python3 "${SCRIPT_DIR}/tech_lef_to_process.py" \
  --tech-lef "${TECH_LEF}" \
  --itf "${ITF}" \
  --all-corners \
  --out-dir "${GEN_DIR}"

is_legacy_process() {
  local file="$1"
  [[ -f "${file}" ]] || return 1
  if grep -qE '^CONDUCTOR M(6M|M7M)' "${file}"; then
    return 0
  fi
  local cnt
  cnt="$(grep -c '^CONDUCTOR M' "${file}" || true)"
  [[ "${cnt}" -lt 10 ]]
}

echo "==> [2/5] Archive legacy 7-metal abstract process files (if needed)"
ts="$(date +%Y%m%d_%H%M%S)"
for f in process.TYP process.MIN; do
  src="${DATA_DIR}/${f}"
  if is_legacy_process "${src}"; then
    cp -a "${src}" "${ARCHIVE_DIR}/${f}.${ts}.bak"
    cp -a "${src}" "${ARCHIVE_DIR}/${f}"
    echo "    archived ${src} -> ${ARCHIVE_DIR}/${f}.${ts}.bak"
  else
    echo "    skip archive for ${src} (already 10-metal or missing)"
  fi
done

if [[ "${INSTALL}" == "1" ]]; then
  echo "==> [3/5] Install generated 10-metal process files"
  cp -a "${GEN_DIR}/process.TYP" "${DATA_DIR}/process.TYP"
  cp -a "${GEN_DIR}/process.MIN" "${DATA_DIR}/process.MIN"
  echo "    installed ${DATA_DIR}/process.TYP"
  echo "    installed ${DATA_DIR}/process.MIN"
else
  echo "==> [3/5] Skip install (INSTALL=0)"
fi

echo "==> [4/5] Sanity checks"
grep -c '^CONDUCTOR M' "${DATA_DIR}/process.TYP" | awk '{ if ($1==10) print "    OK: 10 CONDUCTOR entries in process.TYP"; else { print "    FAIL: expected 10 CONDUCTOR, got " $1; exit 1 } }'
grep -E '^CONDUCTOR M(6M|M7M)' "${DATA_DIR}/process.TYP" && die "legacy M6M/M7M still present" || echo "    OK: no legacy M6M/M7M"
grep -c '^DIELECTRIC ' "${DATA_DIR}/process.TYP" | awk '{ print "    INFO: " $1 " DIELECTRIC entries" }'

if [[ "${VALIDATE}" == "1" ]]; then
  echo "==> [5/5] Validate gen_solver_patterns (smoke run: ${RUN_DIR})"
  rm -rf "${FC_DIR}/${RUN_DIR}"
  if [[ -x "${FC_DIR}/bin/openroad" ]] && "${FC_DIR}/bin/openroad" -version >/dev/null 2>&1; then
    (
      cd "${FC_DIR}"
      ./scripts/gen_patterns.bash "${RUN_DIR}" "${FC_DIR}/bin/openroad" \
        "${DATA_DIR}/process.TYP" TYP 5 2
    ) || die "gen_solver_patterns smoke run failed"
  elif command -v openroad >/dev/null 2>&1; then
    (
      cd "${FC_DIR}"
      ./scripts/gen_patterns.bash "${RUN_DIR}" openroad \
        "${DATA_DIR}/process.TYP" TYP 5 2
    ) || die "gen_solver_patterns smoke run failed"
  elif [[ -x "${REPO_ROOT}/openroad_run.sh" ]]; then
    echo "    using Docker: ${REPO_ROOT}/openroad_run.sh"
    "${REPO_ROOT}/openroad_run.sh" -c \
      "cd tools/OpenROAD/src/rcx/calibration/fastercapnangate45 && ./scripts/gen_patterns.bash ${RUN_DIR} openroad ${DATA_DIR}/process.TYP TYP 5 2" \
      || die "gen_solver_patterns smoke run failed (docker)"
  else
    die "openroad not found; set VALIDATE=0 to skip"
  fi

  pattern_cnt="$(find "${FC_DIR}/${RUN_DIR}" -name wires 2>/dev/null | wc -l | tr -d ' ')"
  echo "    OK: generated ${pattern_cnt} wires files"
  echo "    sample M8/M9/M10 dirs:"
  find "${FC_DIR}/${RUN_DIR}" -type d | grep -E '/M(8|9|10)' | head -5 || true
else
  echo "==> [5/5] Skip validation (VALIDATE=0)"
fi

echo "Done."
