#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../../../../../../.. && pwd)"
TCL_SCRIPT="tools/OpenROAD/src/rcx/calibration/fastercapnangate45/scripts/gen_case_def_snapshot_underdiag5.tcl"
RAW_DEF="tools/OpenROAD/src/rcx/calibration/fastercapnangate45/5v2_typ/case_snapshot_UnderDiag5_like.def"
GUI_DEF="tools/OpenROAD/src/rcx/calibration/fastercapnangate45/5v2_typ/case_snapshot_UnderDiag5_like_gui.def"

cd "${REPO_ROOT}"
./openroad_run.sh -exit "${TCL_SCRIPT}"

REPO_ROOT="${REPO_ROOT}" python3 - <<'PY'
import os
import re
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
raw_def = repo / "tools/OpenROAD/src/rcx/calibration/fastercapnangate45/5v2_typ/case_snapshot_UnderDiag5_like.def"
gui_def = repo / "tools/OpenROAD/src/rcx/calibration/fastercapnangate45/5v2_typ/case_snapshot_UnderDiag5_like_gui.def"

text = raw_def.read_text(encoding="utf-8", errors="replace")
text = re.sub(r"\s+TAPERRULE\s+ADS_ND_\d+", "", text)
gui_def.write_text(text, encoding="utf-8")
print(f"Generated GUI DEF: {gui_def}")
PY

echo "Done."
echo "RAW DEF : ${REPO_ROOT}/${RAW_DEF}"
echo "GUI DEF : ${REPO_ROOT}/${GUI_DEF}"
