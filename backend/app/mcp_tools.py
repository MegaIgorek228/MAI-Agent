"""MCP tools exposed to the Hermes agent (mounted at ``/mcp`` inside Backend).

Three data capabilities, no user context, mapped to the three-database
architecture:
- ФИС ГИА (synthetic EGE results source, ``mai_fis_gia`` DB) — read-only:
  ``search_synthetic_ege_results`` (full name + date of birth),
  ``list_synthetic_ege_candidates`` and ``get_synthetic_ege_results``
  (browse the registry by candidate id);
- the agent's own database (``mai_agent`` DB) — ``sql_query``: open SQL
  access to applicants, applications, ege_scores, ratings, knowledge_*;
- the internet — ``fetch_web_page``: live MAI admission pages over HTTPS
  (SSRF-guarded); the agent may also use its native terminal/curl/Python
  tools for web work.

The Backend service database (agent_sessions, telegram_checkpoints) is NOT
reachable from any tool below.

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
from sqlalchemy import func, select, text

from app.db import FisSessionLocal, OwnSessionLocal
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
# Synthetic ФИС ГИА registry (test EGE data source) — mai_fis_gia database
# Read-only from the agent's side: data flows FROM ФИС into the agent's own
# database, never the other way round.
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
    with FisSessionLocal() as db:
        return jsonable_encoder(search_synthetic_candidates(db, full_name, date_of_birth))


@mcp.tool
def list_synthetic_ege_candidates(limit: int = 100, offset: int = 0) -> dict[str, object]:
    """List people from the synthetic ФИС ГИА registry (ordered by candidate_id).

    Use it to browse the registry when the person is unknown or to enumerate
    candidates before transferring their data into the own database via
    sql_query.

    Args:
        limit: maximum number of candidates per page (default 100, max 500).
        offset: zero-based offset of the first candidate of the page.
    """
    rows_limit = max(1, min(int(limit or 100), 500))
    with FisSessionLocal() as db:
        total_count = db.scalar(select(func.count(SyntheticEgeCandidate.candidate_id)))
        rows = db.scalars(
            select(SyntheticEgeCandidate)
            .order_by(SyntheticEgeCandidate.candidate_id)
            .limit(rows_limit)
            .offset(max(0, int(offset or 0)))
        )
        return jsonable_encoder(
            {
                "total": int(total_count or 0),
                "limit": rows_limit,
                "offset": max(0, int(offset or 0)),
                "candidates": [
                    {
                        "candidate_id": c.candidate_id,
                        "full_name": c.full_name,
                        "date_of_birth": c.date_of_birth,
                    }
                    for c in rows
                ],
            }
        )


@mcp.tool
def get_synthetic_ege_results(candidate_id: str) -> dict[str, object]:
    """Get all valid ЕGE results of one synthetic ФИС ГИА candidate by id.

    Use it together with list_synthetic_ege_candidates to read a person's
    results (candidate_id looks like SYN-1001).

    Args:
        candidate_id: the registry id of the person.
    """
    candidate_id = (candidate_id or "").strip()
    if not candidate_id:
        raise ValueError("candidate_id is required")
    with FisSessionLocal() as db:
        candidate = db.get(SyntheticEgeCandidate, candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found in the synthetic registry")
        results = db.scalars(
            select(SyntheticEgeResult)
            .where(
                SyntheticEgeResult.candidate_id == candidate_id,
                SyntheticEgeResult.status == "valid",
            )
            .order_by(SyntheticEgeResult.subject, SyntheticEgeResult.year.desc())
        )
        return jsonable_encoder(
            {
                "candidate_id": candidate.candidate_id,
                "full_name": candidate.full_name,
                "date_of_birth": candidate.date_of_birth,
                "results": [
                    {"subject": r.subject, "year": r.year, "score": r.score}
                    for r in results
                ],
            }
        )


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
# SQL tool: the agent's own database (mai_agent) — second external data source
# ─────────────────────────────────────────────────────────────────────────────
#
# Demo-version policy: access is intentionally OPEN. Any single PostgreSQL
# statement is allowed — SELECT, INSERT, UPDATE, DELETE, DDL, etc. There is
# no RBAC, no statement-type filtering and no table-level restrictions.
# The 500-row cap below limits SELECT RESULT DISPLAY ONLY, never execution.
#
# The tool is bound to the agent's own database ONLY: the ФИС ГИА registry
# (another database) is reachable exclusively through the ФИС MCP tools, and
# the Backend service database is not reachable at all.

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
    """Run a SQL statement against the agent's own database (mai_agent).

    Open access (demo version): any single statement is allowed —
    SELECT, INSERT, UPDATE, DELETE, CREATE/ALTER/DROP and other
    supported PostgreSQL commands. No query-type or table restrictions.

    This is the agent's own campaign database:
    - applicants — applicants (id, full_name, date_of_birth, contact);
    - ege_scores — EGE scores (applicant_id, candidate_id — ФИС reference,
      subject, year, score);
    - applications — applications (applicant_id, program_code, program_name,
      form: budget/paid, status);
    - ratings — admission ratings (program_code, form, year, applicant_id,
      place, total_score);
    - knowledge_sources / knowledge_chunks — official admission materials
      (title, url, content).

    The synthetic ФИС ГИА registry lives in ANOTHER database and is not
    visible here: read it only through the ФИС MCP tools
    (search_synthetic_ege_results, list_synthetic_ege_candidates,
    get_synthetic_ege_results) and transfer the data into this database
    (applicants + ege_scores) when working with a person.

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
    with OwnSessionLocal() as db:
        return run_sql(db, statement, limit)
