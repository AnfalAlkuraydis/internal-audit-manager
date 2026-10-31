# Synthetic data and audit scope

All names, policies and system records are fictional. The policy catalog is in data/catalog.json; versioned population/evidence bundles are separate JSON files.

## Initial development data

- Three policies, three controls each.
- Eight project deployments between 1 January and 31 August 2026.
- Eight privileged accounts and eight managed devices active during that period.
- 71 evidence records across seven fictional original/secondary sources.
- One unavailable original approval, affecting two dependent checks.
- A separate evaluation partition: four of each population, 35 evidence records, February-April 2027, different IDs and record order.

Each policy/control/procedure has a stable versioned record ID. Procedure definitions are typed data, not executable strings. No control engine exists yet.

| Control | Objective requirement |
|---|---|
| PR-01 | Original risk assessment date is on or before deployment. |
| PR-02 | Original approval date is on or before deployment. |
| PR-03 | Original approval and Compass-style GRC approval dates agree. Mismatches require investigation before findings. |
| PA-01 | Account owner has no employment end date, or it is later than the in-scope date. Employment end means first day no longer employed. |
| PA-02 | MFA is enabled on the in-scope date. |
| PA-03 | Access review is dated on/before the in-scope date and at most 90 calendar days old. |
| ES-01 | EDR coverage is active on the in-scope date. |
| ES-02 | Scan is dated on/before the in-scope date and at most 30 calendar days old. |
| ES-03 | Disk encryption is enabled on the in-scope date. |

Periods include both boundary days. Projects are eligible on their deployment date. Accounts/devices are eligible when their active interval overlaps scope; their in-scope snapshot date is the earlier of their active end and the engagement end. Open-ended active intervals are supported.

A source must be authorized for its evidence kind. A secondary GRC assertion is not a substitute for original approval history. Evidence absence is MISSING_EVIDENCE, not an automatic failure or pass. The later engine will distinguish errors, noncompliance and contradictory evidence.

## Evidence lineage and preservation

Evidence stores an entity link, dataset partition, original system, original record ID, version, observed/captured dates, structured facts, optional superseded-version link and SHA-256 fingerprint. Superseding versions preserve the original record. A fingerprint detects content differences; it does not prove source authenticity.

The seed importer inserts only. Existing IDs with changed content are rejected atomically. SQLite foreign keys are enabled on every application connection; compound references prevent cross-dataset evidence links. Normalized dates are stored as database dates; fact dates use ISO strings in JSON.

The immutable dataset fingerprint describes its initial seed manifest, with record lists sorted by stable ID. It is not an assertion that the database will never receive additional evidence. Future email ingestion will append evidence through its own validated service, not rewrite or reseed historical records.

## Planned missing-evidence and remediation story

PRJ-002 has an available late approval. PRJ-003 initially lacks original approval history despite its GRC claim. Its withheld reply supplies 22 March approval for 20 March deployment. PRJ-004 has a discrepancy between GRC and original-source dates. Other fixtures include a late assessment, terminated employee access, disabled MFA, stale review/scan, missing EDR coverage and disabled encryption.

tests/fixtures/followup_messages.json contains synthetic messages for future testing: the missing approval reply, a department-owned action plan, and a subsequent project with timely approval. They are not loaded into initial evidence and cannot influence initial tests. The new project is outside the historical audit period and has an explicit September verification period. It must not erase the original failures. Closure will require independent retesting and auditor approval in later phases.

No email processor, finding, action-plan workflow or closure mechanism is implemented here.

## Ground truth and limits

The separately authored answer keys contain one label for each control/eligible-entity pair: 72 development and 36 held-out labels, plus development follow-up expectations. They were defined without a testing-engine implementation. Phase 2 checks completeness and valid references only. Human review is still required before treating the labels as a validated benchmark.

The held-out cases remain outside default data loading and future development prompts. Their labels are visible in this local repository; this is a small reproducible evaluation partition, not a secret external benchmark.

New population records can be supplied in structured data without changing query logic. New kinds of testing may require an additional supported rule implementation later. Date-only evidence, compact JSON sources and one active procedure version per control record intentionally limit this phase. Policy changes should use new versioned control/procedure IDs; later execution must bind each test to the applicable policy version rather than mixing versions.
