#!/bin/bash -f
# python_script=~/z/72424/scripts/UniversalFormat2FasterCap.py
# works python_script=~/z/72424/scripts/UniversalFormat2FasterCap_923.py
# works fasterCap=/home/dimitris-ic/fasterCap/920/FasterCAP_v2/FasterCap_v2/build_fasterCap_920/FasterCap

#README - DKF - 092524 : change ext_y and ext_z from 0 to ext_x

if [ $# -lt 7 ] 
then
	echo "Usage <in_dir> <out_dir> <standard|normalized> <ext> <converter_python> <fasterCap_exec>"
	exit
fi
script_dir="$(cd "$(dirname "$0")" && pwd)"

in_dir=$1
outDir=$2
std_normal=$3
ext_x=$4
ext_y=$4
ext_z=0
pattern=$5
python_script=$6
fasterCap=$7
error=0.01

# FasterCap solver knobs (see fastcap_debug.md, run_halfmin542_cfg.py).
# FASTER_CAP_PROFILE=optimized  ->  -g -ps128 -t1e-2 -d2.0 -m0.05 -mc0.5 -r  (no -ap/-a)
use_g="${FASTER_CAP_USE_G:-1}"
use_ap="${FASTER_CAP_USE_AP:-1}"
use_a="${FASTER_CAP_USE_A:-1}"
extra_args="${FASTER_CAP_EXTRA_ARGS:-}"
case "${FASTER_CAP_PROFILE:-}" in
optimized|halfmin542|ps128)
	use_ap=0
	use_a=0
	if [ -z "$extra_args" ]; then
		extra_args="-ps128 -t1e-2 -d2.0 -m0.05 -mc0.5 -r"
	fi
	;;
esac
force_rerun="${FASTER_CAP_FORCE_RERUN:-0}"
skip_list="${FASTER_CAP_SKIP_LIST:-}"
failed_list="${FASTER_CAP_FAILED_LIST:-}"
allow_failures="${FASTER_CAP_ALLOW_FAILURES:-0}"
if [ -n "$failed_list" ]; then
	: > "$failed_list"
fi

cd $in_dir
find . -name wires -print | sort > wires_file_list

cd ../
out_dir=$outDir.$std_normal.$ext_x.$ext_y.$ext_z.$pattern
#  echo "out_dir=$outDir.$std_normal.$ext_x.$ext_y.$ext_z.$pattern"
mkdir -p $out_dir
out=$out_dir/OUT

echo "$out" > $out
{
	echo "FASTER_CAP_PROFILE=${FASTER_CAP_PROFILE:-default}"
	echo "use_g=${use_g} use_ap=${use_ap} use_a=${use_a} error=${error}"
	echo "extra_args=${extra_args:-<none>}"
	echo "force_rerun=${force_rerun}"
} >> "$out"

START_DIR=`pwd`
# echo "----------------------------------------- start DIR: $START_DIR"
failed_cases=0
reuse_cases=0
run_cases=0
progress_file="${FASTER_CAP_PROGRESS_FILE:-}"

emit_progress() {
	# Usage: emit_progress <idx> <total> <action> <rel_dir>
	local idx="$1" total="$2" action="$3" rel="$4"
	local msg="[PROGRESS] ${idx}/${total} ${action} ${rel}"
	echo "$msg"
	if [ -n "$progress_file" ]; then
		printf '%s\t%s\t%s\t%s\n' "$idx" "$total" "$action" "$rel" > "$progress_file"
	fi
}

has_valid_wires_log() {
	# Resume policy (user): any non-empty wires.log means "already ran — skip".
	# Parse can extract from intermediate matrices; do not require Total time: here.
	# Empty 0-byte logs are re-run. Force-rerun with FASTER_CAP_FORCE_RERUN=1.
	[ -s wires.log ]
}

# Timeout/failure path renames wires.log -> wires.log.failed. For resume, treat a
# non-empty failed log the same as a normal log: restore it and skip re-solve.
restore_failed_wires_log_if_needed() {
	if [ ! -s wires.log ] && [ -s wires.log.failed ]; then
		mv -f wires.log.failed wires.log
		echo "Restored wires.log from wires.log.failed"
		return 0
	fi
	return 1
}

# Build the case list once so progress can show idx/total.
work_list=()
while IFS= read -r ii; do
	[ -n "$ii" ] || continue
	dirName=`dirname "$ii"`
	rel_dir="${dirName#./}"
	if [ -n "$skip_list" ] && [ -f "$skip_list" ] && grep -Fxq "$rel_dir" "$skip_list"; then
		echo "Skipped preflight: $dirName"
		continue
	fi
	if [ "$pattern" != "ALL" ]; then
		if [[ "$dirName" != *"$pattern"* ]]; then
			continue
		fi
	fi
	work_list+=("$rel_dir")
done < "$in_dir/wires_file_list"

