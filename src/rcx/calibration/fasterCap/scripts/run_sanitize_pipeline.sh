#!/usr/bin/env bash
set -euo pipefail

# One-click sanitize pipeline for FasterCap calibration.
# Stages:
#   1) optional precheck (precheck_patterns.py)
#   2) run 10 priority cases
#   3) run 367 remaining cases
#   4) sync selected solver logs back to parse input log name
#   5) summarize states + failed list + timing stats
#
# Default behavior is resume-friendly:
#   - if output CSV exists, continue from the next unfinished case
#   - set RESUME=0 to restart a stage from scratch
#
# Usage:
#   cd ~/OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fasterCap
#   scripts/run_sanitize_pipeline.sh
#
# Common overrides:
#   RUN_PRECHECK=0 scripts/run_sanitize_pipeline.sh
#   RESUME=0 RUN_PHASE1=0 RUN_PHASE2=1 scripts/run_sanitize_pipeline.sh
#   A_VALUE=0.2 EXT=20 FASTER_CAP_TIME_LIMIT=90 scripts/run_sanitize_pipeline.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
cd "${ROOT_DIR}"

# ----- Config (override by env vars) -----
RUN_DIR="${RUN_DIR:-5v2_typ}"
CORNER="${CORNER:-TYP}"
STD_NORMAL="${STD_NORMAL:-standard}"
EXT="${EXT:-20}"
A_VALUE="${A_VALUE:-0.2}"
RESUME="${RESUME:-1}"

RUN_PRECHECK="${RUN_PRECHECK:-1}"
RUN_PHASE1="${RUN_PHASE1:-1}"
RUN_PHASE2="${RUN_PHASE2:-1}"

PRECHECK_MAX_CASES="${PRECHECK_MAX_CASES:-0}"
PRECHECK_OUT="${PRECHECK_OUT:-precheck_pathology_report.csv}"

PHASE1_LIST="${PHASE1_LIST:-batch_m4o2_after_sanitize_v3.csv}"
PHASE2_LIST="${PHASE2_LIST:-cases_other_than10.txt}"
PHASE1_OUT="${PHASE1_OUT:-batch_10cases_sanitize_v3_results.csv}"
PHASE2_OUT="${PHASE2_OUT:-batch_others367_sanitize_v3_results.csv}"

PIPELINE_SUMMARY="${PIPELINE_SUMMARY:-sanitize_pipeline_summary.txt}"
FAILED_LIST_OUT="${FAILED_LIST_OUT:-sanitize_failed_cases.list}"
OK_TIMES_CSV="${OK_TIMES_CSV:-ok_pattern_times.csv}"
OK_TIMES_SUMMARY="${OK_TIMES_SUMMARY:-ok_pattern_times_summary.txt}"
SYNC_PARSE_LOGS="${SYNC_PARSE_LOGS:-1}"
PARSE_LOG_TARGET_NAME="${PARSE_LOG_TARGET_NAME:-wires.log}"

# Solver knobs (same defaults as your current sanitize-v3 batch)
export FASTER_CAP_SANITIZE_GEOM="${FASTER_CAP_SANITIZE_GEOM:-1}"
export FASTER_CAP_TIME_LIMIT="${FASTER_CAP_TIME_LIMIT:-90}"
export FASTER_CAP_EXTRA_ARGS="${FASTER_CAP_EXTRA_ARGS:--m0.5 -mc1 -pj -t0.1}"
# keep script default behavior for -g/-ap when not explicitly set

SWEEP_SCRIPT="${ROOT_DIR}/scripts/run_single_pattern_sweep.bash"
CONVERTER_SCRIPT="${ROOT_DIR}/scripts/UniversalFormat2FasterCap_923.py"
FASTERCAP_BIN="${ROOT_DIR}/bin/FasterCap"
PRECHECK_SCRIPT="${ROOT_DIR}/scripts/precheck_patterns.py"

for req in "${SWEEP_SCRIPT}" "${CONVERTER_SCRIPT}" "${FASTERCAP_BIN}" "${PRECHECK_SCRIPT}"; do
  if [[ ! -e "${req}" ]]; then
    echo "ERROR: required file missing: ${req}" >&2
    exit 2
  fi
done

run_precheck() {
  echo "== [precheck] start"
  local cmd=(python3 "${PRECHECK_SCRIPT}" --run-dir "${RUN_DIR}" --corner "${CORNER}" --output-csv "${PRECHECK_OUT}")
  if [[ "${PRECHECK_MAX_CASES}" != "0" ]]; then
    cmd+=(--max-cases "${PRECHECK_MAX_CASES}")
  fi
  "${cmd[@]}"
  echo "== [precheck] done: ${PRECHECK_OUT}"
}

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

