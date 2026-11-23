"""Synthetic ФИС ГИА registry: fixture loader and MCP search tool."""
import json
from datetime import date
from pathlib import Path

import pytest

from sqlalchemy import select

from app.db import SessionLocal
from app.models import SyntheticEgeCandidate, SyntheticEgeResult
from app.mcp_tools import search_synthetic_candidates
from app.synthetic_ege_registry import (
    SyntheticCandidateInput,
    SyntheticEgeInput,
    load_candidates,
    load_fixture,
    load_results,
)

FIXTURE = Path(__file__).parents[1] / "backend" / "fixtures" / "synthetic_ege_registry.json"


def seed_registry() -> None:
    with SessionLocal() as db:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        people = load_candidates(
            db, [SyntheticCandidateInput.model_validate(item) for item in data["candidates"]]
        )
        results = load_results(
            db, [SyntheticEgeInput.model_validate(item) for item in data["results"]]
        )
    assert people == 10
    assert results == 30


def test_fixture_shape_is_stable():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(data["candidates"]) == 10
    assert len(data["results"]) == 30
    assert all(item["candidate_id"].startswith("SYN-") for item in data["candidates"])
    assert all(item["candidate_id"].startswith("SYN-") for item in data["results"])
    # Every person in the reference registry is unique by full name + date of birth.
    keys = {(item["full_name"], item["date_of_birth"]) for item in data["candidates"]}
    assert len(keys) == 10


def test_loader_is_idempotent():
    seed_registry()
    with SessionLocal() as db:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        people, scores = load_fixture(
            db,
            [SyntheticCandidateInput.model_validate(item) for item in data["candidates"]],
            [SyntheticEgeInput.model_validate(item) for item in data["results"]],
        )
    assert people == (0, 0)
    assert scores == (0, 0)


def test_loader_rejects_non_synthetic_ids():
    with pytest.raises(Exception):
        with SessionLocal() as db:
            load_candidates(db, [
                SyntheticCandidateInput(
                    candidate_id="REAL-1",
                    full_name="Иванов Иван Иванович",
                    date_of_birth=date(1999, 1, 1),
                )
            ])


def test_search_by_name_and_dob():
    seed_registry()
    with SessionLocal() as db:
        first = db.scalars(select(SyntheticEgeCandidate)).first()
        result = search_synthetic_candidates(
            db, first.full_name, first.date_of_birth
        )
    assert result["match_count"] == 1
    assert result["ambiguous"] is False
    match = result["matches"][0]
    assert match["candidate_id"] == first.candidate_id
    assert all(row["score"] >= 0 for row in match["results"])


def test_search_normalizes_case_and_whitespace():
    seed_registry()
    with SessionLocal() as db:
        first = db.scalars(select(SyntheticEgeCandidate)).first()
        mangled = "  ".join(first.full_name.upper().split())
        result = search_synthetic_candidates(db, mangled, first.date_of_birth)
    assert result["match_count"] == 1


def test_search_accepts_surname_first_order():
    seed_registry()
    with SessionLocal() as db:
        three_part = next(
            candidate
            for candidate in db.scalars(select(SyntheticEgeCandidate))
            if len(candidate.full_name.split()) == 3
        )
        parts = three_part.full_name.split()
        surname_first = " ".join((*parts[1:], parts[0]))
        result = search_synthetic_candidates(db, surname_first, three_part.date_of_birth)
    assert result["match_count"] == 1


def test_search_no_match():
    seed_registry()
    with SessionLocal() as db:
        result = search_synthetic_candidates(
            db, "Неизвестный Неизвестов Неизвестич", date(1990, 5, 5)
        )
    assert result == {"match_count": 0, "ambiguous": False, "matches": []}


def test_mcp_tool_returns_jsonable_result():
    seed_registry()
    with SessionLocal() as db:
        first = db.scalars(select(SyntheticEgeCandidate)).first()
    from app.mcp_tools import search_synthetic_ege_results

    result = search_synthetic_ege_results.fn(first.full_name, first.date_of_birth)
    assert isinstance(result, dict)
    assert result["match_count"] == 1
    json.dumps(result, ensure_ascii=False)  # fully serialisable
