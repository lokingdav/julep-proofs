#!/usr/bin/env bash
# Compatibility wrapper. Individual verdicts still require checked helper dependencies.
set -euo pipefail
here="$(cd -- "$(dirname -- "$0")" && pwd)"
theory="${1:?usage: prove.sh theory.spthy [lemma] [timeout] [threads] [heap_gb]}"
lemma="${2:-ALL}"
args=(run "$theory" "$lemma" --timeout "${3:-180}" --threads "${4:-2}" --heap "${5:-4}")
case "$lemma" in
  *_expected_falsified) args+=(--expect falsified) ;;
esac
case "$lemma" in
  pair_agreement_A_expected_falsified|pair_K_forward_secret_A_expected_falsified)
    args+=(--heuristic o --oracle "$here/oracle.py" --search SEQDFS) ;;
  callst_only_after_ca|oda2_accept_after_ca|oda2_present_after_ca|dh_exponents_secret|ltk_secret_ordered|authenticated_share_origin|dh_shared_secret|derived_key_secret|presentation_key_origin|oda2_presentation_secret|oda2_no_harvesting)
    if [[ "$theory" == *julep_oda.spthy ]]; then
      args+=(--heuristic o --oracle "$here/oracle.py")
    fi ;;
  share_A_secret|share_B_secret|pair_K_forward_secret_B|pair_K_forward_secret_A_genuine|oda2_recipient_present_after_answer|auth2_key_agreement_with_exposed_state|executable_with_state_reveal) args+=(--heuristic o --oracle "$here/oracle.py") ;;
  executable_after_state_exposure)
    args+=(--heuristic o --oracle "$here/oracle.py" --search DFS) ;;
  deniability_witness_icv*)
    args+=(--heuristic o --oracle "$here/oracle.py" --search SEQDFS) ;;
  deniability_witness_ca*)
    args+=(--search SEQDFS) ;;
  executable*)
    if [[ "$theory" == *julep_oda.spthy ]]; then
      args+=(--heuristic o --oracle "$here/oracle.py" --search SEQDFS)
    elif [[ "$theory" == *julep_pairing.spthy && "$lemma" == executable_delegated* ]]; then
      # Find a short witness before pursuing deeper alternative derivations.
      args+=(--heuristic o --oracle "$here/oracle.py" --search SEQDFS)
    fi ;;
esac
exec python3 "$here/workflow.py" "${args[@]}"