run_list_phase() {
  local phase_name="$1"
  local list_file="$2"
  local out_csv="$3"
  local list_has_header="$4"  # 1/0

  if [[ ! -f "${list_file}" ]]; then
    echo "ERROR: list file not found: ${list_file}" >&2
    return 1
  fi

  local done_n
  done_n="$(init_or_resume_csv "${out_csv}" "${RESUME}")"

  local list_tmp
  list_tmp="$(mktemp)"
  if [[ "${list_has_header}" == "1" ]]; then
    awk -F, 'NR>1 && $1!="" {print $1}' "${list_file}" > "${list_tmp}"
  else
    awk 'NF>0 {print $1}' "${list_file}" > "${list_tmp}"
  fi

  local total
  total="$(wc -l < "${list_tmp}")"
  local remain=$(( total - done_n ))
  if (( remain < 0 )); then
    remain=0
  fi
  echo "== [${phase_name}] total=${total} done=${done_n} remain=${remain}"

  local idx=0
  while IFS= read -r case_rel; do
    idx=$(( idx + 1 ))
    if (( idx <= done_n )); then
      continue
    fi
    [[ -z "${case_rel}" ]] && continue

    echo "== [${phase_name}] (${idx}/${total}) RUN ${case_rel}"
    set +e
    "${SWEEP_SCRIPT}" "${RUN_DIR}" "${case_rel}" "${CONVERTER_SCRIPT}" "${FASTERCAP_BIN}" "${A_VALUE}" "${STD_NORMAL}" "${EXT}"
    local sweep_rc=$?
    set -e

    local status_csv="${RUN_DIR}/${case_rel}/sweep_status.csv"
    local state=""
    local logf=""
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
    echo "${case_rel},${A_VALUE},${state},${logf}" >> "${out_csv}"
    echo "== [${phase_name}] DONE ${case_rel} => ${state}"
  done < "${list_tmp}"

  rm -f "${list_tmp}"
}

sync_logs_for_parse() {
  local target_name="$1"
  echo "== [sync] start: copying successful run logs to ${target_name}"
  TARGET_NAME="${target_name}" python3 - <<'PY'
import csv
import os
from pathlib import Path

root = Path(".")
run_dir = root / "5v2_typ"
inputs = [
    root / "batch_10cases_sanitize_v3_results.csv",
    root / "batch_others367_sanitize_v3_results.csv",
]
updated = 0
missing = 0
empty = 0

target_name = os.environ.get("TARGET_NAME", "wires.log")
for f in inputs:
    if not f.exists():
        continue
    with f.open() as fp:
        for r in csv.DictReader(fp):
            if r.get("state") != "ok":
                continue
            case = (r.get("case") or "").strip()
            if not case:
                continue
            logn = (r.get("log") or "wires_a0p2.log").strip() or "wires_a0p2.log"
            case_dir = run_dir / case
            src = case_dir / logn
            dst = case_dir / target_name
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
  echo "== [sync] done"
}

write_state_summary() {
  local in_csv="$1"
  local label="$2"
  if [[ ! -f "${in_csv}" ]]; then
    echo "${label}: missing (${in_csv})"
    return
  fi
  awk -F, -v label="${label}" '
    NR==1 {next}
    {cnt[$3]++}
    END {
      printf "%s", label
      for (k in cnt) printf " %s=%d", k, cnt[k]
      printf "\n"
    }
  ' "${in_csv}"
}

