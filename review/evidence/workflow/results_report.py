"""Render protocol explanations alongside dependency-checked proof outcomes."""
from collections import Counter
import json
from pathlib import Path
from os.path import relpath
import re

import workflow

HERE = Path(__file__).resolve().parent
GROUPS = {
    "claim": "Protocol claims",
    "counterexample": "Boundary and variant checks",
    "example": "Checks that an execution is possible",
    "helper": "Supporting checks used by the proofs",
}
DECLARATION = re.compile(r"^lemma\s+(\w+)(?:\s*\[[^]]*\])?\s*:\s*(exists-trace)?", re.M)


# S1-S6 are the paper's numbering. The objective keys are report identifiers,
# not additional security requirements invented for the paper.
PAPER_ROOT = HERE.parents[1]
REQUIREMENTS_SOURCE = "sections/problem-statement-v2.tex"
CLAIMS_SOURCE = "tamarin/modeling/03-security-claims.md"
REFERENCE_FILES = tuple(dict.fromkeys((
    REQUIREMENTS_SOURCE, CLAIMS_SOURCE,
    "sections/background.tex", "sections/design-approach.tex", "sections/protocol.tex",
    "sections/adversarial-robustness.tex", "sections/formal-verification.tex",
    *(str(p.relative_to(PAPER_ROOT)) for p in sorted((PAPER_ROOT / "figures/protocols").glob("*.tex"))),
    *(str(p.relative_to(PAPER_ROOT)) for p in sorted((PAPER_ROOT / "tamarin/modeling").glob("*.md"))),
    "tamarin/proofs/ABSTRACTIONS.md", "tamarin/proofs/README.md",
)))
PAPER_TARGETS = {
    "S1": dict(
        title="S1 — Identity Confidentiality", marker=r"\item \myparagraph{\em \reqIdentitySecrecy}",
        meaning="Reveal a person’s identity only with that person’s authorization.",
        scope="Identity-disclosure, answer, consent, and secrecy checks address parts of this requirement. Candidate-identity guessing and privacy of credential attribute values are outside these models."),
    "S2": dict(
        title="S2 — Call Pair Unlinkability", marker=r"\item \myparagraph{\em \reqPairSecrecy}",
        meaning="Hide who communicated with whom and whether calls involve the same pair, subject to the paper’s first-contact and network-metadata exceptions.",
        scope="Not established by this suite. Keeping a key or identity secret alone does not prove that calls cannot be linked."),
    "S3": dict(
        title="S3 — Call Deniability", marker=r"\item \myparagraph{\em \reqDeniability}",
        meaning="Let call parties deny participation to third parties other than the designated law-enforcement authority.",
        scope="Not established by this suite. Modeling the ability to fabricate some messages is not a deniability proof."),
    "S4": dict(
        title="S4 — Call Accountability", marker=r"\item \myparagraph{\em \reqAccountability}",
        meaning="Let the designated law-enforcement authority confirm participation from the required call transcripts.",
        scope="Not established by this suite. The authority’s report-verification procedure is not modeled here."),
    "S5": dict(
        title="S5 — Forward & Backward Security", marker=r"\item \myparagraph{\em \reqForwardBackwardSecurity}",
        meaning="Protect past authentication messages after device-key theft, and restore secrecy after a completed authenticated refresh following shared-key exposure.",
        scope="Pairing-key secrecy, including after later theft of long-term private keys, authentication key agreement, and secrecy of replacement keys in the ODA model support this requirement. Replacement-key secrecy permits theft of other shared keys but excludes exposure of the target key, relevant long-term keys, and temporary DH secrets. These are component guarantees, not a proof of the full protocol lifecycle."),
    "S6": dict(
        title="S6 — Access Throttling", marker=r"\item \myparagraph{\em \reqRateLimit}",
        meaning="When enabled, cryptographically limit access without tracking users.",
        scope="Not established by this suite; rate-token issuance and spending are outside these protocol models."),
    "objective-1": dict(
        title="Objective 1 — Number authorization", marker="We have four objectives for",
        meaning="Let both call parties verify authorization to use their numbers, including authorized delegation.",
        scope="Pairing agreement, caller/recipient authentication, and delegation checks address this design objective. The paper does not assign it a separate S-number."),
    "objective-3": dict(
        title="Objective 3 — Additional credential requests", marker="We have four objectives for",
        meaning="Let either party request additional evidence during the call.",
        scope="Authentication, answer, consent, and existence checks address the credential flow. Disclosure control and transport confidentiality also support S1. Credential generation and validation are assumed external operations. The paper does not assign this objective a separate S-number."),
}


