#!/usr/bin/env bash
# Explicit bounded suite, with no automatic README rewriting or global process wait.
set -euo pipefail
cd -- "$(dirname -- "$0")"
exec python3 suite.py julep_pairing.spthy julep_auth.spthy julep_oda.spthy julep_ratchet_regression.spthy "$@"
