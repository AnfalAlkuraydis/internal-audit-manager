# Evaluation methodology ? Phase 1

Component tests cover settings, safe representations, invalid modes/timeouts/URLs, and typed message contracts. Integration tests exercise the actual HTTP adapter with mocked transport: request serialization, a tool-result round trip, usage, provider rejection, malformed responses, timeout, connection failure, and health state.

The live system check runs only when configuration is complete. It requests a test-only echo function, verifies its arguments, executes it locally, and sends the result back to Grok. It is a compatibility check, not proof of audit autonomy. Missing configuration is NOT RUN; a configured provider failure is FAIL.

Run python -m scripts.run_tests to preserve actual results. Six append-only TXT files retain test and run metadata. Execution mode is live, but inference_source distinguishes mocked/absent inference from actual Azure calls. Zero retries are performed. Cost is unknown until deployment pricing and suitable usage reporting are available. Reports contain no raw provider messages or exception bodies.

Held-out audit evaluation, all audit metrics, baseline experiments, live autonomy scenarios, and demo evaluation are NOT RUN and deferred to their approved phases. No synthetic performance scores are generated. Future changes will preserve prior failures, describe fixes, and link actual retests by run ID.

## Phase 2 evaluation additions

Run python -m scripts.run_tests for offline regressions; add --live only when deliberately validating paid Grok inference. Unrequested inference is recorded as NOT RUN rather than a pass. The Phase 1 live result remains historical measured evidence.

Schema tests exercise counts, malformed facts, date intervals, duplicate IDs, evidence versions and procedure relationships. Database tests exercise actual Alembic migrations, schema parity, rollback, source authorization, foreign keys, changed/empty/reordered imports, repeatability, additional records, boundary dates and engagement/partition isolation. System tests launch the documented setup command in a clean temporary directory twice and verify persisted counts. These are whole-data-setup tests, not whole-audit tests.

Ground-truth files in evaluation/ground_truth/ have 72 development labels and 36 held-out labels. Validation checks coverage and references only. Expected labels were separately authored without calling a deterministic testing implementation. They need human review. Runtime modules do not load these files. The held-out data changes IDs, record order, period, population size and boundary conditions. Shared policy definitions are intentional. Future performance runs must freeze versions and avoid tuning on the held-out outcomes.

The final logged suite has 38 test methods: 13 component, 21 integration, 3 system, 1 live check. Of these, 37 passed and the live check was not run. Zero paid inference calls were made in Phase 2. No control-correctness, autonomy, retrieval, finding, recovery or comparative-model score has been measured in this phase. Ground-truth expectations are not actual engine results.

The reordered-import defect originally raised DataConflict because list order affected the manifest fingerprint. Canonical ID ordering fixed it; the failed run and full successful retest remain in regression_history.txt. Test observations record actual data counts. Test and trace dates use explicit UTC timestamps.

## Phase 3 measured verification

The full offline suite includes rule boundaries, invalid schema arguments, original/secondary sources, missing/conflicting/corrupt evidence, age and employment boundaries, empty populations, immutable-record enforcement, plan/finding/escalation/closure gates, edit history, stale versions, cross-scope misuse, recipient restrictions and concurrent duplicate operations. API tests exercise actual HTTP authentication and body-role spoof attempts. A whole deterministic workflow verifies new compliant evidence without rewriting historical failures.

The rule engine was compared only with the separately authored development key: 72/72 item/control outcomes matched; 61 PASS, 9 FAIL, 2 MISSING_EVIDENCE. The labels remain provisional pending human review. All 72 result evidence-reference sets were checked against retrieved records, including nonempty supporting references for every failed result. This tests traceability, not narrative correctness or an evidence-retrieval accuracy benchmark.

Final suite 81531990-67c5-497f-80c8-ddf72c90ac1c (phase3-v5): 64 test methods, 63 PASS, 0 FAIL, 1 intentionally NOT RUN; duration 18.026111 seconds, no automatic retries. No paid inference calls were made. The dataset validation test still marks its own control-correctness observation NOT RUN because that particular test checks label coverage only; the separate Phase 3 rule-workflow test records the actual 72/72 comparison.

Held-out control performance, real Grok tool-selection/argument performance, autonomous adaptation, end-to-end agent success, email recovery, narrative finding correctness and model ablations are NOT RUN in this phase. Later evaluations must use distinct cases and record actual denominators; no agent success rate is inferred from backend tests. Previous failures and Phase 1 real compatibility evidence remain in append-only history.

Safe backend tool/review traces are now retained for every instrumented workflow test, including rejected attempts, reference IDs and calculated outcomes. They are marked inference_source=none and must never be presented as Grok decisions. Narrative/email content and credentials are omitted. Final recorded backend trace events: 177.

## Phase 4 measured verification and limits

Final backend run 2f6898a9-0338-4b04-be0b-78c4d72aa9de: 75 methods, 74 PASS, 0 FAIL, 1 intentionally NOT RUN (the separately opt-in legacy live compatibility test). This skip does not describe the six real autonomy evaluations, which ran separately with actual Azure Grok calls.

All six required small development scenarios have passing results. Their initial attempt was 5 PASS/1 FAIL; the failed transient-tool case passed after focused recovery guidance. This is a development validation result after fixes, not an unbiased generalization or narrative-quality score. The evaluation harness supplies synthetic external events and explicit test-human approvals; actual model responses choose business tools and arguments.

The additional nine-control audit tested 72 entity/control pairs and matched 72/72 provisional development outcomes: 61 PASS, 9 FAIL, 2 MISSING_EVIDENCE. It tested PR-03 after PR-02 became blocked, and continued independent controls while earlier findings awaited review. Both missing outcomes share one outstanding request. Checkpoint recovery required fixes for rate limiting, an unresolved-evidence coordination gap and a payload reference; each failed attempt is retained.

Across retained attempts there are 119 successfully cached inference responses and 92 unique model-requested tool executions, including the failed recovery case and the reused full-audit checkpoint history. These are measured trace counts, not billable request totals: failed provider calls may lack usage, and billing cost remains unknown. The full-audit cumulative trace is not counted as a new independent fresh run at each resume.

Production build and three UI DOM interactions passed. npm audit reported zero vulnerabilities after updating Vite. API tests verify automatic background execution without browser action and actual compiled-UI serving. Browser visual/manual acceptance and held-out autonomy/performance are NOT RUN. No DEMO performance, model comparison or ablation is claimed.

See evaluation/phase4_summary.json for current counters and case references, live_agent_tests.txt for all actual case attempts, frontend_tests.txt for command output, regression_history.txt for failures/fixes, agent_traces.txt for actual tool selections/arguments/results and phase4_traces/ for archived synthetic inference/operation records. Initial runtime databases remain ignored under var/; their synthetic trace JSON is archived separately. No credentials or provider headers are intentionally logged.

## Follow-up: minimal held-out evaluation

The existing synthetic held-out partition was subsequently executed without changing production code, prompts, data or labels. Two metrics were measured: control-result accuracy 36/36 and real-agent task completion 3/3. The existing component suite also passed 21/21 tests. See [the short results report](../evaluation/heldout_report.md) and [named component proof](../evaluation/component_test_proof.md). Earlier NOT RUN entries describe the historical state before this follow-up; they are preserved. The small synthetic label set is provisional, and task completion ends at required human review/evidence waits.
