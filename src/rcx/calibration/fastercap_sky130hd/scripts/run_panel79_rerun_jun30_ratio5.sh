#!/usr/bin/env bash
# Re-run Jun30 FasterCap cases (ratio bin <= 5) with current process.out / panel template.
# Saves wires.log.panel74 (backup of original) and wires.log.panel79 (new run).
# Restores wires.log from panel74 so the main tree stays unchanged.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

RUN_DIR="${RUN_DIR:-6v2_typ_ict_smoke}"
PROCESS_OUT="${PROCESS_OUT:-${FC_DIR}/${RUN_DIR}/process.out}"
CONVERTER="${CONVERTER:-${FC_DIR}/scripts/UniversalFormat2FasterCap_923.py}"
FASTER_CAP="${FASTER_CAP:-${FC_DIR}/bin/FasterCap}"
CASE_LIST="${CASE_LIST:-${FC_DIR}/${RUN_DIR}/panel79_rerun_case_list.txt}"
PROGRESS_LOG="${PROGRESS_LOG:-${FC_DIR}/${RUN_DIR}/panel79_rerun_progress.log}"
MAX_RATIO_BIN="${MAX_RATIO_BIN:-5}"
JUN30_CUTOFF="${JUN30_CUTOFF:-2026-07-01}"   # mtime date strictly before this
TIME_LIMIT="${TIME_LIMIT:-600}"                # seconds per FasterCap solve
DRY_RUN="${DRY_RUN:-0}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -f "${PROCESS_OUT}" ]] || die "process.out not found: ${PROCESS_OUT}"
[[ -x "${FASTER_CAP}" ]] || die "FasterCap not found: ${FASTER_CAP}"
[[ -f "${CONVERTER}" ]] || die "converter not found: ${CONVERTER}"

echo "==> Discover Jun30 cases with ratio bin <= ${MAX_RATIO_BIN}"
python3 - "${FC_DIR}/${RUN_DIR}" "${CASE_LIST}" "${MAX_RATIO_BIN}" "${JUN30_CUTOFF}" <<'PY'
import datetime, os, re, sys

root, out_list, max_bin, cutoff_s = sys.argv[1:5]
max_bin = float(max_bin)
cutoff = datetime.datetime.strptime(cutoff_s, "%Y-%m-%d").date()
pat = re.compile(r"S(\d+\.?\d*)_S(\d+\.?\d*)_L(\d+)")

def ratio_bin(dist):
    d = float(dist)
    edges = [(0.21, 0.5), (0.30, 1), (0.43, 2), (0.68, 3), (0.94, 4), (1.15, 5),
             (1.36, 6), (1.70, 7), (2.04, 8), (2.38, 9), (2.72, 10)]
    for hi, rb in edges:
        if d <= hi + 1e-9:
            return rb
    return None

cases = []
for dirpath, _, files in os.walk(root):
    if "wires.log" not in files:
        continue
    log = os.path.join(dirpath, "wires.log")
    if os.path.getsize(log) == 0:
        continue
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(log)).date()
    if mtime >= cutoff:
        continue
    rel = os.path.relpath(dirpath, root)
    m = pat.search(rel)
    if not m:
        continue
    rb = ratio_bin(m.group(1))
    if rb is None or rb > max_bin:
        continue
    cases.append(rel)

cases.sort()
with open(out_list, "w") as f:
    for c in cases:
        f.write(c + "\n")
print(f"    {len(cases)} cases -> {out_list}")
PY

total="$(wc -l < "${CASE_LIST}" | tr -d ' ')"
[[ "${total}" -gt 0 ]] || die "empty case list"

echo "==> Rerun panel79 for ${total} cases (DRY_RUN=${DRY_RUN})"
: > "${PROGRESS_LOG}"
done_cnt=0
skip_cnt=0
fail_cnt=0
idx=0

while IFS= read -r rel; do
  idx=$((idx + 1))
  case_dir="${FC_DIR}/${RUN_DIR}/${rel}"
  [[ -d "${case_dir}" ]] || { echo "MISSING ${rel}" >> "${PROGRESS_LOG}"; fail_cnt=$((fail_cnt + 1)); continue; }

  if [[ -f "${case_dir}/wires.log.panel79" ]] && grep -q 'Total time:' "${case_dir}/wires.log.panel79" 2>/dev/null; then
    echo "[${idx}/${total}] SKIP (panel79 exists) ${rel}" | tee -a "${PROGRESS_LOG}"
    skip_cnt=$((skip_cnt + 1))
    continue
  fi

  echo "[${idx}/${total}] RUN ${rel}" | tee -a "${PROGRESS_LOG}"

  if [[ "${DRY_RUN}" == "1" ]]; then
    continue
  fi

  (
    cd "${case_dir}"
    if [[ ! -f wires.log.panel74 ]]; then
      cp -a wires.log wires.log.panel74
    fi
    [[ -f wires.lst ]] && [[ ! -f wires.lst.panel74 ]] && cp -a wires.lst wires.lst.panel74

    python3 "${CONVERTER}" "${PROCESS_OUT}" ./ ./ standard \
      -sim_window_ext -20 0 -20 20 0 20 > wireDielGeomGen.panel79.log 2>&1

    "${FASTER_CAP}" -b wires.lst -g -ps128 -t1e-2 -d2.0 -m0.05 -mc0.5 -r > wires.log.panel79 2>&1 &
    fc_pid=$!
    "${SCRIPT_DIR}/limit_kill.bash" "${fc_pid}" "${TIME_LIMIT}" 2 &
    killer_pid=$!
    wait "${fc_pid}" 2>/dev/null || true
    kill "${killer_pid}" 2>/dev/null || true
    wait "${killer_pid}" 2>/dev/null || true

    if ! grep -q 'Total time:' wires.log.panel79 2>/dev/null; then
      echo "FAIL incomplete ${rel}" >> "${PROGRESS_LOG}"
      exit 1
    fi

    cp -a wires.log.panel74 wires.log
    if [[ -f wires.lst.panel74 ]]; then
      cp -a wires.lst.panel74 wires.lst
    fi
  ) && done_cnt=$((done_cnt + 1)) || fail_cnt=$((fail_cnt + 1))

done < "${CASE_LIST}"

echo ""
echo "Done. total=${total} rerun=${done_cnt} skip=${skip_cnt} fail=${fail_cnt}"
echo "  case list : ${CASE_LIST}"
echo "  progress  : ${PROGRESS_LOG}"
echo "Next: OUT_DIR=... ${SCRIPT_DIR}/compare_panel74_vs_panel79.py"
