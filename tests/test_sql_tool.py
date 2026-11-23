"""Unit tests for the read-only SQL MCP tool (sql_query backing logic)."""

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.mcp_tools import _validate_readonly_sql, run_readonly_sql


def test_validate_accepts_selects():
    assert _validate_readonly_sql("  SELECT * FROM knowledge_sources  ") == "SELECT * FROM knowledge_sources"
    assert (
        _validate_readonly_sql("WITH x AS (SELECT 1) SELECT * FROM x;")
        == "WITH x AS (SELECT 1) SELECT * FROM x"
    )
    assert (
        _validate_readonly_sql("select count(*) from synthetic_ege_results")
        == "select count(*) from synthetic_ege_results"
    )


def test_validate_rejects_non_select_and_multiple_statements():
    with pytest.raises(ValueError, match="SELECT"):
        _validate_readonly_sql("DELETE FROM applications WHERE id = 1")
    with pytest.raises(ValueError, match="single"):
        _validate_readonly_sql("SELECT 1; UPDATE users SET is_active = 0")
    with pytest.raises(ValueError, match="Empty"):
        _validate_readonly_sql("   ")


def test_validate_forbids_account_tables():
    with pytest.raises(ValueError, match="users"):
        _validate_readonly_sql("SELECT * FROM users")
    with pytest.raises(ValueError, match="staff_invites"):
        _validate_readonly_sql(
            "SELECT s.id FROM applications a JOIN staff_invites s ON a.id = s.application_id"
        )
    # Other tables remain accessible.
    assert _validate_readonly_sql("SELECT * FROM applications") == "SELECT * FROM applications"


def test_run_readonly_sql_returns_rows_and_caps_limit():
    with SessionLocal() as db:
        db.execute(text("DROP TABLE IF EXISTS sql_probe"))
        db.execute(text("CREATE TABLE sql_probe (id INTEGER PRIMARY KEY, note TEXT)"))
        db.execute(text("INSERT INTO sql_probe (note) VALUES ('a'), ('b'), ('c')"))
        db.commit()
        result = run_readonly_sql(db, "SELECT id, note FROM sql_probe ORDER BY id", limit=2)
        assert result["columns"] == ["id", "note"]
        assert result["row_count"] == 2
        assert result["limit"] == 2
        assert result["rows"][0]["note"] == "a"
        assert result["rows"][1]["note"] == "b"
        db.execute(text("DROP TABLE sql_probe"))
        db.commit()

    with SessionLocal() as db:
        result = run_readonly_sql(db, "SELECT 1 AS one", limit=10_000)
        assert result["limit"] == 500
        assert result["rows"] == [{"one": 1}]