def paper_references(*, relative_to=None):
    """Link to current source lines rather than storing line numbers that drift."""
    directory = HERE / "review" if relative_to is None else Path(relative_to)
    requirement_path = relpath(PAPER_ROOT / REQUIREMENTS_SOURCE, directory)
    claim_path = relpath(PAPER_ROOT / CLAIMS_SOURCE, directory)
    source = (PAPER_ROOT / REQUIREMENTS_SOURCE).read_text()
    targets = {}
    for name, entry in PAPER_TARGETS.items():
        marker = entry["marker"]
        if source.count(marker) != 1:
            raise ValueError(f"Paper reference is missing or ambiguous: {name}")
        line = source.count("\n", 0, source.index(marker)) + 1
        targets[name] = f"[{entry['title']}]({requirement_path}#L{line})"
    claim_source = (PAPER_ROOT / CLAIMS_SOURCE).read_text()
    claims = {}
    for match in re.finditer(r"^\*\*(C-[A-Z]+-\d+)\s", claim_source, re.M):
        line = claim_source.count("\n", 0, match.start()) + 1
        claims[match[1]] = f"[{match[1]}]({claim_path}#L{line})"
    return targets, claims


def requirement_cell(entry, target_links, claim_links):
    mapping = entry["paper"]
    targets = "<br>".join(cell(target_links[t]) for t in mapping["targets"])
    claims = ", ".join(claim_links[c] for c in mapping["claims"])
    return targets + "<br>" + cell(mapping["role"]) + "<br>Model claim: " + claims


def result_label(row, category):
    verdict = row["verdict"]
    # A local verdict is not a checked result while dependencies are pending.
    if "dependencies pending:" in verdict:
        return "Unresolved: supporting checks pending"
    if verdict == "verified":
        if category == "example":
            return "Proved: execution exists"
        if category == "counterexample":
            return "Check failed: expected counterexample not found"
        return "Proved in model"
    if verdict == "falsified":
        if category == "counterexample":
            return "Check passed: counterexample reproduced"
        if category == "example":
            return "No such execution exists in the model"
        return "Counterexample found"
    if verdict == "CONFLICT":
        return "Unresolved: conflicting results"
    return "Unresolved: " + verdict


def checked_catalog(theories, rows):
    catalog = json.loads((HERE / "lemma_explanations.json").read_text())
    sources = {Path(p).stem: Path(p).read_text() for p in theories}
    if set(catalog) != set(sources):
        raise ValueError("Theory explanations do not match the requested sources")
    target_links, claim_links = paper_references()
    positions = {}
    row_keys = [(r["theory"], r["lemma"]) for r in rows]
    for theory, source in sources.items():
        declarations = {m[1]: m for m in DECLARATION.finditer(source)}
        entries = catalog[theory]["lemmas"]
        if set(entries) != set(declarations):
            raise ValueError(f"Lemma explanations do not match {theory}: {set(entries) ^ set(declarations)}")
        for name, entry in entries.items():
            match = declarations[name]
            if entry["category"] not in GROUPS:
                raise ValueError(f"Unknown explanation category for {theory}/{name}")
            if (entry["category"] == "example") != bool(match[2]):
                raise ValueError(f"Example/claim mismatch for {theory}/{name}")
            if (entry["category"] == "counterexample") != name.endswith("_expected_falsified"):
                raise ValueError(f"Counterexample expectation mismatch for {theory}/{name}")
            if not all(entry.get(field, "").strip() for field in ("title", "statement", "context")):
                raise ValueError(f"Incomplete explanation for {theory}/{name}")
            if entry.get("report") not in ("protocol", "regression"):
                raise ValueError(f"Missing or invalid report classification for {theory}/{name}")
            if entry["category"] == "counterexample" and entry["report"] != "regression":
                raise ValueError(f"Expected-counterexample report assignment must be diagnostic: {theory}/{name}")
            mapping = entry.get("paper", {})
            if not mapping.get("role", "").strip():
                raise ValueError(f"Missing paper-requirement explanation for {theory}/{name}")
            for field, known in (("targets", target_links), ("claims", claim_links)):
                refs = mapping.get(field)
                if (not isinstance(refs, list) or not refs
                        or any(not isinstance(ref, str) or ref not in known for ref in refs)
                        or len(refs) != len(set(refs))):
                    raise ValueError(f"Invalid paper {field} for {theory}/{name}: {refs}")
            positions[theory, name] = source.count("\n", 0, match.start()) + 1
    if len(row_keys) != len(set(row_keys)) or set(row_keys) != set(positions):
        raise ValueError("Collected results do not cover each explained lemma exactly once")
    return catalog, positions


