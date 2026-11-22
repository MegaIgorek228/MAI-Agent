"""Load an explicitly synthetic set of exam fixtures into a test database.

The registry is reference data: the only supported way to change it is this
administrative loader (a fixture file that must already be present on the
server). Applicant-facing routes and MCP tools only read it.

Fixture format (JSON):
- {"candidates": [ {...}, ... ], "results": [ {...}, ... ]} — people plus
  their results (the standard layout, see fixtures/synthetic_ege_registry.json);
- [ {...}, ... ] — a flat list of results (legacy layout, candidates untouched).

All entries are required to be synthetic (candidate ids start with "SYN-").
The loader applies the complete fixture in one transaction. Re-loading the
same fixture changes nothing. Updating existing values requires the explicit
--replace-conflicts option; contradictory rows within a file are always rejected.
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


def _apply_results(
    db: Session, values: list[SyntheticEgeInput], *, replace_conflicts: bool,
) -> tuple[int, int]:
    seen: dict[tuple[str, str, int], SyntheticEgeInput] = {}
    for item in values:
        key = (item.candidate_id, item.subject, item.year)
        if key in seen and seen[key] != item:
            raise ValueError(f"Conflicting synthetic fixture for {key}")
        seen[key] = item
    added = updated = 0
    for key, item in seen.items():
        existing = db.get(SyntheticEgeResult, key)
        if existing is None:
            db.add(SyntheticEgeResult(**item.model_dump()))
            added += 1
        elif (existing.score, existing.status) != (item.score, item.status):
            if not replace_conflicts:
                raise ValueError(f"Synthetic fixture {key} is already defined with a different result")
            existing.score = item.score
            existing.status = item.status
            updated += 1
    return added, updated


def _apply_candidates(
    db: Session, values: list[SyntheticCandidateInput], *, replace_conflicts: bool,
) -> tuple[int, int]:
    seen: dict[str, SyntheticCandidateInput] = {}
    for item in values:
        if item.candidate_id in seen and seen[item.candidate_id] != item:
            raise ValueError(f"Conflicting synthetic fixture for {item.candidate_id}")
        seen[item.candidate_id] = item
    added = updated = 0
    for candidate_id, item in seen.items():
        existing = db.get(SyntheticEgeCandidate, candidate_id)
        if existing is None:
            db.add(SyntheticEgeCandidate(**item.model_dump()))
            added += 1
        elif (existing.full_name, existing.date_of_birth) != (item.full_name, item.date_of_birth):
            if not replace_conflicts:
                raise ValueError(
                    f"Synthetic candidate {candidate_id} is already defined with a different identity"
                )
            existing.full_name = item.full_name
            existing.date_of_birth = item.date_of_birth
            updated += 1
    return added, updated


def load_results(db: Session, values: list[SyntheticEgeInput]) -> int:
    added, _ = _apply_results(db, values, replace_conflicts=False)
    db.commit()
    return added


def load_candidates(db: Session, values: list[SyntheticCandidateInput]) -> int:
    added, _ = _apply_candidates(db, values, replace_conflicts=False)
    db.commit()
    return added


def load_fixture(
    db: Session,
    candidates: list[SyntheticCandidateInput],
    results: list[SyntheticEgeInput],
    *,
    replace_conflicts: bool = False,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return added and updated counts for candidates and scores, respectively."""
    with db.begin():
        people = _apply_candidates(db, candidates, replace_conflicts=replace_conflicts)
        scores = _apply_results(db, results, replace_conflicts=replace_conflicts)
    return people, scores


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "fixture", type=Path, help="JSON fixture with SYN-prefixed synthetic candidates/results"
    )
    parser.add_argument(
        "--replace-conflicts", action="store_true",
        help="Update existing synthetic candidates and results with the same keys",
    )
    args = parser.parse_args()
    try:
        candidates, results = _parse(args.fixture.read_bytes())
        with SessionLocal() as db:
            (added_people, updated_people), (added_scores, updated_scores) = load_fixture(
                db, candidates, results, replace_conflicts=args.replace_conflicts,
            )
    except (OSError, ValidationError, ValueError) as exc:
        parser.exit(2, f"Unable to load synthetic registry: {exc}\n")
    print(f"Added {added_people} candidate(s) and {added_scores} synthetic result(s).")
    if args.replace_conflicts:
        print(f"Updated {updated_people} candidate(s) and {updated_scores} synthetic result(s).")


if __name__ == "__main__":
    main()
