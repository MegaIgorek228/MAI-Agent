"""Load an explicitly synthetic set of exam fixtures into a test database."""

import argparse
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.admissions_schemas import SyntheticEgeInput
from app.db import SessionLocal
from app.models import SyntheticEgeResult


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="JSON list of results for SYN-prefixed test candidates")
    args = parser.parse_args()
    try:
        values = TypeAdapter(list[SyntheticEgeInput]).validate_json(args.fixture.read_bytes())
        with SessionLocal() as db:
            count = load_results(db, values)
    except (OSError, ValidationError, ValueError) as exc:
        parser.exit(2, f"Unable to load synthetic registry: {exc}\n")
    print(f"Added {count} synthetic result(s).")


if __name__ == "__main__":
    main()
