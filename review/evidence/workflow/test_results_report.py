"""Keep human explanations complete and proof outcomes accurately labeled."""
import copy
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import results_report

HERE = Path(__file__).resolve().parent
THEORIES = [HERE / f"julep_{name}.spthy" for name in ("pairing", "auth", "oda", "ratchet_regression")]


def unrun_rows(theories=THEORIES):
    return [dict(theory=p.stem, lemma=m[1], verdict="not run", steps="", seconds="")
            for p in theories for m in results_report.DECLARATION.finditer(p.read_text())]


class ResultsReportTests(unittest.TestCase):
    def test_every_lemma_appears_in_its_assigned_report_with_context_and_links(self):
        rows = unrun_rows()
        reports = {"protocol": results_report.render_report(THEORIES, rows, 2),
                   "regression": results_report.render_findings_appendix(THEORIES, rows, 2)}
        catalog, positions = results_report.checked_catalog(THEORIES, rows)
        for row in rows:
            with self.subTest(theory=row["theory"], lemma=row["lemma"]):
                entry = catalog[row["theory"]]["lemmas"][row["lemma"]]
                report = reports[entry["report"]]
                other_report = reports["regression" if entry["report"] == "protocol" else "protocol"]
                self.assertNotIn(f"`{row['lemma']}`", other_report)
                line = positions[row["theory"], row["lemma"]]
                protocol = entry["report"] == "protocol"
                targets, claims = results_report.paper_references(relative_to=HERE / "review" if protocol else HERE)
                prefix = "../" if protocol else ""
                link = f"[{entry['title']}]({prefix}{row['theory']}.spthy#L{line})"
                self.assertIn(link, report)
                self.assertIn(results_report.cell(entry["statement"]), report)
                self.assertIn(results_report.cell(entry["context"]), report)
                self.assertIn(f"`{row['lemma']}`", report)
                self.assertIn(results_report.requirement_cell(entry, targets, claims), report)
                declaration = (HERE / (row["theory"] + ".spthy")).read_text().splitlines()[line - 1]
                self.assertTrue(declaration.startswith("lemma " + row["lemma"]))

    def test_refresh_findings_preserves_author_text_and_is_idempotent(self):
        narrative = "# Findings\n\nAuthor explanation with [a link](julep_auth.spthy).\n\n"
        appendix = "## Supporting verification checks\n\nGenerated results.\n"
        initial = results_report.update_findings(narrative, "Previous generated content")
        tail = "\nAuthor notes after the appendix.\n"
        updated = results_report.update_findings(initial + tail, appendix)
        self.assertTrue(updated.startswith(narrative))
        self.assertTrue(updated.endswith(tail))
        self.assertNotIn("Previous generated content", updated)
        self.assertIn(appendix, updated)
        self.assertEqual(results_report.update_findings(updated, appendix), updated)
        self.assertEqual(updated.count(results_report.FINDINGS_BEGIN), 1)

    def test_malformed_findings_markers_cannot_overwrite_author_text(self):
        begin, end = results_report.FINDINGS_BEGIN, results_report.FINDINGS_END
        for document in (begin, end, begin + begin + end, end + begin):
            with self.subTest(document=document):
                with self.assertRaisesRegex(ValueError, "markers"):
                    results_report.update_findings(document, "Generated content")

    def test_new_lemma_requires_an_explanation(self):
        with tempfile.TemporaryDirectory() as folder:
            theories = []
            for original in THEORIES:
                path = Path(folder) / original.name
                path.write_text(original.read_text())
                theories.append(path)
            theories[0].write_text(theories[0].read_text().replace('\nend', '\nlemma new_claim: "T"\nend'))
            with self.assertRaisesRegex(ValueError, "Lemma explanations do not match"):
                results_report.render_report(theories, unrun_rows(theories), 2)

    def test_missing_or_duplicate_result_cannot_be_silently_dropped(self):
        rows = unrun_rows()
        for malformed in (rows[:-1], rows + rows[:1]):
            with self.assertRaisesRegex(ValueError, "exactly once"):
                results_report.render_report(THEORIES, malformed, 2)

    def test_example_cannot_be_mislabeled_as_a_security_claim(self):
        catalog = json.loads((HERE / "lemma_explanations.json").read_text())
        bad_catalog = copy.deepcopy(catalog)
        bad_catalog["julep_auth"]["lemmas"]["executable_direct"]["category"] = "claim"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "lemma_explanations.json").write_text(json.dumps(bad_catalog))
            with patch.object(results_report, "HERE", path):
                with self.assertRaisesRegex(ValueError, "Example/claim mismatch"):
                    results_report.render_report(THEORIES, unrun_rows(), 2)

    def test_outcome_labels_distinguish_proofs_examples_and_negative_controls(self):
        cases = [
            ("verified", "claim", "Proved in model"),
            ("verified", "helper", "Proved in model"),
            ("verified", "example", "Proved: execution exists"),
            ("falsified", "claim", "Counterexample found"),
            ("falsified", "example", "No such execution exists in the model"),
            ("falsified", "counterexample", "Check passed: counterexample reproduced"),
            ("verified", "counterexample", "Check failed: expected counterexample not found"),
            ("timeout", "counterexample", "Unresolved: timeout"),
            ("timeout", "example", "Unresolved: timeout"),
            ("CONFLICT", "claim", "Unresolved: conflicting results"),
            ("verified (dependencies pending: helper)", "claim", "Unresolved: supporting checks pending"),
            ("verified (dependencies pending: helper)", "example", "Unresolved: supporting checks pending"),
            ("falsified (dependencies pending: helper)", "counterexample", "Unresolved: supporting checks pending"),
        ]
        for verdict, category, expected in cases:
            with self.subTest(verdict=verdict, category=category):
                self.assertEqual(results_report.result_label({"verdict": verdict}, category), expected)

    def test_paper_requirement_numbers_and_source_links_match_the_paper(self):
        source = (results_report.PAPER_ROOT / results_report.REQUIREMENTS_SOURCE).read_text()
        macros = re.findall(r"\\item\s+\\myparagraph\{\\em\s+(\\req\w+)\}", source)
        self.assertEqual(len(macros), 6)
        targets, claims = results_report.paper_references()
        for index, macro in enumerate(macros, 1):
            name = f"S{index}"
            target = results_report.PAPER_TARGETS[name]
            self.assertIn(macro, target["marker"])
            line = int(targets[name].rsplit("#L", 1)[1].rstrip(")"))
            self.assertIn(macro, source.splitlines()[line - 1])
        claim_source = (results_report.PAPER_ROOT / results_report.CLAIMS_SOURCE).read_text()
        for name, link in claims.items():
            line = int(link.rsplit("#L", 1)[1].rstrip(")"))
            self.assertTrue(claim_source.splitlines()[line - 1].startswith("**" + name + " "))

    def test_missing_or_unknown_paper_mapping_is_rejected(self):
        original = json.loads((HERE / "lemma_explanations.json").read_text())
        for invalid in ({}, {"role": "Example", "targets": ["S7"], "claims": ["C-AUTH-1"]},
                        {"role": "Example", "targets": ["S1"], "claims": ["C-AUTH-99"]}):
            with self.subTest(mapping=invalid), tempfile.TemporaryDirectory() as folder:
                catalog = copy.deepcopy(original)
                catalog["julep_auth"]["lemmas"]["executable_direct"]["paper"] = invalid
                path = Path(folder)
                (path / "lemma_explanations.json").write_text(json.dumps(catalog))
                with patch.object(results_report, "HERE", path):
                    with self.assertRaisesRegex(ValueError, "paper"):
                        results_report.render_report(THEORIES, unrun_rows(), 2)

    def test_number_authorization_is_mapped_to_the_design_objective(self):
        catalog, _ = results_report.checked_catalog(THEORIES, unrun_rows())
        for theory, name in (("julep_auth", "auth1_caller_authentication"),
                            ("julep_auth", "auth2_recipient_authentication"),
                            ("julep_pairing", "del1_delegation_chain")):
            self.assertEqual(catalog[theory]["lemmas"][name]["paper"]["targets"], ["objective-1"])

    def test_reports_partition_the_full_suite_without_changing_verdicts(self):
        rows = unrun_rows()
        reports = {"protocol": results_report.render_report(THEORIES, rows, 2),
                   "regression": results_report.render_findings_appendix(THEORIES, rows, 2)}
        tables = {kind: [line for line in report.splitlines() if line.startswith("| julep_")]
                  for kind, report in reports.items()}
        self.assertEqual(len(tables["protocol"]), 69)
        self.assertEqual(len(tables["regression"]), 7)
        self.assertEqual(set(tables["protocol"]) & set(tables["regression"]), set())
        self.assertEqual(sorted(tables["protocol"] + tables["regression"]),
                         sorted(results_report.workflow.result_table(rows).splitlines()[2:]))
        self.assertNotRegex(reports["protocol"], r"\b(old|legacy|overstrong|repaired|corrected)\b")
        self.assertNotIn("julep_ratchet_regression", reports["protocol"])
        self.assertNotIn("_expected_falsified", reports["protocol"])

    def test_current_protocol_failure_and_timeout_remain_visible(self):
        rows = unrun_rows()
        for row in rows:
            if row["lemma"] == "auth1_caller_authentication":
                row["verdict"] = "falsified"
            if row["lemma"] == "pair_K_forward_secret_B":
                row["verdict"] = "timeout"
        report = results_report.render_report(THEORIES, rows, 2)
        self.assertIn("| julep_auth | `auth1_caller_authentication` | falsified |", report)
        self.assertIn("| julep_pairing | `pair_K_forward_secret_B` | timeout |", report)
        self.assertIn("**1 falsified**", report)
        self.assertIn("Counterexample found", report)
        self.assertIn("Unresolved: timeout", report)

    def test_invalid_report_assignment_cannot_hide_or_promote_checks(self):
        original = json.loads((HERE / "lemma_explanations.json").read_text())
        for value in (None, "omitted", "protocol"):
            with self.subTest(assignment=value), tempfile.TemporaryDirectory() as folder:
                catalog = copy.deepcopy(original)
                catalog["julep_auth"]["lemmas"]["auth4_recipient_identity_confidentiality_expected_falsified"]["report"] = value
                path = Path(folder)
                (path / "lemma_explanations.json").write_text(json.dumps(catalog))
                with patch.object(results_report, "HERE", path):
                    with self.assertRaisesRegex(ValueError, "report"):
                        results_report.render_report(THEORIES, unrun_rows(), 2)

    def test_report_keeps_dependency_failure_and_conflict_visible(self):
        rows = unrun_rows()
        rows[0]["verdict"] = "CONFLICT"
        rows[1]["verdict"] = "verified (dependencies pending: unresolved_helper)"
        report = results_report.render_report(THEORIES, rows, 2)
        self.assertIn("Unresolved: conflicting results", report)
        self.assertIn("Unresolved: supporting checks pending", report)
        self.assertIn("verified (dependencies pending: unresolved_helper)", report)
        self.assertIn("Full-suite collector exit code: `2`", report)


if __name__ == "__main__":
    unittest.main()
