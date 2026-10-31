# Phase 3 handover

## What was built

Eight typed tools now retrieve requirements, propose a work program, snapshot the full population/evidence, execute deterministic tests, queue evidence requests, propose findings and prepare verified closure. Separate human routes edit/review proposals. No autonomous agent loop, UI or email sender has been built.

Original evidence, calculated results and decision histories are protected from updates/deletes. New proposal versions preserve edits; approvals apply to the precise current version. Concurrent retry receipts and business fingerprints prevent duplicate effects.

## Actual verification

Run the offline suite with:
```powershell
.\.venv\Scripts\python.exe -m scripts.run_tests
```

The suite covers the existing foundation/data regressions, rule edge cases, invalid inputs, real SQLite migration/constraints, role spoofing, review versions, stale scope, concurrent retries, request routing/escalations and a whole deterministic remediation/closure scenario.

All 72 development labels matched: 61 PASS, 9 FAIL, 2 MISSING_EVIDENCE. These are actual calculated outcomes in test databases, compared against the separately authored provisional development key. They are not held-out agent-performance scores. The system test preserves detailed numerator/denominator observations.

The remediation test adds new compliant project evidence through test-fixture setup, not email. The original late-approval failure remains FAIL. Closure requires an explicit human decision. Updating the finding invalidates the pending closure; repeated approval creates no duplicate decision.

Live Grok inference was not needed for deterministic backend changes and remains NOT RUN in these runs. Phase 1's successful real tool-call verification remains historical evidence. No claim of audit autonomy or model superiority is made.

## Local use

Apply the migration without overwriting source data:
```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_data --database var/audit.sqlite
```

The local database keeps its existing 24 members and 71 evidence records. Tests use temporary databases, so the local workspace does not contain test-generated approvals/findings.

For the protected API, set distinct AUDIT_AUDITOR_TOKEN and AUDIT_REVIEWER_TOKEN values in your ignored .env, then start the backend using the README command. Empty tokens grant no access; there are no default passwords or tokens. Use the Authorize button in /docs with the relevant bearer token. Never put tokens in command-line URLs, source code or logs.

GET /tools provides schemas. POST /engagements creates an assignment. POST /tools/{name} performs one tool operation. GET /reviews and review routes inspect/edit/decide versions. GET /runs/{id} reads calculated results. No evidence/result mutation endpoint exists.

## Important files

- backend/agent/tools/contracts.py: typed inputs, outputs and exactly eight definitions.
- backend/services/control_testing.py: pure rule evaluation.
- backend/services/audit.py: persistence, scope, permissions, review/closure safeguards.
- backend/auth.py and backend/api.py: local role authentication and protected routes.
- migrations/versions/0002_execution_reviews.py: new tables and immutable-record triggers.
- tests/component/test_control_rules.py: independent rule boundaries.
- tests/integration/test_execution_reviews.py and test_review_api.py: safeguards and component handoffs.
- tests/system/test_control_workflow.py: 72 labelled outcomes and independent retest/closure.

## Limitations and next checkpoint

This phase provides callable backend operations, not the real agent decision loop. There is no automatic email receipt/resumption, reminder scheduler, chat UI or simulated-inference demo. Department action claims currently require an auditor to record them. Queued requests are not sent.

Each run binds one saved control/procedure/policy version. Current audit fixtures use one policy version throughout scope; complete mixed-version historical audit coverage still requires dedicated cases before claiming support. Narrative finding correctness, held-out performance, real-model adaptation and email recovery have not been evaluated. Demo token authentication is the agreed local prototype mechanism, not enterprise identity management.

Review the policy/answer assumptions and this backend before authorizing Phase 4: real Grok/LangGraph orchestration and the minimal working workspace.

## Final recorded run

Run 81531990-67c5-497f-80c8-ddf72c90ac1c (phase3-v5): 64 test methods, 63 PASS / 0 FAIL / 1 NOT RUN; 18.026111 seconds. Live check intentionally unrequested. All current Python modules/functions have descriptions. Local migration is 0002_execution_reviews; existing source counts remain unchanged and the local database contains no test-generated reviews/results.
