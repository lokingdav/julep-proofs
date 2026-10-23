# Julep Tamarin models and proofs

Tamarin models of the Julep call-authentication protocols and the records of their verification. Three theories cover Number Pairing (`julep_pairing.spthy`), Call Authentication (`julep_auth.spthy`), and Identity Claim Verification (`julep_oda.spthy`). A fourth, `julep_ratchet_regression.spthy`, isolates the key-derivation comparison described in `MODELING_FINDINGS.md`.

- `review/RESULTS.md` lists every lemma with its plain-language meaning and recorded verdict.
- `MODELING_FINDINGS.md` explains what the modeling helped fix and keeps the supporting diagnostic checks.
- `ABSTRACTIONS.md` is the technical reference for modeling assumptions and limits, including the derivability audit.
- `lemma_explanations.json` is the catalog the results report was generated from.
- `review/evidence/` holds the selected final run log for every lemma, the exact oracle versions used, the source snapshots, the audit logs, and `MANIFEST.json` with their hashes.

## Requirements

Tamarin 1.12.0, Maude 3.5.1, Python 3, and Bash on PATH. Every proof is run with a heap cap and a timeout; the defaults are 4 GiB and 180 s per lemma with 2 threads. Running the whole suite with `--jobs 3` needs about 12 GiB of prover heap.

## Reproduce

```sh
bash prove.sh julep_auth.spthy auth1_caller_authentication 120   # one lemma
bash prove.sh julep_pairing.spthy share_A_secret 120
bash finish.sh --jobs 3 --timeout 180 --threads 2 --heap 4        # every lemma of every theory
bash collect.sh                                                   # compact table; exits nonzero if anything is pending
python3 -m unittest test_workflow -v
```

`prove.sh` takes `theory [lemma] [timeout_seconds] [threads] [heap_GB]` and selects the goal-ordering oracle and search strategy for the few lemmas that need them. `sweep.sh theory.spthy` runs one theory. For an explicit strategy:

```sh
python3 workflow.py run julep_oda.spthy executable \
  --heuristic o --oracle oracle.py --search SEQDFS --timeout 180 --threads 2 --heap 4
```

The oracle only orders goals. It neither proves goals nor removes proof cases. Lemmas whose names end in `_expected_falsified` are negative controls; the runner expects Tamarin to find their counterexample. Wall-clock times vary with machine load.

## How results are recorded

Each run writes its exact source snapshot, SHA-256, prover version, command, oracle hash, expected verdict, process status, and full log under `logs/review/<source-hash>/`. `collect.sh` counts only records whose source hash matches the current theories, rejects conflicting verdicts, requires verified helper dependencies, and exits nonzero while any lemma is pending. A process that exits zero without the requested verdict is a failure, as are timeouts, heap exhaustion, and incomplete proofs.

`--derivcheck-timeout=0` disables Tamarin's automated derivability check during proof search. The separate derivability audits in `review/audits/` and the manual review of intentional verification patterns are described in `ABSTRACTIONS.md`. A skipped derivability check is not a clean automated audit.

`review/audits/VALIDATION.json` records the well-formedness, derivability, workflow-test, and prover self-test audits with the hashes of the sources they ran against. For this release the paper-build audit and the hashes of the paper sources were removed; nothing else in the record changed.

`watchdog.sh` is an optional memory backstop that stops only prover processes started by this workflow.
