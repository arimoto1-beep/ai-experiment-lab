"""Score values and citations separately from JSON formatting; no subjective reason judge."""

from __future__ import annotations

from typing import Any

from ai_lab.long_context_data import FACTS, Case, conclusion
from ai_lab.spec_rescore import normalize_answer
from ai_lab.spec_scoring import _json


def _same(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def score_response(text: str | None, case: Case, *, execution_error: str | None = None) -> dict[str, Any]:
    normalization = normalize_answer(text if isinstance(text, str) else "")
    parsed = None
    try:
        parsed = _json(normalization["text"])
    except (ValueError, TypeError):
        pass
    normalization.pop("text")
    root = parsed if isinstance(parsed, dict) else {}
    facts = root.get("facts") if isinstance(root.get("facts"), dict) else {}
    final = root.get("final") if isinstance(root.get("final"), dict) else {}
    schema_valid = set(root) == {"facts", "final", "boundary_checks"} and set(facts) == set(FACTS)
    details = {}
    omissions = fabricated = wrong_entity = bad_sources = 0
    for name in FACTS:
        gold = case.gold["facts"][name]
        answer = facts.get(name)
        well_formed = (isinstance(answer, dict) and set(answer) == {"value", "sources"}
                       and isinstance(answer["sources"], list) and all(type(sid) is str for sid in answer["sources"])
                       and len(set(answer["sources"])) == len(answer["sources"])
                       and (answer["value"] is None or type(answer["value"]) is type(gold["value"])
                            or (gold["value"] is None and type(answer["value"]) in (int, str))))
        schema_valid = schema_valid and well_formed
        value = answer.get("value") if isinstance(answer, dict) else None
        sources = answer.get("sources", []) if isinstance(answer, dict) else []
        sources = sources if isinstance(sources, list) else []
        correct = well_formed and _same(value, gold["value"])
        missing = gold["value"] is not None and (name not in facts or value is None)
        supported_somewhere = any(_same(value, record.get(name)) for record in case.gold["source_values"].values() if name in record)
        invented = value is not None and not supported_somewhere
        contamination = value is not None and not correct and supported_somewhere
        source_correct = well_formed and set(sources) == set(gold["sources"])
        unsupported_sources = sum(type(sid) is not str or sid not in case.gold["source_values"]
                                  or not _same(value, case.gold["source_values"][sid].get(name)) for sid in sources)
        omissions += missing
        fabricated += invented
        wrong_entity += contamination
        bad_sources += unsupported_sources
        details[name] = {"correct": correct, "omitted": missing, "fabricated_value": invented,
                         "wrong_entity_value": contamination, "source_correct": source_correct,
                         "unsupported_citations": unsupported_sources}
    final_sources = final.get("sources")
    final_schema = (set(final) == {"amount", "route", "sources"} and type(final.get("amount")) is int
                    and type(final.get("route")) is str and isinstance(final_sources, list)
                    and all(type(sid) is str for sid in final_sources)
                    and len(set(final_sources)) == len(final_sources))
    schema_valid = bool(schema_valid and final_schema and isinstance(root.get("boundary_checks"), dict)
                        and set(root["boundary_checks"]) == {"start", "middle", "end"}
                        and all(type(value) is str for value in root["boundary_checks"].values()))
    final_correct = (_same(final.get("amount"), case.gold["final"]["amount"])
                     and _same(final.get("route"), case.gold["final"]["route"]))
    final_source_correct = final_schema and set(final_sources) == set(case.gold["final"]["sources"])
    fabricated_final_route = (type(final.get("route")) is str and not any(
        _same(final["route"], record.get(name)) for record in case.gold["source_values"].values()
        for name in ("standard_route", "exception_route")))
    fabricated += fabricated_final_route
    bad_sources += sum(type(sid) is not str or sid not in case.gold["final"]["sources"]
                       for sid in final_sources) if isinstance(final_sources, list) else 0
    prerequisites = all(details[name]["correct"] for name in FACTS[:-1])
    consistent = None
    try:
        reported = conclusion({name: facts[name]["value"] for name in FACTS[:-1]}, case.question)
        consistent = all(_same(final.get(name), reported[name]) for name in ("amount", "route"))
    except (KeyError, TypeError, ValueError):
        pass
    content_available = isinstance(parsed, dict) and isinstance(parsed.get("facts"), dict) and isinstance(parsed.get("final"), dict)
    format_compliant = normalization["original_json_valid"] and schema_valid
    content_correct = all(row["correct"] for row in details.values()) and final_correct
    citations_correct = all(row["source_correct"] for row in details.values()) and final_source_correct
    return {**normalization, "schema_valid": schema_valid, "format_compliant": format_compliant,
            "content_scorable": content_available, "execution_error": execution_error,
            "fact_accuracy": sum(row["correct"] for row in details.values()) / len(FACTS),
            "extraction_correct": all(details[name]["correct"] for name in ("base_fee", "standard_route")),
            "prerequisites_correct": prerequisites, "composition_correct": final_correct,
            "composition_failure_given_correct_facts": prerequisites and not final_correct,
            "conclusion_consistent_with_reported_facts": consistent,
            "omitted_facts": omissions, "fabricated_values": fabricated, "wrong_entity_values": wrong_entity,
            "fabricated_final_route": fabricated_final_route,
            "unsupported_citations": bad_sources, "citation_accuracy": (sum(row["source_correct"] for row in details.values()) + final_source_correct) / (len(FACTS) + 1),
            "final_source_correct": final_source_correct, "content_correct": content_correct,
            "strict_success": not execution_error and format_compliant and content_correct and citations_correct,
            "boundary_probes_match": root.get("boundary_checks") == case.gold["boundary_checks"], "facts": details}
