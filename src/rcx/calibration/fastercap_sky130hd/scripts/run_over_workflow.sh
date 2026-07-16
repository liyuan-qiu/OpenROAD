#!/usr/bin/env bash
# End-to-end SKY130 FasterCap family workflow with fail-fast quality gates.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

LEN="${LEN:-20}"
FAMILY="${FAMILY:-Over5}"
case "${FAMILY}" in
  Over5) FAMILY_LABEL="OVER"; FAMILY_SLUG="over" ;;
  Under5) FAMILY_LABEL="UNDER"; FAMILY_SLUG="under" ;;
  OverUnder5) FAMILY_LABEL="OVER_UNDER"; FAMILY_SLUG="overunder" ;;
  UnderDiag5|DiagUnder5)
    FAMILY="UnderDiag5"
    FAMILY_LABEL="DIAGUNDER"
    FAMILY_SLUG="diagunder"
    ;;
  *) echo "ERROR unsupported FAMILY=${FAMILY}" >&2; exit 2 ;;
esac
if [[ -z "${RUN_DIR:-}" ]]; then
  if [[ "${FAMILY_WORKFLOW_ENTRY:-0}" == "1" ]]; then
    RUN_DIR="6v2_typ_ict_len${LEN}"
  else
    RUN_DIR="6v2_typ_over_len${LEN}"
  fi
