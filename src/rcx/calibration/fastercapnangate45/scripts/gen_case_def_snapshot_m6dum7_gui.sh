#!/usr/bin/env bash
set -euo pipefail

# Generate a single-case GUI DEF directly from the existing pattern wires file.
# Target case:
#   5v2_typ/TYP/Under5/M3uM6/W0.14_W0.14/S0.42_S0.42_L10
#   5v2_typ/TYP/UnderDiag5/M6duM7/W0.42_W1.6/S0.84_S6.72_L10
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../../../../../../.. && pwd)"
CONVERTER="tools/OpenROAD/src/rcx/calibration/fastercapnangate45/scripts/convert_wires_to_quantus_bench.py"
WIRES_FILE="tools/OpenROAD/src/rcx/calibration/fastercapnangate45/5v2_typ/TYP/Under5/M3uM6/W0.14_W0.14/S0.42_S0.42_L10/wires"
OUT_DIR="tools/OpenROAD/src/rcx/calibration/fastercapnangate45/5v2_typ/case_snapshot_Under5_M3uM6_exact"
DESIGN_NAME="case_snapshot_Under5_M3uM6_exact"
GUI_DEF="tools/OpenROAD/src/rcx/calibration/fastercapnangate45/5v2_typ/case_snapshot_Under5_M3uM6_gui.def"

cd "${REPO_ROOT}"
python3 "${CONVERTER}" \
  --wires-file "${WIRES_FILE}" \
  --out-dir "${OUT_DIR}" \
  --design-name "${DESIGN_NAME}"

cp "${OUT_DIR}/${DESIGN_NAME}.def" "${GUI_DEF}"

echo "Done."
echo "WIRES   : ${REPO_ROOT}/${WIRES_FILE}"
echo "OUT DIR : ${REPO_ROOT}/${OUT_DIR}"
echo "GUI DEF : ${REPO_ROOT}/${GUI_DEF}"

