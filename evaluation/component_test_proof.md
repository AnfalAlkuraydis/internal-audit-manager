# Component-level test proof

Executed existing Phase 1-4 component tests on 31 October 2026 (Asia/Riyadh).

Run ID: 8439ca22-2637-4d7a-9b25-b03be95fec2b

Actual result: **21 PASS / 0 FAIL / 0 NOT RUN**.

| Coverage | Passed tests |
|---|---:|
| Configuration and message/tool schemas | 5 |
| Audit-data schemas and relationships | 6 |
| Deterministic control rules | 8 |
| Evaluation logging and honest result reporting | 2 |

| Actual test ID | Result |
|---|---|
| tests.component.test_audit_data.DataSchemaTests.test_duplicate_and_wrong_entity_references | PASS |
| tests.component.test_audit_data.DataSchemaTests.test_engagement_period_validation | PASS |
| tests.component.test_audit_data.DataSchemaTests.test_evidence_version_chain_is_validated | PASS |
| tests.component.test_audit_data.DataSchemaTests.test_invalid_date_intervals_and_payloads | PASS |
| tests.component.test_audit_data.DataSchemaTests.test_invalid_procedure_relationships | PASS |
| tests.component.test_audit_data.DataSchemaTests.test_required_catalog_and_population_sizes | PASS |
| tests.component.test_control_rules.RuleTests.test_boolean_values_and_exact_snapshot_date | PASS |
| tests.component.test_control_rules.RuleTests.test_conflicting_and_corrupted_evidence | PASS |
| tests.component.test_control_rules.RuleTests.test_employment_end_boundaries | PASS |
| tests.component.test_control_rules.RuleTests.test_exactly_eight_typed_tools_and_no_approval_argument | PASS |
| tests.component.test_control_rules.RuleTests.test_project_date_equality_and_late_approval | PASS |
| tests.component.test_control_rules.RuleTests.test_recency_boundary_stale_and_future | PASS |
| tests.component.test_control_rules.RuleTests.test_source_agreement_and_discrepancy | PASS |
| tests.component.test_control_rules.RuleTests.test_superseding_evidence_and_policy_effective_dates | PASS |
| tests.component.test_foundation.ConfigurationTests.test_configuration_repr_hides_secrets | PASS |
| tests.component.test_foundation.ConfigurationTests.test_defaults_and_missing_credentials | PASS |
| tests.component.test_foundation.ConfigurationTests.test_invalid_modes_and_timeouts | PASS |
| tests.component.test_foundation.ConfigurationTests.test_message_and_tool_contracts | PASS |
| tests.component.test_foundation.ConfigurationTests.test_unsafe_urls | PASS |
| tests.component.test_reporting.ReportingTests.test_append_preserves_history | PASS |
| tests.component.test_reporting.ReportingTests.test_failed_and_skipped_tests_are_reported_honestly | PASS |

[Machine-readable execution proof](evaluation\heldout_runs\8439ca22-2637-4d7a-9b25-b03be95fec2b/component_proof.json)
[Original append-only component log](component_tests.txt)

Component tests are supporting evidence, not another held-out performance metric.
