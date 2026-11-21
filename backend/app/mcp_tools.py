import ipaddress
import socket
from urllib.parse import urlsplit

import httpx
from fastmcp import Context, FastMCP
from jwt import InvalidTokenError

from app.mcp_service import get_authorized_user_for_mcp

mcp = FastMCP("MAI-Agent tools")

# Safety limits for the web-fetch tool (called by the LLM agent).
_FETCH_TIMEOUT_S = 25.0
_FETCH_MAX_BODY_BYTES = 2_000_000
_FETCH_MAX_OUTPUT_CHARS = 25_000
_FETCH_MAX_REDIRECTS = 5
_FETCH_USER_AGENT = "Mozilla/5.0 (compatible; MAI-Agent/1.0)"


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


def _html_to_text(html: str) -> str:
    """Strip markup to readable plain text (lxml is available via python-docx)."""
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(html)
    for tag in ("script", "style", "noscript", "svg", "head", "nav", "footer"):
        for el in tree.xpath(f"//{tag}"):
            el.getparent().remove(el)
    text = tree.text_content()
    # Normalize whitespace: collapse runs of spaces/tabs, keep paragraph breaks.
    lines = [ln.strip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if not ln:
            if out and out[-1] != "":
                out.append("")
            continue
        out.append(" ".join(ln.split()))
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


@mcp.tool
def fetch_web_page(url: str) -> str:
    """Fetch a web page over HTTPS and return its visible text content.

    This is the agent's data source for live admission information:
    passing scores, program lists, tuition, deadlines, admission results.

    Ready-to-use pages (admissions site of MGU Bauman / MAI):
      https://priem.mai.ru/base/score/           - passing scores (table by
            program FZ code and full name, budget/paid, by year)
      https://priem.mai.ru/base/offers/          - educational programs
      https://priem.mai.ru/base/tuition-fees/    - tuition (paid education)
      https://priem.mai.ru/results/orders/2026.php - admission results 2026
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
    """
    parts = urlsplit(url.strip())
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
    if "text/html" in content_type or not content_type:
        text = _html_to_text(resp.text)
    elif "text/plain" in content_type:
        text = resp.text
    else:
        raise ValueError(f"Unsupported content type: {content_type or 'unknown'}")

    text = text.strip()
    if not text:
        raise ValueError("Page contains no readable text")
    if len(text) > _FETCH_MAX_OUTPUT_CHARS:
        text = text[:_FETCH_MAX_OUTPUT_CHARS] + "\n... [truncated]"
    return text
