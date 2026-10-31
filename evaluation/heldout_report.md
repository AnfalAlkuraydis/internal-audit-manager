# Phase 1-4 testing results

Executed 31 October 2026 (Asia/Riyadh). Run ID: 8439ca22-2637-4d7a-9b25-b03be95fec2b.

| Metric | Actual result |
|---|---|
| Held-out control-result accuracy | **100% (36/36)** |
| Held-out real-agent task completion | **100% (3/3)** |

Real Grok tasks: project governance **PASS**, privileged access **PASS**, endpoint security **PASS**. Each tested its full held-out population, proposed confirmed findings, requested missing evidence when needed, and stopped at the required human-review/evidence wait. Completion does not mean findings were automatically approved or closed.

## Held-out cases used

Audit period: **1 February-30 April 2027**. Each case covered four held-out entities and three controls (12 checks).

| Case | What was tested | Actual control outcomes |
|---|---|---|
| Project governance | Risk assessment before deployment, original approval before deployment, and agreement between GRC and original approval dates. The agent proposed confirmed findings and requested the missing original approval for HX-TEAL, shared by two controls. | 7 PASS, 3 FAIL, 2 MISSING_EVIDENCE |
| Privileged access | Active employment of account owners, MFA enabled, and access reviews within 90 days. The agent proposed findings for the confirmed exceptions. | 9 PASS, 3 FAIL |
| Endpoint security | EDR coverage, vulnerability scans within 30 days, and device encryption. The agent proposed findings for the confirmed exceptions. | 9 PASS, 3 FAIL |

PASS/FAIL above describe the audited controls. A failed control is not a failed agent test: success means the agent correctly identified and handled it. All three agent cases passed, including correctly leaving missing evidence unresolved.

Component-level evidence: **21 passed, 0 failed**. [Named component-test proof](component_test_proof.md).

The existing synthetic held-out partition contains 12 entities and 36 control/entity checks. Expected labels remain provisional. All three agent tasks passed on their first run; no prompts, production code, data or labels were changed during evaluation (input hashes verified).

[Raw metric results](heldout_summary.json) / [Protocol, traces and component receipts](heldout_runs/8439ca22-2637-4d7a-9b25-b03be95fec2b/summary.json).

Only the Phase 1-4 LIVE agent/backend were evaluated. The standalone prototype was excluded. No stress tests, Gmail or later-phase implementation was added. This evaluation supersedes earlier historical held-out NOT RUN notes.
