#!/usr/bin/env python3
"""Only orders Tamarin goals. It never adds, removes, or discharges a goal."""
import re
import sys

lemma = sys.argv[1] if len(sys.argv) > 1 else ""
goals = sys.stdin.readlines()


def priority(line):
    if lemma in ("pair_agreement_A_expected_falsified", "pair_K_forward_secret_A_expected_falsified"):
        # Distinguish attacker-known shares and token-generated responses
        # before expanding additional honest pairing sessions.
        if "∥" in line:
            return -50
        if "ResponseSent(" in line or "SendB(" in line:
            return -49
        if "ResponseReceived(" in line or "PairedA(" in line:
            return -48
        if "!Proof(" in line or "!Token(" in line:
            return -47
        if re.search(r"!KU\( ~", line):
            return -46

    if lemma in ("oda2_accept_after_ca", "oda2_present_after_ca"):
        if "CaDone(" in line or "CallState(" in line:
            return -60
        if "∥" in line:
            return -59

    if lemma in ("callst_only_after_ca", "oda2_accept_after_ca", "oda2_present_after_ca"):
        # Follow the protocol state that produced this step, before considering
        # the independent bookkeeping for its currently retained key.
        if "▶" in line and any(x in line for x in ("CallSt(", "IcvAsk(", "IcvAskOk(", "IcvStR(")):
            return -50
        if "∥" in line:
            return -49
        if "CaDone(" in line or "CallState(" in line:
            return -48
        if "CurrentKey(" in line:
            return 20

    if lemma == "dh_shared_secret":
        if re.search(r"!KU\( (?:~|'g'\^)", line):
            return -60
    if lemma == "dh_exponents_secret":
        if "▶" in line and any(x in line for x in ("CaStA(", "IcvStR(", "IcvAskOk(", "IcvAsk(")):
            return -40

    if lemma in ("oda2_presentation_secret", "oda2_no_harvesting"):
        if "∥" in line:
            return -50
        if "!Cred(" in line:
            return -49
        if "!KU(" in line:
            return -48
        if "~~>" in line:
            return -47

    if lemma == "derived_key_secret" and "!KU( kdf(" in line:
        return -45
    if lemma == "presentation_key_origin":
        if "▶" in line and any(x in line for x in ("IcvAskOk(", "IcvAsk(", "CallSt(")):
            return -45

    if lemma in ("dh_shared_secret", "derived_key_secret"):
        if "∥" in line:
            return -40
        if "FreshShare(" in line:
            return -39
        if "!Ltk(" in line:
            return -38
        if "~~>" in line:
            return -37
        if re.search(r"!KU\( (?:~|'g'\^)", line):
            return -36
        if "CurrentKey(" in line and "'private'" in line:
            return -35
        if "AuthShare(" in line:
            return -34

    if lemma == "dh_exponents_secret":
        if "CurrentKey(" in line and "'private'" in line:
            return -30
        if "~~>" in line:
            return -29
    if lemma == "authenticated_share_origin":
        if "!Ltk(" in line:
            return -30
        if "∥" in line:
            return -29

    if lemma in ("authenticated_share_origin", "dh_exponents_secret"):
        if "!Amf(" in line:
            return -10
        if re.search(r"!KU\( ~", line):
            return -9
        if "∥" in line:
            return -8
        if "splitEqs(" in line:
            return -7
        if "!Ltk(" in line:
            return -6
    if lemma == "auth2_key_agreement_with_exposed_state":
        if "Answered(" in line:
            return -7
        if "∥" in line:
            return -6
        if re.search(r"!KU\( ~", line):
            return -5
    if lemma in ("pair_K_forward_secret_B", "pair_K_forward_secret_A_genuine"):
        # Resolve DH-value origins before expanding further protocol sessions.
        if "SendB(" in line or "ResponseSent(" in line:
            return -8
        if "PairedA(" in line:
            return -7
        if "∥" in line:
            return -6
        if re.search(r"!KU\( ~", line):
            return -5
        if re.search(r"!KU\( 'g'\^", line):
            return -4
    if lemma in ("share_A_secret", "share_B_secret"):
        # A-generated and B-generated exponents cannot coincide by freshness.
        if "SendB(" in line or "ResponseSent(" in line:
            return -5
        if "∥" in line:
            return -4
        if re.search(r"!KU\( 'g'\^", line):
            return -3
        if re.search(r"!KU\( ~", line):
            return -2
    # Use established state invariants before unrolling another ICV round.
    if lemma.startswith("oda2_") and "▶" not in line:
        if any(event in line for event in ("CaDone(", "CallState(", "Answered(", "Consent(")):
            return 0
    if lemma.startswith("executable") or lemma.startswith("deniability_witness"):
        if "∥" in line:
            return -4
        if re.search(r"!KU\( ~", line):
            return -3
        if "DisplayRecipient(" in line or "Displayed(" in line:
            return 0
    if "▶" in line:
        return 1
    if re.search(r"!KU\( ~", line):
        return 2
    if re.search(r"!KU\( 'g'\^", line):
        return 3
    if "∥" in line:
        return 4
    return 5


for goal in sorted(goals, key=priority):
    identifier, separator, _ = goal.partition(":")
    if separator and identifier.strip().isdigit():
        print(identifier.strip())
