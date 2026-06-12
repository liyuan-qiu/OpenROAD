# Generate a GUI-viewable DEF snapshot for an UnderDiag5-like M6duM7 case.
#
# Target-like case:
#   UnderDiag5 / M6duM7 / W0.42_W1.6 / S0.84_S6.72 / L10
#
# Notes:
# - This is a bench_wires_gen reconstruction for visualization.
# - It is for geometry inspection in GUI, not a replacement for calibration data.

read_lef /OpenROAD-flow-scripts/flow/platforms/nangate45/lef/NangateOpenCellLibrary.tech.lef

bench_wires_gen \
  -diag \
  -wire_cnt 5 \
  -met 6 \
  -len 10 \
  -width "1" \
  -spacing "2" \
  -couple_width "2" \
  -couple_spacing "4" \
  -dbg 1

write_def /OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fasterCap/5v2_typ/case_snapshot_UnderDiag5_M6duM7_like.def
exit

