"""Validate structured data without implementing a control-testing engine."""
from copy import deepcopy
from pathlib import Path
import unittest
from backend.database.schemas import Catalog, SeedBundle, Engagement
from backend.database.repository import read_catalog, read_bundle

ROOT = Path(__file__).resolve().parents[2]

class DataSchemaTests(unittest.TestCase):
    def setUp(self):
        """Load validated fixtures without creating database state."""
        self.catalog = read_catalog(ROOT / "data/catalog.json")
        self.bundle = read_bundle(ROOT / "data/development/dataset.json")

    def test_required_catalog_and_population_sizes(self):
        """Three policies, three controls each, eight members of each population."""
        self.assertEqual(len(self.catalog.policies), 3)
        self.assertEqual(len(self.catalog.controls), 9)
        for policy in self.catalog.policies:
            self.assertEqual(sum(c.policy_id == policy.id for c in self.catalog.controls), 3)
        self.assertEqual(len(self.catalog.procedures), 9)
        for kind in ("project", "privileged_account", "device"):
            self.assertEqual(sum(e.kind == kind for e in self.bundle.entities), 8)
        self.observations = {"policies": 3, "controls": 9, "entities": 24, "evidence": 71}

    def test_invalid_date_intervals_and_payloads(self):
        """Invalid intervals, non-boolean evidence, unknown fields and bad dates are rejected."""
        original = self.bundle.model_dump(mode="json")
        mutations = []
        bad = deepcopy(original)
        bad["entities"][0]["active_to"] = "2025-12-31"
        mutations.append(bad)
        bad = deepcopy(original)
        next(e for e in bad["evidence"] if e["kind"] == "mfa")["facts"]["enabled"] = "yes"
        mutations.append(bad)
        bad = deepcopy(original)
        bad["entities"][0]["facts"]["deployed_on"] = "not-a-date"
        mutations.append(bad)
        bad = deepcopy(original)
        bad["evidence"][0]["captured_on"] = "2020-01-01"
        mutations.append(bad)
        bad = deepcopy(original)
        bad["entities"][0]["unexpected"] = True
        mutations.append(bad)
        for index, data in enumerate(mutations):
            with self.subTest(case=index), self.assertRaises(ValueError):
                SeedBundle.model_validate(data)

    def test_duplicate_and_wrong_entity_references(self):
        """Duplicate records, missing entities and evidence attached to the wrong kind fail."""
        original = self.bundle.model_dump(mode="json")
        bad = deepcopy(original)
        bad["entities"].append(deepcopy(bad["entities"][0]))
        with self.assertRaises(ValueError):
            SeedBundle.model_validate(bad)
        for entity_id in ("UNKNOWN", "ACC-001"):
            bad = deepcopy(original)
            bad["evidence"][0]["entity_id"] = entity_id
            with self.subTest(entity_id=entity_id), self.assertRaises(ValueError):
                SeedBundle.model_validate(bad)

    def test_invalid_procedure_relationships(self):
        """Procedures must match a real control, population and evidence field."""
        original = self.catalog.model_dump(mode="json")
        for mutation in ("unknown_policy", "wrong_field", "wrong_population", "missing_procedure"):
            bad = deepcopy(original)
            if mutation == "unknown_policy":
                bad["controls"][0]["policy_id"] = "UNKNOWN"
            elif mutation == "wrong_field":
                bad["procedures"][0]["rule"]["evidence_field"] = "approved_on"
            elif mutation == "wrong_population":
                bad["controls"][0]["entity_kind"] = "device"
            else:
                bad["procedures"].pop()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                Catalog.model_validate(bad)

    def test_evidence_version_chain_is_validated(self):
        """Replacement versions refer to the same entity and original-source record."""
        data = self.bundle.model_dump(mode="json")
        prior = data["evidence"][0]
        newer = deepcopy(prior)
        newer.update(id=prior["id"] + ".replacement", version=2, supersedes_id=prior["id"])
        data["evidence"].append(newer)
        SeedBundle.model_validate(data)
        newer["entity_id"] = "PRJ-002"
        with self.assertRaises(ValueError):
            SeedBundle.model_validate(data)

    def test_engagement_period_validation(self):
        """Reversed audit periods are rejected before database writes."""
        with self.assertRaises(ValueError):
            Engagement(id="AUDIT-BAD", dataset_id=self.bundle.dataset.id,
                       department="Digital Risk", period_start="2026-08-31",
                       period_end="2026-01-01")