fi
RUN_PATH="${FC_DIR}/${RUN_DIR}"
REPORT_DIR="${REPORT_DIR:-${FC_DIR}/workflow_${RUN_DIR}}"
if [[ "${REPORT_DIR}" != /* ]]; then
  REPORT_DIR="${FC_DIR}/${REPORT_DIR}"
fi
W_LIST="${W_LIST:-1}"
S_LIST="${S_LIST:-1.0 1.5 2.0 3 5 6 7 8 9 10}"
STACK="${STACK:-}"
CORNER="${CORNER:-TYP}"
REGENERATE="${REGENERATE:-0}"
FORCE_SOLVER="${FORCE_SOLVER:-0}"
MAX_CASES="${MAX_CASES:-0}"
MAX_ASYM_REL="${MAX_ASYM_REL:-0.10}"
PARSE_RETRIES="${PARSE_RETRIES:-2}"
PARSE_STACK_DELAY="${PARSE_STACK_DELAY:-0.25}"
STRICT_POSTCHECK="${STRICT_POSTCHECK:-1}"
REJECT_POS_OFFDIAG="${REJECT_POS_OFFDIAG:-1}"
REJECT_SIGN_FLIP="${REJECT_SIGN_FLIP:-1}"
WORKFLOW_FROM="${WORKFLOW_FROM:-}"
SKIP_PREFLIGHT_FAILURES="${SKIP_PREFLIGHT_FAILURES:-0}"
SKIP_SOLVER_FAILURES="${SKIP_SOLVER_FAILURES:-0}"
REUSE_SOLVER_FAILURES="${REUSE_SOLVER_FAILURES:-1}"
FASTER_CAP_PROFILE="${FASTER_CAP_PROFILE:-optimized}"
FASTER_CAP_TIME_LIMIT="${FASTER_CAP_TIME_LIMIT:-1800}"
FASTER_CAP_CHECK_INTERVAL="${FASTER_CAP_CHECK_INTERVAL:-1}"
FASTER_CAP_EXTRA_SKIP_LIST="${FASTER_CAP_EXTRA_SKIP_LIST:-}"
FASTER_CAP_LOG_APPEND="${FASTER_CAP_LOG_APPEND:-0}"
REL_THR="${REL_THR:-1e-5}"
ICT_FILE="${ICT_FILE:-}"
PREPARE_ICT="${PREPARE_ICT:-0}"
CG_MODE="${CG_MODE:-a}"
DIAG_CG_MODE="${DIAG_CG_MODE:-full}"
WORKFLOW_NUM_THREADS="${WORKFLOW_NUM_THREADS:-1}"

export MPLBACKEND="${MPLBACKEND:-Agg}"
export OMP_NUM_THREADS="${WORKFLOW_NUM_THREADS}"
export OPENBLAS_NUM_THREADS="${WORKFLOW_NUM_THREADS}"
export MKL_NUM_THREADS="${WORKFLOW_NUM_THREADS}"
export NUMEXPR_NUM_THREADS="${WORKFLOW_NUM_THREADS}"

RULES="${RULES:-${REPO_ROOT}/flow/platforms/sky130hs/rcx_patterns.rules}"
CONVERTER="${FC_DIR}/scripts/UniversalFormat2FasterCap_923.py"
FASTER_CAP="${FC_DIR}/bin/FasterCap"
RUNNER="${FC_DIR}/scripts/run_fasterCap.bash"
PRECHECK="${FC_DIR}/../fastercapnangate45/scripts/precheck_patterns.py"
COMPARE_SCRIPT="${REPO_ROOT}/bench_wires_nangate45_20260710/compare_fastercap_caps_vs_rules.py"
ERROR_SCRIPT="${REPO_ROOT}/bench_wires_nangate45_20260710/analyze_fastercap_vs_rules_errors.py"

STATUS_FILE="${REPORT_DIR}/stage_status.tsv"
SUMMARY="${REPORT_DIR}/summary.md"
CURRENT_STAGE="setup"

mkdir -p "${REPORT_DIR}"
: > "${STATUS_FILE}"
cd "${FC_DIR}"

mark_stage() {
  local stage="$1"
  local status="$2"
  local detail="$3"
  printf '%s\t%s\t%s\n' "${stage}" "${status}" "${detail//$'\t'/ }" >> "${STATUS_FILE}"
}

start_stage() {
  CURRENT_STAGE="$1"
  mark_stage "${CURRENT_STAGE}" RUNNING "$2"
  echo "==> [${CURRENT_STAGE}] $2"
}

pause_between_stacks() {
  if [[ "${PARSE_STACK_DELAY}" != "0" && "${PARSE_STACK_DELAY}" != "0.0" ]]; then
    sleep "${PARSE_STACK_DELAY}"
  fi
}

finalize() {
  local rc=$?
  if [[ "${rc}" -ne 0 ]]; then
    mark_stage "${CURRENT_STAGE}" "FAIL" "workflow exited with status ${rc}"
  fi
  python3 - "${STATUS_FILE}" "${SUMMARY}" "${rc}" "${LEN}" "${RUN_PATH}" \
    "${RULES}" "${STACK}" "${REPORT_DIR}" "${FAMILY}" "${FAMILY_LABEL}" <<'PY'
import sys
from pathlib import Path

status_path, summary_path = map(Path, sys.argv[1:3])
rc, length = int(sys.argv[3]), int(sys.argv[4])
run_path, rules = sys.argv[5], sys.argv[6]
stack, report_dir = sys.argv[7], Path(sys.argv[8])
family, family_label = sys.argv[9], sys.argv[10]

latest = {}
order = []
for line in status_path.read_text(errors="replace").splitlines():
    parts = line.split("\t", 2)
    if len(parts) != 3:
        continue
    stage, status, detail = parts
    if stage not in latest:
        order.append(stage)
    latest[stage] = (status, detail)

lines = [
    f"# SKY130 {family_label} FasterCap workflow — L{length}",
    "",
    f"- Overall status: **{'PASS' if rc == 0 else 'FAIL'}**",
    f"- Run directory: `{run_path}`",
    f"- Rules: `{rules}`",
    f"- Stack scope: `{stack or ('ALL ' + family)}`",
    "",
    "## Stage gates",
    "",
    "| stage | status | detail |",
    "|-------|--------|--------|",
]
for stage in order:
    status, detail = latest[stage]
    lines.append(f"| {stage} | **{status}** | {detail} |")

lines += [
    "",
    "## Artifacts",
    "",
    f"- Source geometry: `{report_dir / 'source_geometry.csv'}`",
    f"- Converter/overlap precheck: `{report_dir / 'converter_overlap_precheck.csv'}`",
    f"- Preflight skip list: `{report_dir / 'skipped_preflight.txt'}`",
    f"- Runtime solver failures: `{report_dir / 'failed_solver.txt'}`",
    f"- Solver completeness: `{report_dir / 'solver_completeness.csv'}`",
    f"- Matrix symmetry: `{report_dir / 'symmetry_summary.txt'}`",
    f"- Matrix details: `{report_dir / 'symmetry_full.csv'}`",
    f"- Parse failures: `{report_dir / 'failed_parse_stacks.txt'}`",
    f"- Compare/plot failures: `{report_dir / 'failed_compare_stacks.txt'}`",
    f"- Per-pattern rules plots: `{report_dir / 'compare_rules'}`",
    f"- Error analysis: `{report_dir / 'error_analysis'}`",
]

error_summary = report_dir / "error_analysis" / "summary.md"
if error_summary.is_file():
    lines += ["", "## Rules comparison", "", error_summary.read_text(errors="replace")]

summary_path.write_text("\n".join(lines) + "\n")
print(f"workflow summary: {summary_path}")
PY
  exit "${rc}"
}
trap finalize EXIT

require_file() {
  [[ -f "$1" ]] || { echo "ERROR missing file: $1" >&2; return 2; }
}

_workflow_stage_num() {
  case "$1" in
    setup) echo 1 ;;
    process_ict) echo 2 ;;
    generate_patterns) echo 3 ;;
    source_geometry) echo 4 ;;
    converter_overlap) echo 5 ;;
    fastercap) echo 6 ;;
    solver_completeness) echo 7 ;;
    matrix_quality) echo 8 ;;
    parse) echo 9 ;;
    compare) echo 10 ;;
    error_analysis) echo 11 ;;
    complete) echo 12 ;;
    *) echo 0 ;;
  esac
}

_workflow_from_num() {
  if [[ -z "${WORKFLOW_FROM}" ]]; then
    echo 1
    return
  fi
  local num
  num="$(_workflow_stage_num "${WORKFLOW_FROM}")"
  if [[ "${num}" == "0" ]]; then
    echo "ERROR unknown WORKFLOW_FROM=${WORKFLOW_FROM}" >&2
    exit 2
  fi
  echo "${num}"
}

_should_run_stage() {
  local stage="$1"
  [[ "$(_workflow_stage_num "${stage}")" -ge "$(_workflow_from_num)" ]]
}

_skip_stage() {
  mark_stage "$1" SKIP "$2"
}

_parse_gate_args() {
  PARSE_GATE_ARGS=(--max-asym-rel "${MAX_ASYM_REL}")
  if [[ "${REJECT_POS_OFFDIAG}" == "1" ]]; then
    PARSE_GATE_ARGS+=(--reject-pos-offdiag)
  fi
  if [[ "${REJECT_SIGN_FLIP}" == "1" ]]; then
    PARSE_GATE_ARGS+=(--reject-sign-flip)
  fi
}
_parse_gate_args

_quality_check_args() {
  QUALITY_ARGS=(
    --root "${RUN_PATH}"
    --out-prefix "${REPORT_DIR}/symmetry"
    --only-pattern-type "${FAMILY}"
    --max-rel "${MAX_ASYM_REL}"
    --skip-list "${SKIP_LIST}"
  )
  if [[ "${REJECT_POS_OFFDIAG}" == "1" ]]; then
    QUALITY_ARGS+=(--reject-pos-offdiag)
  else
    QUALITY_ARGS+=(--no-reject-pos-offdiag)
  fi
  if [[ "${REJECT_SIGN_FLIP}" == "1" ]]; then
    QUALITY_ARGS+=(--reject-sign-flip)
  else
    QUALITY_ARGS+=(--no-reject-sign-flip)
  fi
  if [[ "${STRICT_POSTCHECK}" == "1" ]]; then
    QUALITY_ARGS+=(--check)
  fi
}

start_stage setup "checking required tools and inputs"
[[ "${PARSE_STACK_DELAY}" =~ ^[0-9]+([.][0-9]+)?$ ]] \
  || { echo "ERROR PARSE_STACK_DELAY must be a non-negative number" >&2; exit 2; }
[[ "${WORKFLOW_NUM_THREADS}" =~ ^[1-9][0-9]*$ ]] \
  || { echo "ERROR WORKFLOW_NUM_THREADS must be a positive integer" >&2; exit 2; }
if _should_run_stage process_ict && [[ "${PREPARE_ICT}" == "1" ]]; then
  if [[ -n "${ICT_FILE}" ]]; then
    require_file "${ICT_FILE}"
  fi
elif _should_run_stage generate_patterns; then
  require_file "${FC_DIR}/data/process.TYP"
fi
[[ -d "${RUN_PATH}" ]] || { echo "ERROR missing RUN_DIR: ${RUN_PATH}" >&2; exit 2; }
require_file "${RULES}"
require_file "${COMPARE_SCRIPT}"
require_file "${ERROR_SCRIPT}"
if _should_run_stage converter_overlap; then
  require_file "${CONVERTER}"
  require_file "${PRECHECK}"
fi
if _should_run_stage fastercap; then
  require_file "${FASTER_CAP}"
  require_file "${RUNNER}"
fi
mark_stage setup PASS "all required tools and inputs found"

if _should_run_stage process_ict; then
if [[ "${PREPARE_ICT}" == "1" ]]; then
  if [[ -n "${ICT_FILE}" ]]; then
    start_stage process_ict "generating process.TYP/MIN from ICT"
    process_detail="installed ICT-derived process.TYP/MIN"
  else
    start_stage process_ict "generating process.TYP/MIN (built-in, no ICT)"
    process_detail="installed built-in no-ICT process.TYP/MIN"
  fi
  GEN_DIR="${GEN_DIR:-${FC_DIR}/data/generated/sky130hs_6m_no_ict}" \
    ICT_FILE="${ICT_FILE}" VALIDATE=0 \
    "${FC_DIR}/scripts/generate_process_sky130hd.sh" \
    > "${REPORT_DIR}/process_ict.log" 2>&1
  require_file "${FC_DIR}/data/process.TYP"
  if [[ -d "${RUN_PATH}" ]]; then
    cp -a "${FC_DIR}/data/process.TYP" "${RUN_PATH}/process.out"
  fi
  mark_stage process_ict PASS "${process_detail}"
else
  mark_stage process_ict SKIP "reusing installed process.TYP/MIN"
fi
else
  _skip_stage process_ict "WORKFLOW_FROM=${WORKFLOW_FROM}"
fi

if _should_run_stage generate_patterns; then
start_stage generate_patterns "preparing LEN=${LEN} ${FAMILY} patterns"
if [[ "${REGENERATE}" == "1" || ! -d "${RUN_PATH}/${CORNER}/${FAMILY}" ]]; then
  RUN_DIR="${RUN_DIR}" LEN="${LEN}" W_LIST="${W_LIST}" S_LIST="${S_LIST}" \
    CORNER="${CORNER}" "${FC_DIR}/scripts/gen_6v2_typ_patterns.sh" \
    > "${REPORT_DIR}/generate_patterns.log" 2>&1
  mark_stage generate_patterns PASS "generated patterns with LEN=${LEN}"
else
  mark_stage generate_patterns SKIP "reusing existing ${RUN_PATH}"
fi
else
  _skip_stage generate_patterns "WORKFLOW_FROM=${WORKFLOW_FROM}"
fi

SKIP_LIST="${REPORT_DIR}/skipped_preflight.txt"
SOLVER_FAILED_LIST="${REPORT_DIR}/failed_solver.txt"
touch "${SKIP_LIST}"

scope_args=(--run-dir "${RUN_PATH}" --corner "${CORNER}" --family "${FAMILY}" --len-mult "${LEN}")
if [[ -n "${STACK}" ]]; then
  scope_args+=(--stack "${STACK}")
fi
if [[ "${MAX_CASES}" -gt 0 ]]; then
  scope_args+=(--max-cases "${MAX_CASES}")
fi

if _should_run_stage source_geometry; then
start_stage source_geometry "checking five-wire source symmetry"
python3 "${FC_DIR}/scripts/validate_pattern_geometry.py" \
  "${scope_args[@]}" \
  --output-csv "${REPORT_DIR}/source_geometry.csv" \
  > "${REPORT_DIR}/source_geometry.log" 2>&1
expected_cases="$(python3 - "${REPORT_DIR}/source_geometry.csv" <<'PY'
import csv, sys
with open(sys.argv[1], newline="") as stream:
    print(sum(1 for _ in csv.DictReader(stream)))
PY
)"
mark_stage source_geometry PASS "${expected_cases} five-wire cases are geometrically symmetric"
else
  if [[ -f "${REPORT_DIR}/source_geometry.csv" ]]; then
    expected_cases="$(python3 - "${REPORT_DIR}/source_geometry.csv" <<'PY'
import csv, sys
with open(sys.argv[1], newline="") as stream:
    print(sum(1 for _ in csv.DictReader(stream)))
PY
)"
  else
    expected_cases="$(find "${RUN_PATH}/${CORNER}/${FAMILY}" -name wires.log 2>/dev/null | wc -l | tr -d ' ')"
  fi
  _skip_stage source_geometry "WORKFLOW_FROM=${WORKFLOW_FROM}; cached expected_cases=${expected_cases}"
fi

if _should_run_stage converter_overlap; then
start_stage converter_overlap "running converter and dielectric geometry precheck"
python3 "${PRECHECK}" \
  "${scope_args[@]}" \
  --converter "${CONVERTER}" \
  --process-out "${RUN_PATH}/process.out" \
  --output-csv "${REPORT_DIR}/converter_overlap_precheck.csv" \
  > "${REPORT_DIR}/converter_overlap_precheck.log" 2>&1
preflight_skipped="$(python3 - "${REPORT_DIR}/converter_overlap_precheck.csv" "${SKIP_LIST}" <<'PY'
import csv
import sys
from pathlib import Path

report, output = Path(sys.argv[1]), Path(sys.argv[2])
with report.open(newline="") as stream:
    rows = list(csv.DictReader(stream))
skipped = [row["case"] for row in rows if row["risk"] in {"high", "error"}]
output.write_text("".join(f"{case}\n" for case in skipped))
print(len(skipped))
PY
)"
if [[ "${MAX_CASES}" -gt 0 ]]; then
  python3 - "${RUN_PATH}" "${CORNER}" "${FAMILY}" "${LEN}" "${STACK}" \
    "${REPORT_DIR}/source_geometry.csv" "${SKIP_LIST}" <<'PY'
import csv
import sys
from pathlib import Path

root, corner, family, length, stack, selected_csv, skip_path = (
    Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5],
    Path(sys.argv[6]), Path(sys.argv[7])
)
with selected_csv.open(newline="") as stream:
    selected = {
        str(Path(row["case"]).relative_to(root))
        for row in csv.DictReader(stream)
    }
all_cases = {
    str(path.parent.relative_to(root))
    for path in (root / corner / family).rglob("wires")
    if path.parent.name.endswith(f"_L{length}")
    and (not stack or f"/{stack}/" in path.as_posix())
}
existing = {
    line.strip().removeprefix("./")
    for line in skip_path.read_text(errors="replace").splitlines()
    if line.strip()
}
skip_path.write_text(
    "".join(f"{case}\n" for case in sorted(existing | (all_cases - selected)))
)
PY
fi
if [[ "${preflight_skipped}" -gt 0 ]]; then
  if [[ "${SKIP_PREFLIGHT_FAILURES}" != "1" ]]; then
    mark_stage converter_overlap FAIL \
      "${preflight_skipped} high/error case(s); enable SKIP_PREFLIGHT_FAILURES=1 to quarantine"
    exit 2
  fi
  mark_stage converter_overlap PASS \
    "quarantined ${preflight_skipped} high/error case(s); see skipped_preflight.txt"
else
  mark_stage converter_overlap PASS \
    "converter succeeded; no high-risk dielectric-interface overlap candidates"
fi
eligible_cases=$((expected_cases - preflight_skipped))
[[ "${eligible_cases}" -gt 0 ]] || { echo "ERROR: no eligible cases after preflight" >&2; exit 2; }
reused_solver_failed=0
if [[ "${REUSE_SOLVER_FAILURES}" == "1" && -s "${SOLVER_FAILED_LIST}" ]]; then
  reused_solver_failed="$(python3 - "${SKIP_LIST}" "${SOLVER_FAILED_LIST}" <<'PY'
import sys
from pathlib import Path

skip_path, failed_path = map(Path, sys.argv[1:3])
skipped = {
    line.strip().removeprefix("./")
    for line in skip_path.read_text(errors="replace").splitlines()
    if line.strip()
}
failed = {
    line.strip().removeprefix("./")
    for line in failed_path.read_text(errors="replace").splitlines()
    if line.strip()
}
new_failures = failed - skipped
skip_path.write_text("".join(f"{case}\n" for case in sorted(skipped | failed)))
print(len(new_failures))
PY
)"
  eligible_cases=$((eligible_cases - reused_solver_failed))
fi
else
  preflight_skipped="$(wc -l < "${SKIP_LIST}" | tr -d ' ')"
  eligible_cases=$((expected_cases - preflight_skipped))
  reused_solver_failed=0
  _skip_stage converter_overlap "WORKFLOW_FROM=${WORKFLOW_FROM}"
fi

if _should_run_stage fastercap; then
FASTER_CAP_SKIP_LIST_FOR_RUN="${SKIP_LIST}"
if [[ -n "${FASTER_CAP_EXTRA_SKIP_LIST}" && -f "${FASTER_CAP_EXTRA_SKIP_LIST}" ]]; then
  FASTER_CAP_SKIP_LIST_FOR_RUN="${REPORT_DIR}/fastercap_skip_merged.txt"
  resume_extra_skipped="$(python3 - "${SKIP_LIST}" "${FASTER_CAP_EXTRA_SKIP_LIST}" \
    "${FASTER_CAP_SKIP_LIST_FOR_RUN}" <<'PY'
import sys
from pathlib import Path

base_path, extra_path, merged_path = map(Path, sys.argv[1:4])

def load_cases(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        line.strip().removeprefix("./")
        for line in path.read_text(errors="replace").splitlines()
        if line.strip()
    }

base = load_cases(base_path)
extra = load_cases(extra_path)
merged_path.write_text("".join(f"{case}\n" for case in sorted(base | extra)))
print(len(extra - base))
PY
)"
  eligible_cases=$((eligible_cases - resume_extra_skipped))
  echo "==> fastercap resume: skipping ${resume_extra_skipped} extra case(s) from ${FASTER_CAP_EXTRA_SKIP_LIST}"
fi
start_stage fastercap "solving ${eligible_cases} eligible case(s); resume skips non-empty wires.log"
pattern_filter="${STACK:-${FAMILY}}"
SOLVER_FAILED_CURRENT="${REPORT_DIR}/failed_solver_current.txt"
FASTER_CAP_PROGRESS_FILE="${REPORT_DIR}/fastercap_progress.txt"
_run_fastercap() {
  FASTER_CAP_PROFILE="${FASTER_CAP_PROFILE}" \
  FASTER_CAP_FORCE_RERUN="${FORCE_SOLVER}" \
  FASTER_CAP_TIME_LIMIT="${FASTER_CAP_TIME_LIMIT}" \
  FASTER_CAP_CHECK_INTERVAL="${FASTER_CAP_CHECK_INTERVAL}" \
  FASTER_CAP_SKIP_LIST="${FASTER_CAP_SKIP_LIST_FOR_RUN}" \
  FASTER_CAP_FAILED_LIST="${SOLVER_FAILED_CURRENT}" \
  FASTER_CAP_ALLOW_FAILURES="${SKIP_SOLVER_FAILURES}" \
  FASTER_CAP_PROGRESS_FILE="${FASTER_CAP_PROGRESS_FILE}" \
    stdbuf -oL -eL "${RUNNER}" "${RUN_DIR}" "${RUN_DIR}_fasterCap" standard 20 \
    "${pattern_filter}" "${CONVERTER}" "${FASTER_CAP}"
}
# Forward [PROGRESS] n/total lines to stdout (GUI log) and stage_status; keep full log on disk.
fastercap_rc=0
set +e
if [[ "${FASTER_CAP_LOG_APPEND}" == "1" ]]; then
  _run_fastercap 2>&1 | tee -a "${REPORT_DIR}/fastercap.log" | while IFS= read -r line; do
    if [[ "${line}" == "[PROGRESS]"* ]]; then
      echo "${line}"
      mark_stage fastercap RUNNING "${line#\[PROGRESS\] }"
    fi
  done
else
  : > "${REPORT_DIR}/fastercap.log"
  _run_fastercap 2>&1 | tee "${REPORT_DIR}/fastercap.log" | while IFS= read -r line; do
    if [[ "${line}" == "[PROGRESS]"* ]]; then
      echo "${line}"
      mark_stage fastercap RUNNING "${line#\[PROGRESS\] }"
    fi
  done
fi
fastercap_rc=${PIPESTATUS[0]}
set -e
if [[ "${fastercap_rc}" -ne 0 ]]; then
  exit "${fastercap_rc}"
fi
runtime_failed="$(python3 - "${SKIP_LIST}" "${SOLVER_FAILED_CURRENT}" "${SOLVER_FAILED_LIST}" <<'PY'
import sys
from pathlib import Path

skip_path, current_path, canonical_path = map(Path, sys.argv[1:4])
existing = {
    line.strip().removeprefix("./")
    for line in skip_path.read_text(errors="replace").splitlines()
    if line.strip()
}
current = {
    line.strip().removeprefix("./")
    for line in current_path.read_text(errors="replace").splitlines()
    if line.strip()
} if current_path.is_file() else set()
prior = {
    line.strip().removeprefix("./")
    for line in canonical_path.read_text(errors="replace").splitlines()
    if line.strip()
} if canonical_path.is_file() else set()
canonical_path.write_text("".join(f"{case}\n" for case in sorted(prior | current)))
skip_path.write_text("".join(f"{case}\n" for case in sorted(existing | current)))
print(len(current))
PY
)"
if [[ "${runtime_failed}" -gt 0 ]]; then
  mark_stage fastercap PASS \
    "quarantined ${runtime_failed} runtime failure(s); see failed_solver.txt"
else
  if [[ "${reused_solver_failed}" -gt 0 ]]; then
    mark_stage fastercap SKIP \
      "reused ${reused_solver_failed} prior runtime failure(s); remaining logs reused"
  else
    mark_stage fastercap PASS "FasterCap runner completed without converter/solver failures"
  fi
fi
eligible_cases=$((eligible_cases - runtime_failed))
[[ "${eligible_cases}" -gt 0 ]] || { echo "ERROR: no eligible cases after solver" >&2; exit 2; }
else
  _skip_stage fastercap "WORKFLOW_FROM=${WORKFLOW_FROM}; reusing existing wires.log"
fi

if _should_run_stage solver_completeness; then
start_stage solver_completeness "checking every expected capacitance matrix"
python3 - "${RUN_PATH}" "${LEN}" "${STACK}" "${eligible_cases}" \
  "${SKIP_LIST}" "${REPORT_DIR}/solver_completeness.csv" "${FAMILY}" \
  "${MAX_CASES}" <<'PY'
import csv
import sys
from pathlib import Path

root, length, stack, expected, skip_path, output = (
    Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3], int(sys.argv[4]),
    Path(sys.argv[5]), Path(sys.argv[6])
)
skipped = {
    line.strip().removeprefix("./")
    for line in skip_path.read_text(errors="replace").splitlines()
    if line.strip()
}
family = sys.argv[7]
max_cases = int(sys.argv[8])
paths = sorted((root / "TYP" / family).rglob("wires"))
paths = [p for p in paths if p.parent.name.endswith(f"_L{length}")]
if family == "UnderDiag5":
    paths = [p for p in paths if "_S0_L" in p.parent.name]
if stack:
    paths = [p for p in paths if f"/{stack}/" in p.as_posix()]
if max_cases > 0:
    paths = paths[:max_cases]
paths = [
    p for p in paths
    if str(p.parent.relative_to(root)).removeprefix("./") not in skipped
]
rows = []
for wires in paths:
    log = wires.parent / "wires.log"
    text = log.read_text(errors="replace") if log.is_file() else ""
    has_matrix = "Capacitance matrix is:" in text
    has_total_time = "Total time:" in text
    # Intermediate iterations also print Capacitance matrix; Total time: marks completion.
    ok = bool(text) and has_matrix and has_total_time
    rows.append({
        "case": str(wires.parent.relative_to(root)),
        "log_nonempty": int(bool(text)),
        "has_cap_matrix": int(has_matrix),
        "has_total_time": int(has_total_time),
        "status": "PASS" if ok else "FAIL",
    })
with output.open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
failed = [row for row in rows if row["status"] == "FAIL"]
print(f"solver completeness: total={len(rows)} expected={expected} failed={len(failed)}")
if len(rows) != expected or failed:
    raise SystemExit(2)
PY
mark_stage solver_completeness PASS "${eligible_cases}/${eligible_cases} eligible cases have capacitance matrices"
else
  _skip_stage solver_completeness "WORKFLOW_FROM=${WORKFLOW_FROM}; reusing existing wires.log"
fi

PARSE_DIR="${REPORT_DIR}/parse_sym${MAX_ASYM_REL}"
SKIPPED_QUALITY="${REPORT_DIR}/skipped_quality.tsv"
COMPARE_DIR="${REPORT_DIR}/compare_rules"
ERROR_DIR="${REPORT_DIR}/error_analysis"
mkdir -p "${PARSE_DIR}" "${COMPARE_DIR}" "${ERROR_DIR}"
parsed_stack_names=()
parsed_stacks=0
compared_stacks=0
PARSE_FAILED_LIST="${REPORT_DIR}/failed_parse_stacks.txt"
COMPARE_FAILED_LIST="${REPORT_DIR}/failed_compare_stacks.txt"

if _should_run_stage matrix_quality; then
start_stage matrix_quality "checking reciprocity, signs, and C32/C34"
_quality_check_args
if python3 "${FC_DIR}/scripts/analyze_symmetry_full.py" "${QUALITY_ARGS[@]}" \
  > "${REPORT_DIR}/matrix_quality.log" 2>&1; then
  mark_stage matrix_quality PASS "strict matrix gate report generated (max_rel=${MAX_ASYM_REL})"
else
  if [[ "${STRICT_POSTCHECK}" == "1" ]]; then
    mark_stage matrix_quality FAIL "see matrix_quality.log and symmetry_summary.txt"
    exit 2
  else
    mark_stage matrix_quality WARN \
      "quality gate failed; continuing with parser strict filtering"
  fi
fi
else
  _skip_stage matrix_quality "WORKFLOW_FROM=${WORKFLOW_FROM}"
fi

if _should_run_stage parse; then
start_stage parse "extracting wire_3 capacitance tables"
: > "${SKIPPED_QUALITY}"
printf 'path\treason\tglobal_max_rel_asym\n' > "${SKIPPED_QUALITY}"

if [[ "${FAMILY}" == "UnderDiag5" ]]; then
  mark_stage parse SKIP "DiagUnder uses its dedicated four-column parser"
  start_stage compare "parsing and plotting DiagUnder against golden rules"
  python3 "${FC_DIR}/scripts/plot_sky130_diagunder_wires_vs_rules.py" \
    --run-dir "${RUN_PATH}" \
    --rules "${RULES}" \
    --out-dir "${COMPARE_DIR}" \
    --summary-csv "${ERROR_DIR}/summary.csv" \
    --cg-mode "${DIAG_CG_MODE}" \
    --skip-list "${SKIP_LIST}" \
    --stack "${STACK}" \
    --len-mult "${LEN}" \
    > "${REPORT_DIR}/error_analysis.log" 2>&1
  mark_stage compare PASS \
    "DiagUnder four-column parse and CC/CG plots generated"
  start_stage error_analysis "finalizing DiagUnder golden-rules statistics"
  mark_stage error_analysis PASS "statistics generated with CG mode ${DIAG_CG_MODE}"
  start_stage complete "finalizing workflow report"
  mark_stage complete PASS "workflow finished"
  exit 0
fi

mapfile -t stack_dirs < <(python3 - "${RUN_PATH}" "${STACK}" "${FAMILY}" <<'PY'
import sys
from pathlib import Path
root, wanted = Path(sys.argv[1]) / "TYP" / sys.argv[3], sys.argv[2]
for path in sorted(p for p in root.iterdir() if p.is_dir()):
    if not wanted or path.name == wanted:
        print(path)
PY
)

: > "${PARSE_FAILED_LIST}"
: > "${COMPARE_FAILED_LIST}"
for stack_dir in "${stack_dirs[@]}"; do
  stack_name="$(basename "${stack_dir}")"
  input_list="${PARSE_DIR}/${stack_name}.input.list"
  python3 - "${stack_dir}" "${RUN_PATH}" "${LEN}" "${SKIP_LIST}" "${input_list}" <<'PY'
import sys
from pathlib import Path
root, run_root, length, skip_path, output = (
    Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5])
)
skipped = {
    line.strip().removeprefix("./")
    for line in skip_path.read_text(errors="replace").splitlines()
    if line.strip()
}
logs = sorted(
    p for p in root.rglob("wires.log")
    if p.parent.name.endswith(f"_L{length}")
    and p.stat().st_size > 0
    and str(p.parent.relative_to(run_root)).removeprefix("./") not in skipped
)
output.write_text("".join(f"{path}\n" for path in logs))
PY
  [[ -s "${input_list}" ]] || continue
  parse_ok=0
  for ((attempt = 1; attempt <= PARSE_RETRIES; attempt++)); do
    if (
      cd "${PARSE_DIR}"
      python3 "${FC_DIR}/scripts/fasterCapParse.py" \
        -in_list_file "${input_list}" \
        -wire 3 \
        --symmetrize-avg \
        "${PARSE_GATE_ARGS[@]}" \
        --skip-quality-log "${SKIPPED_QUALITY}" \
        --skip-quality-append \
        -out_file "${stack_name}.caps" \
        -len_meta_file "${stack_name}.len_meta.csv" \
        > "${stack_name}.parse.out" 2>&1
    ); then
      parse_ok=1
      break
    fi
  done
  if [[ "${parse_ok}" != "1" ]]; then
    printf '%s\tparser failed after %s attempt(s)\n' \
      "${stack_name}" "${PARSE_RETRIES}" >> "${PARSE_FAILED_LIST}"
    pause_between_stacks
    continue
  fi
  if [[ ! -s "${PARSE_DIR}/${stack_name}.caps" ]]; then
    printf '%s\tparser produced an empty caps file\n' \
      "${stack_name}" >> "${PARSE_FAILED_LIST}"
    pause_between_stacks
    continue
  fi
  parsed_stack_names+=("${stack_name}")
  parsed_stacks=$((parsed_stacks + 1))
  pause_between_stacks
done
[[ "${parsed_stacks}" -gt 0 ]] || { echo "ERROR no stacks parsed" >&2; exit 2; }
parse_failed="$(wc -l < "${PARSE_FAILED_LIST}")"
if [[ "${parse_failed}" -gt 0 ]]; then
  mark_stage parse WARN \
    "${parsed_stacks} stack(s) parsed; ${parse_failed} failed stack(s) quarantined"
else
  mark_stage parse PASS "${parsed_stacks} stack(s) parsed"
fi
else
  _skip_stage parse "WORKFLOW_FROM=${WORKFLOW_FROM}; reuse existing caps"
  mapfile -t parsed_stack_names < <(
    find "${PARSE_DIR}" -maxdepth 1 -name '*.caps' -size +0c -printf '%f\n' \
      | sed 's/\.caps$//' | sort
  )
  parsed_stacks="${#parsed_stack_names[@]}"
fi

if _should_run_stage compare; then
start_stage compare "generating per-stack golden-rules comparisons and plots"
: > "${COMPARE_FAILED_LIST}"
compared_stacks=0
[[ "${#parsed_stack_names[@]}" -gt 0 ]] \
  || { echo "ERROR no parsed stacks available for compare" >&2; exit 2; }
for stack_name in "${parsed_stack_names[@]}"; do
  if ! python3 "${COMPARE_SCRIPT}" \
      --caps "${PARSE_DIR}/${stack_name}.caps" \
      --rules "${RULES}" \
      --wire 3 \
      --pattern-label "${stack_name}" \
      --out-dir "${COMPARE_DIR}/${stack_name}" \
      > "${PARSE_DIR}/${stack_name}.compare.out" 2>&1; then
    printf '%s\trules comparison failed\n' \
      "${stack_name}" >> "${COMPARE_FAILED_LIST}"
    pause_between_stacks
    continue
  fi
  compared_stacks=$((compared_stacks + 1))
  pause_between_stacks
done
[[ "${compared_stacks}" -gt 0 ]] || { echo "ERROR no stacks compared" >&2; exit 2; }
compare_failed="$(wc -l < "${COMPARE_FAILED_LIST}")"
if [[ "${compare_failed}" -gt 0 ]]; then
  mark_stage compare WARN \
    "${compared_stacks} stack(s) plotted; ${compare_failed} failed stack(s) quarantined"
else
  mark_stage compare PASS "${compared_stacks} stack(s) compared and plotted"
fi
else
  _skip_stage compare "WORKFLOW_FROM=${WORKFLOW_FROM}"
  compared_stacks="$(find "${COMPARE_DIR}" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
fi

if _should_run_stage error_analysis; then
start_stage error_analysis "comparing against golden rules and plotting errors"
[[ "${compared_stacks}" -gt 0 ]] \
  || { echo "ERROR no compared stacks available for error_analysis" >&2; exit 2; }
python3 "${ERROR_SCRIPT}" \
  --compare-dir "${COMPARE_DIR}" \
  --out-dir "${ERROR_DIR}" \
  --len-mult "${LEN}" \
  --rules "${RULES}" \
  --ratio-tag "sky130_fastercap_len${LEN}" \
  --platform-name SKY130 \
  --expected-patterns "${compared_stacks}" \
  --rel-thr "${REL_THR}" \
  --family "${FAMILY_LABEL}" \
  --cg-mode "${CG_MODE}" \
  > "${REPORT_DIR}/error_analysis.log" 2>&1
mark_stage error_analysis PASS "error-vs-dist plots and aggregate statistics generated"
else
  _skip_stage error_analysis "WORKFLOW_FROM=${WORKFLOW_FROM}"
fi

if _should_run_stage complete; then
start_stage complete "finalizing workflow report"
mark_stage complete PASS "workflow finished"
else
  _skip_stage complete "WORKFLOW_FROM=${WORKFLOW_FROM}"
fi
