"""Pure deterministic rules. No network calls, database writes, LLMs or answer keys."""
from datetime import date
from pydantic import TypeAdapter, ValidationError
from backend.database.schemas import Rule, EVIDENCE_FACTS

def scope_date(entity: dict, engagement: dict) -> date:
    """Use deployment for projects, otherwise the last active date inside the audit."""
    if entity["kind"] == "project":
        return date.fromisoformat(entity["facts"]["deployed_on"])
    return min(date.fromisoformat(entity["active_to"]) if entity["active_to"] else engagement["period_end"],
               engagement["period_end"])

def required_kinds(rule: dict) -> list[str]:
    """Return factual evidence dependencies from the rule definition."""
    return [rule["evidence_kind"]] + ([rule["other_evidence_kind"]] if "other_evidence_kind" in rule else [])

def evaluate(rule: dict, entity: dict, records: list[dict], engagement: dict, policy: dict) -> dict:
    """Calculate an outcome, explanation code and used evidence IDs for one member.

    Conflicting equally authoritative facts remain unresolved. The explicit
    reconciliation rule may FAIL on a source mismatch without declaring which
    approval claim is correct. Missing/stale snapshots are never assumed passes.
    """
    ids = []
    try:
        TypeAdapter(Rule).validate_python(rule)
        as_of = scope_date(entity, engagement)
        start = date.fromisoformat(policy["effective_from"])
        end = date.fromisoformat(policy["effective_to"]) if policy["effective_to"] else None
        if as_of < start or (end and as_of > end):
            return {"outcome": "NOT_APPLICABLE", "reason": "policy_not_effective", "evidence_ids": []}
        values = {}
        for kind in required_kinds(rule):
            candidates = [r for r in records if r["entity_id"] == entity["id"] and r["kind"] == kind]
            # A secondary GRC claim cannot satisfy an original-source control.
            candidates = [r for r in candidates if r["authority"] == ("secondary" if kind == "grc_approval" else "original")]
            superseded = {r["supersedes_id"] for r in candidates if r["supersedes_id"]}
            candidates = [r for r in candidates if r["id"] not in superseded]
            selected = []
            for row in candidates:
                facts = EVIDENCE_FACTS[kind].model_validate(row["facts"]).model_dump(mode="json")
                if "snapshot_on" in facts and date.fromisoformat(facts["snapshot_on"]) != as_of:
                    continue
                if not row.get("integrity_valid", False):
                    return {"outcome": "ERROR", "reason": "evidence_integrity_error", "evidence_ids": [row["id"]]}
                selected.append(row)
            if not selected:
                return {"outcome": "MISSING_EVIDENCE", "reason": "missing_" + kind, "evidence_ids": sorted(ids)}
            ids.extend(r["id"] for r in selected)
            field = rule.get("evidence_field", rule.get("field"))
            facts = {str(r["facts"][field]) for r in selected}
            if len(facts) != 1:
                return {"outcome": "CONTRADICTORY_EVIDENCE", "reason": "conflicting_" + kind,
                        "evidence_ids": sorted(ids)}
            values[kind] = selected[0]["facts"][field]
        operation = rule["operation"]
        value = values[rule["evidence_kind"]]
        if operation == "on_or_before":
            passed = date.fromisoformat(value) <= as_of
        elif operation == "dates_agree":
            passed = value == values[rule["other_evidence_kind"]]
        elif operation == "is_true":
            passed = value is True
        elif operation == "not_older_than":
            age = (as_of - date.fromisoformat(value)).days
            if age < 0:
                return {"outcome": "ERROR", "reason": "future_dated_evidence", "evidence_ids": sorted(ids)}
            passed = age <= rule["max_age_days"]
        else:  # employed_at: employment_end is the first day no longer employed.
            passed = value is None or date.fromisoformat(value) > as_of
        return {"outcome": "PASS" if passed else "FAIL",
                "reason": "requirement_met" if passed else "requirement_not_met",
                "evidence_ids": sorted(ids)}
    except (ValueError, TypeError, KeyError, ValidationError):
        return {"outcome": "ERROR", "reason": "invalid_rule_or_evidence", "evidence_ids": sorted(ids)}
