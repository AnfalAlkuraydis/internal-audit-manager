"""Validate the shape and relationships of incoming audit records.

These Pydantic models turn JSON into checked Python values before storage.
Rule models describe permitted tests; no control-testing engine runs here.
Database tables and constraints are defined separately in tables.py.
"""
from datetime import date
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

EntityKind = Literal["project", "privileged_account", "device"]
EvidenceKind = Literal["risk_assessment", "project_approval", "grc_approval",
                       "employment", "mfa", "access_review", "edr",
                       "vulnerability_scan", "encryption"]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")]
Text = Annotated[str, Field(min_length=1, max_length=2000)]

class Record(BaseModel):
    """Base input rules: reject unknown fields and prevent attribute reassignment."""
    model_config = ConfigDict(extra="forbid", frozen=True)

class Source(Record):
    """Describe a source system and which evidence kinds it may supply."""
    id: Identifier
    system: Text
    authority: Literal["original", "secondary"]
    allowed_kinds: list[EvidenceKind] = Field(min_length=1)

class Policy(Record):
    """A versioned policy with its department and inclusive effective dates."""
    id: Identifier
    title: Text
    version: Annotated[int, Field(strict=True, ge=1)]
    department: Text
    effective_from: date
    effective_to: date | None = None
    text: Text

    @model_validator(mode="after")
    def dates(self):
        """Reject a policy whose effective interval ends before it starts."""
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("Policy end precedes start.")
        return self

class Control(Record):
    """Link one auditable requirement and population kind to a policy record."""
    id: Identifier
    policy_id: Identifier
    title: Text
    entity_kind: EntityKind
    requirement: Text

class BeforeEvent(Record):
    """Describe a date check against project deployment; do not execute it."""
    operation: Literal["on_or_before"]
    evidence_kind: Literal["risk_assessment", "project_approval"]
    evidence_field: Literal["assessed_on", "approved_on"]
    entity_field: Literal["deployed_on"]

class SourceAgreement(Record):
    """Describe comparison of original and GRC approval dates."""
    operation: Literal["dates_agree"]
    evidence_kind: Literal["project_approval"]
    other_evidence_kind: Literal["grc_approval"]
    field: Literal["approved_on"]

class BooleanCheck(Record):
    """Describe a required enabled/covered state on the last active day in scope."""
    operation: Literal["is_true"]
    evidence_kind: Literal["mfa", "edr", "encryption"]
    field: Literal["enabled", "covered"]
    as_of: Literal["last_active_day"]

class RecencyCheck(Record):
    """Describe the maximum permitted age of an in-scope review or scan."""
    operation: Literal["not_older_than"]
    evidence_kind: Literal["access_review", "vulnerability_scan"]
    field: Literal["reviewed_on", "scanned_on"]
    max_age_days: Annotated[int, Field(strict=True, ge=0, le=3650)]
    as_of: Literal["last_active_day"]

class EmploymentCheck(Record):
    """Describe whether employment continues beyond the in-scope date."""
    operation: Literal["employed_at"]
    evidence_kind: Literal["employment"]
    field: Literal["employment_end"]
    as_of: Literal["last_active_day"]

Rule = Annotated[BeforeEvent | SourceAgreement | BooleanCheck | RecencyCheck | EmploymentCheck,
                 Field(discriminator="operation")]
# The operation field selects the rule model; no arbitrary expression is executed.
# These maps describe the domain, rather than specific synthetic records or outcomes.
KIND_OWNER = {
    "risk_assessment": "project", "project_approval": "project", "grc_approval": "project",
    "employment": "privileged_account", "mfa": "privileged_account",
    "access_review": "privileged_account", "edr": "device",
    "vulnerability_scan": "device", "encryption": "device",
}
FACT_FIELDS = {
    "risk_assessment": "assessed_on", "project_approval": "approved_on",
    "grc_approval": "approved_on", "employment": "employment_end",
    "mfa": "enabled", "access_review": "reviewed_on", "edr": "covered",
    "vulnerability_scan": "scanned_on", "encryption": "enabled",
}

class Procedure(Record):
    """Pair a control with versioned instructions and one supported rule shape."""
    id: Identifier
    control_id: Identifier
    version: Annotated[int, Field(strict=True, ge=1)]
    instructions: Text
    rule: Rule

    @model_validator(mode="after")
    def fields_match(self):
        """Ensure the rule reads the factual field defined for its evidence kind."""
        field = getattr(self.rule, "evidence_field", getattr(self.rule, "field", None))
        if field != FACT_FIELDS[self.rule.evidence_kind]:
            raise ValueError("Procedure field does not match its evidence kind.")
        return self

class Catalog(Record):
    """Group source definitions, policies, controls and procedures for validation."""
    schema_version: Literal[1]
    sources: list[Source] = Field(min_length=1)
    policies: list[Policy] = Field(min_length=1)
    controls: list[Control] = Field(min_length=1)
    procedures: list[Procedure] = Field(min_length=1)

    @model_validator(mode="after")
    def relationships(self):
        """Reject duplicate IDs, broken references, or incompatible rule populations."""
        for collection in (self.sources, self.policies, self.controls, self.procedures):
            if len({item.id for item in collection}) != len(collection):
                raise ValueError("Duplicate catalog IDs.")
        policies = {item.id for item in self.policies}
        controls = {item.id: item for item in self.controls}
        if any(item.policy_id not in policies for item in self.controls):
            raise ValueError("Unknown control policy.")
        if {item.control_id for item in self.procedures} != set(controls):
            raise ValueError("Each control needs a procedure.")
        if len({item.control_id for item in self.procedures}) != len(self.procedures):
            raise ValueError("Only one procedure version per control record is supported initially.")
        for item in self.procedures:
            if KIND_OWNER[item.rule.evidence_kind] != controls[item.control_id].entity_kind:
                raise ValueError("Procedure evidence belongs to a different population.")
        return self

