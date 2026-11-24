"""Unit tests for the synthetic ФИС ГИА MCP browse tools.

The registry lives in the ФИС database (FisSessionLocal); in the unit-test
layout (single SQLite file) all engines share the same file.
"""

import json
from pathlib import Path

import pytest

from app.db import FisSessionLocal
from app.mcp_tools import get_synthetic_ege_results, list_synthetic_ege_candidates
from app.synthetic_ege_registry import (
    SyntheticCandidateInput,
    SyntheticEgeInput,
    load_fixture,
)
from pydantic import TypeAdapter

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "backend" / "fixtures" / "synthetic_ege_registry.json"
)


def _seed_registry() -> None:
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    candidates = TypeAdapter(list[SyntheticCandidateInput]).validate_python(raw["candidates"])
    results = TypeAdapter(list[SyntheticEgeInput]).validate_python(raw["results"])
    with FisSessionLocal() as db:
        load_fixture(db, candidates, results)


def test_list_returns_all_candidates_in_id_order():
    _seed_registry()
    page = list_synthetic_ege_candidates.fn()
    assert page["total"] == 10
    assert [c["candidate_id"] for c in page["candidates"]] == [f"SYN-{1000 + i}" for i in range(1, 11)]
    assert page["candidates"][0]["full_name"] == "Алексей Иванович Иванов"
    assert page["candidates"][0]["date_of_birth"] == "2008-03-14"


def test_list_pagination():
    _seed_registry()
    first_page = list_synthetic_ege_candidates.fn(limit=3, offset=0)
    assert first_page["total"] == 10
    assert [c["candidate_id"] for c in first_page["candidates"]] == ["SYN-1001", "SYN-1002", "SYN-1003"]
    second_page = list_synthetic_ege_candidates.fn(limit=3, offset=3)
    assert [c["candidate_id"] for c in second_page["candidates"]] == [
        "SYN-1004",
        "SYN-1005",
        "SYN-1006",
    ]
    empty_tail = list_synthetic_ege_candidates.fn(limit=100, offset=50)
    assert empty_tail["candidates"] == []
    assert empty_tail["total"] == 10


def test_get_results_by_candidate_id():
    _seed_registry()
    result = get_synthetic_ege_results.fn("SYN-1001")
    assert result["candidate_id"] == "SYN-1001"
    assert result["full_name"] == "Алексей Иванович Иванов"
    assert len(result["results"]) == 3
    for row in result["results"]:
        assert set(row) == {"subject", "year", "score"}
        assert 0 <= row["score"] <= 100


def test_get_unknown_candidate_raises():
    _seed_registry()
    with pytest.raises(ValueError, match="not found"):
        get_synthetic_ege_results.fn("SYN-9999")


def test_search_tool_reads_from_fis_database():
    # The person-search tool must read the same ФИС registry.
    from app.mcp_tools import search_synthetic_ege_results

    _seed_registry()
    result = search_synthetic_ege_results.fn("Иванов Алексей Иванович", "2008-03-14")
    assert result["match_count"] == 1
    assert result["matches"][0]["candidate_id"] == "SYN-1001"
    assert len(result["matches"][0]["results"]) == 3
