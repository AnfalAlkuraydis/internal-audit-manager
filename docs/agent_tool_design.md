# Agent tool design - implemented Phase 3 contracts

The canonical schemas are the Pydantic input/output classes in backend/agent/tools/contracts.py. GET /tools returns the eight function definitions and output schemas. All schemas reject unknown top-level fields. The shared LLM interface remains unchanged; there is no autonomous tool-selection loop yet.

## Shared rules

Every input inherits ToolInput: engagement_id and operation_id are required stable identifiers. Actor identity is injected by the backend, not supplied by the LLM. Each call validates its schema and record relationships. Invalid schema -> 422; unknown record/tool -> 404; missing permission/approval -> 403; stale/conflicting business state -> 409.

Calls use a transaction and a persisted retry receipt. The same actor/operation key with identical arguments returns the original response. Reusing it with different arguments is rejected. Business fingerprints also prevent duplicate snapshots, runs, findings and equivalent requests under different operation keys. Concurrent writers serialize their receipt checks.

Tools may create records only as described below. No tool approves a review, modifies evidence, overwrites a test result, executes arbitrary SQL/Python, or sends mail. Human decisions are separate authenticated backend operations.

## 1. get_audit_requirements

- Input/output: RequirementsInput -> RequirementsOutput.
- Depends on: engagement, dataset department, effective policies, controls, procedures and authorized sources.
- Creates/modifies: backend receipt and activity entry only.
- Output consumers: draft_audit_plan and later agent reasoning. Returns factual rules, IDs and versions, not invented tests.
- Permissions/side effects: auditor/internal agent; no external access.
- Errors: missing engagement, malformed arguments.
- Tests: all-control workflow, API authentication, shared schema checks and changed audit dates.

## 2. draft_audit_plan

- Input/output: PlanInput containing PlanDocument -> ProposalOutput.
- Depends on: applicable requirements, scope and optional already-approved finding for an explicit verification plan.
- Creates: plan proposal and immutable initial/revised proposal version. It never creates an approval.
- Output consumers: human review; get_test_population after approval.
- Permissions/side effects: auditor/internal agent may propose. Only authenticated auditor/reviewer roles decide. Agent revision is accepted after Request Changes; it cannot replace an approved/pending proposal silently.
- Errors: duplicate/out-of-scope controls, invalid verification scope, conflicting existing proposal.
- Tests: approval gate, rejection/request changes, version edits, stale decisions and bounded follow-up authorization.

PlanDocument includes objective, work_program and control_ids. Optional follow-up authorization is explicitly reviewed: allow_followup_verification defaults false; verification_window_days defaults 90 and is bounded to 1-365. It permits later evidence verification for approved findings of the same engagement/control within that window. The agent cannot change this authorization. An alternative separately approved verification assignment is also supported.

## 3. get_test_population

- Input/output: PopulationInput -> PopulationOutput.
- Depends on: current approved plan, selected control/procedure/policy, dataset and active/deployment dates.
- Creates: immutable population snapshot containing all eligible members, rule, policy and approved plan-version reference.
- Output consumers: search_evidence and run_control_test.
- Permissions/side effects: auditor/internal agent; read all eligible records, no sampling or source changes.
- Errors: unapproved/stale plan, control outside the approved program, unknown IDs, unapproved/out-of-window follow-up.
- Tests: complete populations, empty populations, date boundaries, stale scope and cross-engagement rejection.

For follow-up under the original plan, supply verification_for_finding_id, verification_start and verification_end together. Dates must be after the original audit period and inside the human-approved window. No extra approval pause is needed within that existing authorization. Findings and closure still require separate human decisions.

## 4. search_evidence

- Input/output: SearchInput -> EvidenceOutput.
- Depends on: valid population snapshot, dataset, source definitions and evidence records. Optional source_ids lets the future agent investigate alternative authorized sources.
- Creates: immutable evidence snapshot with provenance, fingerprints and missing-kind entries.
- Output consumers: run_control_test, request_department_input and future agent reasoning.
- Permissions/side effects: local authorized source retrieval only; no network, no fabricated evidence.
- Errors: unknown source, foreign/stale snapshot or invalid artifact fingerprint.
- Tests: linked retrieval/results, source authorization, missing approval, GRC discrepancy and cross-population rejection.

