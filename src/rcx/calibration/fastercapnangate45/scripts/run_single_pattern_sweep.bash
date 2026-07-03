#!/bin/bash -f

# Run one FasterCap pattern case and sweep solver settings.
#
# Usage:
#   run_single_pattern_sweep.bash \
#     <in_dir> <pattern_rel_dir> <converter_python> <fasterCap_exec> \
#     [a_values_csv] [standard|normalized] [ext]
#
# Example:
#   ./scripts/run_single_pattern_sweep.bash \
#     5v2_typ "TYP/Over5/M3oM2/W0.14_W0.14/S0.14_S0.14_L10" \
#     scripts/UniversalFormat2FasterCap_923.py bin/FasterCap \
#     "0.005,0.01,0.02,0.05" standard 20
#
# Notes:
# - This script sweeps FasterCap "-a" values (often used as convergence/mesh knob).
# - You can pass extra FasterCap args via env var FASTER_CAP_EXTRA_ARGS.
# - Toggle automatic preconditioner by env var FASTER_CAP_USE_AP (1 default, 0 disables -ap).
# - Toggle Galerkin switch by env var FASTER_CAP_USE_G (1 default adds -g, 0 removes -g).
# - Optional geometry sanitization via FASTER_CAP_SANITIZE_GEOM (1 enables).
# - Output logs are written in the pattern directory as wires_a<value>.log.

if [ $# -lt 4 ]; then
  echo "Usage: $0 <in_dir> <pattern_rel_dir> <converter_python> <fasterCap_exec> [a_values_csv] [standard|normalized] [ext]"
  exit 1
fi

in_dir="$1"
pattern_rel_dir="$2"
python_script_in="$3"
fasterCap_in="$4"
a_values_csv="${5:-0.01,0.02,0.05,0.1}"
std_normal="${6:-standard}"
ext_x="${7:-20}"

ext_y="$ext_x"
ext_z=0

time_limit="${FASTER_CAP_TIME_LIMIT:-600}"
check_interval="${FASTER_CAP_CHECK_INTERVAL:-30}"
extra_args="${FASTER_CAP_EXTRA_ARGS:-}"
use_ap="${FASTER_CAP_USE_AP:-1}"
use_g="${FASTER_CAP_USE_G:-1}"
sanitize_geom="${FASTER_CAP_SANITIZE_GEOM:-0}"

script_dir="$(dirname "$0")"
start_dir="$(pwd)"
if [[ "$script_dir" = /* ]]; then
  script_dir_abs="$script_dir"
else
  script_dir_abs="$start_dir/$script_dir"
fi

# Resolve tool paths before entering the case directory so relative paths work.
if [[ "$python_script_in" = /* ]]; then
  python_script="$python_script_in"
else
  python_script="$start_dir/$python_script_in"
fi
if [[ "$fasterCap_in" = /* ]]; then
  fasterCap="$fasterCap_in"
else
  fasterCap="$start_dir/$fasterCap_in"
fi

case_dir="$start_dir/$in_dir/$pattern_rel_dir"
process_out="$start_dir/$in_dir/process.out"

if [ ! -d "$case_dir" ]; then
  echo "ERROR: pattern directory not found: $case_dir"
  exit 2
fi
if [ ! -f "$process_out" ]; then
  echo "ERROR: process.out not found: $process_out"
  exit 2
fi
if [ ! -f "$python_script" ]; then
  echo "ERROR: converter script not found: $python_script"
  exit 2
fi
if [ ! -x "$fasterCap" ]; then
  echo "ERROR: FasterCap executable not found or not executable: $fasterCap"
  exit 2
fi

cd "$case_dir"

if [ ! -f "wires" ]; then
  echo "ERROR: wires file not found in $case_dir"
  exit 3
fi

echo "== Case directory: $case_dir"
echo "== Converter: $python_script"
echo "== FasterCap: $fasterCap"
echo "== -a sweep: $a_values_csv"
echo "== ext window: x=$ext_x y=$ext_y z=$ext_z"
echo "== timeout: ${time_limit}s (check every ${check_interval}s)"
echo "== extra args: ${extra_args:-<none>}"
echo "== use -ap: ${use_ap}"
echo "== use -g: ${use_g}"
echo "== sanitize geometry: ${sanitize_geom}"

# Re-generate wires.lst once for this case.
python3 "$python_script" "$process_out" ./ ./ "$std_normal" \
  -sim_window_ext "-$ext_x" "-$ext_z" "-$ext_y" "$ext_x" "$ext_z" "$ext_y" \
  > wireDielGeomGen.log

if [ ! -s "wires.lst" ]; then
  echo "ERROR: wires.lst was not generated (or empty)."
  exit 4
fi

if [ "$sanitize_geom" = "1" ]; then
  sanitizer="$script_dir_abs/sanitize_wires_lst.py"
  if [ ! -f "$sanitizer" ]; then
    echo "ERROR: sanitizer script not found: $sanitizer"
    exit 5
  fi
  cp wires.lst wires.lst.before_sanitize
  python3 "$sanitizer" wires.lst --backup > sanitize_wires.log
  if [ ! -s "wires.lst" ]; then
    echo "ERROR: wires.lst became empty after sanitization."
    exit 5
  fi
fi

status_file="sweep_status.csv"
echo "a_value,exit_state,log_file,timestamp" > "$status_file"

IFS=',' read -r -a a_values <<< "$a_values_csv"

for a_value in "${a_values[@]}"; do
  a_trimmed="$(echo "$a_value" | xargs)"
  safe_a="${a_trimmed//./p}"
  log_file="wires_a${safe_a}.log"
  run_file="run_a${safe_a}.out"

  echo ""
  echo "== Running -a ${a_trimmed}"
  ap_arg=""
  if [ "$use_ap" = "1" ]; then
    ap_arg="-ap"
  fi
  g_arg=""
  if [ "$use_g" = "1" ]; then
    g_arg="-g"
  fi
  echo "Command: $fasterCap -b wires.lst ${g_arg} ${ap_arg} -a${a_trimmed} ${extra_args}"

  $fasterCap -b wires.lst $g_arg $ap_arg -a"$a_trimmed" $extra_args > "$log_file" 2>&1 &
  job_pid=$!
  "$script_dir_abs/limit_kill.bash" "$job_pid" "$time_limit" "$check_interval"
  wait "$job_pid" 2>/dev/null
  rc=$?

  if [ "$rc" -eq 0 ]; then
    state="ok"
  elif [ "$rc" -eq 137 ] || [ "$rc" -eq 9 ]; then
    state="killed"
  else
    state="failed_${rc}"
  fi

  {
    echo "a=${a_trimmed}"
    echo "state=${state}"
    echo "rc=${rc}"
    echo "time_limit=${time_limit}"
    echo "extra_args=${extra_args}"
  } > "$run_file"

  echo "${a_trimmed},${state},${log_file},$(date '+%F %T')" >> "$status_file"

  # Optional quick convergence hint from log.
  rg -n "converg|iter|Total allocated memory|FATAL|ERROR" "$log_file" > /dev/null 2>&1 || true
done

echo ""
echo "Sweep complete. See:"
echo "  $case_dir/$status_file"
echo "  $case_dir/wires_a*.log"
