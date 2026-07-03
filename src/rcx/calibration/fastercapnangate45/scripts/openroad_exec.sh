#!/usr/bin/env bash
# Run openroad on the host when possible; otherwise delegate to repo Docker wrapper.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FC_DIR}/../../../../../.." && pwd)"
HOST_OPENROAD="${FC_DIR}/bin/openroad"

run_host() {
  exec "${HOST_OPENROAD}" "$@"
}

run_docker() {
  if [[ ! -x "${REPO_ROOT}/openroad_run.sh" ]]; then
    echo "ERROR: host openroad unavailable and ${REPO_ROOT}/openroad_run.sh missing" >&2
    exit 127
  fi
  exec "${REPO_ROOT}/openroad_run.sh" "$@"
}

if [[ -x "${HOST_OPENROAD}" ]] && "${HOST_OPENROAD}" -version >/dev/null 2>&1; then
  run_host "$@"
fi

echo "NOTE: using Docker openroad (${HOST_OPENROAD} unavailable on host)" >&2
run_docker "$@"
