#!/usr/bin/env bash
# Generic entry point. FAMILY defaults to Over5 for backward compatibility.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export FAMILY="${FAMILY:-Over5}"
export FAMILY_WORKFLOW_ENTRY=1
exec "${SCRIPT_DIR}/run_over_workflow.sh" "$@"
