"""Whole deterministic workflows with explicit human decisions, not AI autonomy scores."""
import json
import unittest
import sqlalchemy as sa
from backend.database import tables as t
from backend.database.repository import fingerprint, insert_unchanged
from backend.database.schemas import Entity, Evidence
from backend.agent.tools.contracts import ActionPlanInput, DraftEdit
from backend.services.errors import AuditError
from tests.audit_support import AuditFixture, ROOT

class ControlWorkflowTests(AuditFixture, unittest.TestCase):
    """Verify actual outputs against the pre-existing development answer key."""

    def test_all_development_rules_match_independent_labels(self):
        """Calculate all 72 development item/control outcomes and compare with frozen labels."""
        self.plan()
        key = json.loads((ROOT / "evaluation/ground_truth/development.json").read_text())
        expected = {(row["control_id"], row["entity_id"]): row["expected_outcome"] for row in key["labels"]}
        actual = {}
        provenance_checked = 0
        for control in self.catalog.controls:
            population, evidence, run = self.execute_control(control.id)
            ids = {row["id"] for row in evidence["records"]}
            for row in run["results"]:
                actual[(control.id, row["entity_id"])] = row["outcome"]
                self.assertTrue(set(row["evidence_ids"]) <= ids)
                if row["outcome"] == "FAIL":
                    self.assertTrue(row["evidence_ids"])
                provenance_checked += 1
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 72)
        self.observations = dict(correct_outcomes=sum(actual[k] == expected[k] for k in expected),
            labelled_outcomes=len(expected), provenance_checks=provenance_checked,
            outcome_counts={value: list(actual.values()).count(value) for value in set(actual.values())},
            limitation="Provisional development labels, not held-out agent evaluation; no LLM calls.")

    def test_independent_later_retest_and_manual_closure_preserve_history(self):
        """New compliant evidence supports closure; it never changes the historical late approval."""
        self.plan(allow_followup=True)
        finding = self.finding()
        self.decision(finding)
        self.service.record_action_plan(finding["proposal_id"], ActionPlanInput(
            owner="Department process owner", action="Enforce approval before deployment",
            due_on="2026-09-25", source_reference="Department action-plan statement"), self.auditor)
        fixture = json.loads((ROOT / "tests/fixtures/followup_messages.json").read_text())["messages"][2]
        # This is fixture setup, not an implemented incoming-email integration.
        with self.engine.begin() as c:
            for item in fixture["entities"]:
                entity = Entity.model_validate(item)
                insert_unchanged(c, t.entities, {**entity.model_dump(), "dataset_id": "digital-risk-dev.v1"})
            for item in fixture["evidence"]:
                evidence = Evidence.model_validate(item)
                insert_unchanged(c, t.evidence, {**evidence.model_dump(), "dataset_id": "digital-risk-dev.v1",
                    "fingerprint": fingerprint(evidence.model_dump(mode="json"))})
        population = self.tool("get_test_population", control_id="PR-02.v1",
            verification_for_finding_id=finding["proposal_id"], verification_start="2026-09-01",
            verification_end="2026-09-30")
        evidence = self.tool("search_evidence", population_snapshot_id=population["population_snapshot_id"])
        verification = self.tool("run_control_test", population_snapshot_id=population["population_snapshot_id"],
            evidence_snapshot_id=evidence["evidence_snapshot_id"])
        self.assertEqual(verification["purpose"], "remediation")
        self.assertEqual(verification["counts"]["PASS"], 1)
        output = self.tool("manage_remediation", finding_id=finding["proposal_id"], action="propose_closure",
                           verification_run_id=verification["run_id"])
        self.assertEqual(output["closure"]["status"], "pending")
        # A changed finding must be approved again and the stale closure must be replaced.
        edited = self.service.save_draft(finding["proposal_id"], DraftEdit(
            expected_version_id=finding["version_id"], changes={"severity": "high"}), self.reviewer)
        with self.assertRaises(AuditError):
            self.decision(output["closure"])
        self.decision(edited)
        with self.assertRaises(AuditError):
            self.decision(output["closure"])
        self.decision(output["closure"], "changes_requested")
        output = self.tool("manage_remediation", finding_id=finding["proposal_id"], action="propose_closure",
                           verification_run_id=verification["run_id"])
        finding = edited
        with self.assertRaises(AuditError):
            self.decision(output["closure"], actor=self.agent)
        approved = self.decision(output["closure"])
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(self.decision(output["closure"]), approved)
        with self.engine.connect() as c:
            original = c.execute(sa.select(t.test_results.c.outcome).join(
                t.artifacts, t.test_results.c.run_id == t.artifacts.c.id).where(
                t.artifacts.c.engagement_id == self.engagement_id,
                t.test_results.c.control_id == "PR-02.v1",
                t.test_results.c.entity_id == "PRJ-002")).scalars().all()
            decisions = c.scalar(sa.select(sa.func.count()).select_from(t.review_decisions).where(
                t.review_decisions.c.version_id == output["closure"]["version_id"]))
        self.assertEqual(original, ["FAIL"])
        self.assertEqual(decisions, 1)
        with self.assertRaises(AuditError):
            self.service.save_draft(finding["proposal_id"], DraftEdit(
                expected_version_id=finding["version_id"], changes={"severity": "low"}), self.reviewer)

    def test_historical_audit_run_cannot_be_used_as_remediation(self):
        """An ordinary audit run, even when passing, cannot authorize finding closure."""
        self.plan()
        finding = self.finding()
        self.decision(finding)
        self.service.record_action_plan(finding["proposal_id"], ActionPlanInput(
            owner="Owner", action="Correction", due_on="2026-09-25", source_reference="Statement"), self.auditor)
        _, _, audit = self.execute_control("PR-02.v1")
        with self.assertRaises(AuditError):
            self.tool("manage_remediation", finding_id=finding["proposal_id"],
                      action="propose_closure", verification_run_id=audit["run_id"])
