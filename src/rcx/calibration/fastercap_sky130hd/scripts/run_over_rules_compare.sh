#!/usr/bin/env bash
# Parse one SKY130 Over length sweep, compare it with rcx_patterns.rules,
# aggregate errors, and append the rules report to the symmetry summary.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"

LEN="${LEN:-20}"
RUN_DIR="${RUN_DIR:-6v2_typ_over_len${LEN}}"
PARSE_DIR="${PARSE_DIR:-${RUN_DIR}_parse_sym50}"
COMPARE_DIR="${COMPARE_DIR:-${FC_DIR}/model/compare_${RUN_DIR}_rules}"
ANALYSIS_DIR="${ANALYSIS_DIR:-${FC_DIR}/model/error_analysis_${RUN_DIR}_rules}"
RULES="${RULES:-${REPO_ROOT}/flow/platforms/sky130hs/rcx_patterns.rules}"
MAX_ASYM_REL="${MAX_ASYM_REL:-0.5}"

ROOT="${FC_DIR}/${RUN_DIR}/TYP/Over5"
BENCH_DIR="${REPO_ROOT}/bench_wires_nangate45_20260710"
PARSE_ROOT="${FC_DIR}/${PARSE_DIR}"

[[ -d "${ROOT}" ]] || { echo "ERROR: missing ${ROOT}" >&2; exit 1; }
[[ -f "${RULES}" ]] || { echo "ERROR: missing ${RULES}" >&2; exit 1; }
mkdir -p "${PARSE_ROOT}" "${COMPARE_DIR}" "${ANALYSIS_DIR}"

ok=0
fail=0
for pattern_root in "${ROOT}"/M*oM*; do
  [[ -d "${pattern_root}" ]] || continue
  pattern="$(basename "${pattern_root}")"
  input_list="${PARSE_ROOT}/${pattern}.input.list"
  python3 - "${pattern_root}" "${input_list}" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
out = Path(sys.argv[2])
logs = sorted(p for p in root.rglob("wires.log") if p.stat().st_size > 0)
out.write_text("".join(f"{path}\n" for path in logs))
PY
  count="$(wc -l < "${input_list}" | tr -d ' ')"
  if [[ "${count}" -ne 10 ]]; then
    echo "WARN: ${pattern} has ${count}/10 non-empty logs" >&2
    ((fail++)) || true
    continue
  fi

  if ! (
    cd "${PARSE_ROOT}"
    python3 "${FC_DIR}/scripts/fasterCapParse.py" \
      -in_list_file "${pattern}.input.list" \
      -wire 3 \
      --symmetrize-avg \
      --max-asym-rel "${MAX_ASYM_REL}" \
      -out_file "${pattern}.caps" \
      -len_meta_file "${pattern}.len_meta.csv" \
      > "${pattern}.parse.out" 2>&1
  ); then
    echo "WARN: parser failed for ${pattern}" >&2
    ((fail++)) || true
    continue
  fi

  metal="${pattern#M}"
  metal="${metal%%o*}"
  over="${pattern#*oM}"
  if python3 "${BENCH_DIR}/compare_fastercap_caps_vs_rules.py" \
    --caps "${PARSE_ROOT}/${pattern}.caps" \
    --rules "${RULES}" \
    --wire 3 \
    --metal "${metal}" \
    --over "${over}" \
    --pattern-label "${pattern}" \
    --out-dir "${COMPARE_DIR}/${pattern}"; then
    ((ok++)) || true
  else
    ((fail++)) || true
  fi
done

python3 "${BENCH_DIR}/analyze_fastercap_vs_rules_errors.py" \
  --compare-dir "${COMPARE_DIR}" \
  --out-dir "${ANALYSIS_DIR}" \
  --len-mult "${LEN}" \
  --rules "${RULES}" \
  --ratio-tag "sky130_fastercap_len${LEN}" \
  --platform-name "SKY130" \
  --expected-patterns 20

if ! python3 "${FC_DIR}/scripts/analyze_symmetry_full.py" \
  --root "${FC_DIR}/${RUN_DIR}" \
  --out-prefix "${FC_DIR}/${RUN_DIR}_over" \
  --only-pattern-type Over5 \
  --check \
  --max-rel "${MAX_ASYM_REL}" \
  --rules-summary "${ANALYSIS_DIR}/summary.md"; then
  echo "WARN: symmetry gate failed; combined summary was still written" >&2
fi

echo "Done: ${ok} patterns compared, ${fail} failed/skipped"
echo "Combined summary: ${FC_DIR}/${RUN_DIR}_over_symmetry_summary.txt"