def cell(text):
    return text.replace("|", "&#124;").replace("\n", " ")


FINDINGS_BEGIN = "<!-- BEGIN GENERATED VERIFICATION CHECKS -->"
FINDINGS_END = "<!-- END GENERATED VERIFICATION CHECKS -->"


def check_passed(row):
    expected = "falsified" if row["lemma"].endswith("_expected_falsified") else "verified"
    return row["verdict"] == expected


def explanation_row(theory, name, entry, row, positions, targets, claims, *, source_prefix):
    link = f"{source_prefix}{theory}.spthy#L{positions[theory, name]}"
    cells = [f"[{cell(entry['title'])}]({link})", cell(entry["statement"]),
             cell(entry["context"]), requirement_cell(entry, targets, claims),
             cell(result_label(row, entry["category"]))]
    return "| " + " | ".join(cells) + " |"


def render_report(theories, rows, status):
    catalog, positions = checked_catalog(theories, rows)
    target_links, claim_links = paper_references()
    timeouts = Counter(catalog[r["theory"]]["lemmas"][r["lemma"]]["report"]
                       for r in rows if r["verdict"] == "timeout")
    rows = [r for r in rows if catalog[r["theory"]]["lemmas"][r["lemma"]]["report"] == "protocol"]
    counts = Counter(r["verdict"] for r in rows)
    pending = [r for r in rows if not check_passed(r)]
    lines = [
        "# Current-protocol proof results",
        "",
        "This report covers the current protocol’s claims, supporting proofs, and existence checks. Alice is the caller and Bob is the person being called. For delegated calls, a number’s owner (for example, a business) authorizes another device to call on its behalf.",
        "",
        f"**{len(rows)} current-protocol checks**: " + ", ".join(f"**{n} {verdict}**" for verdict, n in counts.items()) + ". These totals include supporting checks and existence checks; they are not a count of separate security guarantees.",
        "",
        (f"**Timeouts in the full verification suite: {sum(timeouts.values())} total** — "
         f"**{timeouts['protocol']}** among the protocol checks below and "
         f"**{timeouts['regression']}** among the [supporting checks in MODELING_FINDINGS.md](../MODELING_FINDINGS.md#supporting-verification-checks). "
         "These counts concern declared lemmas. Separate derivability-audit warnings/time limits are documented in [ABSTRACTIONS.md](../ABSTRACTIONS.md#derivability-audit) and are not included here. The shared manifest includes all checks."),
        "",
        "## How to read the results",
        "",
        "- **Proved in model:** the statement holds in every execution covered by the model, with the assumptions in the statement and the scope below.",
        "- **Proved: execution exists:** Tamarin proved that at least one execution satisfies all the conditions in the statement. The existence check passes. This establishes that the described behavior is possible in the model; it does not mean that it occurs in every execution.",
        "- **Counterexample found:** an allowed execution violates the stated current-protocol claim; that claim is not proved.",
        "- **Unresolved: timeout:** the search ran out of time. Neither a proof nor a counterexample has been established by that run. Other unresolved labels identify missing runs, unfinished supporting checks, or conflicting results.",
        "",
        "For successful protocol flows, this is an **executability proof**. For example, proving that Alice and Bob can complete authentication establishes that the model permits the stated request, answer, and identity-display steps. The attacker can discard messages, so we cannot promise that every call completes. The successful execution shows that completion is possible when the required messages are delivered. It also checks that the model has not accidentally made the intended flow impossible.",
        "",
        "Some existence checks instead establish that a particular disclosure or compromise scenario is possible. In every case, **Proved: execution exists** proves the statement in that row. Security guarantees that must hold across all allowed executions are checked separately and labeled **Proved in model**.",
        "",
        "A device’s **long-term keys** are its private keys for authenticating or decrypting messages. A **shared key** is the separate secret Alice and Bob use to encrypt a particular exchange. Exposing one is not the same as exposing the other. Where a statement says keys are never exposed, that means throughout the entire modeled execution, including after the call. Statements about later exposure say so explicitly.",
        "",
        "Claim titles below link to the corresponding formal statement. The appendix retains the original lemma IDs, exact verdicts, proof steps, and timings.",
        "",
        "## Scope of these results",
        "",
        "These are checks of separate protocol components under idealized cryptography. The network attacker can intercept, change, replay, and create messages, but can only break the modeled cryptography through the capabilities explicitly provided. Enrollment is trusted. Credential generation and validation are assumed external operations; Julep’s checks concern disclosure control and transport confidentiality. Identity guessing, real expiry/revocation behavior, and implementation bugs are outside these checks. Authentication and credential exchange start with an agreed pairing key; the complete sequence from real pairing through all later exchanges has not been proved as one combined protocol. See [ABSTRACTIONS.md](../ABSTRACTIONS.md) for the precise assumptions and limits.",
        "",
        "## Which paper requirement does each result address?",
        "",
        "The S1–S6 names below come from the paper’s Security & Privacy Requirements. Number authorization and additional credential requests are separate research objectives in the paper, so they retain their objective numbers. Each result’s requirement column names its target and explains whether it checks part of the requirement, supports another proof, checks whether a described execution is possible, or tests a known limitation. A link to a requirement does not mean that the result proves the entire requirement.",
        "",
        "The C-PAIR, C-AUTH, C-DEL, and C-ODA identifiers are claim labels from the [modeling analysis](../../modeling/03-security-claims.md), not the paper’s requirement numbers. The statements and scope in this report define the exact formulations checked for the current protocol. For S5, authentication key agreement and ODA replacement-key secrecy are separate proved properties; the latter permits theft of other shared keys. Credential ordering, consent, and presentation transport confidentiality support S1 under the stated credential-interface assumptions, while attribute values are public inputs.",
        "",
        "| Paper requirement or objective | Meaning in a call | Scope of this suite |",
        "|---|---|---|",
    ]
    for name, target in PAPER_TARGETS.items():
        lines.append("| " + " | ".join((cell(target_links[name]), cell(target["meaning"]), cell(target["scope"]))) + " |")
    lines.append("")
    if pending:
        lines += ["## Checks still unresolved or with an unexpected outcome", ""]
        for row in pending:
            entry = catalog[row["theory"]]["lemmas"][row["lemma"]]
            line = positions[row["theory"], row["lemma"]]
            link = f"../{row['theory']}.spthy#L{line}"
            lines.append(f"- [{entry['title']}]({link}) — {result_label(row, entry['category'])}.")
        lines.append("")
    by_key = {(r["theory"], r["lemma"]): r for r in rows}
    for theory, section in catalog.items():
        selected = {name: entry for name, entry in section["lemmas"].items() if entry["report"] == "protocol"}
        if not selected:
            continue
        lines += ["## " + section["title"], ""]
        for paragraph in section["context"]:
            lines += [paragraph, ""]
        for category, heading in GROUPS.items():
            entries = [(n, e) for n, e in selected.items() if e["category"] == category]
            if not entries:
                continue
            lines += ["### " + heading, "",
                      "| Claim or check (links to formal statement) | Statement in everyday language | Why it matters in the protocol | Paper requirement / objective | Result |",
                      "|---|---|---|---|---|"]
            for name, entry in entries:
                lines.append(explanation_row(theory, name, entry, by_key[theory, name], positions,
                                             target_links, claim_links, source_prefix="../"))
            lines.append("")
    lines += [
        "## Evidence and technical appendix",
        "",
        "Generated by `python3 export_evidence.py` using [lemma_explanations.json](../lemma_explanations.json). The result collector checks the exact current source and all required supporting proofs before a result is labeled proved. See [MANIFEST.json](MANIFEST.json) for hashes, versions, commands, and times, and [evidence.tar.gz](evidence.tar.gz) for source snapshots, full selected logs, workflow files, reports, assumptions, modeling notes, relevant paper sources, and audit logs.",
        "",
        "[MODELING_FINDINGS.md](../MODELING_FINDINGS.md) explains the findings and changes, with their diagnostic results in its [supporting verification checks](../MODELING_FINDINGS.md#supporting-verification-checks). Those checks and this report together account for every declared lemma.",
        "",
        f"Report status: **{'pending or unexpected checks remain' if pending else 'all checks match their expected outcomes'}**. Full-suite collector exit code: `{status}` (includes the supporting checks in MODELING_FINDINGS.md).",
        "",
        "<details>",
        "<summary>Original lemma IDs, exact verdicts, proof steps, and run times</summary>",
        "",
        workflow.result_table(rows).rstrip(),
        "",
        "</details>",
        "",
    ]
    return "\n".join(lines)