Search returns source facts, not a conclusion that every required fact is usable. The testing engine additionally checks snapshot dates, source authority, content integrity and unresolved contradictions. Evidence captured after the audit period may still establish a historical fact.

## 5. run_control_test

- Input/output: TestInput -> TestOutput.
- Depends on: linked population/evidence snapshots and current approval. Rule and policy versions are frozen in the population snapshot.
- Creates: immutable run and one test_result per population member.
- Output consumers: propose_finding, remediation verification, read-only run API and later UI.
- Permissions/side effects: deterministic Python operations only; no LLM outcome inference.
- Errors: foreign/mismatched/stale snapshots. Per-member malformed evidence is recorded as ERROR rather than stopping unrelated members.
- Tests: five supported rule types, equality/age/date boundaries, missing/conflicting/corrupt evidence, duplicate/concurrent calls and 72 independent development labels.

Outcomes: PASS, FAIL, MISSING_EVIDENCE, CONTRADICTORY_EVIDENCE, ERROR, NOT_APPLICABLE. Empty runs contain zero results and zero passes. GRC/original date disagreement fails the explicit reconciliation control; contradictory original-source claims remain unresolved instead of choosing a convenient fact. Findings must still be reviewed.

## 6. request_department_input

- Input/output: RequestInput -> RequestOutput.
- Depends on: current approved plan, evidence/population snapshot, scoped entity IDs and data/department_contacts.json routing.
- Creates: tracked queued request; escalations also create a human-review proposal.
- Output consumers: future email adapter and incoming-reply workflow.
- Permissions/side effects: queue only. Recipient must match the configured department list. Escalation stays on hold until the exact reviewed version is approved; editing it restores that hold.
- Errors: unapproved scope, out-of-scope entity, disallowed recipient or malformed routing configuration.
- Tests: queue/deduplicate requests, reordered members, recipient rejection, escalation approval and revised-message hold.

Queued never means sent. Future email dispatch must revalidate current approval/scope before external delivery. No sender or automatic email resumption exists in Phase 3.

## 7. propose_finding

- Input/output: FindingInput containing narrative FindingDocument and result_ids -> ProposalOutput.
- Depends on: saved FAIL results for one control in this engagement under the approved work program.
- Creates: finding proposal/version. Backend derives policy, control, result and evidence links.
- Output consumers: human review, department action recording and manage_remediation.
- Permissions/side effects: propose only. Permitted human edits: title, wording, severity, rationale and recommendation. Evidence/result links cannot be edited.
- Errors: passing/missing/error results, foreign/stale references, duplicate IDs or unsupported edits.
- Tests: reject unsupported findings, preserve original proposal/edits, prevent fact/result edits and deduplicate repeated findings.

Links enforce traceability; they do not automatically prove every narrative sentence is correct. Narrative evaluation and human review remain required.

## 8. manage_remediation

- Input/output: RemediationInput -> RemediationOutput.
- Depends on: approved finding; closure additionally requires a recorded department action claim and a nonempty all-PASS independent remediation run for the same control/finding.
- Creates: closure proposal/version only when verification conditions hold. Status reads existing action/closure records.
- Output consumers: mandatory closure review and later workspace.
- Permissions/side effects: cannot approve or close. Department claims enter through a human-only backend route now; incoming-email recording is future work.
- Errors: missing action/verification, historical audit run used as retest, wrong finding/control, stale or nonpassing verification.
- Tests: block early closure, reject agent-authored department claims, preserve historical failure, require later compliant evidence, reject stale closure after finding edits and require explicit human closure.

## Backend operations outside the tool list

Bearer authentication maps local demo tokens to server-defined auditor/reviewer identities. Human-only routes save draft versions and approve/reject/request changes. Decisions, identities and timestamps remain in history. Editing a plan invalidates prior execution snapshots. Editing a finding invalidates pending closure; approved closure prevents later silent changes to that finding.

ActionPlanInput records owner, action, due_on and source_reference through the auditor route. It is a department claim, not proof of success. Independent rule execution and human closure approval remain mandatory.

SQLite triggers reject updates/deletes of evidence, snapshots, results, proposal versions, decisions, action-plan history, receipts and activity. The schema migration is explicit; tests never seed approvals into the user's local database.