build_timing_artifacts() {
  python3 - <<'PY'
import csv
import statistics
from pathlib import Path
import re

root = Path(".")
inputs = [root / "batch_10cases_sanitize_v3_results.csv", root / "batch_others367_sanitize_v3_results.csv"]
time_re = re.compile(r"^Total time:\s*([0-9.]+)s")
rows = []
for f in inputs:
    if not f.exists():
        continue
    with f.open() as fp:
        for r in csv.DictReader(fp):
            if r.get("state") != "ok":
                continue
            case = r["case"]
            log_name = r.get("log", "wires_a0p2.log")
            log_path = root / "5v2_typ" / case / log_name
            if not log_path.exists():
                rows.append((case, "", "missing_log"))
                continue
            sec = ""
            for line in log_path.read_text(errors="ignore").splitlines():
                m = time_re.match(line.strip())
                if m:
                    sec = m.group(1)
            if sec:
                rows.append((case, sec, "ok"))
            else:
                rows.append((case, "", "no_total_time"))

out_csv = root / "ok_pattern_times.csv"
with out_csv.open("w", newline="") as fp:
    w = csv.writer(fp)
    w.writerow(["case", "total_time_sec", "parse_state"])
    w.writerows(rows)

vals = sorted(float(r[1]) for r in rows if r[2] == "ok" and r[1])
summary = root / "ok_pattern_times_summary.txt"
with summary.open("w") as fp:
    if not vals:
        fp.write("no valid data\n")
    else:
        p95 = vals[int(0.95 * (len(vals) - 1))]
        fp.write(
            "count={count} min={minv:.6f}s median={med:.6f}s mean={mean:.6f}s p95={p95:.6f}s max={maxv:.6f}s\n".format(
                count=len(vals),
                minv=vals[0],
                med=statistics.median(vals),
                mean=statistics.mean(vals),
                p95=p95,
                maxv=vals[-1],
            )
        )
PY
}

build_failed_list() {
  {
    if [[ -f "${PHASE1_OUT}" ]]; then
      awk -F, 'NR>1 && $3!="ok" {print $1}' "${PHASE1_OUT}"
    fi
    if [[ -f "${PHASE2_OUT}" ]]; then
      awk -F, 'NR>1 && $3!="ok" {print $1}' "${PHASE2_OUT}"
    fi
  } | awk 'NF>0' | sort -u > "${FAILED_LIST_OUT}"
}

write_pipeline_summary() {
  {
    echo "sanitize pipeline summary"
    echo "run_dir=${RUN_DIR} corner=${CORNER} a=${A_VALUE} std_normal=${STD_NORMAL} ext=${EXT}"
    echo "sanitize=${FASTER_CAP_SANITIZE_GEOM} time_limit=${FASTER_CAP_TIME_LIMIT} extra_args=${FASTER_CAP_EXTRA_ARGS}"
    echo "sync_parse_logs=${SYNC_PARSE_LOGS} parse_log_target_name=${PARSE_LOG_TARGET_NAME}"
    [[ -f "${PRECHECK_OUT}" ]] && echo "precheck_csv=${PRECHECK_OUT}"
    write_state_summary "${PHASE1_OUT}" "phase1(10cases):"
    write_state_summary "${PHASE2_OUT}" "phase2(others):"
    if [[ -f "${FAILED_LIST_OUT}" ]]; then
      echo "failed_cases=$(wc -l < "${FAILED_LIST_OUT}") list=${FAILED_LIST_OUT}"
    fi
    if [[ -f "${OK_TIMES_SUMMARY}" ]]; then
      echo "timing: $(tr -d '\n' < "${OK_TIMES_SUMMARY}")"
    fi
  } > "${PIPELINE_SUMMARY}"
}

echo "== pipeline start @ ${ROOT_DIR}"
echo "== config: RUN_PRECHECK=${RUN_PRECHECK} RUN_PHASE1=${RUN_PHASE1} RUN_PHASE2=${RUN_PHASE2} RESUME=${RESUME}"
echo "== config: SYNC_PARSE_LOGS=${SYNC_PARSE_LOGS} PARSE_LOG_TARGET_NAME=${PARSE_LOG_TARGET_NAME}"

if [[ "${RUN_PRECHECK}" == "1" ]]; then
  run_precheck
fi

if [[ "${RUN_PHASE1}" == "1" ]]; then
  run_list_phase "phase1" "${PHASE1_LIST}" "${PHASE1_OUT}" "1"
fi

if [[ "${RUN_PHASE2}" == "1" ]]; then
  run_list_phase "phase2" "${PHASE2_LIST}" "${PHASE2_OUT}" "0"
fi

if [[ "${SYNC_PARSE_LOGS}" == "1" ]]; then
  if [[ "${PARSE_LOG_TARGET_NAME}" != "wires.log" ]]; then
    echo "ERROR: current sync helper supports PARSE_LOG_TARGET_NAME=wires.log only." >&2
    exit 2
  fi
  sync_logs_for_parse "${PARSE_LOG_TARGET_NAME}"
fi

build_failed_list
build_timing_artifacts
write_pipeline_summary

echo "== pipeline done"
echo "summary: ${PIPELINE_SUMMARY}"
echo "failed : ${FAILED_LIST_OUT}"
echo "timing : ${OK_TIMES_CSV} / ${OK_TIMES_SUMMARY}"
