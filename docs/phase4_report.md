# Phase 4 review

Phase 4 adds one LIVE Grok agent coordinated by LangGraph, durable automatic evidence follow-ups, and a local React/TypeScript workspace. Exactly eight business tools remain. Python calculates outcomes and enforces approvals; the model selects tools and arguments. No production mock LLM, demo playback, or Gmail adapter was added.

## What changed

- `backend/agent/orchestrator.py`, `context.py`, `prompt.py`: model-interpreted scope, current factual observations, bounded tool calls, SQLite checkpoints, interrupts, external-event resumption, cached inference and stable action receipts. Pending findings do not stop independent control testing. Missing-evidence obligations remain actionable until covered by a request.
- `backend/email/models.py`, `service.py`, `simulated.py`: normalized messages, durable deadlines/cadence, automatic simulated delivery, inbound validation and communication history. Default reminders recur every three days, with an earlier final pre-deadline reminder. Default evidence deadline is seven days when none was supplied.
- `backend/services/activity.py`, `workspace.py`, `app.py`: factual activity, protected workspace endpoints and a background worker. The server, rather than the browser, runs follow-ups. Restart reconnects to persisted sessions and checkpoints.
- `backend/database/tables.py`, migration `0003_agent_followups.py`: schedules, inbox/outbox, immutable delivery ledger, inference/tool receipts, work items, sessions and activity.
- Existing contracts/audit service: evidence/action-plan/implementation request purposes, approved remediation scope, same-record request deduplication across controls, and current-version escalation checks.
- `frontend/`: seven agreed sections, AI Chat assignment/activity, contextual version-aware Reviews, actual control outcomes, saved evidence/results, findings, editable deadlines and clearly labeled simulated department replies.
- `tests/integration/test_followups.py`, `test_workspace.py`: timing, retries, restarts, spoofed/incomplete replies, duplicate messages, obsolete deadlines, edited escalation wording, shared dependencies, authentication and automatic execution.
- `scripts/evaluate_phase4.py`, `check_frontend.py`, evaluation logs/traces, requirements/lockfiles, README and architecture/methodology notes: reproducible checks and measured results.

Files and important functions include explanatory docstrings/comments.

## Follow-up behavior and safeguards

An authorized ordinary evidence request is sent through the simulated transport automatically. Its durable schedule survives restarts. Missed intervals never generate a burst of historical reminders. Transport failures retry the same outgoing intent and message ID; simulated ledger insertion and delivery state commit atomically.

A reply must match an actually delivered thread and its authorized recipient. Valid source facts append new records without rewriting history. Duplicate incoming message IDs are idempotent; altered content under the same ID is rejected. Incomplete, conflicting or invalid evidence keeps the request outstanding. A resolving reply stops reminders and wakes the agent; dependent blocked controls become ready to investigate and retest. Late approval evidence can resolve a request while producing a FAIL result.

Overdue notices become human-review proposals. Sending checks the current reviewed wording, current deadline, current request status, approved scope and recipient again. Extending a deadline or resolving its request invalidates the old overdue escalation. Superseded-scope requests cannot keep sending. Several controls needing the same missing original record share one request.

Department action plans remain department-owned claims. Implementation evidence is independently retested in the auditor-approved follow-up period. A nonempty all-PASS remediation run is required before proposing closure; only a human can approve closure. Historical failures remain unchanged.

## Actual validation

Final backend run: 74 PASS, 0 FAIL, 1 NOT RUN (75 methods). UI: three DOM tests PASS, production build PASS, dependency audit zero vulnerabilities. Development full-audit outcomes matched 72/72 provisional labels. Complete measured counters and attempt history are in the summary below.

See `evaluation/phase4_summary.json`, `live_agent_tests.txt`, `frontend_tests.txt`, `regression_history.txt` and `phase4_traces/` for measured counts and full synthetic execution traces.

The six required real Azure Grok cases have passing results: complete evidence, authorized alternate original source, missing evidence requiring department communication, contradictory originals, post-block reply/restart through independent remediation and human closure, and transient tool-error recovery. These are small development cases, not held-out generalization scores.

The additional full-population run tested all nine controls and 72 entity/control pairs. It continued testing after pending findings and after a missing-evidence result; seven controls completed and two share the outstanding original-approval request. Full-run outcomes are compared to the separately authored provisional development key in the summary.

Failures were retained: the first transient-source case did not retry and attempted an unsupported finding (blocked by the backend); a focused recovery instruction fixed its retest. The full run encountered Azure rate limiting, then exposed an unresolved-evidence coordination gap and a payload-reference defect during its fix. Those failed attempts and the successful checkpoint recovery remain recorded. Offline checks also exposed a static mount changing an API response and a background-test timing race; both were fixed. The original UI worker runner failed to start; three in-process DOM checks now pass. The patched Vite dependency audit reports zero vulnerabilities.

## Running for review

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:create_app --factory --env-file .env --host 127.0.0.1
```

Open http://127.0.0.1:8000 and sign in with the private `AUDIT_AUDITOR_TOKEN` from your local ignored `.env`. Missing auditor/reviewer tokens were generated locally without displaying them or changing Azure credentials. Use an exact assignment such as ?Audit Digital Risk from 2026-01-01 through 2026-08-31.? Reviewers can sign in with their separate token. There are no default tokens.

The local database was migrated without adding evaluation approvals, results or messages to it. Evaluation cases use separate databases. The compiled UI is served by FastAPI. Rebuild with `python -m scripts.check_frontend` after changing UI source; a Node/npm installation or the verified local portable Node is required.

Reproduce offline checks with `python -m scripts.run_tests`. Explicit paid validation: `python -m scripts.evaluate_phase4` (six cases plus the additional full-population case). The evaluation driver acts as an explicitly identified test human at review checkpoints; this is never runtime auto-approval.

## Limits and Phase 5 boundary

Automatic work runs while the backend process is running; it catches up after restart. There is no operating-system service or external scheduler. A crashed in-flight agent lease expires within 120 seconds before another worker recovers it. The intended deployment is one local backend process, not a distributed worker fleet.

Email is simulated. Normalized reply JSON supplies source facts; free-text attachment extraction and real sender authentication belong with future Gmail integration. The current phase never sends real email. No DEMO inference adapter or three-minute playback exists yet.

Browser visual/manual acceptance testing is NOT RUN; production build, DOM interactions and HTTP serving were checked. Exact screenshot matching awaits supplied references. Held-out autonomy/performance, model comparisons and verified billing cost are NOT RUN/unknown. Development labels still require human review. Azure rate limits may pause a session; the visible retry action preserves checkpoint and receipt history.

Stop here for Phase 4 review. Phase 5 is not implemented.
