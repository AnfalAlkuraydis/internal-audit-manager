# Architecture decisions

## Phase 1 ? accepted scope

One agent will use Grok through Azure Foundry; LangGraph will coordinate future resumable work; Python will perform deterministic checks. Phase 1 implements only configuration, the inference boundary, an Azure adapter, health endpoint, and actual test reporting.

Use a small typed protocol and Pydantic messages rather than a provider framework. HTTPX handles Azure Chat Completions directly, keeping wire behavior inspectable. The deployment URL is explicit configuration. Azure api-key authentication is the initial supported method. No model name is hardcoded. Source: https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-grok

LIVE is the default and sole implemented mode. A later isolated demo adapter will implement the same interface. No runtime demo imports exist.

No automatic retries: future orchestration must distinguish safe inference retries from repeated business actions. Errors expose codes and retryability, never provider bodies. Redirects and proxy environment inheritance are disabled. Missing usage stays unknown.

SQLite business records/checkpoints, eight business tools, event-triggered Gmail, backend human approvals, structured synthetic evidence and independent ground truth remain approved future work. MCP is deferred. These choices keep the MVP small while preserving objective results and human authority. They are not implemented or measured yet.

## Evidence versus rationale

Architectural simplicity is a design rationale, not measured superiority. Actual compatibility results are in evaluation/. No Grok-versus-other-model claim is made. No real-agent autonomy score exists in Phase 1.

## Observed Phase 1 verification

Suite f572d50a-02b8-4044-b593-da36dd4c1604: 15 PASS, 0 FAIL, 1 NOT RUN. The real Grok check could not run because no Azure configuration was present. Mocked tests verify adapter behavior, not Azure compatibility. One malformed-usage handling defect and one reporting-test path error were found and fixed; their original failures remain recorded. pip check reported no broken requirements. No later phase has been implemented.

## Subsequent real-deployment verification

Run 2cb5eadd-701c-430c-a6ec-b15fbd961322 completed with 16 PASS, 0 FAIL, 0 NOT RUN after the user configured local credentials. The actual deployed Grok model successfully selected the compatibility tool, provided the expected arguments, and consumed the returned result in a second inference call. This supersedes the earlier unverified status without removing historical results. It provides no audit-autonomy or comparative-model evidence. Phase 1 is complete; later phases remain unimplemented.

## Phase 2 - storage and data foundation

SQLAlchemy Core tables provide relational storage while Pydantic models validate structured inputs. Core avoids an additional ORM object layer for this small data-ingestion phase; the agreed SQLAlchemy/Alembic stack is preserved. Alembic revision 0001_audit_data freezes its own table definitions, independent of future runtime schema edits. The migration is tested against current metadata and repeated fresh setup.

Foreign keys are enabled for every SQLite connection; SQLite does not enable them automatically. Compound references prevent evidence from pointing into another dataset. Reference: https://docs.sqlalchemy.org/en/20/dialects/sqlite.html

Catalog and seed import share a transaction. Changed content under an existing stable ID is rejected, never overwritten. Dataset fingerprints use canonical ID ordering so JSON list order has no business meaning. A seed manifest is immutable; future replies require an append-only ingestion service in a later phase. Evidence versions store provenance and preserve prior versions. Application-layer validation protects typed relationships; direct unrestricted SQL administration is outside the application permission boundary.

Dates are inclusive calendar days. Population retrieval selects deployments within scope and active accounts/devices overlapping scope. Snapshot controls reference the last active day in scope. Effective policies are retrieved by overlap; the later engine must bind tests to precise policy-effective dates. Current fixtures have one policy version throughout scope.

Ground-truth labels and future messages are outside runtime imports. The default local database contains only the development partition. No expected outcomes are saved as business results. Independently specified labels require human review before benchmarking.

Paid inference tests now require an explicit --live flag. Routine data changes do not justify repeated Grok calls. Previous Phase 1 live verification is retained. No demo inference implementation or live agent workflow exists.

Latest suite b67074ba-50b2-468f-a248-4e339c17e30d: 37 PASS, 0 FAIL, 1 NOT RUN. The skipped test is the unchanged live compatibility check. The fingerprint-order defect was caught and fixed with its failed run preserved. Data checks are not control-correctness or agent-performance scores.

## Phase 3 - deterministic execution and human boundaries

Typed schemas expose exactly eight tools. A single AuditService coordinates their database operations; control_testing.py contains pure rule calculations, auth.py owns demo role mapping, and api.py exposes human routes separately from tools. Grok and LangGraph orchestration remain Phase 4. No demo inference adapter exists.

Snapshots freeze actual populations, evidence, procedure/policy versions and the approved plan version. Rules never read evaluation labels or scenario IDs. Missing, contradictory, invalid and inapplicable evidence have explicit outcomes. Current fixtures use one policy version throughout the audit scope; complete multi-version historical coverage is not yet validated.

SQLite append-only triggers protect evidence, calculated records and human decision history. Narrative edits create versions; current-version approval is required. A changed work program invalidates old execution snapshots; changed findings invalidate pending closure. Closed findings cannot be silently edited. These are backend checks, independent of model instructions and UI behavior.

BEGIN IMMEDIATE serializes writer receipt checks; retry keys and business fingerprints avoid duplicate results/requests/findings. Read-only retrieval can still create backend trace/receipt records. Reference: https://www.sqlite.org/lang_transaction.html

Local demo bearer tokens are separate environment settings with fixed server-side roles, no agent login and no insecure default values. Missing tokens grant no access. The protected API is a local prototype, not production identity management. Real keys and tokens remain outside source and logs.

Remediation uses independent saved rule execution and separate human closure approval. Explicit bounds in the original approved program can authorize later verification without adding an approval pause to the demo. A department action plan is a claim, not evidence of success. The agent cannot author that claim through its tools; current entry is human-only until email processing exists.

Requests are queued only. Escalation approval releases exactly the reviewed wording; editing it restores the hold. A future mail dispatcher must recheck scope and approvals immediately before sending. No messages are sent in Phase 3.

Measured verification: run 81531990-67c5-497f-80c8-ddf72c90ac1c, 63 PASS / 0 FAIL / 1 NOT RUN. All 72 development labels matched. No Phase 3 test failures occurred. No autonomous-agent, held-out, model-comparison or Gmail result is claimed.

## Phase 4 decision: model choices with durable coordination

A single StateGraph coordinates scope interpretation, reasoning, tool execution and interrupt/resume. Grok selects actual tools/arguments; there is no synthetic-ID decision map or production mock fallback. Approval-dependent capability exposure narrows the schema offered to the model, while AuditService rechecks authorization at execution.

Separate SQLite application records and LangGraph checkpoints retain sessions, model decisions, operation receipts and external-event wakes. Stable tool operation IDs close the replay window between business commit and graph checkpoint. A local lease prevents overlapping activations and expires after 120 seconds for crash recovery. Completed inference is cached before replay; errors never become fabricated inference. Azure Retry-After durations are bounded and honored.

The lifespan worker runs independently of browser activity. Mail schedules/outbox/inbox are durable, and simulated delivery/ledger commits atomically. One missing record can cover multiple control dependencies. Resolving evidence wakes blocked audit work; Python retests it. Human review remains outside the agent's tool set, including current-version overdue escalation and independent-verification closure.

Phase 4 uses only normalized simulated mail; no Gmail integration or attachment extraction exists. No external LangSmith tracing is enabled. The intended deployment remains one local backend process. Operating-system scheduling, distributed worker recovery and presentation playback are outside this phase.
