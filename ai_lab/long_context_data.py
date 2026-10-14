"""Seeded fictional manuals. Token targets are character estimates, never measured tokens."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_lab.experiment import _write_json

VERSION = 1
DEFAULT_LENGTHS = ("short", "medium", "long")
LENGTHS = {"short": 10_000, "medium": 50_000, "long": 120_000, "long90k": 90_000}
POSITIONS = {"start": 0.05, "middle": 0.50, "end": 0.95}
DISTRACTIONS = ("neutral", "similar")
FACTS = ("base_fee", "standard_route", "discount_percent", "discount_segment",
         "exception_kind", "exception_surcharge", "exception_route", "grace_period_days")
PROMPT_VERSION = "long-context-v1"


@dataclass(frozen=True)
class Case:
    case_id: str
    document: str
    question: dict[str, str]
    gold: dict[str, Any]
    config: dict[str, Any]


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def conclusion(values: dict[str, Any], question: dict[str, str]) -> dict[str, Any]:
    discount = values["discount_percent"] if values["discount_segment"] == question["segment"] else 0
    applies = values["exception_kind"] == question["kind"]
    return {"amount": values["base_fee"] * (100 - discount) // 100 + (values["exception_surcharge"] if applies else 0),
            "route": values["exception_route"] if applies else values["standard_route"]}


def build_case(seed: int, length: str, position: str, distraction: str, *, chars_per_token: float = 4.0) -> Case:
    if seed < 0 or length not in LENGTHS or position not in POSITIONS or distraction not in DISTRACTIONS:
        raise ValueError("Unknown case dimension or negative seed")
    if not 1 <= chars_per_token <= 8:
        raise ValueError("chars_per_token must be between 1 and 8")
    rng = random.Random(seed)
    product = f"P{rng.randrange(1000, 9999)}-A"
    customer = f"C{rng.randrange(1000, 9999)}-A"
    policy = f"X{rng.randrange(1000, 9999)}-A"
    values = {"base_fee": rng.randrange(10, 91) * 100, "standard_route": rng.choice(("review", "queue", "standard")),
              "discount_percent": rng.choice((10, 20, 30)), "discount_segment": rng.choice(("education", "business")),
              "exception_kind": rng.choice(("renewal", "migration")), "exception_surcharge": rng.randrange(1, 10) * 100,
              "exception_route": rng.choice(("priority", "manual", "special")), "grace_period_days": None}
    question = {"product": product, "segment": rng.choice(("education", "business")), "kind": rng.choice(("renewal", "migration"))}
    used_ids: set[str] = set()

    def source_id() -> str:
        while True:
            value = f"S{rng.randrange(100000, 999999)}"
            if value not in used_ids:
                used_ids.add(value)
                return value

    ids = [source_id() for _ in range(3)]
    evidence = {
        ids[0]: {key: values[key] for key in ("base_fee", "standard_route")},
        ids[1]: {key: values[key] for key in ("discount_percent", "discount_segment")},
        ids[2]: {key: values[key] for key in ("exception_kind", "exception_surcharge", "exception_route")},
    }
    # Labels have the same shape as distractor labels; no answer markers enter the manual.
    blocks = [
        f"[{ids[0]}] Product {product}: base fee is {values['base_fee']} credits; standard route is {values['standard_route']}. "
        f"Use customer rule {customer} and exception rule {policy}. The fee is for one transaction.\n",
        f"[{ids[1]}] Customer rule {customer}: discount is {values['discount_percent']} percent only for segment {values['discount_segment']}. "
        "Other segments receive zero discount. Apply the discount to the base fee before any surcharge.\n",
        f"[{ids[2]}] Exception rule {policy}: only transaction kind {values['exception_kind']} adds {values['exception_surcharge']} credits "
        f"after the discount and replaces the route with {values['exception_route']}. Other kinds keep the standard route with no surcharge.\n",
    ]
    markers = {label: f"B{rng.getrandbits(48):012x}" for label in ("start", "middle", "end")}
    header = f"FICTIONAL OPERATIONS MANUAL\nBoundary check start: {markers['start']}\nAll amounts are integer credits. "
    header += "Only explicit rules apply. Product, customer and policy IDs must match exactly.\n"
    center = f"Boundary check middle: {markers['middle']}\n"
    footer = f"Boundary check end: {markers['end']}\n"
    budget = round(LENGTHS[length] * chars_per_token)
    remaining = budget - len(header + center + footer + "".join(blocks))
    fillers: list[str] = []
    similar_count = 0
    index = 0
    # Equal width makes length and similarity separately manipulable; all filler facts remain explicit.
    prose = " Staff record each completed request in the daily ledger. Confirm the record before closing the service ticket."
    while remaining >= 480:
        sid = source_id()
        near = distraction == "similar" and index % 5 == 0
        similar_count += near
        other_product = (product[:-1] + "B" if near else f"Q{rng.randrange(1000,9999)}-B") + f"{index:04d}"
        other_customer = (customer[:-1] + "B" if near else f"D{rng.randrange(1000,9999)}-B") + f"{index:04d}"
        other_policy = (policy[:-1] + "B" if near else f"Y{rng.randrange(1000,9999)}-B") + f"{index:04d}"
        # Consume the same random draws in both profiles so factual content and block counts match.
        if near:
            rng.randrange(1000,9999); rng.randrange(1000,9999); rng.randrange(1000,9999)
        other = {"base_fee": rng.randrange(10, 91) * 100, "standard_route": rng.choice(("review", "queue", "standard")),
                 "discount_percent": rng.choice((10, 20, 30)), "discount_segment": rng.choice(("education", "business")),
                 "exception_kind": rng.choice(("renewal", "migration")), "exception_surcharge": rng.randrange(1, 10) * 100,
                 "exception_route": rng.choice(("priority", "manual", "special")), "grace_period_days": rng.randrange(1, 31)}
        evidence[sid] = other
        line = (f"[{sid}] Product {other_product}; customer {other_customer}; policy {other_policy}. "
                f"Base fee {other['base_fee']} credits; standard route {other['standard_route']}; discount {other['discount_percent']} percent "
                f"for segment {other['discount_segment']}; exception kind {other['exception_kind']}; surcharge {other['exception_surcharge']} credits; "
                f"exception route {other['exception_route']}; grace period {other['grace_period_days']} days.")
        while len(line) + len(prose) <= 479:
            line += prose
        fillers.append(line.ljust(479) + "\n")
        remaining -= 480
        index += 1
    tail = ("General archive notes. " + prose)[:remaining].ljust(remaining)
    # Rotate which evidence is near the selected position, while spreading all three over the document.
    rotation = ("start", "middle", "end").index(position)
    slots: dict[int, list[str]] = {}
    for i, block in enumerate(blocks):
        fraction = (0.05, 0.5, 0.95)[(i + rotation) % 3]
        slots.setdefault(round(len(fillers) * fraction), []).append(block)
    slots.setdefault(len(fillers) // 2, []).append(center)
    parts = [header]
    for i in range(len(fillers) + 1):
        parts.extend(slots.get(i, []))
        if i < len(fillers):
            parts.append(fillers[i])
    document = "".join(parts) + tail + footer
    assert len(document) == budget
    facts = {name: {"value": values[name], "sources": [next(sid for sid, row in evidence.items() if name in row)] if values[name] is not None else []}
             for name in FACTS}
    gold = {"facts": facts, "final": {**conclusion(values, question), "sources": sorted(ids)}, "boundary_checks": markers,
            "source_values": evidence, "evidence_offsets": {sid: document.index(f"[{sid}]") for sid in ids}}
    config = {"version": VERSION, "seed": seed, "length": length, "target_tokens": LENGTHS[length], "position": position,
              "distraction": distraction, "chars_per_token": chars_per_token, "document_characters": len(document),
              "document_bytes": len(document.encode("utf-8")), "document_tokens_measured": None,
              "estimate_method": "characters / chars_per_token; not a tokenizer", "filler_count": len(fillers), "similar_filler_count": similar_count}
    return Case(f"s{seed}_{length}_{position}_{distraction}", document, question, gold, config)


def build_prompt(case: Case) -> str:
    example = {"facts": {name: {"value": None, "sources": []} for name in FACTS},
               "final": {"amount": None, "route": None, "sources": []},
               "boundary_checks": {name: None for name in ("start", "middle", "end")}}
    return ("Read the fictional manual. Use exact IDs and only the explicit rules. Extract all named facts, then calculate the final "
            "amount and route. Follow the customer and exception rule IDs linked from the requested product record. "
            "Cite source labels for each fact and all three applicable rule sections for the final conclusion. "
            "For any fact not explicitly stated for the requested IDs, use null and an empty source list; never borrow another entity's rule. "
            "Copy the three Boundary check values from the manual. Return one JSON object without Markdown. "
            "The example defines the output structure; its null values are placeholders, not answers.\n"
            + json.dumps(example) + "\nQuestion: " + json.dumps(case.question)
            + "\n===== MANUAL =====\n" + case.document + "\n===== END MANUAL =====\n")


def save_case(case: Case, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "manual.txt").write_bytes(case.document.encode("utf-8"))
    (directory / "prompt.txt").write_bytes(build_prompt(case).encode("utf-8"))
    _write_json(directory / "question.json", case.question)
    _write_json(directory / "answer_key.json", case.gold)
    _write_json(directory / "case.json", {"case_id": case.case_id, **case.config, "manual_sha256": digest(case.document),
                                          "prompt_sha256": digest(build_prompt(case)), "prompt_version": PROMPT_VERSION})


def load_case(directory: Path) -> Case:
    meta = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    case = build_case(meta["seed"], meta["length"], meta["position"], meta["distraction"], chars_per_token=meta["chars_per_token"])
    expected = {"manual.txt": case.document, "prompt.txt": build_prompt(case)}
    for filename, text in expected.items():
        if (directory / filename).read_bytes() != text.encode("utf-8"):
            raise ValueError(f"Generated input changed: {directory / filename}")
    if (json.loads((directory / "answer_key.json").read_text(encoding="utf-8")) != case.gold
            or json.loads((directory / "question.json").read_text(encoding="utf-8")) != case.question
            or meta != {"case_id": case.case_id, **case.config, "manual_sha256": digest(case.document),
                        "prompt_sha256": digest(build_prompt(case)), "prompt_version": PROMPT_VERSION}):
        raise ValueError(f"Generated metadata or gold changed: {directory}")
    return case
