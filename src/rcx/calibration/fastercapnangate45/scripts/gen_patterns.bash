#!/bin/bash -f
set -euo pipefail

if [ $# -lt 6 ]
then
	echo "Usage <run_dir> <openroad_exec> <process_file> <process_name> <wire_cnt> <version>"
	exit 1
fi
dir=$1
or_exec=$2
process=$3
outname=$4
wire_cnt=$5
version=$6

if [ ! -f "$process" ]; then
	echo "ERROR: process file not found: $process" >&2
	exit 1
fi

start_dir="$(pwd)"
repo_root="$(cd "${start_dir}/../../../../../.." && pwd)"
tcl_script=tmp_gen_patterns.tcl
abs_tcl_script="${start_dir}/${dir}/${tcl_script}"

to_runtime_path() {
	local p="$1"
	case "${or_exec}" in
		*openroad_exec*)
			case "$p" in
				"${repo_root}"/*) echo "/OpenROAD-flow-scripts/${p#${repo_root}/}" ;;
				*) echo "$p" ;;
			esac
			;;
		*) echo "$p" ;;
	esac
}

run_dir_abs="${start_dir}/${dir}"
run_dir_runtime="$(to_runtime_path "${run_dir_abs}")"
process_runtime="$(to_runtime_path "$process")"

rm -rf "$dir"
mkdir "$dir"

{
	echo "cd ${run_dir_runtime}"
	echo "gen_solver_patterns -process_file ${process_runtime} -process_name $outname -wire_cnt $wire_cnt -version $version"
} > "${abs_tcl_script}"

tcl_runtime="$(to_runtime_path "${abs_tcl_script}")"

set +e
"$or_exec" -exit "${tcl_runtime}" > "${start_dir}/${dir}/${outname}.log" 2>&1
rc=$?
set -e

if [ $rc -ne 0 ]; then
	echo "ERROR: openroad failed (exit $rc) for $outname; see ${start_dir}/${dir}/${outname}.log" >&2
	tail -20 "${start_dir}/${dir}/${outname}.log" >&2 || true
	exit $rc
fi

if ! grep -q "Finished .* patterns" "${start_dir}/${dir}/${outname}.log"; then
	echo "ERROR: pattern generation did not finish; see ${start_dir}/${dir}/${outname}.log" >&2
	tail -20 "${start_dir}/${dir}/${outname}.log" >&2 || true
	exit 1
fi

wire_cnt_out="$(find "${start_dir}/${dir}" -name wires | wc -l | tr -d ' ')"
echo "OK: $outname generated $wire_cnt_out wires files"