total=${#work_list[@]}
echo "[PROGRESS] 0/${total} start force_rerun=${force_rerun}"
if [ -n "$progress_file" ]; then
	printf '0\t%s\tstart\t\n' "$total" > "$progress_file"
fi

idx=0
for rel_dir in "${work_list[@]}"
do
	idx=$((idx + 1))
	dirName="./${rel_dir}"

	cd "$START_DIR/$in_dir/$rel_dir"

	# Prefer existing non-empty result. wires.log.failed (timeout/quarantine) counts too.
	if [ "$force_rerun" != "1" ]; then
		restore_failed_wires_log_if_needed || true
		if has_valid_wires_log; then
			reuse_cases=$((reuse_cases + 1))
			emit_progress "$idx" "$total" "reuse" "$rel_dir"
			echo "Done $dirName `ls -ltr wires.log | awk '{print $5 " " $6 " " $7 " " $8}' `"
			cd "$START_DIR"
			continue
		fi
	fi
	if [ -e wires.log ] && [ ! -s wires.log ]; then
		echo "Empty $dirName (wires.log is 0 bytes), re-running"
	fi

	emit_progress "$idx" "$total" "running" "$rel_dir"
	echo " "
	echo "`date` $dirName Running "
	# echo "python3 $python_script  $START_DIR/$in_dir/process.out ./ ./ $std_normal -sim_window_ext  -$ext_x -$ext_z -$ext_y $ext_x $ext_z $ext_y > conv.log "
	if ! python3 "$python_script" "$START_DIR/$in_dir/process.out" ./ ./ "$std_normal" \
		-sim_window_ext -$ext_x -$ext_z -$ext_y $ext_x $ext_z $ext_y \
		> wireDielGeomGen.log 2>&1; then
		echo "ERROR converter failed: $dirName"
		rm -f wires.log
		[ -z "$failed_list" ] || echo "$rel_dir" >> "$failed_list"
		failed_cases=$((failed_cases + 1))
		emit_progress "$idx" "$total" "failed" "$rel_dir"
		cd "$START_DIR"
		continue
	fi
	if [ ! -s wires.lst ]; then
		echo "ERROR converter produced empty/missing wires.lst: $dirName"
		rm -f wires.log
		[ -z "$failed_list" ] || echo "$rel_dir" >> "$failed_list"
		failed_cases=$((failed_cases + 1))
		emit_progress "$idx" "$total" "failed" "$rel_dir"
		cd "$START_DIR"
		continue
	fi

	fc_args=(-b wires.lst)
	if [ "$use_g" = "1" ]; then
		fc_args+=(-g)
	fi
	if [ "$use_ap" = "1" ]; then
		fc_args+=(-ap)
	fi
	if [ "$use_a" = "1" ]; then
		fc_args+=(-a"$error")
	fi
	echo "Command: $fasterCap ${fc_args[*]} ${extra_args}"
	$fasterCap "${fc_args[@]}" $extra_args > wires.log &

	job_pid=$!

	# FasterCap may run longer depending on machine/mesh; allow tuning kill-time via env vars.
	# Default to a longer timeout to reduce empty/partial wires.log outputs.
	TIME_LIMIT="${FASTER_CAP_TIME_LIMIT:-600}"
	CHECK_INTERVAL="${FASTER_CAP_CHECK_INTERVAL:-30}"
	$script_dir/limit_kill.bash $job_pid "$TIME_LIMIT" "$CHECK_INTERVAL"
	wait "$job_pid"
	status=$?
	if [ "$status" -ne 0 ] \
		|| ! grep -q "Capacitance matrix is:" wires.log \
		|| ! grep -q "Total time:" wires.log; then
		echo "ERROR FasterCap failed or incomplete (exit=$status; need Capacitance matrix + Total time): $dirName"
		mv -f wires.log wires.log.failed
		[ -z "$failed_list" ] || echo "$rel_dir" >> "$failed_list"
		failed_cases=$((failed_cases + 1))
		emit_progress "$idx" "$total" "failed" "$rel_dir"
		cd "$START_DIR"
		continue
	fi
	grep "w3 " wires.log
	run_cases=$((run_cases + 1))
	emit_progress "$idx" "$total" "completed" "$rel_dir"
	echo "`date` $dirName Completed"
	cd $START_DIR
done

echo "[PROGRESS] ${total}/${total} finished reuse=${reuse_cases} ran=${run_cases} failed=${failed_cases}"
if [ -n "$progress_file" ]; then
	printf '%s\t%s\tfinished\treuse=%s ran=%s failed=%s\n' \
		"$total" "$total" "$reuse_cases" "$run_cases" "$failed_cases" > "$progress_file"
fi

if [ "$failed_cases" -gt 0 ]; then
	if [ "$allow_failures" = "1" ]; then
		echo "WARN: quarantined $failed_cases FasterCap case(s)"
	else
		echo "ERROR: $failed_cases FasterCap case(s) failed"
		exit 2
	fi
fi

