#!/usr/bin/env bash
# Quick status for 10v2 FasterCap calibration runs.
set -euo pipefail
FC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="${1:-10v2_typ}"

total="$(find "${FC_DIR}/${RUN}" -name wires 2>/dev/null | wc -l | tr -d ' ')"
done="$(find "${FC_DIR}/${RUN}" -name wires.log -size +0c 2>/dev/null | wc -l | tr -d ' ')"
empty="$(find "${FC_DIR}/${RUN}" -name wires.log -size 0c 2>/dev/null | wc -l | tr -d ' ')"
running="$(ps aux | grep -c '[r]un_fasterCap.bash '"${RUN}" || true)"

echo "run_dir=${RUN}"
echo "patterns_total=${total}"
echo "wires.log_nonempty=${done}"
echo "wires.log_empty=${empty}"
echo "fastercap_runner_processes=${running}"

# Prefer run-specific log from run_10v2_fastercap_optimized.sh, then legacy names.
log=""
for candidate in \
  "${FC_DIR}/typ_fastercap_${RUN}_run.log" \
  "${FC_DIR}/typ_fastercap_run.log"; do
  if [[ -f "${candidate}" ]]; then
    log="${candidate}"
    break
  fi
done

if [[ -n "${log}" ]]; then
  echo "--- tail $(basename "${log}") ---"
  tail -3 "${log}"
fi
