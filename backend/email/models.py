"""Typed normalized email events shared by simulated and future Gmail adapters."""
from datetime import datetime, date
from pydantic import Field, model_validator
from backend.database.schemas import Record, Evidence, Entity, Identifier, Text
from backend.agent.tools.contracts import ActionPlanInput

class VerificationPeriod(Record):
    """Department-supplied dates remain subject to the auditor-approved follow-up bounds."""
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def ordered(self):
        """Reject reversed verification intervals."""
        if self.period_end < self.period_start:
            raise ValueError("Invalid verification interval.")
        return self

class DepartmentPlan(Record):
    """The department owns this claim; email provenance is added by the backend."""
    owner: Text
    action: Text
    due_on: date

class IncomingMail(Record):
    """Match an actual sent message; supplied request IDs or subject text grant no authority."""
    message_id: str = Field(min_length=1, max_length=512)
    in_reply_to: str = Field(min_length=1, max_length=512)
    sender: str = Field(min_length=3, max_length=320)
    body: str = Field(default="", max_length=6000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)
    entities: list[Entity] = Field(default_factory=list, max_length=100)
    action_plan: DepartmentPlan | None = None
    verification_period: VerificationPeriod | None = None

class FollowupEdit(Record):
    """Human scheduling changes do not authorize sending an escalation."""
    due_at: datetime
    reminder_interval_days: int = Field(default=3, strict=True, ge=1, le=30)

    @model_validator(mode="after")
    def aware_time(self):
        """Reject ambiguous local timestamps instead of guessing a timezone."""
        if self.due_at.tzinfo is None:
            raise ValueError("Deadline requires a timezone offset.")
        return self
