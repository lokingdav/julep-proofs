#!/usr/bin/env bash
# Optional memory backstop; only stop prover runs created by this workflow.
set -euo pipefail
here="$(cd -- "$(dirname -- "$0")" && pwd)"
threshold_gb="${1:-10}"
[[ "$threshold_gb" =~ ^[0-9]+$ ]] || { echo 'usage: watchdog.sh [free_memory_threshold_GB]' >&2; exit 2; }
mkdir -p "$here/logs"
while true; do
  available_gb=$(free -g | awk '/Mem:/{print $7}')
  if [[ "$available_gb" -lt "$threshold_gb" ]]; then
    prover_pid=$(ps -eo pid,rss,args | awk -v scope="$here/logs/review/" \
      '$3 ~ /(^|\/)tamarin-prover$/ && $4 ~ /^--prove/ && index($0,scope) && $2 > largest {largest=$2; pid=$1} END {print pid}')
    if [[ -n "$prover_pid" ]]; then
      echo "$(date +%T) avail=${available_gb}GB below ${threshold_gb}GB, stopping workflow prover pid=$prover_pid" >> "$here/logs/watchdog.log"
      kill -TERM "$prover_pid" 2>/dev/null || true
      sleep 20
    fi
  fi
  sleep 10
done
