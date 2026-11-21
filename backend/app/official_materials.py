from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from app.config import get_settings


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        if self._in_title:
            self.title_parts.append(value)
        self.text_parts.append(value)


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
    parser = _TextExtractor()
    parser.feed(response.text)
    text = " ".join(parser.text_parts).strip()
    if not text:
        raise ValueError("Official material contains no readable text")
    title = " ".join(parser.title_parts).strip() or str(response.url)
    return str(response.url), title, text


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
