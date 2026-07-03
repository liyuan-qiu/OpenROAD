top_dir=$(shell pwd)
data_dir=$(top_dir)/data
met_cnt=6

gen_patterns=$(top_dir)/scripts/gen_patterns.bash
gen_process=$(top_dir)/scripts/generate_process_sky130hd.sh
openroad=$(top_dir)/scripts/openroad_exec.sh
run_fasterCap=$(top_dir)/scripts/run_fasterCap.bash
rcx2fasterCap=$(top_dir)/scripts/UniversalFormat2FasterCap_923.py
fasterCap=$(top_dir)/bin/FasterCap
parse_fasterCap_bash=$(top_dir)/scripts/parse_fasterCap.bash
fasterCapParsePython=$(top_dir)/scripts/fasterCapParse.py
readCaps_tcl=readCaps.rcx.tcl

fc_rel=tools/OpenROAD/src/rcx/calibration/fastercap_sky130hd
docker_fc=/OpenROAD-flow-scripts/$(fc_rel)

.PHONY: process_6m 6v2_typ 6v2_min 6v2_typ_fasterCap 6v2_typ_fasterCap_baseline \
	6v2_typ_parse model model_typ_only pipeline_6v2 setup_links

# Symlink shared scripts/binaries from fastercapnangate45 (run once after clone).
setup_links:
	@./scripts/setup_shared_links.sh

process_6m:
	$(gen_process)

6v2_typ:
	$(gen_patterns) $@ $(openroad) $(data_dir)/process.TYP TYP 5 2
	@echo " --- Wire Patterns Directory: $@"

6v2_min:
	$(gen_patterns) $@ $(openroad) $(data_dir)/process.MIN MIN 5 2
	@echo " --- Wire Patterns Directory: $@"

# 6v2: tuned FasterCap knobs — same as nangate45 10v2 (§12.1)
#   -g -ps128 -t1e-2 -d2.0 -m0.05 -mc0.5 -r  (no -ap/-a)
6v2_typ_fasterCap:
	FASTER_CAP_PROFILE=optimized $(run_fasterCap) 6v2_typ $@ standard 20 ALL $(rcx2fasterCap) $(fasterCap)

6v2_typ_fasterCap_baseline:
	$(run_fasterCap) 6v2_typ 6v2_typ_fasterCap standard 20 ALL $(rcx2fasterCap) $(fasterCap)

6v2_min_fasterCap:
	FASTER_CAP_PROFILE=optimized $(run_fasterCap) 6v2_min $@ standard 20 ALL $(rcx2fasterCap) $(fasterCap)

6v2_typ_parse:
	$(parse_fasterCap_bash) $@ $(top_dir) 6v2_typ $(fasterCapParsePython) 3

6v2_min_parse:
	$(parse_fasterCap_bash) $@ $(top_dir) 6v2_min $(fasterCapParsePython) 3

model_typ_only:
	@set -e; \
	out_dir=$(top_dir)/model; \
	mkdir -p $$out_dir; \
	tcl=$$out_dir/$(readCaps_tcl); \
	echo "init_rcx_model -corner_names \"TYP\" -met_cnt $(met_cnt)" > $$tcl; \
	echo "read_rcx_tables -corner TYP -file $(docker_fc)/6v2_typ_parse_sym50/6v2_typ.caps" >> $$tcl; \
	echo "read_rcx_tables -corner TYP -file $(docker_fc)/6v2_typ/resistance.TYP" >> $$tcl; \
	echo "write_rcx_model -file $(docker_fc)/model/130.rcx.model" >> $$tcl; \
	$(openroad) -exit $$tcl > $$out_dir/OUT; \
	test -s $$out_dir/130.rcx.model; \
	echo "OK: $$out_dir/130.rcx.model (met_cnt=$(met_cnt))"

model: model_typ_only

pipeline_6m:
	$(MAKE) process_6m
	$(MAKE) 6v2_typ
	@echo "Patterns ready (396 cases). Start FasterCap (nangate45 §12 optimized):"
	@echo "  ./scripts/run_6v2_fastercap_optimized.sh"
	@echo "After FasterCap: ./scripts/run_6v2_parse_model_compare.sh"

pipeline_6v2: pipeline_6m
