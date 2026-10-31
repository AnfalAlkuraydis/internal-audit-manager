# Connected demo-style UI / Phase 4 agent

The polished React design is now the LIVE workspace at http://127.0.0.1:8000/.
Sign in with AUDIT_AUDITOR_TOKEN from the ignored local .env. Select an existing audit or start a new assignment. Reviewers can use their separate token and cannot start audits or submit synthetic evidence.

The standalone frontend-only prototype is intentionally excluded from this repository. Only the connected LIVE workspace is distributed.

## Connected behavior

- All seven sections use actual saved backend records; no prototype mock model or fallback is imported.
- Chat queues real Grok assignments and displays factual persisted activity. Timing follows actual inference and tool execution.
- Plan/finding/escalation/closure editing and approval retain exact-version checks. Department claims and independent verification remain separate.
- Charts, counts, source previews, control results and remediation state come from the selected session. Risk statements use saved finding rationale; no synthetic risk ratings are shown.
- Simulated outgoing mail, deadlines, reminders and complete communication history use Phase 4 services.
- Prepare synthetic reply reads the actual outstanding request and creates a preview only. Explicitly receiving the reviewed JSON submits it through normal validation and wakes the real agent.
- Action-plan and implementation reply previews support actual retesting and human closure approval. Generated evidence is marked synthetic; no Gmail or document-extraction service is connected.
- New audit starts a separate saved session; it does not erase existing audits. Credentials remain in memory.

## Validation

Backend regression: 76 PASS / 0 FAIL / 1 NOT RUN (77 methods). The unrequested legacy compatibility check is separate from the real connected-browser validation.

Frontend: production build PASS; 3 existing DOM tests PASS; dependency audit zero vulnerabilities.

Actual Chrome workflow in a separate PR-02 development database: real Grok plan, explicit test-human approval, original-evidence reply, finding approval, department action-plan reply, implementation reply, independent retest and human-approved closure all passed. Three synthetic replies resolved; one closure was approved. Real inference and tool receipts are in evaluation/connected_ui_trace.json. This focused UI integration check does not replace or change earlier held-out metrics.

Desktop/mobile screenshots and browser results: frontend/review/. No browser JavaScript errors or mobile horizontal overflow were observed. Test approvals and synthetic records were not inserted into the user's audit database.

## Main files

frontend/src/main.tsx, style.css, Icon.tsx and ReviewPanel.tsx connect the prototype visual system to existing backend APIs.
backend/workspace.py adds authenticated role discovery and synthetic-reply preview.
backend/email/samples.py creates explicit scoped previews without writes or approval.
tests/integration/test_connected_mail.py verifies roles, preview isolation, idempotent receipt and independent closure.
scripts/serve_connected_test.py and frontend/scripts/connected-browser.mjs reproduce the isolated real UI check.

Normalized reply JSON can be edited before submission. Missing-evidence sample previews require an actual evidence gap; unsupported/conflicting cases can use manually supplied normalized replies. Real email, attachment extraction and unrestricted conversational follow-ups remain outside this integration. The chat composer creates a new audit assignment; existing work resumes automatically from persisted events.
