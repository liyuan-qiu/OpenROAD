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
script_dir="$(dirname "$0")"

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

cd $in_dir
find . -name wires -print | sort > wires_file_list

cd ../
out_dir=$outDir.$std_normal.$ext_x.$ext_y.$ext_z.$pattern
#  echo "out_dir=$outDir.$std_normal.$ext_x.$ext_y.$ext_z.$pattern"
mkdir -p $out_dir
out=$out_dir/OUT

echo "$out" > $out

START_DIR=`pwd`
# echo "----------------------------------------- start DIR: $START_DIR"

for ii in `cat $in_dir/wires_file_list`
do
	dirName=`dirname $ii`
	if [ "$pattern" != "ALL" ] ; then
		if [[ "$dirName" != *"$pattern"* && $pattern!="ALL" ]] ; then
			continue
		fi
	fi

	cd $START_DIR/$in_dir/$dirName 

	# incrementality -- if wires.log has total allocated memore greater than 100MB, skip pattern
	wires_log=wires.log
	if [ -e $wires_log ]; then
		# Only skip if the previous run produced a non-empty log.
		# (Empty files are typically from early kill/permission issues.)
		if [ -s $wires_log ]; then
			echo "Done $dirName `ls -ltr $wires_log | awk '{print $5 " " $6 " " $7 " " $8}' `"
			continue
		else
			echo "Empty $dirName ($wires_log is 0 bytes), re-running"
		fi
		bytes=$(grep "Total allocated memory" "$wires_log" 2>/dev/null | awk '{print $4}' | head -n 1)
		# If the log is incomplete/empty, $bytes can be empty; guard numeric compare.
		if [[ -n "${bytes:-}" && "$bytes" =~ ^[0-9]+$ ]]; then
			if [ "$bytes" -gt 100000 ]; then
				ls -ltr -h "$wires_log"
				continue
			fi
		fi
	fi
	echo " "
	echo "`date` $dirName Running "
	# echo "python3 $python_script  $START_DIR/$in_dir/process.out ./ ./ $std_normal -sim_window_ext  -$ext_x -$ext_z -$ext_y $ext_x $ext_z $ext_y > conv.log "
	python3 $python_script  $START_DIR/$in_dir/process.out ./ ./ $std_normal -sim_window_ext  -$ext_x -$ext_z -$ext_y $ext_x $ext_z $ext_y > wireDielGeomGen.log
	# echo "$fasterCap -b wires.lst -g -a$error > wires.log" >> OUT

	$fasterCap -b wires.lst -g -ap -a$error > wires.log &

	job_pid=$!

	# FasterCap may run longer depending on machine/mesh; allow tuning kill-time via env vars.
	# Default to a longer timeout to reduce empty/partial wires.log outputs.
	TIME_LIMIT="${FASTER_CAP_TIME_LIMIT:-600}"
	CHECK_INTERVAL="${FASTER_CAP_CHECK_INTERVAL:-30}"
	$script_dir/limit_kill.bash $job_pid "$TIME_LIMIT" "$CHECK_INTERVAL"
	egrep "w3 " wires.log
	echo "`date` $dirName Completed"
	cd $START_DIR
done

