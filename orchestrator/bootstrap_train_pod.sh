#!/usr/bin/env bash
# The CoreWeave fleet and system-Python bootstrap are retired.
set -euo pipefail
printf '%s\n' 'Use orchestrator/deploy/puget1/: setup-node.sh and worker.yaml provision the single GPU worker; the GCP controller uses the existing controller-workspace disk.' >&2
exit 2
