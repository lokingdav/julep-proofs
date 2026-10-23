#!/usr/bin/env bash
# Only exact-current-source records count; fail if any result/dependency is pending.
set -euo pipefail
cd -- "$(dirname -- "$0")"
exec python3 workflow.py collect julep_pairing.spthy julep_auth.spthy julep_oda.spthy julep_ratchet_regression.spthy
