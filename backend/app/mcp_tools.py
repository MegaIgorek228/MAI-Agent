import ipaddress
import socket
from datetime import date
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastapi.encoders import jsonable_encoder
from fastmcp import Context, FastMCP
from jwt import InvalidTokenError
from pydantic import Field

from app.admissions_schemas import (
    ApplicationCreate, ApplicationStatus, ApplicationUpdate, CampaignYear, EgeInput,
    StaffDocumentUpdate, StaffStatusUpdate,
)
from app.admissions_service import (
    application_for,
    bind_synthetic_results,
    ege_response,
    search_synthetic_candidates,
)
from app.knowledge_service import search_knowledge
from app.mcp_service import get_authorized_user_for_mcp, mcp_operation
from app.models import UserRole
from app.official_materials import extract_html_content
from app.routers import admissions, applicants, knowledge
from app.schemas import DocumentResponse, DocumentTypeUpdate, ProfileResponse, ProfileUpdate

mcp = FastMCP("MAI-Agent tools")

# Safety limits for the web-fetch tool (called by the LLM agent).
_FETCH_TIMEOUT_S = 25.0
_FETCH_MAX_BODY_BYTES = 2_000_000
_FETCH_MAX_OUTPUT_CHARS = 25_000
_FETCH_MAX_REDIRECTS = 5
_FETCH_USER_AGENT = "Mozilla/5.0 (compatible; MAI-Agent/1.0)"
_DOCUMENT_ROLES = (UserRole.applicant, UserRole.admissions_staff, UserRole.administrator)
_STAFF_ROLES = (UserRole.admissions_staff, UserRole.administrator)


@mcp.tool
def get_authenticated_user(
    context_token: str | None = None, context: Context | None = None
) -> dict[str, str | int]:
    """Return the minimum user identity authorized by Backend for this MCP call."""
    try:
        if context_token is None and context is not None:
            request = context.request_context.request if context.request_context else None
            if request is not None:
                context_token = request.headers.get("x-mai-context")
        if context_token is None:
            raise ValueError("Missing trusted user context")
        user, session_id = get_authorized_user_for_mcp(context_token)
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid trusted user context") from exc
    return {"user_id": user.id, "role": user.role, "session_id": session_id}


@mcp.tool
def search_admissions_knowledge(query: str, limit: int = 5) -> list[dict[str, object]]:
    """Search the admissions corpus and return relevant passages with source URLs and titles."""
    request = knowledge.KnowledgeSearchRequest(query=query, limit=limit)
    with mcp_operation() as (db, _):
        return search_knowledge(db, request.query, min(request.limit, 20))


@mcp.tool
def get_applicant_profile() -> dict[str, object]:
    """Read the authenticated user's own admissions profile."""
    with mcp_operation() as (db, actor):
        profile = applicants.get_profile(current_user=actor, db=db)
        return ProfileResponse.model_validate(profile).model_dump(mode="json")


@mcp.tool
def update_applicant_profile(payload: ProfileUpdate) -> dict[str, object]:
    """Save only explicitly supplied fields for the authenticated user's own profile."""
    with mcp_operation() as (db, actor):
        profile = applicants.update_profile(payload, current_user=actor, db=db)
        return ProfileResponse.model_validate(profile).model_dump(mode="json")


@mcp.tool
def list_applicant_documents() -> list[dict[str, object]]:
    """List the authenticated user's uploaded documents and their processing statuses."""
    with mcp_operation(*_DOCUMENT_ROLES) as (db, actor):
        documents = applicants.list_documents(current_user=actor, db=db)
        return [
            DocumentResponse.model_validate(document).model_dump(
                mode="json", exclude={"extracted_text", "analysis_json", "analysis_error"}
            )
            for document in documents
        ]


@mcp.tool
def analyze_applicant_document(document_id: int) -> dict[str, object]:
    """Analyze an existing document owned by the user. Analysis does not approve the document."""
    with mcp_operation(*_DOCUMENT_ROLES) as (db, actor):
        return applicants.analyze_uploaded_document(document_id, current_user=actor, db=db)


@mcp.tool
def update_applicant_document_type(document_id: int, payload: DocumentTypeUpdate) -> dict[str, object]:
    """Set an existing owned document's type as explicitly requested by the applicant."""
    with mcp_operation(*_DOCUMENT_ROLES) as (db, actor):
        document = applicants.update_document_type(document_id, payload, current_user=actor, db=db)
        return {"id": document.id, "document_type": document.document_type, "status": document.status}


@mcp.tool
def check_applicant_documents() -> dict[str, object]:
    """Check the user's documents against the applicable profile requirements."""
    with mcp_operation(*_DOCUMENT_ROLES) as (db, actor):
        return applicants.document_completeness(current_user=actor, db=db)


@mcp.tool
def get_admission_document_rules(
    target_program: str | None = None, admission_basis: str | None = None
) -> list[dict[str, object]]:
    """Read general and matching document requirements. Pass a program and basis when known."""
    with mcp_operation() as (db, _):
        return knowledge.list_admission_requirements(target_program, admission_basis, db)


@mcp.tool
def list_admission_rule_sets(campaign_year: CampaignYear | None = None) -> list[dict[str, object]]:
    """Read configured and versioned admission rules, optionally for a selected year."""
    with mcp_operation() as (db, actor):
        return jsonable_encoder(admissions.list_admission_rules(actor, db, campaign_year=campaign_year))


@mcp.tool
def list_applicant_applications() -> list[dict[str, object]]:
    """List applications and their current states for the authenticated applicant."""
    with mcp_operation(UserRole.applicant) as (db, actor):
        return jsonable_encoder(admissions.list_applications(actor, db))


