"""Reusable isolated database fixtures; never imported by application code."""
from pathlib import Path
from uuid import uuid4
import tempfile
from backend.auth import Principal
from backend.database.connection import create_database
from backend.database.migrate import migrate
from backend.database.repository import read_catalog, read_bundle, load_seed, create_engagement
from backend.database.schemas import Engagement
from backend.agent.tools.contracts import ReviewDecision
from backend.services.audit import AuditService

ROOT = Path(__file__).resolve().parents[1]
NARRATIVE = dict(title="Recorded control exception", wording="The saved evidence violates the requirement.",
                 severity="medium", rationale="Based on the referenced deterministic result.",
                 recommendation="Correct the process and submit new evidence.")

class AuditFixture:
    """Give each test a migrated database, synthetic records and trusted test identities."""

    def setUp(self):
        """Prepare the database and dispose its connections before removing temporary files."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = create_database(Path(self.temp.name) / "audit.sqlite")
        self.addCleanup(self.engine.dispose)
        migrate(self.engine)
        self.catalog = read_catalog(ROOT / "data/catalog.json")
        load_seed(self.engine, self.catalog, read_bundle(ROOT / "data/development/dataset.json"))
        self.safe_trace = []
        self.service = AuditService(self.engine)
        self.agent = Principal("test-agent", "agent")
        self.auditor = Principal("test-auditor", "auditor")
        self.reviewer = Principal("test-reviewer", "reviewer")
        self.engagement_id = "AUDIT-DEV"
        self.new_engagement(self.engagement_id, "digital-risk-dev.v1", "2026-01-01", "2026-08-31")

    def new_engagement(self, id, dataset_id, start, end):
        """Create a scoped assignment without silently approving it."""
        create_engagement(self.engine, Engagement(id=id, dataset_id=dataset_id, department="Digital Risk",
                                                 period_start=start, period_end=end))

    def tool(self, name, engagement_id=None, operation_id=None, **arguments):
        """Call the actual business tool service with a fresh retry identity by default."""
        call = dict(engagement_id=engagement_id or self.engagement_id,
                    operation_id=operation_id or str(uuid4()), **arguments)
        trace = dict(event="backend_tool_test", tool=name, inference_source="none",
                     engagement_id=call["engagement_id"], operation_id=call["operation_id"],
                     input_references={key: value for key, value in arguments.items()
                                       if key.endswith("_id") or key.endswith("_ids")})
        try:
            result = self.service.invoke(name, call, self.agent)
        except Exception as error:
            self.safe_trace.append({**trace, "outcome": "rejected",
                                    "error_code": getattr(error, "code", type(error).__name__)})
            raise
        summary = {key: value for key, value in result.items()
                   if key.endswith("_id") or key in {"counts", "status", "purpose", "kind", "version", "results"}}
        for key, target in (("members", "entity_ids"), ("records", "evidence_ids")):
            if key in result:
                summary[target] = [row["id"] for row in result[key]]
        self.safe_trace.append({**trace, "outcome": "completed", "result": summary})
        return result

    def decision(self, proposal, choice="approved", actor=None):
        """Submit an explicit test human decision to the version opened by the test."""
        reviewer = actor or self.reviewer
        trace = dict(event="backend_review_test", inference_source="none",
                     proposal_id=proposal["proposal_id"], version_id=proposal["version_id"],
                     decision=choice, actor_role=reviewer.role)
        try:
            result = self.service.decide(proposal["proposal_id"], ReviewDecision(
                expected_version_id=proposal["version_id"], decision=choice, reason="Test human review"), reviewer)
        except Exception as error:
            self.safe_trace.append({**trace, "outcome": "rejected",
                                    "error_code": getattr(error, "code", type(error).__name__)})
            raise
        self.safe_trace.append({**trace, "outcome": "completed", "result": result})
        return result

    def plan(self, engagement_id=None, controls=None, finding_id=None, allow_followup=False):
        """Draft and manually approve the configured full or verification work program."""
        id = engagement_id or self.engagement_id
        requirements = self.tool("get_audit_requirements", engagement_id=id)
        proposal = self.tool("draft_audit_plan", engagement_id=id, plan=dict(
            objective="Test configured controls", work_program="Inspect the full eligible population.",
            control_ids=controls or [r["control_id"] for r in requirements["controls"]],
            remediation_for_finding_id=finding_id, allow_followup_verification=allow_followup))
        return self.decision(proposal)

    def execute_control(self, control_id, engagement_id=None):
        """Exercise the actual population -> evidence -> deterministic result handoffs."""
        id = engagement_id or self.engagement_id
        population = self.tool("get_test_population", engagement_id=id, control_id=control_id)
        evidence = self.tool("search_evidence", engagement_id=id,
                             population_snapshot_id=population["population_snapshot_id"])
        result = self.tool("run_control_test", engagement_id=id,
            population_snapshot_id=population["population_snapshot_id"],
            evidence_snapshot_id=evidence["evidence_snapshot_id"])
        return population, evidence, result

    def finding(self, control_id="PR-02.v1"):
        """Propose a finding from actual failed results, without approving it automatically."""
        _, _, run = self.execute_control(control_id)
        result_ids = [r["id"] for r in run["results"] if r["outcome"] == "FAIL"]
        return self.tool("propose_finding", result_ids=result_ids, finding=NARRATIVE)
