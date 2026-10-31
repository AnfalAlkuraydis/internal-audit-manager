"""Inputs and outputs for the eight tools, plus separate human-only review inputs."""
from datetime import date, datetime
from typing import Literal
from pydantic import Field, model_validator
from backend.database.schemas import Record, Identifier, Text, Rule, Source, EvidenceKind
from backend.agent.llm_interface import ToolDefinition

Outcome = Literal["PASS", "FAIL", "MISSING_EVIDENCE", "CONTRADICTORY_EVIDENCE", "ERROR", "NOT_APPLICABLE"]
OUTCOMES = ("PASS", "FAIL", "MISSING_EVIDENCE", "CONTRADICTORY_EVIDENCE", "ERROR", "NOT_APPLICABLE")
ReviewKind = Literal["plan", "finding", "escalation", "closure"]

class ToolInput(Record):
    """Scope every operation and give retries a stable caller-supplied identity."""
    engagement_id: Identifier
    operation_id: Identifier

class RequirementsInput(ToolInput):
    """Retrieve scope and applicable requirements without starting execution."""

class PlanDocument(Record):
    """Editable work program; backend validation binds its controls to this audit."""
    objective: Text
    work_program: Text
    control_ids: list[Identifier] = Field(min_length=1)
    remediation_for_finding_id: Identifier | None = None
    allow_followup_verification: bool = False
    verification_window_days: int = Field(default=90, ge=1, le=365, strict=True)

    @model_validator(mode="after")
    def unique_controls(self):
        """Reject duplicate controls rather than executing the same work twice."""
        if len(set(self.control_ids)) != len(self.control_ids):
            raise ValueError("Duplicate controls.")
        return self

class PlanInput(ToolInput):
    """Propose a work program, never approve it."""
    plan: PlanDocument

class PopulationInput(ToolInput):
    """Snapshot the full population for one approved control."""
    control_id: Identifier
    verification_for_finding_id: Identifier | None = None
    verification_start: date | None = None
    verification_end: date | None = None

    @model_validator(mode="after")
    def verification_fields(self):
        """Require a complete, ordered verification scope or no override at all."""
        provided = (self.verification_for_finding_id, self.verification_start, self.verification_end)
        if any(value is not None for value in provided) and not all(value is not None for value in provided):
            raise ValueError("Incomplete verification scope.")
        if self.verification_start and self.verification_end < self.verification_start:
            raise ValueError("Reversed verification dates.")
        return self

class SearchInput(ToolInput):
    """Search a stored population with optional authorized source filters."""
    population_snapshot_id: Identifier
    source_ids: list[Identifier] | None = Field(default=None, min_length=1)

class TestInput(ToolInput):
    """Execute the saved procedure against linked, immutable snapshots."""
    population_snapshot_id: Identifier
    evidence_snapshot_id: Identifier

class RequestInput(ToolInput):
    """Queue a scoped evidence request; escalation requires a separate human review."""
    evidence_snapshot_id: Identifier
    entity_ids: list[Identifier] = Field(min_length=1)
    recipient: Text
    subject: Text
    message: Text
    escalation: bool = False
    purpose: Literal["evidence", "action_plan", "implementation"] = "evidence"
    finding_id: Identifier | None = None
    due_at: datetime | None = None
    reminder_interval_days: int = Field(default=3, ge=1, le=30, strict=True)

    @model_validator(mode="after")
    def communication_scope(self):
        """Require approved-finding context for remediation and aware deadline timestamps."""
        if self.purpose != "evidence" and not self.finding_id:
            raise ValueError("Remediation requests require a finding.")
        if self.due_at is not None and self.due_at.tzinfo is None:
            raise ValueError("Deadline requires a timezone offset.")
        return self

class FindingDocument(Record):
    """Only narrative fields are editable; supporting results are supplied separately."""
    title: Text
    wording: Text
    severity: Literal["low", "medium", "high", "critical"]
    rationale: Text
    recommendation: Text

class FindingInput(ToolInput):
    """Propose a finding using saved failed results rather than model-supplied outcomes."""
    result_ids: list[Identifier] = Field(min_length=1)
    finding: FindingDocument

