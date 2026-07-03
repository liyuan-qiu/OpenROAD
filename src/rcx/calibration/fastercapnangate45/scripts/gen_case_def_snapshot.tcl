# Generate a GUI-viewable DEF snapshot for one RCX pattern case.
#
# Target case (approximation):
#   Over5 / M4oM2 / W0.14_W0.14 / S0.28_S0.28 / L10
#
# Notes:
# - This is a "bench_wires_gen" reconstruction for visualization.
# - It is intended for geometry inspection in GUI, not for replacing calibration data.

read_lef /OpenROAD-flow-scripts/flow/platforms/nangate45/lef/NangateOpenCellLibrary.tech.lef

# Approximate case mapping:
# - wire_cnt 5            -> Over5
# - met 4 + -over         -> M4 as target with over-context
# - width 1               -> 1x min width (0.14um for M4 in this tech)
# - spacing 2             -> 2x min spacing (0.28um when min is 0.14um)
# - len 10                -> L10
bench_wires_gen \
  -over \
  -wire_cnt 5 \
  -met 4 \
  -len 10 \
  -width "1" \
  -spacing "2" \
  -couple_width "1" \
  -couple_spacing "2" \
  -dbg 1

write_def /OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fastercapnangate45/5v2_typ/case_snapshot_M4_over5_W014_S028_L10.def
exit
