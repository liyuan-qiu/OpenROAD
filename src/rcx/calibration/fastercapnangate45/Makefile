top_dir=$(shell pwd)
# top_dir=$(top_dir1)
data_dir=$(top_dir)/data
# @echo "Top Dir = $(top_dir)"
# -------------------------------------------------------------------------------------
#                        rcx model file generation steps
# -------------------------------------------------------------------------------------

# -------------------------------------------------------------------------------------
# REQUIRED Manual actions:
#       create link to openroad executable: 
#			ln -s /home/dimitris-ic/z/v2_rcx/OpenROAD-OpenRCX-v2-fotakis/build/src/openroad bin/
#	Copy FasterCap executable into bin
#	Copy process.TYP files onto dir data: one process.TYP per corner
# -------------------------------------------------------------------------------------

gen_pattern_bash=$(top_dir)/scripts/run_patterns.bash
gen_patterns=$(top_dir)/scripts/gen_patterns.bash
gen_process=$(top_dir)/scripts/generate_process_nangate45_10m.sh
script_dir=$(top_dir)/scripts
openroad=$(script_dir)/openroad_exec.sh
met_cnt=10

.PHONY: process_10m 10v2_typ 10v2_min 10v2_typ_fasterCap 10v2_typ_fasterCap_baseline 10v2_min_fasterCap \
	10v2_typ_parse 10v2_min_parse model model_10m model_typ_only pipeline_10v2 \
	10v2_typ_wirefix 10v2_typ_wirefix_fasterCap 10v2_typ_wirefix_parse_model_compare

# -------------------------------------------------------------------------------------
#                        Generate 10-metal process.TYP / process.MIN
# -------------------------------------------------------------------------------------

process_10m:
	$(gen_process)

# -------------------------------------------------------------------------------------
#                        rcx generates patterns (10-metal nangate45, wire_cnt=5, v2)
# -------------------------------------------------------------------------------------

10v2_min:
	$(gen_patterns) $@ $(openroad) $(data_dir)/process.MIN MIN 5 2 ;  \
	echo " --- Wire Patterns Directory: $@"

10v2_typ:
	$(gen_patterns) $@ $(openroad) $(data_dir)/process.TYP TYP 5 2 ; \
	echo " --- Wire Patterns Directory: $@"

# wirefix + dist2x (w_list=1, s_list 10 points, UnderDiag s2=0); see §16 in nangate45_10m_process_conversion.md
10v2_typ_wirefix:
	RUN_DIR=10v2_typ_wirefix $(script_dir)/gen_10v2_typ_patterns.sh
	RUN_DIR=10v2_typ_wirefix STOP_FC=0 $(script_dir)/prune_underdiag_s2_nonzero.sh

10v2_typ_wirefix_fasterCap:
	FASTER_CAP_PROFILE=optimized $(run_fasterCap) 10v2_typ_wirefix $@ standard 20 ALL $(rcx2fasterCap) $(fasterCap)

# sym50 parse -> CG(A) + CG(B) models -> rules contrast plots (strict/multiwidth/diagunder)
10v2_typ_wirefix_parse_model_compare:
	RUN_DIR=10v2_typ_wirefix \
	PARSE_DIR=10v2_typ_wirefix_parse_sym50 \
	OUT_TAG=wirefix_$$(date +%Y%m%d) \
	MET_CNT=$(met_cnt) \
	$(script_dir)/run_10v2_parse_model_compare.sh

# Re-plot only (requires existing caps + both models)
10v2_typ_wirefix_plots:
	PLOTS_ONLY=1 \
	RUN_DIR=10v2_typ_wirefix \
	PARSE_DIR=10v2_typ_wirefix_parse_sym50 \
	OUT_TAG=wirefix_$$(date +%Y%m%d) \
	MET_CNT=$(met_cnt) \
	$(script_dir)/run_10v2_parse_model_compare.sh

