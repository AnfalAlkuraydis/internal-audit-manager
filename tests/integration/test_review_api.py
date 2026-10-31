"""Authenticate requests and exercise permission checks through the actual FastAPI routes."""
import unittest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.auth import AuthConfig
from backend.config import Settings
from tests.audit_support import AuditFixture

class ReviewApiTests(AuditFixture, unittest.TestCase):
    """Use injected test credentials, never real environment tokens or Azure inference."""

    def setUp(self):
        """Create an isolated database and bind only synthetic test credentials."""
        super().setUp()
        self.client = TestClient(create_app(Settings.from_env({}), engine=self.engine,
            auth_config=AuthConfig("test-only-auditor", "test-only-reviewer")))
        self.addCleanup(self.client.close)
        self.auditor_headers = {"Authorization": "Bearer test-only-auditor"}
        self.reviewer_headers = {"Authorization": "Bearer test-only-reviewer"}

    def test_authentication_and_role_spoofing(self):
        """Missing/invalid tokens fail; reviewers cannot run tools and body roles grant no power."""
        self.assertEqual(self.client.get("/reviews").status_code, 401)
        self.assertEqual(self.client.get("/reviews", headers={"Authorization": "Bearer invalid"}).status_code, 401)
        body = dict(engagement_id=self.engagement_id, operation_id="API-1")
        self.assertEqual(self.client.post("/tools/get_audit_requirements", json=body,
            headers=self.reviewer_headers).status_code, 403)
        self.assertEqual(self.client.post("/tools/get_audit_requirements", json={**body, "role": "reviewer"},
            headers=self.auditor_headers).status_code, 422)
        self.assertEqual(len(self.client.get("/tools", headers=self.auditor_headers).json()["tools"]), 8)
        self.assertEqual(self.client.post("/tools/approve_finding", json=body,
            headers=self.auditor_headers).status_code, 404)

    def test_manual_review_version_history_and_no_fact_edit_route(self):
        """The API saves human edits, rejects stale approvals and offers no evidence mutation endpoint."""
        plan = self.tool("draft_audit_plan", plan=dict(
            objective="Audit", work_program="Test all records", control_ids=["PR-02.v1"]))
        response = self.client.post(f"/reviews/{plan['proposal_id']}/draft",
            json={"expected_version_id": plan["version_id"], "changes": {"objective": "Reviewed objective"}},
            headers=self.reviewer_headers)
        self.assertEqual(response.status_code, 200)
        edited = response.json()
        stale = self.client.post(f"/reviews/{plan['proposal_id']}/decision",
            json={"expected_version_id": plan["version_id"], "decision": "approved", "reason": "Reviewed"},
            headers=self.reviewer_headers)
        self.assertEqual(stale.status_code, 409)
        approved = self.client.post(f"/reviews/{plan['proposal_id']}/decision",
            json={"expected_version_id": edited["version_id"], "decision": "approved", "reason": "Reviewed"},
            headers=self.reviewer_headers)
        self.assertEqual(approved.status_code, 200)
        record = self.client.get(f"/reviews/{plan['proposal_id']}", headers=self.reviewer_headers).json()
        self.assertEqual(len(record["versions"]), 2)
        self.assertEqual(record["decisions"][0]["reviewer_id"], "demo-reviewer")
        spoofed = self.client.post(f"/reviews/{plan['proposal_id']}/decision",
            json={"expected_version_id": edited["version_id"], "decision": "approved",
                  "reason": "Reviewed", "reviewer_role": "agent"}, headers=self.auditor_headers)
        self.assertEqual(spoofed.status_code, 422)
        self.assertEqual(self.client.patch("/evidence/ANY", json={}, headers=self.auditor_headers).status_code, 404)
        forbidden = self.client.post(f"/reviews/{plan['proposal_id']}/draft",
            json={"expected_version_id": edited["version_id"], "changes": {"evidence_ids": []}},
            headers=self.reviewer_headers)
        self.assertEqual(forbidden.status_code, 403)

    def test_saved_results_and_invalid_assignment_api(self):
        """Expose actual saved outcomes read-only and reject invalid department scope safely."""
        self.plan()
        _, _, run = self.execute_control("PR-02.v1")
        fetched = self.client.get(f"/runs/{run['run_id']}", headers=self.reviewer_headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json(), run)
        invalid = self.client.post("/engagements", headers=self.auditor_headers, json={
            "id": "BAD-DEPARTMENT", "dataset_id": "digital-risk-dev.v1", "department": "Other",
            "period_start": "2026-01-01", "period_end": "2026-08-31"})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json(), {"error": "invalid_scope"})