class RemediationInput(ToolInput):
    """Inspect remediation or propose closure after independent saved verification."""
    finding_id: Identifier
    action: Literal["status", "propose_closure"]
    verification_run_id: Identifier | None = None
    rationale: Text = "Independent verification requested."

class RequirementItem(Record):
    """Return policy/procedure versions and factual requirements for one control."""
    control_id: Identifier
    title: Text
    requirement: Text
    policy_id: Identifier
    policy_version: int
    policy_text: Text
    procedure_id: Identifier
    procedure_version: int
    rule: Rule

class RequirementsOutput(Record):
    """Actual scope, applicable controls and source definitions."""
    engagement_id: Identifier
    period_start: date
    period_end: date
    controls: list[RequirementItem]
    sources: list[Source]

class ProposalOutput(Record):
    """A reviewable saved proposal, with the precise version requiring a decision."""
    proposal_id: Identifier
    version_id: Identifier
    version: int
    kind: ReviewKind
    status: Literal["pending", "approved", "rejected", "changes_requested"]

class PopulationOutput(Record):
    """Saved complete population and its approved work-plan reference."""
    population_snapshot_id: Identifier
    control_id: Identifier
    plan_version_id: Identifier
    count: int
    members: list[dict]

class Gap(Record):
    """One missing necessary evidence kind for a population member."""
    entity_id: Identifier
    evidence_kind: EvidenceKind

class EvidenceOutput(Record):
    """Source-backed evidence candidates, saved for reproducible execution."""
    evidence_snapshot_id: Identifier
    population_snapshot_id: Identifier
    records: list[dict]
    gaps: list[Gap]

class ResultRecord(Record):
    """An immutable calculated outcome with IDs back to its evidence and procedure."""
    id: Identifier
    entity_id: Identifier
    outcome: Outcome
    reason: Text
    evidence_ids: list[Identifier]

class TestOutput(Record):
    """Actual per-member results and counts; empty populations never count as passes."""
    run_id: Identifier
    control_id: Identifier
    purpose: Literal["audit", "remediation"]
    results: list[ResultRecord]
    counts: dict[str, int]

class RequestOutput(Record):
    """A persisted request; queued is not a claim that an email was sent."""
    request_id: Identifier
    status: Literal["queued", "waiting_for_approval", "sent", "received", "resolved", "cancelled"]
    review: ProposalOutput | None = None

class RemediationOutput(Record):
    """Current department action claim and any pending auditor closure review."""
    finding_id: Identifier
    action_plan: dict | None
    closure: ProposalOutput | None = None

class DraftEdit(Record):
    """Human edits require the version actually opened and an allowlisted patch."""
    expected_version_id: Identifier
    changes: dict = Field(min_length=1)

class ReviewDecision(Record):
    """A human decision; identity and role are supplied only by authentication."""
    expected_version_id: Identifier
    decision: Literal["approved", "rejected", "changes_requested"]
    reason: Text

class ActionPlanInput(Record):
    """Record a department-owned claim; it does not prove remediation worked."""
    owner: Text
    action: Text
    due_on: date
    source_reference: Text

CONTRACTS = {
    "get_audit_requirements": (RequirementsInput, RequirementsOutput, "Retrieve applicable requirements and source definitions."),
    "draft_audit_plan": (PlanInput, ProposalOutput, "Save a work-program proposal for mandatory human approval."),
    "get_test_population": (PopulationInput, PopulationOutput, "Snapshot every eligible record for an approved control."),
    "search_evidence": (SearchInput, EvidenceOutput, "Retrieve stored evidence from authorized local sources."),
    "run_control_test": (TestInput, TestOutput, "Execute the saved deterministic rule; do not infer outcomes."),
    "request_department_input": (RequestInput, RequestOutput, "Queue a department evidence request; never approve escalation."),
    "propose_finding": (FindingInput, ProposalOutput, "Submit an evidence-backed finding for human review."),
    "manage_remediation": (RemediationInput, RemediationOutput, "Inspect remediation or submit independently verified closure for review."),
}

def tool_definitions() -> list[ToolDefinition]:
    """Expose exactly eight JSON tool definitions, with no approval or SQL capability."""
    return [ToolDefinition(name=name, description=description, parameters=inputs.model_json_schema())
            for name, (inputs, _, description) in CONTRACTS.items()]
