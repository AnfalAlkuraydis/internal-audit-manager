"""Authenticated backend routes for Phase 3 tools, immutable records and human reviews."""
from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from backend.auth import Principal, require_role
from backend.agent.tools.contracts import (
    tool_definitions, CONTRACTS, DraftEdit, ReviewDecision, ActionPlanInput,
)
from backend.database.schemas import Engagement
from backend.database.repository import create_engagement
from backend.database import tables as t
import sqlalchemy as sa

def create_router(service, auth):
    """Bind one database service and local-demo credential configuration to the API."""
    router = APIRouter()
    bearer = HTTPBearer(auto_error=False)

    def current(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        """Authenticate a bearer token; callers cannot supply their own role or identity."""
        return auth.authenticate(credentials.credentials if credentials else "")

    @router.get("/tools")
    def definitions(actor: Principal = Depends(current)):
        """Describe the eight allowed tools and their typed output shapes."""
        require_role(actor, "auditor", "reviewer")
        return {"tools": [tool.model_dump() for tool in tool_definitions()],
                "outputs": {name: output.model_json_schema() for name, (_, output, _) in CONTRACTS.items()}}

    @router.post("/engagements")
    def engagement(value: Engagement, actor: Principal = Depends(current)):
        """Record an auditor assignment without approving or executing its work program."""
        require_role(actor, "auditor")
        return {"created": create_engagement(service.engine, value), "id": value.id}

    @router.post("/tools/{name}")
    def invoke(name: str, arguments: dict, actor: Principal = Depends(current)):
        """Execute a tool as the internal agent after authenticating its human initiator."""
        require_role(actor, "auditor")
        return service.invoke(name, arguments, Principal("audit-agent", "agent"))

    @router.get("/reviews")
    def reviews(actor: Principal = Depends(current)):
        """List actual saved proposals and their complete edit/decision histories."""
        return service.reviews(actor)

    @router.get("/reviews/{proposal_id}")
    def review(proposal_id: str, actor: Principal = Depends(current)):
        """Open a contextual review record by its stable ID."""
        return service.reviews(actor, proposal_id)

    @router.post("/reviews/{proposal_id}/draft")
    def draft(proposal_id: str, value: DraftEdit, actor: Principal = Depends(current)):
        """Save only permitted proposal fields as a new pending version."""
        return service.save_draft(proposal_id, value, actor)

    @router.post("/reviews/{proposal_id}/decision")
    def decide(proposal_id: str, value: ReviewDecision, actor: Principal = Depends(current)):
        """Apply a human approval, rejection or request for changes to the opened version."""
        return service.decide(proposal_id, value, actor)

    @router.post("/findings/{finding_id}/action-plan")
    def action_plan(finding_id: str, value: ActionPlanInput, actor: Principal = Depends(current)):
        """Record a department claim through an auditor; it cannot close the finding."""
        return service.record_action_plan(finding_id, value, actor)

    @router.get("/runs/{run_id}")
    def run(run_id: str, actor: Principal = Depends(current)):
        """Read a saved calculated run; this route cannot edit or rerun it."""
        from backend.services.errors import AuditError
        require_role(actor, "auditor", "reviewer")
        with service.engine.connect() as c:
            row = service._row(c, t.artifacts, run_id)
            if row["kind"] != "run":
                raise AuditError("record_is_not_a_run", 404)
            return service._run_output(c, run_id)

    @router.get("/records/{kind}/{engagement_id}")
    def records(kind: str, engagement_id: str, actor: Principal = Depends(current)):
        """Read real persisted artifacts, results, requests or activity for one engagement."""
        from backend.services.errors import AuditError
        require_role(actor, "auditor", "reviewer")
        choices = {"artifacts": t.artifacts, "requests": t.evidence_requests, "activity": t.audit_events}
        if kind not in choices:
            raise AuditError("unknown_record_type", 404)
        table = choices[kind]
        with service.engine.connect() as c:
            service._row(c, t.engagements, engagement_id)
            return [dict(row) for row in c.execute(sa.select(table).where(
                table.c.engagement_id == engagement_id)).mappings()]
    return router
