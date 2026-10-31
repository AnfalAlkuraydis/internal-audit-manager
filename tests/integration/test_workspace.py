"""Exercise authenticated Phase 4 workspace routes and actual background processing."""
import json
import time
import unittest
import sqlalchemy as sa
from backend.database import tables as t
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.auth import AuthConfig
from backend.config import Settings
from backend.agent.orchestrator import AgentRuntime
from backend.agent.llm_interface import Message, InferenceResult, Usage
from tests.audit_support import AuditFixture

class ScopeOnlyLLM:
    """Test-only fault boundary: interpret scope then fail before any paid inference."""
    def __init__(self):
        """Count actual graph requests to prove the server worker ran without browser polling."""
        self.calls=0
    async def complete(self,messages,tools):
        """Return only the assignment scope; later calls surface a visible safe failure."""
        self.calls+=1
        if self.calls>1:
            raise RuntimeError("injected test inference failure")
        return InferenceResult(message=Message(role="assistant",content=json.dumps(dict(
            department="Digital Risk",period_start="2026-01-01",period_end="2026-08-31"))),
            usage=Usage(),finish_reason="stop",latency_ms=0)

class WorkspaceTests(AuditFixture,unittest.TestCase):
    """Check authentication, automatic worker operation and truthful failure visibility."""
    def test_worker_runs_without_polling_and_records_failure(self):
        """An assignment advances in the background and persists its safe error state."""
        llm=ScopeOnlyLLM()
        runtime=AgentRuntime(self.service,Path(self.temp.name)/"checkpoints.sqlite",llm=llm,inference_source="test-only")
        app=create_app(Settings(),engine=self.engine,auth_config=AuthConfig("auditor","reviewer"),
                       runtime=runtime,enable_worker=True)
        headers={"Authorization":"Bearer auditor"}
        with TestClient(app) as client:
            self.assertEqual(client.get("/workspace/sessions").status_code,401)
            self.assertEqual(client.post("/workspace/sessions",headers={"Authorization":"Bearer reviewer"},
                json={"assignment":"Audit","dataset_id":"digital-risk-dev.v1"}).status_code,403)
            response=client.post("/workspace/sessions",headers=headers,json=dict(
                assignment="Audit Digital Risk for 2026-01-01 through 2026-08-31",dataset_id="digital-risk-dev.v1"))
            self.assertEqual(response.status_code,200)
            # No client interaction drives execution; the lifespan worker handles the queued session.
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                with self.engine.connect() as c:
                    state=c.scalar(sa.select(t.agent_sessions.c.status).where(
                        t.agent_sessions.c.id==response.json()["session_id"]))
                if state=="attention_required":
                    break
                time.sleep(.05)
            self.assertEqual(llm.calls,2)
            snapshot=client.get("/workspace/sessions/"+response.json()["session_id"],headers=headers).json()
            self.assertEqual(snapshot["session"]["status"],"attention_required")
            self.assertEqual(snapshot["session"]["error_code"],"RuntimeError")
            self.assertEqual(snapshot["progress"]["total_controls"],0)
            self.assertTrue(any(a["status"]=="Failed" for a in snapshot["activity"]))
            self.assertEqual(client.post("/mail/incoming",headers={"Authorization":"Bearer reviewer"},
                json=dict(message_id="x",in_reply_to="x",sender="x@department.example",body="test")).status_code,403)
            datasets=client.get("/workspace/datasets",headers=headers).json()
            self.assertTrue(all(d["split"]=="development" for d in datasets))

    def test_built_workspace_and_assets_are_served(self):
        """Same-origin delivery serves real compiled assets when the UI has been built."""
        from tests.audit_support import ROOT
        if not (ROOT/"frontend/dist/index.html").exists():
            self.skipTest("Frontend production build NOT RUN")
        app=create_app(Settings(),engine=self.engine,auth_config=AuthConfig("auditor","reviewer"))
        client=TestClient(app)
        page=client.get("/")
        self.assertEqual(page.status_code,200)
        self.assertIn('id="root"',page.text)
        self.assertEqual(client.get("/health").json()["phase"],4)
