#!/usr/bin/env bash
# Link shared FasterCap/OpenROAD scripts from fastercapnangate45.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
NG_DIR="$(cd "${FC_DIR}/../fastercapnangate45" && pwd)"

die() { echo "ERROR: $*" >&2; exit 1; }
[[ -d "${NG_DIR}" ]] || die "missing ${NG_DIR}"

link_file() {
  local src="$1" dst="$2"
  mkdir -p "$(dirname "${dst}")"
  if [[ -e "${dst}" && ! -L "${dst}" ]]; then
    die "${dst} exists and is not a symlink"
  fi
  ln -sfn "${src}" "${dst}"
  echo "  ${dst} -> ${src}"
}

echo "==> scripts"
for f in gen_patterns.bash openroad_exec.sh run_fasterCap.bash parse_fasterCap.bash \
  limit_kill.bash monitor_10v2_fastercap.sh compare_partial_model_vs_rules.sh \
  UniversalFormat2FasterCap_923.py fasterCapParse.py plot_rcx_model_vs_rules.py scan_wires_quality.py; do
  link_file "${NG_DIR}/scripts/${f}" "${FC_DIR}/scripts/${f}"
done

echo "==> bin"
link_file "${NG_DIR}/bin/FasterCap" "${FC_DIR}/bin/FasterCap"
link_file "${NG_DIR}/bin/openroad" "${FC_DIR}/bin/openroad"

chmod +x "${SCRIPT_DIR}/generate_process_sky130hd.sh" \
  "${SCRIPT_DIR}/run_6v2_parse_model_compare.sh" \
  "${SCRIPT_DIR}/run_6v2_fastercap_optimized.sh" \
  "${SCRIPT_DIR}/compare_partial_model_vs_rules_6v2.sh" \
  "${SCRIPT_DIR}/tech_lef_to_process_sky130.py" 2>/dev/null || true

echo "Done."
