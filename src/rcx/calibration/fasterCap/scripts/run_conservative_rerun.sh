#!/usr/bin/env bash
set -euo pipefail

# Conservative targeted rerun for FasterCap calibration.
# - Defaults to rerun_near_layer_cases.list (not full 547 cases)
# - Resume-friendly
# - Auto sync successful wires_a*.log to wires.log for parse
#
# Usage:
#   cd tools/OpenROAD/src/rcx/calibration/fasterCap
#   scripts/run_conservative_rerun.sh
#
# Common overrides:
#   CASE_LIST=rerun_near_layer_cases.list OUT_CSV=rerun_conservative_results.csv scripts/run_conservative_rerun.sh
#   RESUME=0 scripts/run_conservative_rerun.sh
#   A_VALUE=0.2 FASTER_CAP_TIME_LIMIT=120 scripts/run_conservative_rerun.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
cd "${ROOT_DIR}"

RUN_DIR="${RUN_DIR:-5v2_typ}"
CASE_LIST="${CASE_LIST:-rerun_near_layer_cases.list}"
OUT_CSV="${OUT_CSV:-rerun_conservative_results.csv}"
RESUME="${RESUME:-1}"
A_VALUE="${A_VALUE:-0.2}"
STD_NORMAL="${STD_NORMAL:-standard}"
EXT="${EXT:-20}"

export FASTER_CAP_SANITIZE_GEOM="${FASTER_CAP_SANITIZE_GEOM:-1}"
export FASTER_CAP_TIME_LIMIT="${FASTER_CAP_TIME_LIMIT:-120}"
export FASTER_CAP_EXTRA_ARGS="${FASTER_CAP_EXTRA_ARGS:--m0.5 -mc1 -pj -t0.1}"

SWEEP_SCRIPT="${ROOT_DIR}/scripts/run_single_pattern_sweep.bash"
CONVERTER_SCRIPT="${ROOT_DIR}/scripts/UniversalFormat2FasterCap_923.py"
FASTERCAP_BIN="${ROOT_DIR}/bin/FasterCap"

for req in "${SWEEP_SCRIPT}" "${CONVERTER_SCRIPT}" "${FASTERCAP_BIN}" "${CASE_LIST}"; do
  if [[ ! -e "${req}" ]]; then
    echo "ERROR: required file missing: ${req}" >&2
    exit 2
  fi
done

init_or_resume_csv() {
  local out_csv="$1"
  local mode_resume="$2"
  local done_n=0
  if [[ "${mode_resume}" == "1" && -f "${out_csv}" ]]; then
    done_n=$(( $(wc -l < "${out_csv}") - 1 ))
    if (( done_n < 0 )); then
      done_n=0
    fi
  else
    echo "case,a,state,log" > "${out_csv}"
    done_n=0
  fi
  echo "${done_n}"
}

sync_logs_for_parse() {
  local in_csv="$1"
  local target_name="${2:-wires.log}"
  TARGET_NAME="${target_name}" INPUT_CSV="${in_csv}" python3 - <<'PY'
import csv
import os
from pathlib import Path

root = Path(".")
run_dir = root / "5v2_typ"
inp = root / os.environ["INPUT_CSV"]
target_name = os.environ.get("TARGET_NAME", "wires.log")
updated = 0
missing = 0
empty = 0

if inp.exists():
    with inp.open() as fp:
        for r in csv.DictReader(fp):
            if r.get("state") != "ok":
                continue
            case = (r.get("case") or "").strip()
            if not case:
                continue
            logn = (r.get("log") or "wires_a0p2.log").strip() or "wires_a0p2.log"
            src = run_dir / case / logn
            dst = run_dir / case / target_name
            if not src.exists():
                missing += 1
                continue
            if src.stat().st_size == 0:
                empty += 1
                continue
            dst.write_bytes(src.read_bytes())
            updated += 1

print(f"sync_updated={updated} sync_missing_src={missing} sync_empty_src={empty} target={target_name}")
PY
}

done_n="$(init_or_resume_csv "${OUT_CSV}" "${RESUME}")"
total="$(awk 'NF>0 {c+=1} END {print c+0}' "${CASE_LIST}")"
remain=$(( total - done_n ))
if (( remain < 0 )); then remain=0; fi

echo "== conservative rerun start"
echo "== list=${CASE_LIST} total=${total} done=${done_n} remain=${remain}"
echo "== run_dir=${RUN_DIR} a=${A_VALUE} ext=${EXT} sanitize=${FASTER_CAP_SANITIZE_GEOM} timeout=${FASTER_CAP_TIME_LIMIT}"
echo "== extra_args=${FASTER_CAP_EXTRA_ARGS}"

idx=0
while IFS= read -r case_rel; do
  [[ -z "${case_rel}" ]] && continue
  idx=$(( idx + 1 ))
  if (( idx <= done_n )); then
    continue
  fi

  echo "== (${idx}/${total}) RUN ${case_rel}"
  set +e
  "${SWEEP_SCRIPT}" "${RUN_DIR}" "${case_rel}" "${CONVERTER_SCRIPT}" "${FASTERCAP_BIN}" "${A_VALUE}" "${STD_NORMAL}" "${EXT}"
  sweep_rc=$?
  set -e

  status_csv="${RUN_DIR}/${case_rel}/sweep_status.csv"
  state=""
  logf=""
  if [[ -f "${status_csv}" ]]; then
    state="$(awk -F, 'NR==2{print $2}' "${status_csv}")"
    logf="$(awk -F, 'NR==2{print $3}' "${status_csv}")"
  fi
  if [[ -z "${state}" ]]; then
    state="failed_script_rc${sweep_rc}"
  fi
  if [[ -z "${logf}" ]]; then
    logf="n/a"
  fi
  echo "${case_rel},${A_VALUE},${state},${logf}" >> "${OUT_CSV}"
  echo "== (${idx}/${total}) DONE ${case_rel} => ${state}"
done < "${CASE_LIST}"

sync_logs_for_parse "${OUT_CSV}" "wires.log"

echo "== conservative rerun done"
echo "== results: ${OUT_CSV}"
awk -F, 'NR>1{cnt[$3]++} END{for (k in cnt) print "state["k"]="cnt[k]}' "${OUT_CSV}" | sort

