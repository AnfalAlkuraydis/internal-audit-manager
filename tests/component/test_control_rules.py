"""Independent edge-case expectations for the five supported deterministic rule shapes."""
from datetime import date
import unittest
from backend.services.control_testing import evaluate
from backend.agent.tools.contracts import CONTRACTS, tool_definitions, TestInput

class RuleTests(unittest.TestCase):
    """Keep rule expectations explicit, not computed by a second copy of the engine."""

    def check(self, rule, facts, expected, *, kind="project_approval", extra=None, entity=None):
        """Evaluate a compact source-backed fixture and compare its outcome to a literal label."""
        entity = entity or dict(id="P", kind="project", facts={"deployed_on": "2026-08-31"}, active_to=None)
        record = dict(id="E", entity_id=entity["id"], kind=kind, facts=facts,
                      authority="secondary" if kind == "grc_approval" else "original",
                      integrity_valid=True, supersedes_id=None)
        records = [record] + (extra or [])
        result = evaluate(rule, entity, records,
            dict(period_start=date(2026, 1, 1), period_end=date(2026, 8, 31)),
            dict(effective_from="2026-01-01", effective_to=None))
        self.assertEqual(result["outcome"], expected)
        return result

    def test_project_date_equality_and_late_approval(self):
        """Same-day approval passes; approval the following day fails."""
        rule = dict(operation="on_or_before", evidence_kind="project_approval",
                    evidence_field="approved_on", entity_field="deployed_on")
        self.check(rule, {"approved_on": "2026-08-31"}, "PASS")
        self.check(rule, {"approved_on": "2026-09-01"}, "FAIL")

    def test_boolean_values_and_exact_snapshot_date(self):
        """Strict booleans are objective; wrong-date snapshots are missing evidence."""
        rule = dict(operation="is_true", evidence_kind="mfa", field="enabled", as_of="last_active_day")
        entity = dict(id="A", kind="privileged_account", facts={}, active_to=None)
        for value, expected in ((True, "PASS"), (False, "FAIL"), ("true", "ERROR")):
            self.check(rule, {"enabled": value, "snapshot_on": "2026-08-31"},
                       expected, kind="mfa", entity=entity)
        self.check(rule, {"enabled": True, "snapshot_on": "2026-08-30"},
                   "MISSING_EVIDENCE", kind="mfa", entity=entity)

    def test_recency_boundary_stale_and_future(self):
        """Thirty days is allowed, thirty-one fails, and future-dated scans are errors."""
        rule = dict(operation="not_older_than", evidence_kind="vulnerability_scan",
                    field="scanned_on", max_age_days=30, as_of="last_active_day")
        entity = dict(id="D", kind="device", facts={}, active_to=None)
        for when, expected in (("2026-08-01", "PASS"), ("2026-07-31", "FAIL"), ("2026-09-01", "ERROR")):
            self.check(rule, {"scanned_on": when}, expected, kind="vulnerability_scan", entity=entity)

    def test_employment_end_boundaries(self):
        """Employment ending on the snapshot date is already inactive; later or absent ends pass."""
        rule = dict(operation="employed_at", evidence_kind="employment", field="employment_end", as_of="last_active_day")
        entity = dict(id="A", kind="privileged_account", facts={}, active_to=None)
        for end, expected in ((None, "PASS"), ("2026-09-01", "PASS"), ("2026-08-31", "FAIL")):
            self.check(rule, {"employment_end": end}, expected, kind="employment", entity=entity)

    def test_source_agreement_and_discrepancy(self):
        """The reconciliation rule detects mismatch without inventing which source is correct."""
        rule = dict(operation="dates_agree", evidence_kind="project_approval",
                    other_evidence_kind="grc_approval", field="approved_on")
        grc = dict(id="G", entity_id="P", kind="grc_approval", facts={"approved_on": "2026-08-30"},
                   authority="secondary", integrity_valid=True, supersedes_id=None)
        self.check(rule, {"approved_on": "2026-08-30"}, "PASS", extra=[grc])
        self.check(rule, {"approved_on": "2026-08-29"}, "FAIL", extra=[grc])

    def test_conflicting_and_corrupted_evidence(self):
        """Equally authoritative contradictions remain unresolved; bad fingerprints cause errors."""
        rule = dict(operation="on_or_before", evidence_kind="project_approval",
                    evidence_field="approved_on", entity_field="deployed_on")
        other = dict(id="E2", entity_id="P", kind="project_approval", facts={"approved_on": "2026-08-29"},
                     authority="original", integrity_valid=True, supersedes_id=None)
        self.check(rule, {"approved_on": "2026-08-30"}, "CONTRADICTORY_EVIDENCE", extra=[other])
        other["integrity_valid"] = False
        self.check(rule, {"approved_on": "2026-08-30"}, "ERROR", extra=[other])

    def test_superseding_evidence_and_policy_effective_dates(self):
        """A replacement supersedes its predecessor; a policy outside scope is not applicable."""
        rule = dict(operation="on_or_before", evidence_kind="project_approval",
                    evidence_field="approved_on", entity_field="deployed_on")
        newer = dict(id="E2", entity_id="P", kind="project_approval", facts={"approved_on": "2026-08-30"},
                     authority="original", integrity_valid=True, supersedes_id="E")
        self.check(rule, {"approved_on": "2026-09-01"}, "PASS", extra=[newer])
        result = evaluate(rule, dict(id="P", kind="project", facts={"deployed_on": "2025-12-31"}),
            [], dict(period_end=date(2026, 8, 31)),
            dict(effective_from="2026-01-01", effective_to=None))
        self.assertEqual(result["outcome"], "NOT_APPLICABLE")

    def test_exactly_eight_typed_tools_and_no_approval_argument(self):
        """Tool schemas are complete, exclude approvals, and reject role/result spoofing."""
        self.assertEqual(len(tool_definitions()), 8)
        self.assertEqual(set(CONTRACTS), {t.name for t in tool_definitions()})
        with self.assertRaises(ValueError):
            TestInput.model_validate(dict(engagement_id="A", operation_id="O",
                population_snapshot_id="P", evidence_snapshot_id="E", approved=True, role="reviewer"))
