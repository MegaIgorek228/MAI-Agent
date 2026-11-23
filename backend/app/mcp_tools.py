"""MCP tools exposed to the Hermes agent (mounted at ``/mcp`` inside Backend).

Three data capabilities, no user context:
- ``fetch_web_page`` — live MAI admission pages over HTTPS (SSRF-guarded);
- ``search_synthetic_ege_results`` — the synthetic ФИС ГИА registry;
- ``sql_query`` — SQL access to the MAI data store (knowledge_* official
  materials, synthetic_ege_* registry, campaign data). The demo version
  intentionally leaves SQL open: any single PostgreSQL statement
  (SELECT, INSERT, UPDATE, DELETE, DDL) is allowed.

None of the tools is bound to a user profile: there are no user accounts in
the system, and the trusted-context header is not sent to the MCP server.
"""

import ipaddress
import socket
from datetime import date
from urllib.parse import urlsplit

import httpx
from fastapi.encoders import jsonable_encoder
from fastmcp import FastMCP
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import SyntheticEgeCandidate, SyntheticEgeResult
from app.official_materials import extract_html_content

mcp = FastMCP("MAI-Agent tools")

# Safety limits for the web-fetch tool (called by the LLM agent).
_FETCH_TIMEOUT_S = 25.0
_FETCH_MAX_BODY_BYTES = 2_000_000
_FETCH_MAX_OUTPUT_CHARS = 25_000
_FETCH_MAX_REDIRECTS = 5
_FETCH_USER_AGENT = "Mozilla/5.0 (compatible; MAI-Agent/1.0)"


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic ФИС ГИА registry (test EGE data source)
# ─────────────────────────────────────────────────────────────────────────────


def normalize_full_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def alternate_full_name_order(value: str) -> str | None:
    parts = value.split()
    if len(parts) != 3:
        return None
    return " ".join((*parts[1:], parts[0]))


def search_synthetic_candidates(db, full_name: str, date_of_birth: date) -> dict[str, object]:
    """Look the person up in the synthetic registry by full name + date of birth.

    Names are compared ignoring case and extra whitespace, with an exact date
    of birth; both surname-first and given-name-first orderings are accepted
    for three-part names. All matching rows are reported (ambiguous match).
    """
    needle = normalize_full_name(full_name)
    if not needle:
        raise ValueError("Full name is required")
    alternate = alternate_full_name_order(needle)
    candidates = db.scalars(
        select(SyntheticEgeCandidate).where(
            SyntheticEgeCandidate.date_of_birth == date_of_birth
        )
    )
    matched = []
    for candidate in candidates:
        name = normalize_full_name(candidate.full_name)
        if name in (needle, alternate) or alternate_full_name_order(name) == needle:
            matched.append(candidate)
    matches = []
    for item in sorted(matched, key=lambda candidate: candidate.candidate_id):
        results = db.scalars(
            select(SyntheticEgeResult)
            .where(
                SyntheticEgeResult.candidate_id == item.candidate_id,
                SyntheticEgeResult.status == "valid",
            )
            .order_by(SyntheticEgeResult.subject, SyntheticEgeResult.year.desc())
        )
        matches.append(
            {
                "candidate_id": item.candidate_id,
                "full_name": item.full_name,
                "date_of_birth": item.date_of_birth,
                "results": [
                    {"subject": row.subject, "year": row.year, "score": row.score}
                    for row in results
                ],
            }
        )
    return {
        "match_count": len(matches),
        "ambiguous": len(matches) > 1,
        "matches": matches,
    }


@mcp.tool
def search_synthetic_ege_results(full_name: str, date_of_birth: date) -> dict[str, object]:
    """Search the synthetic test EGE registry (imitation of ФИС ГИА) by full name and date of birth.

    Use it when the person gives their full name (surname, first name,
    patronymic) and date of birth (YYYY-MM-DD).

    Returns match_count and the matches (subject, year, score per result):
    - match_count == 1: present the found results to the user.
    - match_count == 0: tell the user that no record was found and suggest
      checking the full name and date of birth. Do not guess a person.
    - match_count > 1 (ambiguous): tell the user that several records share
      the same full name and date of birth. Do not offer a choice between
      records automatically.
    """
    with SessionLocal() as db:
        return jsonable_encoder(search_synthetic_candidates(db, full_name, date_of_birth))


# ─────────────────────────────────────────────────────────────────────────────
# Live MAI admission pages
# ─────────────────────────────────────────────────────────────────────────────