# DIAGUNDER only: rules col[3] vs FasterCap |C32|+|C34| (wire_3, s2=0)
10v2_typ_wirefix_diagunder_col3_plots:
	RUN_DIR=10v2_typ_wirefix \
	PARSE_DIR=10v2_typ_wirefix_parse_sym50 \
	OUT_TAG=wirefix_$$(date +%Y%m%d) \
	$(script_dir)/run_nangate45_diagunder_col3_compare.sh

# Legacy 7-metal abstract flow (M1-M5 + M6M/M7M); kept for comparison only.
5v2_min:
	@echo "WARN: legacy 7-metal flow; use 10v2_min for nangate45 metal1-metal10" ; \
	$(gen_patterns) $@ $(openroad) $(data_dir)/archive/7m_abstract/process.MIN MIN 5 2 ;  \
	echo " --- Wire Patterns Directory: $@"

5v2_typ:
	@echo "WARN: legacy 7-metal flow; use 10v2_typ for nangate45 metal1-metal10" ; \
	$(gen_patterns) $@ $(openroad) $(data_dir)/archive/7m_abstract/process.TYP TYP 5 2 ; \
	echo " --- Wire Patterns Directory: $@"


# -------------------------------------------------------------------------------------
#                        Run fasterCap
# -------------------------------------------------------------------------------------
run_fasterCap=$(top_dir)/scripts/run_fasterCap.bash
rcx2fasterCap=$(top_dir)/scripts/UniversalFormat2FasterCap_923.py
fasterCap=$(top_dir)/bin/FasterCap

# 10v2: tuned FasterCap knobs from fastcap_debug.md / run_halfmin542_cfg.py
#   -g -ps128 -t1e-2 -d2.0 -m0.05 -mc0.5 -r  (no -ap/-a)
10v2_typ_fasterCap:
	FASTER_CAP_PROFILE=optimized $(run_fasterCap) 10v2_typ $@ standard 20 ALL $(rcx2fasterCap) $(fasterCap)

10v2_typ_fasterCap_baseline:
	$(run_fasterCap) 10v2_typ 10v2_typ_fasterCap standard 20 ALL $(rcx2fasterCap) $(fasterCap)

10v2_min_fasterCap:
	FASTER_CAP_PROFILE=optimized $(run_fasterCap) 10v2_min $@ standard 20 ALL $(rcx2fasterCap) $(fasterCap)

5v2_typ_fasterCap:
	$(run_fasterCap) 5v2_typ $@ standard 20 ALL $(rcx2fasterCap) $(fasterCap)

5v2_min_fasterCap:
	$(run_fasterCap) 5v2_min $@ standard 20 ALL $(rcx2fasterCap) $(fasterCap)

# -------------------------------------------------------------------------------------
#                        fasterCapParse parse of fasterCap Output
# -------------------------------------------------------------------------------------
parse_fasterCap_bash=$(top_dir)/scripts/parse_fasterCap.bash
fasterCapParsePython=$(top_dir)/scripts/fasterCapParse.py

10v2_typ_parse:
	$(parse_fasterCap_bash) $@  $(top_dir) 10v2_typ $(fasterCapParsePython) 3

10v2_min_parse:
	$(parse_fasterCap_bash) $@  $(top_dir) 10v2_min $(fasterCapParsePython) 3

5v2_typ_parse:
	$(parse_fasterCap_bash) $@  $(top_dir) 5v2_typ $(fasterCapParsePython) 3
	
5v2_min_parse:
	$(parse_fasterCap_bash) $@  $(top_dir) 5v2_min $(fasterCapParsePython) 3
	

# -------------------------------------------------------------------------------------
#                        rcx generates model file
# -------------------------------------------------------------------------------------
readCaps_tcl=readCaps.rcx.tcl

fc_rel=tools/OpenROAD/src/rcx/calibration/fastercapnangate45
docker_fc=/OpenROAD-flow-scripts/$(fc_rel)