class ProjectFacts(Record):
    """Store the deployment date used to select projects for an audit."""
    deployed_on: date

class AccountFacts(Record):
    """Describe the fictional account owner and privileged role."""
    owner: Text
    role: Text

class DeviceFacts(Record):
    """Identify a managed device by its recorded hostname."""
    hostname: Text

ENTITY_FACTS = {"project": ProjectFacts, "privileged_account": AccountFacts, "device": DeviceFacts}

class Entity(Record):
    """A typed population member with an inclusive active interval."""
    id: Identifier
    source_id: Identifier
    kind: EntityKind
    name: Text
    active_from: date
    active_to: date | None = None
    facts: dict

    @model_validator(mode="after")
    def valid_facts(self):
        """Validate kind-specific facts and normalize dates for JSON storage."""
        parsed = ENTITY_FACTS[self.kind].model_validate(self.facts)
        if self.active_to and self.active_to < self.active_from:
            raise ValueError("Entity end precedes start.")
        if self.kind == "project" and not (
            self.active_from == parsed.deployed_on == self.active_to
        ):
            raise ValueError("Project eligibility must equal its deployment date.")
        # Normalize once during validation, despite later attribute reassignment being blocked.
        object.__setattr__(self, "facts", parsed.model_dump(mode="json"))
        return self

class AssessmentFacts(Record):
    """Record when the project risk assessment took place."""
    assessed_on: date

class ApprovalFacts(Record):
    """Record the approval date claimed by a particular source."""
    approved_on: date

class EmploymentFacts(Record):
    """Record the first day no longer employed; None means no known end date."""
    employment_end: date | None

class EnabledFacts(Record):
    """Record a strict boolean state and the date the snapshot describes."""
    enabled: StrictBool
    snapshot_on: date

class CoverageFacts(Record):
    """Record endpoint protection coverage for a specified snapshot date."""
    covered: StrictBool
    snapshot_on: date

class ReviewFacts(Record):
    """Record when the privileged-access review took place."""
    reviewed_on: date

class ScanFacts(Record):
    """Record when the vulnerability scan took place."""
    scanned_on: date

EVIDENCE_FACTS = {
    "risk_assessment": AssessmentFacts, "project_approval": ApprovalFacts,
    "grc_approval": ApprovalFacts, "employment": EmploymentFacts, "mfa": EnabledFacts,
    "access_review": ReviewFacts, "edr": CoverageFacts, "vulnerability_scan": ScanFacts,
    "encryption": EnabledFacts,
}

class Evidence(Record):
    """Preserve source identity, dates, version links and typed factual content."""
    id: Identifier
    entity_id: Identifier
    source_id: Identifier
    source_record_id: Identifier
    kind: EvidenceKind
    version: Annotated[int, Field(strict=True, ge=1)] = 1
    observed_on: date
    captured_on: date
    supersedes_id: Identifier | None = None
    facts: dict

    @model_validator(mode="after")
    def valid_facts(self):
        """Validate evidence facts and reject capture dates preceding observation."""
        parsed = EVIDENCE_FACTS[self.kind].model_validate(self.facts)
        if self.captured_on < self.observed_on:
            raise ValueError("Evidence cannot be captured before it was observed.")
        # JSON mode stores dates consistently as ISO strings in the facts column.
        object.__setattr__(self, "facts", parsed.model_dump(mode="json"))
        return self

class Dataset(Record):
    """Identify a versioned development or held-out partition without answer labels."""
    id: Identifier
    version: Annotated[int, Field(strict=True, ge=1)]
    split: Literal["development", "held_out"]
    department: Text
    description: Text

class SeedBundle(Record):
    """The initial population and evidence imported for one dataset partition."""
    schema_version: Literal[1]
    dataset: Dataset
    entities: list[Entity]
    evidence: list[Evidence]

    @model_validator(mode="after")
    def relationships(self):
        """Validate entity links, unique source versions and replacement lineage."""
        entities = {item.id: item for item in self.entities}
        evidence = {item.id: item for item in self.evidence}
        if len(entities) != len(self.entities) or len(evidence) != len(self.evidence):
            raise ValueError("Duplicate entity or evidence IDs.")
        source_versions = set()
        for item in self.evidence:
            entity = entities.get(item.entity_id)
            if entity is None or KIND_OWNER[item.kind] != entity.kind:
                raise ValueError("Evidence does not match its entity.")
            key = (item.source_id, item.source_record_id, item.version)
            if key in source_versions:
                raise ValueError("Duplicate source-record version.")
            source_versions.add(key)
            if item.supersedes_id:
                prior = evidence.get(item.supersedes_id)
                if (prior is None or prior.entity_id != item.entity_id
                        or prior.source_id != item.source_id or prior.kind != item.kind
                        or prior.source_record_id != item.source_record_id
                        or prior.version >= item.version):
                    raise ValueError("Invalid evidence version relationship.")
        return self

class Engagement(Record):
    """An audit assignment selecting a dataset, department and inclusive period."""
    id: Identifier
    dataset_id: Identifier
    department: Text
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def dates(self):
        """Reject an audit period whose end precedes its start."""
        if self.period_end < self.period_start:
            raise ValueError("Audit end precedes start.")
        return self
