"""Regression checks for trustworthy result collection, using a fake prover."""
import argparse
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.theory = self.root / "toy.spthy"
        self.theory.write_text('theory Toy begin\nlemma helper [reuse]: "T"\nlemma goal: "T"\nend\n')
        self.prover = self.root / "prover"
        self.prover.write_text('#!/usr/bin/env python3\nimport os,sys,time\nif "--version" in sys.argv:\n print("test double")\n sys.exit(0)\ntime.sleep(float(os.environ.get("FAKE_DELAY","0")))\nprint(os.environ.get("FAKE_OUTPUT",""))\nsys.exit(int(os.environ.get("FAKE_CODE","0")))\n')
        self.prover.chmod(0o755)
        self.output = io.StringIO()

    def run_fake(self, output="", code=0, delay=0, lemma="goal", timeout=2):
        args = argparse.Namespace(theory=str(self.theory), lemma=lemma, prover=str(self.prover),
                                  timeout=timeout, threads=1, heap=1, heuristic=None,
                                  oracle=None, search=None, expect="verified")
        with patch.object(workflow, "HERE", self.root), patch.dict("os.environ", {
            "FAKE_OUTPUT": output, "FAKE_CODE": str(code), "FAKE_DELAY": str(delay)
        }), contextlib.redirect_stdout(self.output):
            return workflow.run(args)

    def collect(self):
        with patch.object(workflow, "HERE", self.root), contextlib.redirect_stdout(self.output):
            return workflow.collect(argparse.Namespace(theories=[str(self.theory)]))

    def test_exit_zero_without_verdict_is_incomplete(self):
        self.assertEqual(self.run_fake("parse failure despite exit zero"), 2)

    def test_error_with_printed_verdict_is_not_success(self):
        self.assertEqual(self.run_fake("  goal (all-traces): verified (3 steps)", code=1), 2)

    def test_missing_selected_verdict_is_incomplete(self):
        self.assertEqual(self.run_fake("  helper (all-traces): verified (3 steps)"), 2)

    def test_unexpected_counterexample_fails(self):
        self.assertEqual(self.run_fake("  goal (all-traces): falsified (3 steps)"), 1)

    def test_timeout_is_not_success(self):
        self.assertEqual(self.run_fake(delay=2, timeout=1), 2)

    def test_dependencies_and_source_hash(self):
        self.assertEqual(self.run_fake("  goal (all-traces): verified (3 steps)"), 0)
        self.assertEqual(self.collect(), 2)
        self.assertIn("dependencies pending: helper", self.output.getvalue())
        self.assertEqual(self.run_fake("  helper (all-traces): verified (2 steps)", lemma="helper"), 0)
        self.assertEqual(self.collect(), 0)
        self.theory.write_text(self.theory.read_text()+"\n// new source\n")
        self.assertEqual(self.collect(), 2)

    def test_conflicting_helper_invalidates_dependent_result(self):
        self.run_fake("  helper (all-traces): verified (2 steps)", lemma="helper")
        self.run_fake("  helper (all-traces): falsified (2 steps)", lemma="helper")
        self.run_fake("  goal (all-traces): verified (2 steps)")
        self.assertEqual(self.collect(), 2)
        self.assertIn("CONFLICT", self.output.getvalue())
        self.assertIn("dependencies pending: helper", self.output.getvalue())

    def test_transitive_dependencies_and_explicit_hiding(self):
        source = 'lemma source [ sources ]:\nlemma a [reuse]:\nlemma b [reuse]:\nlemma c [hide_lemma=a]:\n'
        self.assertEqual(workflow.lemma_dependencies(source), {
            "source": [], "a": ["source"], "b": ["source", "a"], "c": ["source", "b"]})


if __name__ == "__main__":
    unittest.main()
