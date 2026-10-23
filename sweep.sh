#!/usr/bin/env bash
# Bounded jobs, fresh source snapshots, no stale-log skipping, fail-closed status.
set -euo pipefail
here="$(cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$here/suite.py" "${1:?usage: sweep.sh theory.spthy [jobs] [timeout] [threads] [heap_gb]}" \
  --jobs "${2:-2}" --timeout "${3:-180}" --threads "${4:-2}" --heap "${5:-4}"