def _assert_public_host(hostname: str) -> None:
    """Reject hostnames that resolve to non-public addresses (SSRF guard)."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve host: {hostname}") from exc
    if not infos:
        raise ValueError(f"Cannot resolve host: {hostname}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError(f"Host {hostname} resolves to a non-public address")


@mcp.tool
def fetch_web_page(url: str, section_query: str | None = None) -> str:
    """Fetch visible HTTPS page content, retaining source URL and table rows.

    This is the agent's data source for live admission information:
    passing scores, program lists, tuition, deadlines, admission results.

    Ready-to-use pages (admissions site of MAI — Moscow Aviation Institute):
      https://priem.mai.ru/base/score/           - passing scores (table by
            program FZ code and full name, budget/paid, by year)
      https://priem.mai.ru/base/offers/          - educational programs
      https://priem.mai.ru/base/tuition-fees/    - tuition (paid education)
      https://priem.mai.ru/orders/deadlines/     - application deadlines
      https://priem.mai.ru/calendar/             - admissions campaign calendar
      https://www.mai.ru                         - university main site

    Notes:
    - Only https URLs are allowed; private/internal addresses are rejected.
    - Programs in the score tables are listed by FZ code and full name
      (e.g. 01.03.02 "Прикладная математика и информатика"); abbreviations
      like "ПМИ" are NOT used — search by code or full name.
    - Returns up to ~25k characters of plain text (truncated if longer).

    Args:
        url: absolute https URL of the page to fetch.
        section_query: optional program code or phrase to extract surrounding lines from long pages.
    """
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("Only absolute https:// URLs are allowed")
    for _hop in range(_FETCH_MAX_REDIRECTS):
        _assert_public_host(parts.hostname)
        try:
            resp = httpx.get(
                url,
                timeout=_FETCH_TIMEOUT_S,
                follow_redirects=False,
                headers={"User-Agent": _FETCH_USER_AGENT},
            )
        except httpx.HTTPError as exc:
            raise ValueError(f"Request failed: {exc.__class__.__name__}") from exc
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if not location:
                raise ValueError("Redirect without Location header")
            url = httpx.URL(url).join(location).url
            parts = urlsplit(url)
            if parts.scheme != "https" or not parts.hostname:
                raise ValueError("Redirect left https scope")
            continue
        break
    else:
        raise ValueError("Too many redirects")

    if resp.status_code != 200:
        raise ValueError(f"Page returned HTTP {resp.status_code}")
    if len(resp.content) > _FETCH_MAX_BODY_BYTES:
        raise ValueError("Page too large to process")

    content_type = resp.headers.get("content-type", "").lower()
    title = ""
    if "text/html" in content_type or not content_type:
        title, text = extract_html_content(resp.text)
    elif "text/plain" in content_type:
        text = resp.text
    else:
        raise ValueError(f"Unsupported content type: {content_type or 'unknown'}")

    text = text.strip()
    if not text:
        raise ValueError("Page contains no readable text")
    if section_query and section_query.strip():
        lines = text.splitlines()
        query = section_query.casefold().strip()
        matched_lines = [index for index, line in enumerate(lines) if query in line.casefold()]
        if not matched_lines:
            raise ValueError("The requested program code or phrase was not found on the page")
        context_lines = set(range(min(6, len(lines))))
        for index in matched_lines[:30]:
            context_lines.update(range(max(0, index - 3), min(len(lines), index + 4)))
        text = "\n".join(lines[index] for index in sorted(context_lines))
    if len(text) > _FETCH_MAX_OUTPUT_CHARS:
        text = text[:_FETCH_MAX_OUTPUT_CHARS] + "\n... [truncated]"
    return f"Source: {resp.url}\nTitle: {title or resp.url}\n\n{text}"


# ─────────────────────────────────────────────────────────────────────────────
# SQL tool: direct SQL access to the MAI data store (second external data source)
# ─────────────────────────────────────────────────────────────────────────────
#
# Demo-version policy: access is intentionally OPEN. Any single PostgreSQL
# statement is allowed — SELECT, INSERT, UPDATE, DELETE, DDL, etc. There is
# no RBAC, no statement-type filtering and no table-level restrictions.
# The 500-row cap below limits SELECT RESULT DISPLAY ONLY, never execution.

_SQL_MAX_RESULT_ROWS = 500


def _validate_sql(sql: str) -> str:
    """Validate and normalise a SQL statement: a single non-empty statement.

    Statement types are NOT restricted (open access by design); only
    multi-statement strings and empty input are rejected.
    """
    statement = (sql or "").strip().rstrip(";").strip()
    if not statement:
        raise ValueError("Empty SQL statement")
    if ";" in statement:
        raise ValueError("Only a single SQL statement is allowed")
    return statement


def run_sql(db, statement: str, limit: int = 100) -> dict[str, object]:
    """Execute a SQL statement and return a JSON-friendly result.

    Statements returning rows (SELECT, ... RETURNING) come back as
    columns + rows (display capped at 500 rows). Statements without a
    result set (INSERT/UPDATE/DELETE/DDL) report the affected row count.
    The transaction is committed — writes are intentional and persisted.
    """
    rows_limit = max(1, min(int(limit or 100), _SQL_MAX_RESULT_ROWS))
    result = db.execute(text(statement))
    if result.returns_rows:
        columns = list(result.keys())
        rows = [dict(row._mapping) for row in result.fetchmany(rows_limit)]
        db.commit()
        return {
            "columns": columns,
            "rows": jsonable_encoder(rows),
            "row_count": len(rows),
            "limit": rows_limit,
        }
    affected = result.rowcount
    db.commit()
    return {"executed": True, "affected_rows": affected if affected and affected >= 0 else 0}


@mcp.tool
def sql_query(sql: str, limit: int = 100) -> dict[str, object]:
    """Run a SQL statement against the MAI data store.

    Open access (demo version): any single statement is allowed —
    SELECT, INSERT, UPDATE, DELETE, CREATE/ALTER/DROP and other
    supported PostgreSQL commands. No query-type or table restrictions.

    Available data:
    - knowledge_sources / knowledge_chunks — official admission materials
      (title, url, content);
    - synthetic_ege_candidates / synthetic_ege_results — the synthetic
      ФИС ГИА registry (people, subjects, scores);
    - agent_sessions / telegram_checkpoints — session mappings.

    Result shapes:
    - row-returning statements: JSON with columns, rows, row_count, limit
      (rows are capped at 500 for display only — execution is unaffected);
    - other statements (INSERT/UPDATE/DELETE/DDL): {"executed": true,
      "affected_rows": N}.

    Only a single statement per call (no ';'-separated chains).

    Args:
        sql: the SQL statement to execute.
        limit: maximum number of rows to display for SELECT (default 100, max 500).
    """
    statement = _validate_sql(sql)
    with SessionLocal() as db:
        return run_sql(db, statement, limit)
