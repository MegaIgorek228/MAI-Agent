from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx
from lxml import etree, html

from app.config import get_settings


def extract_html_content(markup: str) -> tuple[str, str]:
    if not markup.strip():
        return "", ""
    try:
        tree = html.fromstring(markup)
    except etree.ParserError as exc:
        raise ValueError("Page HTML could not be parsed") from exc
    title = " ".join(" ".join(tree.xpath("//title/text()")).split())
    etree.strip_elements(tree, "script", "style", "noscript", "svg", "head", "nav", "footer", with_tail=False)
    for row in list(tree.iter("tr")):
        cells = [child for child in row if child.tag in {"th", "td"}]
        if not cells:
            continue
        row.text = " | ".join(" ".join(cell.text_content().split()) for cell in cells)
        for child in list(row):
            row.remove(child)
    for node in tree.iter("br", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
        if not any(ancestor.tag in {"td", "th"} for ancestor in node.iterancestors()):
            node.tail = "\n" + (node.tail or "")
            if node.tag != "br":
                node.text = "\n" + (node.text or "")
    lines = (" ".join(line.split()).strip() for line in tree.text_content().splitlines())
    return title, "\n".join(line for line in lines if line)


def _validate_official_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Official material URL must use HTTPS")
    domains = [item.strip().lower() for item in get_settings().official_source_domains.split(",") if item.strip()]
    if not domains:
        raise ValueError("OFFICIAL_SOURCE_DOMAINS is not configured")
    hostname = parsed.hostname.lower()
    if not any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
        raise ValueError("URL is outside the configured official source domains")


def fetch_official_material(url: str) -> tuple[str, str, str]:
    _validate_official_url(url)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
    _validate_official_url(str(response.url))
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/pdf":
        from app.document_service import extract_text

        title, text = str(response.url), extract_text(response.url.path, content_type, response.content) or ""
    elif content_type == "text/plain":
        title, text = str(response.url), response.text.strip()
    elif content_type in {"", "text/html", "application/xhtml+xml"}:
        title, text = extract_html_content(response.text)
    else:
        raise ValueError("Official material must be HTML, text, or a readable PDF")
    if not text:
        raise ValueError("Official material contains no readable text")
    return str(response.url), title or str(response.url), text


def discover_official_urls() -> list[str]:
    roots = [
        item.strip()
        for item in get_settings().official_source_root_urls.split(",")
        if item.strip()
    ]
    discovered: set[str] = set()
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for root in roots:
            _validate_official_url(root)
            response = client.get(root)
            response.raise_for_status()
            _validate_official_url(str(response.url))
            parser = _LinkExtractor(str(response.url))
            parser.feed(response.text)
            discovered.add(str(response.url))
            discovered.update(parser.links)
    return sorted(discovered)[:20]


class _LinkExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        candidate = urljoin(self.base_url, href)
        try:
            _validate_official_url(candidate)
        except ValueError:
            return
        parsed = urlparse(candidate)
        self.links.add(parsed._replace(fragment="").geturl())
