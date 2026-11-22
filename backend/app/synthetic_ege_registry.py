"""Load an explicitly synthetic set of exam fixtures into a test database.

The registry is reference data: the only supported way to change it is this
administrative loader (a fixture file that must already be present on the
server). Applicant-facing routes and MCP tools only read it.

Fixture format (JSON):
- {"candidates": [ {...}, ... ], "results": [ {...}, ... ]} — people plus
  their results (the standard layout, see fixtures/synthetic_ege_registry.json);
- [ {...}, ... ] — a flat list of results (legacy layout, candidates untouched).

All entries are required to be synthetic (candidate ids start with "SYN-").
The loader is idempotent: re-loading the same fixture adds nothing; a
conflicting fixture value is an error, never a silent overwrite.
"""

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.admissions_schemas import SyntheticCandidateInput, SyntheticEgeInput
from app.db import SessionLocal
from app.models import SyntheticEgeCandidate, SyntheticEgeResult


def _parse(raw: bytes) -> tuple[list[SyntheticCandidateInput], list[SyntheticEgeInput]]:
    data = json.loads(raw)
    if isinstance(data, list):
        return [], TypeAdapter(list[SyntheticEgeInput]).validate_python(data)
    if isinstance(data, dict) and ("candidates" in data or "results" in data):
        return (
            TypeAdapter(list[SyntheticCandidateInput]).validate_python(data.get("candidates", [])),
            TypeAdapter(list[SyntheticEgeInput]).validate_python(data.get("results", [])),
        )
    raise ValueError("Fixture must be a JSON object with candidates/results or a JSON list of results")


def load_results(db: Session, values: list[SyntheticEgeInput]) -> int:
    seen: dict[tuple[str, str, int], SyntheticEgeInput] = {}
    for item in values:
        key = (item.candidate_id, item.subject, item.year)
        if key in seen and seen[key] != item:
            raise ValueError(f"Conflicting synthetic fixture for {key}")
        seen[key] = item
    count = 0
    for key, item in seen.items():
        existing = db.get(SyntheticEgeResult, key)
        if existing is None:
            db.add(SyntheticEgeResult(**item.model_dump()))
            count += 1
        elif (existing.score, existing.status) != (item.score, item.status):
            raise ValueError(f"Synthetic fixture {key} is already defined with a different result")
    db.commit()
    return count


def load_candidates(db: Session, values: list[SyntheticCandidateInput]) -> int:
    seen: dict[str, SyntheticCandidateInput] = {}
    for item in values:
        if item.candidate_id in seen and seen[item.candidate_id] != item:
            raise ValueError(f"Conflicting synthetic fixture for {item.candidate_id}")
        seen[item.candidate_id] = item
    count = 0
    for candidate_id, item in seen.items():
        existing = db.get(SyntheticEgeCandidate, candidate_id)
        if existing is None:
            db.add(SyntheticEgeCandidate(**item.model_dump()))
            count += 1
        elif (existing.full_name, existing.date_of_birth) != (item.full_name, item.date_of_birth):
            raise ValueError(
                f"Synthetic candidate {candidate_id} is already defined with a different identity"
            )
    db.commit()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "fixture", type=Path, help="JSON fixture with SYN-prefixed synthetic candidates/results"
    )
    args = parser.parse_args()
    try:
        candidates, results = _parse(args.fixture.read_bytes())
        with SessionLocal() as db:
            added_people = load_candidates(db, candidates)
            added_scores = load_results(db, results)
    except (OSError, ValidationError, ValueError) as exc:
        parser.exit(2, f"Unable to load synthetic registry: {exc}\n")
    print(f"Added {added_people} candidate(s) and {added_scores} synthetic result(s).")


if __name__ == "__main__":
    main()
