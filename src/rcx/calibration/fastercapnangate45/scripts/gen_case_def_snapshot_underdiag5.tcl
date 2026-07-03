# Generate a GUI-viewable DEF snapshot for an UnderDiag5-like RCX pattern case.
#
# This uses bench_wires with -diag to create diagonal-under context patterns.

read_lef /OpenROAD-flow-scripts/flow/platforms/nangate45/lef/NangateOpenCellLibrary.tech.lef

# UnderDiag5-like reconstruction with bench_wires_gen (more stable than bench_wires -diag):
# - wire_cnt 5  -> 5-wire structure
# - -diag       -> diagonal context patterns
# - met 4       -> focus around M4
# - len/width/spacing aligned with prior snapshots
bench_wires_gen \
  -diag \
  -wire_cnt 5 \
  -met 4 \
  -len 10 \
  -width "1" \
  -spacing "2" \
  -couple_width "1" \
  -couple_spacing "2" \
  -dbg 1

write_def /OpenROAD-flow-scripts/tools/OpenROAD/src/rcx/calibration/fastercapnangate45/5v2_typ/case_snapshot_UnderDiag5_like.def
exit
