"""Authenticated Phase 4 session, event and simulated-email API for the local workspace."""
from typing import Annotated
from uuid import uuid4
import sqlalchemy as sa
from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import Field
from fastapi.encoders import jsonable_encoder
from backend.auth import Principal, require_role
from backend.database import tables as t
from backend.database.schemas import Record, Identifier
from backend.agent.context import observe
from backend.email.models import IncomingMail, FollowupEdit
from backend.services.activity import stamp
from backend.services.errors import AuditError

class AssignmentInput(Record):
    """The auditor supplies a high-level instruction and chooses the synthetic source partition."""
    assignment: str = Field(min_length=1, max_length=3000)
    dataset_id: Identifier

def create_workspace_router(audit, auth, get_runtime):
    """Expose backend records and workflow controls without any simulated-inference endpoint."""
    router = APIRouter()
    bearer = HTTPBearer(auto_error=False)

    def current(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        """Authenticate the real local role; no client-supplied role is trusted."""
        actor = auth.authenticate(credentials.credentials if credentials else "")
        require_role(actor, "auditor", "reviewer")
        return actor

    @router.get("/workspace/me")
    def identity(actor: Principal = Depends(current)):
        """Tell the connected UI the authenticated role without exposing credentials."""
        return {"id": actor.id, "role": actor.role}

    @router.get("/workspace/datasets")
    def datasets(actor: Principal = Depends(current)):
        """Keep held-out evaluation partitions outside the normal workspace picker."""
        with audit.engine.connect() as c:
            return [dict(row) for row in c.execute(sa.select(t.datasets).where(
                t.datasets.c.split == "development")).mappings()]

    @router.get("/workspace/sessions")
    def sessions(actor: Principal = Depends(current)):
        """List durable work so the UI reconnects after a browser or backend restart."""
        with audit.engine.connect() as c:
            return [dict(row) for row in c.execute(sa.select(t.agent_sessions).order_by(
                t.agent_sessions.c.updated_at.desc())).mappings()]

    @router.post("/workspace/sessions")
    def start(value: AssignmentInput, actor: Principal = Depends(current)):
        """Queue an actual LIVE inference workflow; it cannot approve its own work."""
        require_role(actor, "auditor")
        runtime = get_runtime()
        id = runtime.start(value.assignment, value.dataset_id)
        return {"session_id": id, "inference": "LIVE Grok", "email": "simulated"}

    @router.post("/workspace/sessions/{session_id}/retry")
    def retry(session_id: str, actor: Principal = Depends(current)):
        """Retry a visible failure using existing checkpoints and idempotency receipts."""
        require_role(actor, "auditor")
        with audit.engine.begin() as c:
            row = audit._row(c, t.agent_sessions, session_id)
            if row["status"] != "attention_required":
                raise AuditError("session_not_waiting_for_retry")
            c.execute(t.agent_sessions.update().where(t.agent_sessions.c.id == session_id).values(
                status="queued", wake_version=t.agent_sessions.c.wake_version + 1,
                error_code=None, updated_at=stamp()))
        return {"status": "queued"}

    @router.get("/workspace/sessions/{session_id}")
    def snapshot(session_id: str, actor: Principal = Depends(current)):
        """Calculate UI views from the same records used by execution and review safeguards."""
        with audit.engine.connect() as c:
            session = audit._row(c, t.agent_sessions, session_id)
        engagement_id = session["engagement_id"]
        context = observe(audit, engagement_id, get_runtime().clock()) if engagement_id else None
        with audit.engine.connect() as c:
            event_scope = t.activity.c.session_id == session_id
            if engagement_id:
                event_scope = sa.or_(event_scope, t.activity.c.engagement_id == engagement_id)
            events = [dict(row) for row in c.execute(sa.select(t.activity).where(
                event_scope).order_by(t.activity.c.id.desc()).limit(150)).mappings()][::-1]
            requests, mail, incoming_mail = [], [], []
            if engagement_id:
                requests = [dict(r) for r in c.execute(sa.select(t.evidence_requests).where(
                    t.evidence_requests.c.engagement_id == engagement_id)).mappings()]
                ids = [row["id"] for row in requests]
                for request in requests:
                    followup = c.execute(sa.select(t.mail_followups).where(
                        t.mail_followups.c.request_id == request["id"])).mappings().first()
                    request["followup"] = dict(followup) if followup else None
                mail = [dict(row) for row in c.execute(sa.select(t.mail_outbox).where(
                    t.mail_outbox.c.request_id.in_(ids)).order_by(t.mail_outbox.c.created_at)).mappings()]
            if engagement_id:
                incoming_mail = [dict(row) for row in c.execute(sa.select(t.mail_inbox).where(
                    t.mail_inbox.c.request_id.in_(ids)).order_by(t.mail_inbox.c.received_at)).mappings()]
            counts = {outcome: 0 for outcome in ("PASS", "FAIL", "MISSING_EVIDENCE", "CONTRADICTORY_EVIDENCE", "ERROR", "NOT_APPLICABLE")}
            if context:
                for task in context["work_items"]:
                    if task["purpose"] == "audit" and task["latest_run_id"]:
                        for key, value in audit._run_output(c, task["latest_run_id"])["counts"].items():
                            counts[key] += value
            audit_tasks = [w for w in (context or {}).get("work_items", []) if w["purpose"] == "audit"]
            findings = (context or {}).get("approved_findings", [])
            progress = dict(completed_controls=sum(w["state"] == "completed" for w in audit_tasks),
                total_controls=len(audit_tasks), closed_findings=sum(f["closed"] for f in findings),
                approved_findings=len(findings))
        return jsonable_encoder(dict(session=session, context=context, activity=events,
            requests=requests, communication=mail, incoming_communication=incoming_mail, counts=counts, progress=progress,
            inference="LIVE Grok", email_transport="simulated"))

    @router.get("/mail/requests/{request_id}/sample-reply")
    def preview_reply(request_id: str, actor: Principal = Depends(current)):
        """Preview synthetic department facts; receiving them remains an explicit separate action."""
        require_role(actor, "auditor")
        from backend.email.samples import sample_reply
        return sample_reply(audit, request_id, get_runtime().clock())

    @router.post("/mail/incoming")
    def incoming(value: IncomingMail, actor: Principal = Depends(current)):
        """Inject a clearly labeled synthetic email through the shared normalized processor."""
        require_role(actor, "auditor")
        return get_runtime().mail.receive(value)

    @router.patch("/mail/requests/{request_id}/schedule")
    def schedule(request_id: str, value: FollowupEdit, actor: Principal = Depends(current)):
        """Change a real request deadline/cadence without approving any escalation."""
        require_role(actor, "auditor")
        get_runtime().mail.update_schedule(request_id, value)
        return {"status": "schedule_updated"}

    return router
