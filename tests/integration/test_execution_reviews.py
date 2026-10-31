"""Actual database/tool handoffs and attempted approval/immutability bypasses."""
import unittest
from concurrent.futures import ThreadPoolExecutor
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from backend.database import tables as t
from backend.agent.tools.contracts import DraftEdit, ReviewDecision
from backend.services.errors import AuditError
from tests.audit_support import AuditFixture, NARRATIVE

class ExecutionTests(AuditFixture, unittest.TestCase):
    """Run tools against temporary migrated databases with no LLM or mail transport."""

    def test_unapproved_plan_blocks_execution_and_agent_review(self):
        """No test population is available before human plan approval; agents cannot approve."""
        with self.assertRaises(AuditError):
            self.tool("get_test_population", control_id="PR-02.v1")
        proposal = self.tool("draft_audit_plan", plan=dict(
            objective="Audit", work_program="Test full population", control_ids=["PR-02.v1"]))
        with self.assertRaises(AuditError):
            self.decision(proposal, actor=self.agent)
        self.assertEqual(self.service.reviews(self.reviewer)[0]["status"], "pending")

    def test_plan_edits_preserve_originals_and_invalidate_snapshots(self):
        """New plan versions require fresh approval and invalidate old execution snapshots."""
        plan = self.plan()
        population = self.tool("get_test_population", control_id="PR-02.v1")
        changed = self.service.save_draft(plan["proposal_id"], DraftEdit(
            expected_version_id=plan["version_id"], changes={"objective": "Revised scope wording"}), self.reviewer)
        self.assertEqual(changed["status"], "pending")
        with self.assertRaises(AuditError):
            self.decision(plan)
        with self.assertRaises(AuditError):
            self.tool("search_evidence", population_snapshot_id=population["population_snapshot_id"])
        self.decision(changed)
        with self.assertRaises(AuditError):
            self.tool("search_evidence", population_snapshot_id=population["population_snapshot_id"])
        history = self.service.reviews(self.reviewer, plan["proposal_id"])
        self.assertEqual(len(history["versions"]), 2)
        self.assertNotEqual(history["versions"][0]["document"], history["versions"][1]["document"])
        self.assertEqual(len(history["decisions"]), 2)

    def test_same_and_concurrent_operations_do_not_duplicate_results(self):
        """Identical retries and distinct calls with identical inputs reuse actual business artifacts."""
        self.plan()
        pop, ev, first = self.execute_control("PR-02.v1")
        args = dict(population_snapshot_id=pop["population_snapshot_id"],
                    evidence_snapshot_id=ev["evidence_snapshot_id"], operation_id="RETRY-KEY")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.tool("run_control_test", **args), range(2)))
        self.assertEqual(results[0], first)
        self.assertEqual(results[1], first)
        with self.engine.connect() as c:
            self.assertEqual(c.scalar(sa.select(sa.func.count()).select_from(t.test_results)), 8)
        with self.assertRaises(AuditError):
            self.tool("get_audit_requirements", operation_id="RETRY-KEY")

    def test_snapshots_cannot_cross_engagements_or_populations(self):
        """Both an engagement mismatch and a population/evidence mismatch are blocked."""
        self.plan()
        pop1, ev1, _ = self.execute_control("PR-01.v1")
        pop2, _, _ = self.execute_control("PR-02.v1")
        with self.assertRaises(AuditError):
            self.tool("run_control_test", population_snapshot_id=pop2["population_snapshot_id"],
                      evidence_snapshot_id=ev1["evidence_snapshot_id"])
        self.new_engagement("OTHER", "digital-risk-dev.v1", "2026-01-01", "2026-08-31")
        self.plan("OTHER")
        with self.assertRaises(AuditError):
            self.tool("search_evidence", engagement_id="OTHER",
                      population_snapshot_id=pop1["population_snapshot_id"])

    def test_findings_require_failed_results_and_allow_narrative_only(self):
        """Findings cannot cite passing results, alter evidence, or silently change test outcomes."""
        self.plan()
        _, _, run = self.execute_control("PR-02.v1")
        passing = next(r for r in run["results"] if r["outcome"] == "PASS")
        with self.assertRaises(AuditError):
            self.tool("propose_finding", result_ids=[passing["id"]], finding=NARRATIVE)
        finding = self.finding()
        duplicate = self.finding()
        self.assertEqual(finding["proposal_id"], duplicate["proposal_id"])
        for changes in ({"result_ids": []}, {"evidence_ids": []}, {"outcome": "PASS"}):
            with self.assertRaises(AuditError):
                self.service.save_draft(finding["proposal_id"], DraftEdit(
                    expected_version_id=finding["version_id"], changes=changes), self.reviewer)
        changed = self.service.save_draft(finding["proposal_id"], DraftEdit(
            expected_version_id=finding["version_id"], changes={"severity": "high"}), self.reviewer)
        self.assertEqual(changed["version"], 2)
        self.assertEqual(changed["status"], "pending")
        with self.engine.connect() as c:
            self.assertEqual(c.execute(sa.select(t.test_results.c.outcome).where(
                t.test_results.c.id == passing["id"])).scalar_one(), "PASS")

    def test_immutable_records_reject_direct_updates_and_deletes(self):
        """SQLite triggers protect original evidence, calculated results and review history."""
        self.plan()
        _, _, run = self.execute_control("PR-02.v1")
        attempts = [(t.evidence, "facts", {}), (t.test_results, "outcome", "PASS"),
                    (t.artifacts, "payload", {}), (t.review_decisions, "reason", "changed")]
        for table, field, value in attempts:
            with self.subTest(table=table.name), self.assertRaises(IntegrityError):
                with self.engine.begin() as c:
                    c.execute(table.update().values(**{field: value}))
        with self.assertRaises(IntegrityError), self.engine.begin() as c:
            c.execute(t.test_results.delete())

    def test_reject_and_request_changes_do_not_authorize_work(self):
        """Rejected or returned plans cannot be used; agent revisions still need review."""
        proposal = self.tool("draft_audit_plan", plan=dict(
            objective="Audit", work_program="Test", control_ids=["PR-02.v1"]))
        self.decision(proposal, "changes_requested")
        revised = self.tool("draft_audit_plan", plan=dict(
            objective="Revised audit", work_program="Test carefully", control_ids=["PR-02.v1"]))
        self.assertEqual(revised["version"], 2)
        self.decision(revised, "rejected")
        with self.assertRaises(AuditError):
            self.tool("get_test_population", control_id="PR-02.v1")

    def test_scoped_requests_and_escalation_approval(self):
        """Routine requests queue once; escalation waits for approval and no email is sent."""
        self.plan()
        _, evidence, _ = self.execute_control("PR-02.v1")
        args = dict(evidence_snapshot_id=evidence["evidence_snapshot_id"], entity_ids=["PRJ-003"],
                    recipient="digital-risk@department.example", subject="Approval evidence", message="Provide original approval.")
        routine = self.tool("request_department_input", **args)
        self.assertEqual(routine["status"], "queued")
        self.assertEqual(self.tool("request_department_input", **args)["request_id"], routine["request_id"])
        with self.assertRaises(AuditError):
            self.tool("request_department_input", **{**args, "recipient": "outsider@example.com"})
        escalation = self.tool("request_department_input", **args, escalation=True)
        self.assertEqual(escalation["status"], "waiting_for_approval")
        with self.assertRaises(AuditError):
            self.decision(escalation["review"], actor=self.agent)
        edit = self.service.save_draft(escalation["review"]["proposal_id"], DraftEdit(
            expected_version_id=escalation["review"]["version_id"], changes={"message": "Human reviewed wording"}), self.reviewer)
        self.decision(edit)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(sa.select(t.evidence_requests.c.status).where(
                t.evidence_requests.c.id == escalation["request_id"])).scalar_one(), "queued")
        newer = self.service.save_draft(edit["proposal_id"], DraftEdit(
            expected_version_id=edit["version_id"], changes={"message": "Another pending revision"}), self.reviewer)
        with self.engine.connect() as c:
            request = c.execute(sa.select(t.evidence_requests).where(
                t.evidence_requests.c.id == escalation["request_id"])).mappings().one()
            self.assertEqual(request["status"], "waiting_for_approval")
            self.assertEqual(request["document"]["message"], "Another pending revision")
        self.decision(newer)

    def test_invalid_recipient_configuration_and_reordered_request_members(self):
        """Reject string-based recipient lists and deduplicate semantically identical requests."""
        from backend.services.audit import AuditService
        with self.assertRaises(AuditError):
            AuditService(self.engine, contacts={"Digital Risk": "someone@example.com"})
        self.plan()
        _, evidence, _ = self.execute_control("PR-02.v1")
        args = dict(evidence_snapshot_id=evidence["evidence_snapshot_id"],
            recipient="digital-risk@department.example", subject="Evidence", message="Clarify records")
        first = self.tool("request_department_input", **args, entity_ids=["PRJ-002", "PRJ-003"])
        second = self.tool("request_department_input", **args, entity_ids=["PRJ-003", "PRJ-002"])
        self.assertEqual(first["request_id"], second["request_id"])

    def test_empty_population_produces_no_fake_pass(self):
        """An approved control with no eligible members creates zero calculated outcomes."""
        self.new_engagement("EMPTY", "digital-risk-dev.v1", "2026-09-01", "2026-09-30")
        self.plan("EMPTY", ["PR-02.v1"])
        _, _, run = self.execute_control("PR-02.v1", "EMPTY")
        self.assertEqual(run["results"], [])
        self.assertEqual(sum(run["counts"].values()), 0)

    def test_early_closure_and_agent_owned_action_plans_are_blocked(self):
        """A department claim cannot replace retesting, and the agent cannot author that claim."""
        from backend.agent.tools.contracts import ActionPlanInput
        self.plan()
        finding = self.finding()
        self.decision(finding)
        value = ActionPlanInput(owner="Department owner", action="Improve approval gating",
                                due_on="2026-09-30", source_reference="Department statement")
        with self.assertRaises(AuditError):
            self.service.record_action_plan(finding["proposal_id"], value, self.agent)
        self.service.record_action_plan(finding["proposal_id"], value, self.auditor)
        with self.assertRaises(AuditError):
            self.tool("manage_remediation", finding_id=finding["proposal_id"], action="propose_closure")

    def test_followup_verification_requires_approved_bounds(self):
        """The agent cannot grant itself follow-up scope or exceed a human-approved time window."""
        plan = self.plan()
        finding = self.finding()
        self.decision(finding)
        args = dict(control_id="PR-02.v1", verification_for_finding_id=finding["proposal_id"],
                    verification_start="2026-09-01", verification_end="2026-09-30")
        with self.assertRaises(AuditError):
            self.tool("get_test_population", **args)
        revised = self.service.save_draft(plan["proposal_id"], DraftEdit(
            expected_version_id=plan["version_id"], changes={"allow_followup_verification": True,
            "verification_window_days": 30}), self.reviewer)
        self.decision(revised)
        with self.assertRaises(AuditError):
            self.tool("get_test_population", **{**args, "verification_end": "2026-10-01"})
        with self.assertRaises(AuditError):
            self.tool("get_test_population", **{**args, "verification_start": "2026-08-31"})