@mcp.tool
def create_applicant_application(payload: ApplicationCreate) -> dict[str, object]:
    """Create a draft application after the applicant explicitly asks to create it."""
    with mcp_operation(UserRole.applicant) as (db, actor):
        return jsonable_encoder(admissions.create_application(payload, actor, db))


@mcp.tool
def update_applicant_application(application_id: int, payload: ApplicationUpdate) -> dict[str, object]:
    """Update explicitly supplied fields of the applicant's own editable application."""
    with mcp_operation(UserRole.applicant) as (db, actor):
        return jsonable_encoder(admissions.update_application(application_id, payload, actor, db))


@mcp.tool
def check_application_requirements(application_id: int) -> dict[str, object]:
    """Check the applicant's own application against configured document and score requirements."""
    with mcp_operation(UserRole.applicant) as (db, actor):
        return jsonable_encoder(admissions.get_application_requirements(application_id, actor, db))


@mcp.tool
def submit_applicant_application(application_id: int) -> dict[str, object]:
    """Submit the applicant's own application for review after explicit confirmation."""
    with mcp_operation(UserRole.applicant) as (db, actor):
        return jsonable_encoder(admissions.submit_application(application_id, actor, db))


@mcp.tool
def get_application_ege_scores(application_id: int) -> dict[str, object]:
    """Get the applicant's declared EGE scores and their latest synthetic comparison result."""
    with mcp_operation(UserRole.applicant) as (db, actor):
        return jsonable_encoder(admissions.get_application_ege(application_id, actor, db))


@mcp.tool
def update_application_ege_scores(application_id: int, payload: EgeInput) -> dict[str, object]:
    """Replace a draft's declared EGE scores with the explicitly confirmed complete list."""
    with mcp_operation(UserRole.applicant) as (db, actor):
        return jsonable_encoder(admissions.put_application_ege(application_id, payload, actor, db))


@mcp.tool
def verify_application_synthetic_ege(application_id: int) -> dict[str, object]:
    """Compare declared EGE scores against the synthetic test registry and return the recorded result."""
    with mcp_operation(UserRole.applicant) as (db, actor):
        return jsonable_encoder(admissions.verify_application_ege(application_id, actor, db))


@mcp.tool
def search_synthetic_ege_results(full_name: str, date_of_birth: date) -> dict[str, object]:
    """Search the synthetic test EGE registry by full name and date of birth.

    Use it when the applicant wants to apply and has given their full name
    (surname, first name, patronymic) and date of birth (YYYY-MM-DD).

    Returns match_count and the matches (subject, year, score per result):
    - match_count == 1: present the found results to the user and ask them
      to confirm that these are their results. After an explicit user
      confirmation call confirm_synthetic_ege_results with the returned
      candidate_id and the application id.
    - match_count == 0: tell the user that no record was found and suggest
      checking the full name and date of birth. Do not guess a person.
    - match_count > 1 (ambiguous): tell the user that several records share
      the same full name and date of birth and that automatic binding is
      forbidden in this case. Do not offer the user a choice between the
      records and do not call confirm_synthetic_ege_results. Suggest that
      the user clarifies the data with the admissions committee.
    """
    with mcp_operation(UserRole.applicant) as (db, _):
        return jsonable_encoder(
            search_synthetic_candidates(db, full_name=full_name, date_of_birth=date_of_birth)
        )


@mcp.tool
def confirm_synthetic_ege_results(application_id: int, candidate_id: str) -> dict[str, object]:
    """Bind the confirmed synthetic EGE results to the applicant's draft application.

    Call it only after the user explicitly confirmed that the presented
    results (from search_synthetic_ege_results) are theirs. Scores are copied
    from the registry as-is; this tool cannot alter the registry.
    """
    with mcp_operation(UserRole.applicant) as (db, actor):
        application = application_for(db, application_id, applicant_id=actor.id, lock=True)
        bind_synthetic_results(db, application, candidate_id)
        db.commit()
        return jsonable_encoder(ege_response(db, application))


@mcp.tool
def list_staff_admission_applications(
    status: ApplicationStatus | None = None,
    applicant_id: Annotated[int, Field(gt=0)] | None = None,
    query: Annotated[str, Field(max_length=255)] | None = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> list[dict[str, object]]:
    """List admissions applications with filters for authorized admissions staff."""
    with mcp_operation(*_STAFF_ROLES) as (db, actor):
        return jsonable_encoder(admissions.list_staff_applications(
            actor, db, status=status, applicant_id=applicant_id, q=query, limit=limit, offset=offset,
        ))


@mcp.tool
def get_staff_admission_application(application_id: int) -> dict[str, object]:
    """Show application details and review history for authorized admissions staff."""
    with mcp_operation(*_STAFF_ROLES) as (db, actor):
        details = admissions.get_staff_application(application_id, actor, db)
        return details.model_dump(
            mode="json",
            exclude={"documents": {"__all__": {"extracted_text", "analysis_json", "analysis_error"}}},
        )


@mcp.tool
def update_staff_admission_application(
    application_id: int, payload: StaffStatusUpdate,
) -> dict[str, object]:
    """Record a permitted status change explicitly requested by an authorized staff member."""
    with mcp_operation(*_STAFF_ROLES) as (db, actor):
        return jsonable_encoder(admissions.update_staff_application(application_id, payload, actor, db))


@mcp.tool
def review_staff_admission_document(
    application_id: int, document_id: int, payload: StaffDocumentUpdate,
) -> dict[str, object]:
    """Save a staff member's explicit document review decision for an application under review."""
    with mcp_operation(*_STAFF_ROLES) as (db, actor):
        document = admissions.review_staff_document(application_id, document_id, payload, actor, db)
        return {"id": document.id, "status": document.status, "review_message": document.review_message}


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
