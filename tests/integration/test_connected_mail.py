"""Connected-UI mail previews use actual requests and preserve every Phase 4 gate."""
import unittest
from datetime import datetime,timezone
from types import SimpleNamespace
import sqlalchemy as sa
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.config import Settings
from backend.auth import AuthConfig
from backend.database import tables as t
from backend.email.service import MailService
from tests.audit_support import AuditFixture,NARRATIVE

class ConnectedMailTests(AuditFixture,unittest.TestCase):
    """Test preview isolation, roles, normalized ingestion and independent remediation."""
    def setUp(self):
        """Create a scoped real missing request with simulated delivered mail."""
        super().setUp()
        self.plan(controls=["PR-02.v1"],allow_followup=True)
        self.population,self.evidence,self.run=self.execute_control("PR-02.v1")
        self.now=datetime(2026,11,1,tzinfo=timezone.utc)
        self.mail=MailService(self.service,clock=lambda:self.now)
        self.request=self.tool("request_department_input",evidence_snapshot_id=self.evidence["evidence_snapshot_id"],
            entity_ids=["PRJ-003"],recipient=self.service.contacts["Digital Risk"][0],
            subject="Original approval required",message="Provide the missing original approval.")
        self.mail.tick()
        self.client=TestClient(create_app(Settings(),engine=self.engine,auth_config=AuthConfig("auditor","reviewer"),
            runtime=SimpleNamespace(mail=self.mail,clock=lambda:self.now)))
        self.headers={"Authorization":"Bearer auditor"}

    def count(self,table):
        """Measure records to prove that reading a preview never writes evidence."""
        with self.engine.connect() as c:
            return c.scalar(sa.select(sa.func.count()).select_from(table))

    def preview(self,request):
        """Read a normalized synthetic preview without receiving it automatically."""
        r=self.client.get("/mail/requests/"+request["request_id"]+"/sample-reply",headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()["message"]

    def test_identity_roles_and_preview_do_not_write_evidence(self):
        """Only an auditor may prepare synthetic facts; actual receipt remains separate."""
        path="/mail/requests/"+self.request["request_id"]+"/sample-reply"
        self.assertEqual(self.client.get(path).status_code,401)
        self.assertEqual(self.client.get(path,headers={"Authorization":"Bearer reviewer"}).status_code,403)
        self.assertEqual(self.client.get("/workspace/me",headers=self.headers).json()["role"],"auditor")
        before=(self.count(t.evidence),self.count(t.mail_inbox),self.count(t.review_decisions))
        message=self.preview(self.request)
        self.assertTrue(message["body"].startswith("SYNTHETIC"))
        self.assertEqual((self.count(t.evidence),self.count(t.mail_inbox),self.count(t.review_decisions)),before)
        receipt=self.client.post("/mail/incoming",headers=self.headers,json=message)
        self.assertEqual(receipt.status_code,200)
        self.assertEqual(receipt.json()["status"],"resolved")
        duplicate=self.client.post("/mail/incoming",headers=self.headers,json=message)
        self.assertEqual(receipt.json(),duplicate.json())
        self.assertEqual(self.client.get(path,headers=self.headers).status_code,409)
        _,_,run=self.execute_control("PR-02.v1")
        self.assertEqual(next(r for r in run["results"] if r["entity_id"]=="PRJ-003")["outcome"],"FAIL")

    def test_department_plan_and_implementation_use_real_validation_and_closure(self):
        """Synthetic replies support real independent retesting; a human still approves closure."""
        finding=self.finding()
        self.decision(finding)
        for purpose in ("action_plan","implementation"):
            request=self.tool("request_department_input",evidence_snapshot_id=self.evidence["evidence_snapshot_id"],
                entity_ids=["PRJ-002"],recipient=self.service.contacts["Digital Risk"][0],
                subject=purpose,message="Supply "+purpose,purpose=purpose,finding_id=finding["proposal_id"])
            self.mail.tick()
            message=self.preview(request)
            receipt=self.client.post("/mail/incoming",headers=self.headers,json=message)
            self.assertEqual(receipt.status_code,200,receipt.text)
            self.assertEqual(receipt.json()["status"],"resolved",receipt.text)
        period=message["verification_period"]
        population=self.tool("get_test_population",control_id="PR-02.v1",
            verification_for_finding_id=finding["proposal_id"],verification_start=period["period_start"],
            verification_end=period["period_end"])
        evidence=self.tool("search_evidence",population_snapshot_id=population["population_snapshot_id"])
        run=self.tool("run_control_test",population_snapshot_id=population["population_snapshot_id"],
                      evidence_snapshot_id=evidence["evidence_snapshot_id"])
        self.assertEqual(run["counts"]["PASS"],1)
        closure=self.tool("manage_remediation",finding_id=finding["proposal_id"],action="propose_closure",
                          verification_run_id=run["run_id"])
        self.assertEqual(closure["closure"]["status"],"pending")
        self.decision(closure["closure"])
