"""Verify append-only history and honest failure/skipped-test reporting."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import run_tests

class ReportingTests(unittest.TestCase):
    def test_append_preserves_history(self):
        """Verify a later passing result does not replace an earlier recorded failure."""
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(run_tests, "ROOT", Path(directory)):
                (Path(directory) / "evaluation").mkdir()
                run_tests.append("regression_history", {"run_id": "before", "status": "FAIL"})
                run_tests.append("regression_history", {"run_id": "after", "status": "PASS"})
            rows = [json.loads(line) for line in (
                Path(directory) / "evaluation" / "regression_history.txt").read_text().splitlines()]
        self.assertEqual([row["status"] for row in rows], ["FAIL", "PASS"])

    def test_failed_and_skipped_tests_are_reported_honestly(self):
        """Verify failure/skip counts and exclusion of sensitive exception text."""
        class Examples(unittest.TestCase):
            def test_pass(self):
                """Supply a successful example for the reporting self-check."""
                pass
            def test_fail(self):
                """Deliberately fail inside the isolated reporting self-check."""
                self.fail("sentinel-sensitive-provider-content")
            def test_skip(self):
                """Supply a skipped example that the logger must label NOT RUN."""
                self.skipTest("Missing test configuration")
            def test_subtest_fail(self):
                """Deliberately fail a subcase to verify parent-test failure counting."""
                for value in (1, 2):
                    with self.subTest(value=value):
                        self.assertEqual(value, 1, "sentinel-sensitive-provider-content")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(run_tests, "ROOT", Path(directory)):
                (Path(directory) / "evaluation").mkdir()
                with contextlib.redirect_stdout(io.StringIO()):
                    result = run_tests.LoggedResult("logger-self-check")
                    unittest.defaultTestLoader.loadTestsFromTestCase(Examples).run(result)
            text = (Path(directory) / "evaluation" / "component_tests.txt").read_text()
        self.assertEqual(result.testsRun, 4)
        self.assertEqual(result.counts, {"PASS": 1, "FAIL": 2, "NOT RUN": 1})
        self.assertFalse(result.wasSuccessful())
        self.assertNotIn("sentinel-sensitive-provider-content", text)
        self.assertEqual(len(text.splitlines()), 4)
