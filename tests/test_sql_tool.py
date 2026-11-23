"""Unit tests for the SQL MCP tool (sql_query backing logic).

The demo-version policy is OPEN SQL access: any single statement
(SELECT, INSERT, UPDATE, DELETE, DDL) must execute; the 500-row cap is a
display limit for SELECT results only, never an execution restriction.
"""

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.mcp_tools import _validate_sql, run_sql, sql_query


def test_validate_normalises_and_strips_trailing_semicolon():
    assert _validate_sql("  SELECT * FROM knowledge_sources  ") == "SELECT * FROM knowledge_sources"
    assert _validate_sql("WITH x AS (SELECT 1) SELECT * FROM x;") == "WITH x AS (SELECT 1) SELECT * FROM x"
    assert _validate_sql("select count(*) from synthetic_ege_results") == "select count(*) from synthetic_ege_results"


def test_validate_accepts_write_and_ddl_statements():
    # Old SELECT/WITH-only restriction must no longer block these.
    assert _validate_sql("DELETE FROM knowledge_sources WHERE id = 1") == "DELETE FROM knowledge_sources WHERE id = 1"
    assert _validate_sql("INSERT INTO knowledge_sources (title) VALUES ('t')") == "INSERT INTO knowledge_sources (title) VALUES ('t')"
    assert _validate_sql("UPDATE knowledge_sources SET title = 'x'") == "UPDATE knowledge_sources SET title = 'x'"
    assert _validate_sql("DROP TABLE IF EXISTS knowledge_sources") == "DROP TABLE IF EXISTS knowledge_sources"
    assert _validate_sql("CREATE TABLE probe (id INTEGER)") == "CREATE TABLE probe (id INTEGER)"


def test_validate_rejects_multiple_and_empty():
    with pytest.raises(ValueError, match="single"):
        _validate_sql("SELECT 1; UPDATE knowledge_sources SET title = ''")
    with pytest.raises(ValueError, match="Empty"):
        _validate_sql("   ")


def test_run_sql_select_returns_rows_and_caps_display():
    with SessionLocal() as db:
        db.execute(text("DROP TABLE IF EXISTS sql_probe"))
        db.execute(text("CREATE TABLE sql_probe (id INTEGER PRIMARY KEY, note TEXT)"))
        db.execute(text("INSERT INTO sql_probe (note) VALUES ('a'), ('b'), ('c')"))
        db.commit()
        result = run_sql(db, "SELECT id, note FROM sql_probe ORDER BY id", limit=2)
        assert result["columns"] == ["id", "note"]
        assert result["row_count"] == 2
        assert result["limit"] == 2
        assert result["rows"][0]["note"] == "a"
        assert result["rows"][1]["note"] == "b"
        db.execute(text("DROP TABLE sql_probe"))
        db.commit()

    with SessionLocal() as db:
        result = run_sql(db, "SELECT 1 AS one", limit=10_000)
        assert result["limit"] == 500
        assert result["rows"] == [{"one": 1}]


def test_run_sql_insert_update_delete_report_affected_rows():
    with SessionLocal() as db:
        db.execute(text("DROP TABLE IF EXISTS sql_probe"))
        db.execute(text("CREATE TABLE sql_probe (id INTEGER PRIMARY KEY, note TEXT)"))
        db.commit()
        try:
            result = run_sql(db, "INSERT INTO sql_probe (note) VALUES ('a'), ('b')")
            assert result == {"executed": True, "affected_rows": 2}

            result = run_sql(db, "UPDATE sql_probe SET note = 'z' WHERE note = 'a'")
            assert result == {"executed": True, "affected_rows": 1}

            # The write persisted (a fresh session sees it) — commit, not rollback.
            with SessionLocal() as db2:
                rows = db2.execute(text("SELECT note FROM sql_probe ORDER BY id")).fetchall()
            assert [row[0] for row in rows] == ["z", "b"]

            result = run_sql(db, "DELETE FROM sql_probe WHERE note = 'b'")
            assert result == {"executed": True, "affected_rows": 1}

            with SessionLocal() as db2:
                assert db2.execute(text("SELECT count(*) FROM sql_probe")).scalar() == 1
        finally:
            db.execute(text("DROP TABLE IF EXISTS sql_probe"))
            db.commit()


def test_run_sql_ddl_create_and_drop():
    with SessionLocal() as db:
        try:
            result = run_sql(db, "CREATE TABLE sql_ddl_probe (id INTEGER PRIMARY KEY, note TEXT)")
            assert result["executed"] is True
            # The table really exists: an INSERT through the same tool works.
            assert run_sql(db, "INSERT INTO sql_ddl_probe (note) VALUES ('x')")["affected_rows"] == 1
            assert run_sql(db, "SELECT note FROM sql_ddl_probe")["rows"] == [{"note": "x"}]
            result = run_sql(db, "DROP TABLE sql_ddl_probe")
            assert result["executed"] is True
        finally:
            db.execute(text("DROP TABLE IF EXISTS sql_ddl_probe"))
            db.commit()


def test_sql_query_public_tool_executes_writes():
    # Public MCP entry point: full read/write cycle through one function.
    # (@mcp.tool wraps the function into FunctionTool — call its .fn)
    sql = sql_query.fn
    assert sql("DROP TABLE IF EXISTS sql_public_probe")["executed"] is True
    assert sql("CREATE TABLE sql_public_probe (id INTEGER PRIMARY KEY, note TEXT)")["executed"] is True
    assert sql("INSERT INTO sql_public_probe (note) VALUES ('p1'), ('p2')") == {"executed": True, "affected_rows": 2}
    select_result = sql("SELECT id, note FROM sql_public_probe ORDER BY id")
    assert select_result["row_count"] == 2
    assert select_result["rows"][0]["note"] == "p1"
    assert sql("DELETE FROM sql_public_probe") == {"executed": True, "affected_rows": 2}
    assert sql("DROP TABLE sql_public_probe")["executed"] is True
    # Cleanup safety: the table is really gone.
    with SessionLocal() as db:
        assert (
            db.execute(text("SELECT count(*) FROM sqlite_master WHERE name = 'sql_public_probe'")).scalar() == 0
        )