def render_findings_appendix(theories, rows, status):
    """Render diagnostic evidence without repeating the findings narrative."""
    catalog, positions = checked_catalog(theories, rows)
    targets, claims = paper_references(relative_to=HERE)
    rows = [r for r in rows if catalog[r["theory"]]["lemmas"][r["lemma"]]["report"] == "regression"]
    pending = [r for r in rows if not check_passed(r)]
    lines = [
        "## Supporting verification checks",
        "",
        "These checks support the findings above by testing key calculations and the limits of proposed guarantees. The protocol’s security results are in [RESULTS.md](review/RESULTS.md).",
        "",
        f"**{len(rows)} diagnostic checks**: **{len(rows) - len(pending)} checks passed**, **{len(pending)} unresolved or unexpected**.",
        "",
        "**Check passed: counterexample reproduced** means the expected violating execution was found; the statement it contradicts is false. **Proved in model** and **Proved: execution exists** have the meanings given in [RESULTS.md](review/RESULTS.md#how-to-read-the-results). A timeout remains unresolved even when a counterexample is expected.",
        "",
        "| Diagnostic check (links to formal statement) | Statement in everyday language | What it checks | Paper requirement / objective | Result |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        theory, name = row["theory"], row["lemma"]
        entry = catalog[theory]["lemmas"][name]
        lines.append(explanation_row(theory, name, entry, row, positions, targets, claims, source_prefix=""))
    lines += [
        "",
        "This appendix is regenerated by `python3 export_evidence.py`; the findings above are preserved. [MANIFEST.json](review/MANIFEST.json) and [evidence.tar.gz](review/evidence.tar.gz) retain the complete proof records for these checks and the protocol results.",
        "",
        f"Full-suite collector exit code: `{status}`. It remains nonzero while any check is unresolved or unexpected.",
        "",
        "<details>",
        "<summary>Original lemma IDs, exact verdicts, proof steps, and run times</summary>",
        "",
        workflow.result_table(rows).rstrip(),
        "",
        "</details>",
        "",
    ]
    return "\n".join(lines)


def update_findings(document, appendix):
    """Replace only the generated appendix, preserving surrounding author text."""
    block = FINDINGS_BEGIN + "\n" + appendix.rstrip() + "\n" + FINDINGS_END
    if FINDINGS_BEGIN not in document and FINDINGS_END not in document:
        return document.rstrip() + "\n\n" + block + "\n"
    if document.count(FINDINGS_BEGIN) != 1 or document.count(FINDINGS_END) != 1:
        raise ValueError("Findings appendix markers are missing or duplicated")
    start, end = document.index(FINDINGS_BEGIN), document.index(FINDINGS_END)
    if end < start:
        raise ValueError("Findings appendix markers are out of order")
    return document[:start] + block + document[end + len(FINDINGS_END):]
