# What the modeling helped us fix

The modeling helped us identify a key-update attack, make protocol requirements explicit, and correct models that did not accurately represent the paper. This document records **the problem, how it was identified, what changed, and what the evidence establishes**. The [current results](review/RESULTS.md) describe the protocol’s guarantees; the [supporting verification checks](#supporting-verification-checks) below retain the experiments supporting these findings.

Alice is the caller and Bob is the recipient. Their **shared key** encrypts an exchange; their **device private keys** authenticate messages. An attacker can learn the shared key without learning those device private keys.

| Finding | What changed | How it was identified |
|---|---|---|
| Alice and Bob could accept an exchange but calculate different next keys | Derive the next key from the authenticated message contents and signatures | Reproduced attack and comparison of both calculations on the same exchange |
| Authentication needed to identify the particular shared state being used | Include a state-and-index value inside the signed request and check it at the receiver | Review of what the signed message actually binds; agreement verified with the complete change |
| Pairing messages needed unambiguous types | Add `rsp` and `fin` tags and reject incorrect tags or malformed fields | Documented prototype reflection finding and model/specification comparison |
| Pairing proofs relied on unstated cryptographic requirements | Require valid key-exchange inputs and encryption resistant to ciphertext manipulation | Audit of the assumptions granted by the symbolic model |
| Credential exchanges needed explicit state and refusal handling | Use the current authenticated-call state; represent and display refusal; advance state independently of credential acceptance | Comparison of protocol prose, figures, and model; successful sharing and refusal scenarios |
| A shared-key theft needed to follow actual storage and account for fresh DH updates | Reveal only a currently retained key; prove the fresh DH contribution and secrecy of each replacement | Review of the compromise rule and completed key-secrecy and transport proofs |
| The identity-confidentiality statement confused calling with answering | State the disclosure rules separately for each role | Reproduced counterexample to the answer-only formulation |
| Some modeled cryptographic operations or verifiers were incomplete | Add attacker operations, encryption randomness, and complete field binding | Model review followed by verification of the relevant claims |
| Proof collection could overstate what had been established | Bind results to exact sources and require completed supporting proofs | Workflow tests for missing, conflicting, stale, and incomplete evidence |
| The model published the owner's identity with every delegation | Publish only the delegation signature; release the token through an explicit delegate-compromise event; record the owner's identity as sent under the call key | Independent review comparing the Delegate rule with the delegation figure |
| Forward secrecy, credential-exchange authentication, and caller authorization were provable but unproven | Strengthen the key-secrecy helpers to before-derivation exposure; add ICV authentication and agreement, the CA delegation chain, and direct caller authorization; add a diagnostic for a fabricated pairing response | Independent review probes verified on copies, then ported |

## 1. Preventing different next keys after an accepted exchange

**The problem.** The key calculation used the encrypted request and response bytes. Those bytes can change even when their authenticated contents do not.

Suppose an attacker learns Alice and Bob’s current shared key `K`, while both device private keys remain secret. The attacker can decrypt and re-encrypt a message using a different encryption nonce—the fresh randomness that makes encryptions differ. The attacker does not need to change the message or forge its signature.

One way the attack works is:

1. Alice signs her request and encrypts it as `C_A`. She saves that ciphertext for the key calculation.
2. The attacker opens `C_A` using `K` and re-encrypts the **same request and signature** with different randomness, producing `C_A′`.
3. Bob opens `C_A′`. Alice’s signature still verifies, so Bob accepts the request and answers with ciphertext `C_B`.
4. Alice accepts Bob’s answer. Both parties have accepted the same authenticated contents, but their saved request ciphertexts differ.

```mermaid
sequenceDiagram
    participant A as Alice
    participant E as Attacker, knows K
    participant B as Bob
    A->>E: C_A: encrypted signed request
    E->>B: C_A′: same signed request, different encryption randomness
    Note right of B: Alice's signature verifies
    B->>A: C_B: encrypted signed answer
    Note over A,B: Alice saved C_A; Bob received C_A′
```

With ciphertext bytes as inputs, they calculate:

```text
Alice: K_A = KDF(K, idx, C_A,  C_B, DH)
Bob:   K_B = KDF(K, idx, C_A′, C_B, DH)
```

Here, `idx` identifies the exchange and `DH` is the shared secret calculated from their fresh key-exchange contributions. Even with the same `K`, `idx`, and `DH`, the differing ciphertext input produces different next keys. Subsequent messages then cannot be decrypted using the peer’s stored key.

**How the modeling helped.** Representing encryption with an explicit nonce allowed the attacker to re-encrypt an unchanged payload. A deterministic encryption representation could not express this distinction. The focused experiment calculates both candidate key updates on the same exchange: Tamarin found an execution in which the ciphertext-based calculation disagrees and the authenticated-content calculation agrees.

**What changed in the protocol.** Call authentication and on-demand credential exchange derive the next key from a canonical encoding of the authenticated request and response, including their signatures:

```text
K_next = KDF(K, idx, m_A, signature_A, m_B, signature_B, DH)
```

A canonical encoding means both devices encode these fields in one specified, unambiguous way. Re-encrypting the same payload leaves every input to this calculation unchanged. Encryption continues to use fresh randomness.

The protocol also includes the state binding explained in the next section. Together, these changes are reflected in the call-authentication figure, credential-exchange figure, and protocol notation.

**Evidence and scope.** The [focused comparison](julep_ratchet_regression.spthy) contains the reproduced discrepancy and a verified agreement statement. More importantly, `auth2_key_agreement_with_exposed_state` in the [full authentication model](julep_auth.spthy) verifies: if Alice stores a next key, Bob has already stored the same next key for that exchange, even when the starting shared key is exposed, provided the relevant device keys stay private.

This establishes **key agreement**. The attack does not establish that the attacker learns the next key, and the agreement proof does not establish recovery of key secrecy. The credential protocol uses the same construction; `icv_key_agreement` in the ODA model verifies that the requester's replacement key was already derived by the prover, also under exposure of the current shared key. The result supports the paper’s S5 key-refresh objective without proving all of S5.

## 2. Binding a signed request to the particular shared state

**The issue.** A valid signature identifies authenticated contents. To protect an exchange after shared-key exposure, those contents must also identify which stored state the sender used. Encryption alone cannot supply that assurance once the attacker can open messages and encrypt them under another exposed key.

**What changed.** Each authentication and credential request now includes:

```text
eta = H("ratchet", current_shared_key, exchange_index)
```

The sender signs `eta` as part of the request. The receiver recomputes it from its own state and index and rejects a mismatch. The response’s existing hash of the signed request also binds the response to this context.

An attacker who knows the shared keys can calculate candidate `eta` values, but cannot replace the signed value without a valid message-authentication signature under the required device keys.

**How the modeling helped.** Examining the signed fields exposed the need to distinguish state instances, including multiple states involving the same devices. The full authentication model permits unbounded state setups and verifies agreement with both this binding and the authenticated-content key calculation in place. This is evidence for the combined construction; the retained focused re-encryption experiment is not a separate proof of an attack on a construction missing only `eta`.

**Where it changed:** request construction and checking, credential requests, and [the model’s state-binding explanation](ABSTRACTIONS.md).

## 3. Giving pairing messages distinct types

**The problem.** The two encrypted pairing messages had different meanings but no explicit message-type tag. An attacker can replay a ciphertext at another protocol step. The documented prototype found a reflection case in which the untyped model accepted a message in the wrong role.

**What changed.** The paper and model use distinct encrypted plaintexts:

```text
Bob's response:          ("rsp", Bob's enrollment proof, B)
Alice's final message:   ("fin", A, B)
```

Each receiver requires the expected tag and field types. Bob also checks that the returned `B` equals the value he sent. A response cannot be accepted as a final message merely because some of its fields fit.

**Evidence and scope.** The modeling plan records the prototype reflection finding. The original prototype attack trace is not in the retained evidence bundle. The [current pairing model](julep_pairing.spthy) verifies recipient agreement, protection against duplicate completion, and the stated pairing-key secrecy properties with the tags in place. The pairing figure now requires the same checks. Alice’s pairing state remains provisional until call authentication confirms her peer; tags do not change that design boundary.

## 4. Making the pairing proof’s cryptographic assumptions explicit

**The issue.** A symbolic model can grant stronger guarantees than the paper requires from an implementation. The review identified two requirements that needed to be stated explicitly.

- **Validate received key-exchange values.** The pairing model assumes valid, non-identity group elements. The paper now requires the corresponding group, subgroup, and encoding checks before a received value is used. The identity element is a special value that would remove the intended fresh secret contribution from the key-exchange calculation.
- **Require encryption resistant to ciphertext manipulation.** Pairing relies on an attacker being unable to turn an encrypted message into a related accepted message without the necessary plaintext knowledge. Confidentiality alone does not establish that property. The paper now requires chosen-ciphertext security/non-malleability while retaining its separate key-privacy requirement.

These are **assumption and specification fixes identified by reviewing the model**, not independently reproduced attacks against a concrete encryption library. They align the implementation requirements with what the pairing proof assumes. A chosen implementation still needs a separate justification that it meets those requirements.

**Where it changed:** cryptographic requirements, input-validation and encoding requirements, and pairing receive steps. The exact abstractions are documented in [ABSTRACTIONS.md](ABSTRACTIONS.md).

## 5. Making credential sharing and refusal follow the intended call state

**The issues.** The review found gaps between the prose, the figures, and the executable model:

- Credential exchange needed to explicitly require a completed call-authentication step and use the current state for that call. Repeated credential rounds need the most recently persisted key.
- The refusal case needed a defined empty presentation and a displayed refusal outcome.
- The requester model required a valid credential presentation before completing its response handling. That excluded the paper’s intended refusal path.

**What changed.** The figure explicitly loads the current authenticated-call state, initially the key from call authentication and subsequently the key from the latest credential round. It initializes the presentation to empty, fills it only with consent, and displays a refusal when it is empty. It also deletes the key actually used for that round.

The model authenticates the response and advances its state before separately checking and displaying the credential evidence or refusal. A credential’s acceptance is therefore not a prerequisite for handling an authenticated refusal.

**Evidence and scope.** The [ODA model](julep_oda.spthy) verifies that accepting or sharing evidence follows call authentication, recipient sharing follows answering, and sharing follows consent. It also demonstrates complete sharing and refusal scenarios (`executable` and `executable_declined`). These scenarios show that the paths are possible; they do not prove that every exchange completes or that all resulting keys agree. The model separately proves replacement-key secrecy and presentation transport confidentiality, including when the attacker remembers a key stolen during another round. Credential generation and validation belong to the assumed external component. The combined recipient check follows from the answer rule and transport confidentiality; it adds no independent requirement.

**Where it changed:** the credential protocol figure, credential flow description, and [ODA model](julep_oda.spthy). This addresses Objective 3 and the consent/disclosure part of S1.

### Shared-key theft, deletion, and the fresh DH contribution

**The modeling issue.** A persistent record of every generated key allowed the compromise rule to reveal a key even after both devices had deleted it. That did not represent the protocol’s storage policy. Separately, the proof search tried to establish presentation confidentiality without an explicit chain of supporting results for the fresh DH secret and replacement key, repeatedly expanding preceding exchanges until it timed out.

**What changed in the ODA model.** Each device has one current shared key per modeled exchange. An update removes that key from its retained state and installs the replacement. The compromise rule can reveal a key only while a device still retains it. The attacker remembers any key already stolen, even after both devices delete their copies. A successful execution after key theft confirms that the model permits continued processing.

**What the proof establishes.** Suppose the attacker steals K1 and decrypts the first credential round. Seeing the two public DH contributions still does not reveal their shared DH secret. The authenticated exchange supplies that fresh secret to the derivation of K2, so K1 and the transcript alone do not reveal K2. Tamarin now proves this for the CA prefix and successive credential updates, provided the replacement key and relevant long-term private keys remain unexposed and temporary DH secrets are unavailable. It then proves confidentiality of a presentation encrypted under such a key. A presentation encrypted under the stolen K1 is outside that guarantee; K2 protects subsequent traffic.

**Protocol impact.** This resolution required correcting the compromise model and adding proved supporting statements and proof-search guidance. It required no further change to the protocol’s fresh-DH update. The existing authenticated-transcript derivation and state binding described in Sections 1–2 remain part of the verified protocol. Credential-system correctness is still assumed, and the result does not cover compromise that also exposes temporary DH secrets or long-term authentication keys.

## 6. Correcting the identity-confidentiality statement

**The problem in the statement.** Requiring every learned identity to have been preceded by that person answering a call ignores the same person’s caller role. Alice can send her identity when placing a call. If the matching shared key is exposed, an attacker can read it even if nobody answers.

**How the modeling helped.** Tamarin demonstrated that scenario without device-key theft, separate identity exposure, or delegation. It therefore identified an incorrect universal statement, rather than a reason to prohibit normal caller disclosure.

**What changed.** The proof statements now separately check permitted disclosure routes, recipient identity transmission only at answer, and secrecy of the transmitted identity until the matching encryption key is exposed, with explicit identity exposure and public delegation treated separately.

This was a **claim correction**, not a change to the protocol’s rule for answering. The [authentication model](julep_auth.spthy) verifies the role-specific statements, and [the results](review/RESULTS.md#call-authentication-knowing-who-called-and-who-answered) explain their S1 scope. Guessing real-world identities is outside these symbolic proofs.

## 7. Correcting the models and the evidence workflow

These changes made the analysis more faithful. They should not be counted as additional attacks on the protocol.

| Correction | Why it mattered | What changed |
|---|---|---|
| Model encryption randomness | Re-encryption had to be possible to expose the key-mismatch attack | Use nonce-bearing authenticated encryption with associated data and explicit attacker encryption operations |
| Include the message-authentication scheme’s receiver capability | A model that omits relevant forgery capabilities can overstate authentication | Allow attacker message creation with the required sender or receiver secret; bind verification to the message, sender, designated receiver, and authority |
| Represent credential and enrollment proofs faithfully | Public token holders must be able to produce proofs; a successful verification must check the right statement and challenge | Add explicit attacker proof generation, randomized proof representations, and complete verification relations |
| Bind enrollment-token fields consistently | A received phone-number field must be the number covered by the issuer’s signature | Match every relevant field against the trusted issuance record in the authentication verifier |
| Diagnose proof-search limits correctly | A timeout does not establish a primitive defect or protocol attack | Use bounded runs, independently verified supporting lemmas, and goal ordering that preserves the permitted executions |
| Collect trustworthy results | A process exit or a proof from different source files is insufficient evidence | Record source hashes and full logs; reject missing/conflicting verdicts; require completed supporting proofs; preserve unresolved checks |

The [delegated-pairing existence check](julep_pairing.spthy#L184) was resolved by changing the proof-search strategy in the runner. The [pairing forward-secrecy claim](julep_pairing.spthy#L200) was resolved by prioritizing checks of where DH values originated before expanding further exchanges. Tamarin then proved that later theft of long-term private keys does not reveal Bob’s completed pairing key. This exposure does not include the stored pairing key or temporary DH secrets. Both changes affect only the search order: the model, cryptographic assumptions, and statements remained unchanged, and neither check required a protocol modification.

The [abstraction audit](ABSTRACTIONS.md) explains the cryptographic representations, including why matching a secret inside a verification pattern does not itself disclose it. The [workflow](README.md#review-workflow) and [run manifest](review/MANIFEST.json) record how the evidence was obtained.

## 8. Stating the guarantees the models already support

**The issues.** An independent review on 2026-09-19 compared each lemma with the paper's figures and prose and found four places where the suite said less than the models support, and one where it mis-described the protocol.

- The `Delegate` rule handed the attacker the whole delegation token, including the owner's identity. The protocol never publishes that identity: pairing sends only `dlgt = (ex_D, ipk_D, sigma_D)`, and the token travels to the delegate and then inside encrypted call messages. Because the identity was public, both identity-confidentiality statements needed an unconditional "the owner delegated" exception and therefore said nothing about delegating owners.
- The ODA key-secrecy helpers excused a long-term-key reveal anywhere in the execution, so S5's forward-secrecy clause was machine-checked only for Bob's pairing key.
- The credential exchange had no authentication or key-agreement statement, although the paper describes it as authenticated and non-desynchronizing.
- The owner-authorization sentence for delegated calls was proved only in the pairing model, and no lemma stated caller authorization for a directly enrolled key at pairing.
- Alice's provisional pairing key was described without saying when it is forward secret.

**What changed in the models.** `Delegate` now outputs only the public delegation material; `Reveal_Dtk` models a compromised delegate disclosing the token; `CA_A1_delegated` records the owner's identity as sent under the call key; the two identity statements replace the delegation exception with that explicit compromise event. ODA's `authenticated_share_origin`, `dh_shared_secret`, and `derived_key_secret` now excuse only long-term-key exposure before the derivation, with the ordered helper `ltk_secret_ordered`. New statements: `icv_request_authentic`, `icv_display_authentic`, `icv_key_agreement` (ODA); `del1_delegation_chain` with helpers `dlg_key_secret` and `dlg_sig_origin` (authentication); `pair_caller_key_authorized` and `pair_K_forward_secret_A_genuine` (pairing); existence checks `executable_delegated_full`, `executable_caller_prover`, `executable_two_rounds`; and the diagnostic `pair_K_forward_secret_A_expected_falsified`, which reproduces the one case where a provisional key is not forward secret: a response fabricated from Bob's public token followed by a later exposure of Bob's decryption key.

**What the evidence establishes.** Every prior statement still verifies. The identity-confidentiality results now cover delegating owners. Forward secrecy against later long-term-key exposure holds for Bob's pairing key, for Alice's pairing key whenever Bob sent the accepted response, and for every CA/ICV replacement key in the ODA model. The credential exchange is authenticated and both parties agree on its replacement key even when the current shared key is exposed. No protocol change was needed.

## What this record does not claim

The caller-side pairing diagnostic also completes after a change in goal ordering and a search for a short counterexample. Tamarin reaches Alice’s unconfirmed pairing state using an adversary-generated token proof and response, without a matching prior Bob response or relevant long-term-key exposure. This confirms an intended limit of pairing and required no change to its model or protocol. Alice deliberately simulating a transcript with her own keys is the related deniability argument. The diagnostic concerns an honest Alice processing an attacker-supplied response; it does not compare genuine and simulated transcripts or prove S3. The authentication results likewise concern honest protocol execution, while the designated judge is the exception to the paper’s transcript-deniability guarantee.

The recipient’s rejection of a delegate-only credential and Alice’s provisional pairing state were already present when this review began; they are checked protections, not additional protocol changes introduced here. The main reproduced protocol defect in this review is the ciphertext-dependent key mismatch. The remaining entries identify explicit requirements, specification/model alignment, or corrections to the statements and evidence.

All declared protocol and diagnostic checks have their expected outcomes; [RESULTS.md](review/RESULTS.md) maintains their current status. Conditional replacement-key secrecy is proved in ODA. Full lifecycle composition, recovery after long-term or temporary-secret theft, and general ODA key agreement remain outside the completed proofs. The separate derivability audit has manual assumptions and inconclusive time limits, as recorded in [ABSTRACTIONS.md](ABSTRACTIONS.md); that is not a pending protocol lemma.

<!-- BEGIN GENERATED VERIFICATION CHECKS -->
## Supporting verification checks

These checks support the findings above by testing key calculations and the limits of proposed guarantees. The protocol’s security results are in [RESULTS.md](review/RESULTS.md).

**7 diagnostic checks**: **7 checks passed**, **0 unresolved or unexpected**.

**Check passed: counterexample reproduced** means the expected violating execution was found; the statement it contradicts is false. **Proved in model** and **Proved: execution exists** have the meanings given in [RESULTS.md](review/RESULTS.md#how-to-read-the-results). A timeout remains unresolved even when a counterexample is expected.

| Diagnostic check (links to formal statement) | Statement in everyday language | What it checks | Paper requirement / objective | Result |
|---|---|---|---|---|
| [Whether Alice’s saved pairing key confirms that Bob replied](julep_pairing.spthy#L239) | If Alice saves a pairing key under Bob’s number, Bob must previously have sent a response to that pairing request, for the same numbers, timestamp, and device keys, provided neither device’s long-term keys are ever exposed. | Tamarin found an execution where a response constructed using a public enrollment token lets an honest Alice save an unconfirmed pairing key without a matching prior reply from Bob. This tests what an outside attacker can cause during pairing. Alice simulating a transcript with her own secrets is the related deniability argument; this one execution does not prove that genuine and simulated transcripts are indistinguishable. | Objective 1 — Number authorization<br>S3 — Call Deniability<br>Confirms the intended limit of unconfirmed pairing, consistent with deniability. It proves neither the full simulation claim nor indistinguishability of genuine and simulated transcripts.<br>Model claim: C-PAIR-2, C-AUTH-6 | Check passed: counterexample reproduced |
| [Whether Alice’s provisional key is forward secret when the response may be fabricated](julep_pairing.spthy#L247) | If Alice saves a provisional pairing key, the attacker never learns it unless a relevant long-term key was exposed before she saved it. | Tamarin found the expected execution: an attacker fabricates Bob’s response from Bob’s public enrollment token with its own share, Alice saves a provisional key, and a later exposure of Bob’s decryption key lets the attacker read Alice’s recorded final message, recover her share, and compute the key. The candidate is discarded at fallback and Bob never holds it; genuine pairings are covered by pair_K_forward_secret_A_genuine. | S5 — Forward & Backward Security<br>Records the limit of forward secrecy for an unconfirmed pairing candidate, so the guarantee is stated precisely.<br>Model claim: C-PAIR-1 | Check passed: counterexample reproduced |
| [Test variant: every identity disclosure requires an answer](julep_auth.spthy#L245) | If the attacker learns an enrolled identity, that person must previously have answered a call, unless their identity or long-term keys are exposed, or a delegate device holding their delegation token is compromised, somewhere in the execution. | This test deliberately excludes the caller-disclosure route from its statement. A caller can send an identity without answering, and an attacker can read it after the matching shared key is exposed. | S1 — Identity Confidentiality<br>Boundary test for S1: checks that an answer-only formulation fails to account for caller disclosure.<br>Model claim: C-AUTH-4 | Check passed: counterexample reproduced |
| [The focused attack does not rely on stealing device private keys](julep_ratchet_regression.spthy#L63) | The attacker never learns either private device key created for the focused exchange. | Keeps the experiment about exposure of the shared exchange key, rather than exposure of the keys that authenticate the devices. | S5 — Forward & Backward Security<br>Objective 1 — Number authorization<br>Supporting check that the key-update experiment isolates shared-key exposure while device keys remain private.<br>Model claim: C-AUTH-2 | Proved in model |
| [Test variant: key derivation from ciphertext bytes gives matching keys](julep_ratchet_regression.spthy#L67) | Whenever Alice finishes using ciphertext bytes to derive the next key, Bob previously calculated the same next key from the same starting shared key, even if that starting shared key is exposed. | The test seeks an exchange in which re-encryption changes the bytes used by one side and the resulting keys differ. The protocol’s key calculation uses authenticated contents. | S5 — Forward & Backward Security<br>Objective 1 — Number authorization<br>Tests the ciphertext-based variant under state exposure; disagreement demonstrates a key-update defect, not disclosure of the next key.<br>Model claim: C-AUTH-2 | Check passed: counterexample reproduced |
| [Key derivation from authenticated contents gives matching keys](julep_ratchet_regression.spthy#L71) | Whenever Alice finishes using authenticated contents to derive the next key, Bob previously calculated that same next key from the same starting shared key, even if the attacker learns the starting shared key. | Checks agreement in this focused experiment with device private keys kept secret. The full authentication model checks agreement with the complete call messages. | S5 — Forward & Backward Security<br>Objective 1 — Number authorization<br>Focused check of key-update agreement, supporting the refresh used by S5; it does not prove recovery of secrecy.<br>Model claim: C-AUTH-2 | Proved in model |
| [The same exchange distinguishes the two key calculations](julep_ratchet_regression.spthy#L75) | There is an execution where the starting shared key leaks before Alice finishes, Bob finishes before Alice, ciphertext-based key derivation gives them different next keys, and derivation from authenticated contents gives them the same next key. | Demonstrates the different outcomes of both calculations on the same exchange. | S5 — Forward & Backward Security<br>Objective 1 — Number authorization<br>Existence check: compares ciphertext-based and authenticated-content key agreement; it does not establish S5.<br>Model claim: C-AUTH-2 | Proved: execution exists |

This appendix is regenerated by `python3 export_evidence.py`; the findings above are preserved. [MANIFEST.json](review/MANIFEST.json) and [evidence.tar.gz](review/evidence/) retain the complete proof records for these checks and the protocol results.

Full-suite collector exit code: `0`. It remains nonzero while any check is unresolved or unexpected.

<details>
<summary>Original lemma IDs, exact verdicts, proof steps, and run times</summary>

| Theory | Lemma | Verdict | Steps | Run seconds |
|---|---|---|---:|---:|
| julep_pairing | `pair_agreement_A_expected_falsified` | falsified | 26 | 27.26 |
| julep_pairing | `pair_K_forward_secret_A_expected_falsified` | falsified | 35 | 31.02 |
| julep_auth | `auth4_recipient_identity_confidentiality_expected_falsified` | falsified | 10 | 28.91 |
| julep_ratchet_regression | `private_keys` | verified | 9 | 0.97 |
| julep_ratchet_regression | `legacy_agreement_expected_falsified` | falsified | 11 | 1.97 |
| julep_ratchet_regression | `corrected_agreement` | verified | 6 | 0.82 |
| julep_ratchet_regression | `executable_reencryption` | verified | 15 | 1.92 |

</details>
<!-- END GENERATED VERIFICATION CHECKS -->
