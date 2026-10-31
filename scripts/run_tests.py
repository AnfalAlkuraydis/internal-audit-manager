"""Append-only JSON-lines TXT reports. No provider content or traceback is logged."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import unittest
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ("component_tests", "integration_tests", "system_tests",
           "agent_traces", "regression_history", "metrics_summary")

def now():
    """Return an explicit UTC timestamp so saved runs can be compared across machines."""
    return datetime.now(timezone.utc).isoformat()

def append(name, entry):
    """Append one JSON report entry without erasing earlier failures or results."""
    with (ROOT / "evaluation" / f"{name}.txt").open("a", encoding="utf-8") as report:
        report.write(json.dumps(entry, ensure_ascii=True) + "\n")

class LoggedResult(unittest.TestResult):
    """Record unittest outcomes with durations, safe errors and run references."""
    def __init__(self, run_id):
        """Start counters for one test run and retain its correlation ID."""
        super().__init__()
        self.run_id = run_id
        self.counts = {"PASS": 0, "FAIL": 0, "NOT RUN": 0}

    def startTest(self, test):
        """Start this test timer and clear its accumulated subtest errors."""
        super().startTest(test)
        self.started = time.perf_counter()
        self.subtest_errors = []

    def record(self, test, status, reason=None, error_type=None):
        """Persist the outcome and any deliberately safe trace/observation fields."""
        test_id = test.id()
        category = "component_tests" if ".component." in test_id else (
            "system_tests" if ".live_agent." in test_id or ".system." in test_id else "integration_tests")
        entry = {
            "run_id": self.run_id, "test_id": test_id, "execution_date_utc": now(),
            "test_version": "phase4-v1", "execution_mode": "live",
            "inference_source": "azure_grok" if ".live_agent." in test_id else "mock_or_none",
            "component_scenario": test.shortDescription() or test_id, "expected_result": test.shortDescription() or "All test assertions pass",
            "observations": getattr(test, "observations", None),
            "actual_result": reason or ("Assertions satisfied" if status == "PASS" else error_type), "status": status,
            "duration_seconds": round(time.perf_counter() - self.started, 6),
            "retry_count": 0, "trace_reference": self.run_id,
            "root_cause": reason or error_type, "fix_applied": None,
            "actual_retest_result": None,
            "subtest_error_types": self.subtest_errors,
        }
        append(category, entry)
        if ".live_agent." in test_id:
            append("agent_traces", entry)
        # Backend test traces contain references/outcomes only, not model reasoning or secrets.
        for trace in getattr(test, "safe_trace", []):
            append("agent_traces", {**trace, "run_id": self.run_id,
                   "execution_date_utc": now(), "execution_mode": "live",
                   "test_id": test_id})
        self.counts[status] += 1
        print(f"{status}: {test_id}" + (f" ({reason})" if reason else ""))

    def addSuccess(self, test):
        """Record PASS only after unittest reports a successful test."""
        super().addSuccess(test)
        self.record(test, "PASS")

    def addFailure(self, test, err):
        """Record an assertion failure without saving sensitive exception text."""
        super().addFailure(test, err)
        self.record(test, "FAIL", error_type=getattr(err[1], "code", err[0].__name__))

    def addError(self, test, err):
        """Record an unexpected exception using only its safe code or type."""
        super().addError(test, err)
        self.record(test, "FAIL", error_type=getattr(err[1], "code", err[0].__name__))

    def addSkip(self, test, reason):
        """Map a skipped test to NOT RUN, never to PASS."""
        super().addSkip(test, reason)
        self.record(test, "NOT RUN", reason=reason)

    def addSubTest(self, test, subtest, err):
        """Collect failed subcases while keeping the parent test as the denominator."""
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.subtest_errors.append(err[0].__name__)

    def stopTest(self, test):
        """Save one failed parent outcome when any of its subcases failed."""
        if self.subtest_errors:
            self.record(test, "FAIL", error_type="Subtest assertion failed")
        super().stopTest(test)

def main():
    """Run discovered tests, opt into paid calls only on request, and append actual totals."""
    parser = argparse.ArgumentParser(description="Run logged tests; paid inference is opt-in.")
    parser.add_argument("--live", action="store_true", help="Include real paid Azure Grok compatibility calls")
    args = parser.parse_args()
    os.environ["AUDIT_RUN_LIVE_TESTS"] = "1" if args.live else "0"
    load_dotenv(ROOT / ".env", override=False)
    os.chdir(ROOT)
    (ROOT / "evaluation").mkdir(exist_ok=True)
    for name in REPORTS:
        (ROOT / "evaluation" / f"{name}.txt").touch(exist_ok=True)
    run_id = str(uuid.uuid4())
    append("agent_traces", {"run_id": run_id, "execution_date_utc": now(),
        "execution_mode": "live", "event": "test_run_started",
        "note": "Only the explicitly live test may contact Azure; other inference uses mocks."})
    if os.environ.get("LLM_MODE", "live") != "live":
        append("regression_history", {"run_id": run_id, "execution_date_utc": now(),
                                     "status": "FAIL", "reason": "Only LIVE mode is implemented."})
        print("Only LIVE mode is implemented.")
        return 1
    result = LoggedResult(run_id)
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    started = time.perf_counter()
    suite.run(result)
    summary = {"run_id": run_id, "execution_date_utc": now(), "execution_mode": "live",
               "test_version": "phase4-v1", "tests_executed_or_skipped": result.testsRun,
               "counts": result.counts, "successful": result.wasSuccessful(),
               "duration_seconds": round(time.perf_counter() - started, 6),
               "live_results_are_not_autonomy_scores": True,
               "requested_live_inference": args.live, "api_cost": None, "note": "Unknown cost is not zero. Phase 4 agent and simulated-mail tests; real autonomy results are reported separately."}
    if result.testsRun == 0:
        summary["successful"] = False
        summary["note"] = "No tests discovered."
    append("metrics_summary", summary)
    append("regression_history", summary)
    print(json.dumps(summary))
    return 0 if summary["successful"] else 1

if __name__ == "__main__":
    sys.exit(main())