model_typ_only:
	@set -e; \
	out_dir=$(top_dir)/model_10m; \
	rm -rf $$out_dir; \
	mkdir $$out_dir; \
	tcl=$$out_dir/$(readCaps_tcl); \
	echo "init_rcx_model -corner_names \"TYP\" -met_cnt $(met_cnt)" > $$tcl; \
	echo "read_rcx_tables -corner TYP -file  $(docker_fc)/10v2_typ_parse/10v2_typ.caps " >> $$tcl; \
	echo "read_rcx_tables -corner TYP -file  $(docker_fc)/10v2_typ/resistance.TYP " >> $$tcl; \
	echo "write_rcx_model -file $(docker_fc)/model_10m/130.rcx.model " >> $$tcl; \
	$(openroad) -exit $(docker_fc)/model_10m/$(readCaps_tcl) > $$out_dir/OUT; \
	test -s $$out_dir/130.rcx.model; \
	echo "OK: $$out_dir/130.rcx.model (TYP only)"

model_10m:
	@set -e; \
	out_dir=$(top_dir)/model_10m; \
	rm -rf $$out_dir; \
	mkdir $$out_dir; \
	tcl=$$out_dir/$(readCaps_tcl); \
	echo "init_rcx_model -corner_names \"TYP MIN\" -met_cnt $(met_cnt)" > $$tcl; \
	echo "read_rcx_tables -corner TYP -file  $(docker_fc)/10v2_typ_parse/10v2_typ.caps " >> $$tcl; \
	echo "read_rcx_tables -corner TYP -file  $(docker_fc)/10v2_typ/resistance.TYP " >> $$tcl; \
	echo "read_rcx_tables -corner MIN -file  $(docker_fc)/10v2_min_parse/10v2_min.caps " >> $$tcl; \
	echo "read_rcx_tables -corner MIN -file  $(docker_fc)/10v2_min/resistance.MIN " >> $$tcl; \
	echo "write_rcx_model -file $(docker_fc)/model_10m/130.rcx.model " >> $$tcl; \
	$(openroad) -exit $(docker_fc)/model_10m/$(readCaps_tcl) > $$out_dir/OUT; \
	test -s $$out_dir/130.rcx.model; \
	echo "OK: $$out_dir/130.rcx.model"

model: model_typ_only

pipeline_10v2:
	$(MAKE) 10v2_typ
	@echo "Patterns ready (TYP only). Start FasterCap in background:"
	@echo "  FASTER_CAP_TIME_LIMIT=1200 nohup make 10v2_typ_fasterCap > typ_fastercap_run.log 2>&1 &"
	@echo "After parse: make -B 10v2_typ_parse && make model_typ_only"

model_7m:
	echo $@ ; \
        rm -rf $@ ; \
        mkdir $@ ; \
        cd $@ ; \
	echo "init_rcx_model -corner_names \"TYP MIN\" -met_cnt 7" > $(readCaps_tcl) ; \
	echo "read_rcx_tables -corner TYP -file  $(top_dir)/5v2_typ_parse/5v2_typ.caps " >>  $(readCaps_tcl) ; \
	echo "read_rcx_tables -corner TYP -file  $(top_dir)/5v2_typ/resistance.TYP " >>  $(readCaps_tcl) ; \
	echo "read_rcx_tables -corner MIN -file  $(top_dir)/5v2_min_parse/5v2_min.caps " >>  $(readCaps_tcl) ; \
	echo "read_rcx_tables -corner MIN -file  $(top_dir)/5v2_min/resistance.MIN " >>  $(readCaps_tcl) ; \
	echo "write_rcx_model -file 130.rcx.model " >> $(readCaps_tcl) ; \
	$(openroad) < $(readCaps_tcl) > OUT ; \
	# echo "$@ diffs: `diff -w -r . ../gen924.GOLD` "

