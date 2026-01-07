from __future__ import annotations

import dataclasses
import html
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Deque, Dict, Iterable, Iterator, List, Mapping, Optional, Set, Tuple, Union
from urllib.parse import quote, urljoin, urlparse

import httpx


ATOM_NS = "http://www.w3.org/2005/Atom"
OPDS_NS = "http://opds-spec.org/2010/catalog"
DC_NS = "http://purl.org/dc/terms/"
CALIBRE_CATALOG_NS = "http://calibre.kovidgoyal.net/2009/catalog"
CALIBRE_METADATA_NS = "http://calibre.kovidgoyal.net/2009/metadata"
NS = {
    "atom": ATOM_NS,
    "opds": OPDS_NS,
    "dc": DC_NS,
    "calibre": CALIBRE_CATALOG_NS,
    "calibre_md": CALIBRE_METADATA_NS,
}


_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_SERIES_PREFIX_RE = re.compile(r"^\s*(series|books?)\s*[:\-]\s*", re.IGNORECASE)
_SERIES_NUMBER_BRACKET_RE = re.compile(r"[\[(]\s*(?:book\s*)?(\d+(?:\.\d+)?)\s*[\])]", re.IGNORECASE)
_SERIES_NUMBER_HASH_RE = re.compile(r"#\s*(\d+(?:\.\d+)?)")
_SERIES_NUMBER_BOOK_RE = re.compile(r"\bbook\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_SERIES_LINE_TEXT_RE = re.compile(r"^\s*series\s*[:\-]\s*(.+)$", re.IGNORECASE)
_SUMMARY_METADATA_LINE_RE = re.compile(r"^([A-Z][A-Z0-9&/\- +'\u2019]{1,40})\s*[:\-]\s*(.+)$")
_EPUB_MIME_TYPES = {
    "application/epub+zip",
    "application/zip",
    "application/x-zip",
    "application/x-zip-compressed",
}
_SUPPORTED_DOWNLOAD_MIME_TYPES = set(_EPUB_MIME_TYPES) | {"application/pdf"}
_SUPPORTED_DOWNLOAD_EXTENSIONS = {".epub", ".pdf"}
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when",
    "at", "by", "for", "from", "in", "into", "of", "off", "on", "onto",
    "to", "with", "is", "are", "was", "were", "be", "been", "being",
    "that", "this", "these", "those", "it", "its"
}


class CalibreOPDSError(RuntimeError):
    """Raised when the Calibre OPDS client encounters an unrecoverable error."""


@dataclass
class OPDSLink:
    href: str
    rel: Optional[str] = None
    type: Optional[str] = None
    title: Optional[str] = None

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "href": self.href,
            "rel": self.rel,
            "type": self.type,
            "title": self.title,
        }


@dataclass
class OPDSEntry:
    id: str
    title: str
    position: Optional[int] = None
    authors: List[str] = field(default_factory=list)
    subtitle: Optional[str] = None
    updated: Optional[str] = None
    published: Optional[str] = None
    summary: Optional[str] = None
    download: Optional[OPDSLink] = None
    alternate: Optional[OPDSLink] = None
    thumbnail: Optional[OPDSLink] = None
    links: List[OPDSLink] = field(default_factory=list)
    series: Optional[str] = None
    series_index: Optional[float] = None
    tags: List[str] = field(default_factory=list)
    rating: Optional[float] = None
    rating_max: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "position": self.position,
            "authors": list(self.authors),
            "subtitle": self.subtitle,
            "updated": self.updated,
            "published": self.published,
            "summary": self.summary,
            "download": self.download.to_dict() if self.download else None,
            "alternate": self.alternate.to_dict() if self.alternate else None,
            "thumbnail": self.thumbnail.to_dict() if self.thumbnail else None,
            "links": [link.to_dict() for link in self.links],
            "series": self.series,
            "series_index": self.series_index,
            "tags": list(self.tags),
            "rating": self.rating,
            "rating_max": self.rating_max,
        }


@dataclass
class OPDSFeed:
    id: Optional[str]
    title: Optional[str]
    entries: List[OPDSEntry]
    links: Dict[str, OPDSLink] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "entries": [entry.to_dict() for entry in self.entries],
            "links": {key: link.to_dict() for key, link in self.links.items()},
        }


def feed_to_dict(feed: OPDSFeed) -> Dict[str, Any]:
    return feed.to_dict()


@dataclass
class DownloadedResource:
    filename: str
    mime_type: str
    content: bytes


class CalibreOPDSClient:
    """Client for interacting with a Calibre-Web OPDS catalog."""

    def __init__(
        self,
        base_url: str,
        *,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 15.0,
        verify: bool = True,
    ) -> None:
        if not base_url:
            raise ValueError("Calibre OPDS base URL is required")
        normalized = base_url.strip()
        if not normalized:
            raise ValueError("Calibre OPDS base URL is required")
        # Store the original URL without forcing a trailing slash.
        # Some servers (e.g., Booklore) return 404 for URLs with trailing slashes.
        self._base_url = normalized.rstrip("/")
        self._auth = None
        if username:
            self._auth = httpx.BasicAuth(username, password or "")
        self._timeout = timeout
        self._verify = verify
        self._headers = {
            "User-Agent": "abogen-calibre-opds/1.0",
            "Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    @staticmethod
    def _strip_html(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = _TAG_STRIP_RE.sub("", value)
        return html.unescape(cleaned).strip() or None

    def _make_url(self, href: Optional[str]) -> str:
        if not href:
            return self._base_url
        href = href.strip()
        if href.startswith("http://") or href.startswith("https://"):
            return href
        if href.startswith("/"):
            # Absolute path - join with origin only
            parsed = urlparse(self._base_url)
            return f"{parsed.scheme}://{parsed.netloc}{href}"
        if href.startswith("?") or href.startswith("#"):
            return f"{self._base_url}{href}"
        if href.startswith("./") or href.startswith("../"):
            # For relative paths, we need a trailing slash for urljoin to work correctly
            base_with_slash = self._base_url if self._base_url.endswith("/") else f"{self._base_url}/"
            return urljoin(base_with_slash, href)
        # Relative path like "search" or "catalog?page=1" - treat as sibling
        base_with_slash = self._base_url if self._base_url.endswith("/") else f"{self._base_url}/"
        return urljoin(base_with_slash, href)

    def _open_client(self) -> httpx.Client:
        return httpx.Client(
            auth=self._auth,
            headers=dict(self._headers),
            timeout=self._timeout,
            verify=self._verify,
        )

    def fetch_feed(self, href: Optional[str] = None, *, params: Optional[Mapping[str, Any]] = None) -> OPDSFeed:
        target = self._make_url(href)
        try:
            with self._open_client() as client:
                response = client.get(target, params=params, follow_redirects=True)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - thin wrapper
            raise CalibreOPDSError(f"Calibre OPDS request failed: {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:  # pragma: no cover - thin wrapper
            raise CalibreOPDSError(f"Calibre OPDS request failed: {exc}") from exc

        return self._parse_feed(response.text, base_url=target)

    def _fetch_opensearch_template(self, href: str) -> Optional[str]:
        target = self._make_url(href)
        try:
            with self._open_client() as client:
                response = client.get(target, follow_redirects=True)
                response.raise_for_status()
            
            # Simple XML parsing to find the Url template
            # We avoid full namespace handling for robustness
            root = ET.fromstring(response.text)
            for node in root.iter():
                if node.tag.endswith("Url"):
                    template = node.attrib.get("template")
                    if template and "{searchTerms}" in template:
                        mime = node.attrib.get("type", "")
                        # Prefer atom/xml feeds
                        if "atom" in mime or "xml" in mime:
                            return template
            return None
        except Exception:
            return None

    def _find_best_seed_feed(self, root_feed: OPDSFeed) -> OPDSFeed:
        # If the root feed already has books, use it
        for entry in root_feed.entries:
            if any("acquisition" in (link.rel or "") for link in entry.links):
                return root_feed
        
        # Otherwise, look for a "By Title" or "All" navigation entry
        candidates = ["title", "all", "books", "catalog"]
        best_href = None
        
        for entry in root_feed.entries:
            title_lower = (entry.title or "").lower()
            if any(c in title_lower for c in candidates):
                # Check if it has a navigation link
                for link in entry.links:
                    if self._is_navigation_link(link):
                        best_href = link.href
                        # Prefer "By Title" explicitly
                        if "title" in title_lower:
                            break
                if best_href and "title" in title_lower:
                    break
        
        if best_href:
            try:
                return self.fetch_feed(best_href)
            except CalibreOPDSError:
                pass
                
        return root_feed

    def search(self, query: str, start_href: Optional[str] = None) -> OPDSFeed:
        cleaned = (query or "").strip()
        if not cleaned:
            return self.fetch_feed(start_href) if start_href else self.fetch_feed()

        base_feed: Optional[OPDSFeed] = None
        try:
            base_feed = self.fetch_feed()
        except CalibreOPDSError:
            pass

        # 1. Try explicit search link from feed
        if base_feed:
            # Check for OpenSearch description first
            search_link = self._resolve_link(base_feed.links, "search")
            if search_link and search_link.type == "application/opensearchdescription+xml":
                template = self._fetch_opensearch_template(search_link.href)
                if template:
                    search_url = template.replace("{searchTerms}", quote(cleaned))
                    try:
                        feed = self.fetch_feed(search_url)
                        if feed.entries:
                            filtered = self._filter_feed_entries(feed, cleaned)
                            if filtered.entries:
                                return filtered
                    except CalibreOPDSError:
                        pass

            # Check for direct template
            search_url = self._resolve_search_url(base_feed, cleaned)
            if search_url:
                try:
                    feed = self.fetch_feed(search_url)
                    if feed.entries:
                        filtered = self._filter_feed_entries(feed, cleaned)
                        if filtered.entries:
                            return filtered
                except CalibreOPDSError:
                    pass

        # 2. Try common guesses if explicit link failed
        candidates: List[Tuple[Optional[str], Optional[Mapping[str, Any]]]] = [
            ("search", {"query": cleaned}),
            ("search", {"q": cleaned}),
            (None, {"search": cleaned}),
        ]

        last_error: Optional[Exception] = None
        
        for path, params in candidates:
            try:
                feed = self.fetch_feed(path, params=params)
                if feed.entries:
                    # Check if the server ignored the query and returned the default feed
                    if base_feed and feed.title == base_feed.title:
                        # Compare first entry ID to see if it's the same feed
                        if feed.entries[0].id == base_feed.entries[0].id:
                            continue

                    filtered = self._filter_feed_entries(feed, cleaned)
                    if filtered.entries:
                        return filtered
            except CalibreOPDSError as exc:
                last_error = exc
                continue
                
        # 3. Fallback to local search (crawling)
        seed_feed: Optional[OPDSFeed] = None
        if start_href:
            try:
                seed_feed = self.fetch_feed(start_href)
            except CalibreOPDSError:
                pass
        
        if not seed_feed and base_feed:
            # If we are falling back to base_feed (Root), try to find a better seed
            seed_feed = self._find_best_seed_feed(base_feed)
            
        if not seed_feed:
             try:
                seed_feed = self.fetch_feed()
             except CalibreOPDSError as exc:
                 if last_error:
                     raise last_error
                 raise exc

        # Heuristic: If the seed feed has acquisition links, use linear scan.
        # Otherwise, use BFS to find content.
        has_books = False
        if seed_feed and seed_feed.entries:
            for entry in seed_feed.entries[:5]:
                for link in entry.links:
                    if "acquisition" in (link.rel or ""):
                        has_books = True
                        break
                if has_books:
                    break
        
        if has_books:
            return self._collect_search_results(seed_feed, cleaned)
        else:
            return self._local_search(cleaned, seed_feed=seed_feed)

    def _collect_search_results(
        self,
        seed_feed: OPDSFeed,
        query: str,
        *,
        max_pages: int = 40,
    ) -> OPDSFeed:
        normalized = (query or "").strip()
        if not normalized:
            return seed_feed
        seen_ids: Set[str] = set()
        collected: List[OPDSEntry] = []
        for page in self._iter_paginated_feeds(seed_feed, max_pages=max_pages):
            filtered = self._filter_feed_entries(page, normalized)
            for entry in filtered.entries:
                entry_id = (entry.id or "").strip()
                if entry_id:
                    if entry_id in seen_ids:
                        continue
                    seen_ids.add(entry_id)
                collected.append(entry)
        return dataclasses.replace(seed_feed, entries=collected)

    def _iter_paginated_feeds(self, seed_feed: OPDSFeed, *, max_pages: int = 40) -> Iterator[OPDSFeed]:
        yield seed_feed
        next_link = self._resolve_link(seed_feed.links, "next")
        visited: Set[str] = set()
        pages_examined = 0
        while next_link and pages_examined < max_pages:
            href = (next_link.href or "").strip()
            if not href:
                break
            absolute = self._make_url(href)
            if absolute in visited:
                break
            visited.add(absolute)
            pages_examined += 1
            try:
                page = self.fetch_feed(absolute)
            except CalibreOPDSError:
                break
            yield page
            next_link = self._resolve_link(page.links, "next")

    @staticmethod
    def _merge_feed_entries(primary: OPDSFeed, secondary: OPDSFeed) -> OPDSFeed:
        if primary is secondary or not secondary.entries:
            return primary
        seen_ids: Set[str] = set()
        combined: List[OPDSEntry] = list(primary.entries)
        for entry in primary.entries:
            entry_id = (entry.id or "").strip()
            if entry_id:
                seen_ids.add(entry_id)
        for entry in secondary.entries:
            entry_id = (entry.id or "").strip()
            if entry_id and entry_id in seen_ids:
                continue
            if entry_id:
                seen_ids.add(entry_id)
            combined.append(entry)
        return dataclasses.replace(primary, entries=combined)

    def _local_search(
        self,
        query: str,
        *,
        seed_feed: Optional[OPDSFeed] = None,
        max_pages: int = 40,
    ) -> OPDSFeed:
        normalized = (query or "").strip()
        if not normalized:
            return seed_feed or self.fetch_feed()
        tokens = [token for token in re.split(r"\s+", normalized.lower()) if token]
        if not tokens:
            return seed_feed or self.fetch_feed()

        start_feed = seed_feed or self.fetch_feed()
        collected: List[OPDSEntry] = []
        seen_match_ids: Set[str] = set()

        def add_matches(feed: OPDSFeed) -> None:
            filtered = self._filter_feed_entries(feed, normalized)
            for entry in filtered.entries:
                entry_id = (entry.id or "").strip()
                if entry_id:
                    if entry_id in seen_match_ids:
                        continue
                    seen_match_ids.add(entry_id)
                collected.append(entry)

        add_matches(start_feed)

        queue: Deque[str] = deque()
        queued: Set[str] = set()
        visited: Set[str] = set()

        def is_navigation_link(rel_hint: Optional[str], link: OPDSLink) -> bool:
            rel_candidates: List[str] = []
            if rel_hint:
                rel_candidates.append(rel_hint)
            if link.rel and link.rel not in rel_candidates:
                rel_candidates.append(link.rel)
            rel_candidates = [(rel or "").strip().lower() for rel in rel_candidates if rel]
            link_type = (link.type or "").strip().lower()
            if link_type and "opds-catalog" in link_type:
                return True
            for rel_value in rel_candidates:
                if not rel_value:
                    continue
                if "acquisition" in rel_value:
                    return False
                if rel_value == "self":
                    continue
                if rel_value == "next":
                    return True
                if rel_value in {"start", "up", "down"}:
                    return True
                if rel_value.endswith("navigation") or rel_value.endswith("collection"):
                    return True
                if rel_value.startswith("http://opds-spec.org/"):
                    if rel_value.startswith("http://opds-spec.org/group") or rel_value.startswith(
                        "http://opds-spec.org/sort"
                    ):
                        return True
                    if rel_value.endswith("navigation") or rel_value.endswith("collection"):
                        return True
            return False

        def enqueue_link(link: OPDSLink, rel_hint: Optional[str] = None) -> None:
            if not is_navigation_link(rel_hint, link):
                return
            href = (link.href or "").strip()
            if not href:
                return
            absolute = self._make_url(href)
            if absolute in queued or absolute in visited:
                return
            queued.add(absolute)
            queue.append(absolute)

        for rel_key, link in (start_feed.links or {}).items():
            enqueue_link(link, rel_key)
        for entry in start_feed.entries:
            for link in entry.links:
                enqueue_link(link, link.rel)

        pages_examined = 0
        while queue and pages_examined < max_pages:
            href = queue.popleft()
            if href in visited:
                continue
            visited.add(href)
            pages_examined += 1
            try:
                feed = self.fetch_feed(href)
            except CalibreOPDSError:
                continue
            add_matches(feed)
            for rel_key, link in (feed.links or {}).items():
                enqueue_link(link, rel_key)
            for entry in feed.entries:
                for link in entry.links:
                    enqueue_link(link, link.rel)
        if collected:
            return dataclasses.replace(start_feed, entries=collected)
        return dataclasses.replace(start_feed, entries=[])

    def download(self, href: str) -> DownloadedResource:
        if not href:
            raise ValueError("Download link missing")
        target = self._make_url(href)
        try:
            with self._open_client() as client:
                response = client.get(target, follow_redirects=True)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - thin wrapper
            raise CalibreOPDSError(
                f"Download failed with status {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:  # pragma: no cover - thin wrapper
            raise CalibreOPDSError(f"Download failed: {exc}") from exc

        mime_type = response.headers.get("Content-Type", "application/octet-stream").split(";")[0].strip()
        filename = self._deduce_filename(response, target, mime_type)
        return DownloadedResource(filename=filename, mime_type=mime_type, content=response.content)

    def _deduce_filename(self, response: httpx.Response, url: str, mime_type: str) -> str:
        header = response.headers.get("Content-Disposition", "")
        match = re.search(r'filename="?([^";]+)"?', header)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate
        parsed = urlparse(url)
        stem = (parsed.path or "").strip("/").split("/")[-1]
        if not stem:
            stem = "download"
        if "." not in stem:
            extension = self._extension_for_mime(mime_type)
            if extension:
                stem = f"{stem}{extension}"
        return stem

    @staticmethod
    def _extension_for_mime(mime_type: str) -> str:
        normalized = mime_type.lower()
        if normalized in _EPUB_MIME_TYPES:
            return ".epub"
        if normalized == "application/pdf":
            return ".pdf"
        if normalized in {"text/plain", "text/html"}:
            return ".txt"
        return ""

    def _parse_feed(self, xml_payload: str, *, base_url: str) -> OPDSFeed:
        try:
            root = ET.fromstring(xml_payload)
        except ET.ParseError as exc:
            raise CalibreOPDSError(f"Unable to parse OPDS feed: {exc}") from exc

        feed_id = root.findtext("atom:id", default=None, namespaces=NS)
        feed_title = root.findtext("atom:title", default=None, namespaces=NS)
        links_list = self._extract_links(root.findall("atom:link", NS), base_url)
        links = self._links_to_dict(links_list)
        parsed_entries = [self._parse_entry(node, base_url) for node in root.findall("atom:entry", NS)]
        entries: List[OPDSEntry] = []
        for entry in parsed_entries:
            if entry.download and self._is_supported_download(entry.download):
                entries.append(entry)
                continue
            if self._has_navigation_link(entry):
                entries.append(entry)
        return OPDSFeed(id=feed_id, title=feed_title, entries=entries, links=links)

    def _parse_entry(self, node: ET.Element, base_url: str) -> OPDSEntry:
        entry_id = node.findtext("atom:id", default="", namespaces=NS).strip()
        title = node.findtext("atom:title", default="Untitled", namespaces=NS).strip() or "Untitled"

        subtitle = (
            node.findtext("calibre_md:subtitle", default=None, namespaces=NS)
            or node.findtext("calibre:subtitle", default=None, namespaces=NS)
            or node.findtext("atom:subtitle", default=None, namespaces=NS)
        )
        subtitle = self._strip_html(subtitle.strip()) if subtitle else None

        position_value = self._extract_position(node)
        updated = node.findtext("atom:updated", default=None, namespaces=NS)
        published = (
            node.findtext("dc:date", default=None, namespaces=NS)
            or node.findtext("atom:published", default=None, namespaces=NS)
        )
        if published:
            published = published.strip() or None

        summary_text = (
            self._extract_text(node.find("atom:summary", NS))
            or self._extract_text(node.find("atom:content", NS))
            or self._extract_text(node.find("dc:description", NS))
        )
        summary_metadata: Dict[str, str] = {}
        summary_body: Optional[str] = None
        if summary_text:
            summary_metadata, summary_body = self._split_summary_metadata(summary_text)
        cleaned_summary = self._strip_html(summary_body or summary_text)

        authors: List[str] = []
        for author_node in node.findall("atom:author", NS):
            name = author_node.findtext("atom:name", default="", namespaces=NS).strip()
            if name:
                authors.append(name)
        if not authors:
            creators = node.findall("dc:creator", NS)
            for creator in creators:
                value = (creator.text or "").strip()
                if value:
                    authors.append(value)

        links = node.findall("atom:link", NS)
        all_links = self._extract_links(links, base_url)
        link_dict = self._links_to_dict(all_links)
        download_link = self._select_download_link(all_links)
        alternate_link = link_dict.get("alternate")
        thumb_link = link_dict.get("http://opds-spec.org/image/thumbnail") or link_dict.get(
            "thumbnail"
        )

        series_name = (
            node.findtext("calibre:series", default=None, namespaces=NS)
            or node.findtext("calibre_md:series", default=None, namespaces=NS)
        )
        if series_name:
            series_name = series_name.strip() or None

        series_index_raw = (
            node.findtext("calibre:series_index", default=None, namespaces=NS)
            or node.findtext("calibre_md:series_index", default=None, namespaces=NS)
        )
        series_index: Optional[float] = None
        if series_index_raw is not None:
            text = str(series_index_raw).strip()
            if text:
                try:
                    series_index = float(text)
                except ValueError:
                    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", "."))
                    if match:
                        try:
                            series_index = float(match.group(0))
                        except ValueError:
                            series_index = None

        if series_name is None or series_index is None:
            category_series_name, category_series_index = self._extract_series_from_categories(
                node.findall("atom:category", NS),
                authors=authors,
            )
            if series_name is None and category_series_name:
                series_name = category_series_name
            if series_index is None and category_series_index is not None:
                series_index = category_series_index

        if (series_name is None or series_index is None) and summary_text:
            text_series_name, text_series_index = self._extract_series_from_text(summary_text)
            if series_name is None and text_series_name:
                series_name = text_series_name
            if series_index is None and text_series_index is not None:
                series_index = text_series_index

        tags_value = summary_metadata.get("TAGS")
        tags = self._parse_tags(tags_value) if tags_value else []
        rating_value = summary_metadata.get("RATING")
        rating, rating_max = self._parse_rating(rating_value) if rating_value else (None, None)

        return OPDSEntry(
            id=entry_id or title,
            title=title,
            position=position_value,
            authors=authors,
            subtitle=subtitle,
            updated=updated,
            published=published,
            summary=cleaned_summary,
            download=download_link,
            alternate=alternate_link,
            thumbnail=thumb_link,
            links=all_links,
            series=series_name,
            series_index=series_index,
            tags=tags,
            rating=rating,
            rating_max=rating_max,
        )

    def _extract_series_from_categories(
        self,
        category_nodes: List[ET.Element],
        *,
        authors: Optional[List[str]] = None,
    ) -> tuple[Optional[str], Optional[float]]:
        name: Optional[str] = None
        index: Optional[float] = None
        author_set = {str(author).strip().casefold() for author in (authors or []) if str(author).strip()}
        for category in category_nodes:
            scheme = (category.attrib.get("scheme") or "").strip().lower()
            label = (category.attrib.get("label") or "").strip()
            term = (category.attrib.get("term") or "").strip()
            values: List[str] = []
            if label:
                values.append(label)
            if term and term not in values:
                values.append(term)

            # Be conservative: category schemes are often URLs and can contain unrelated substrings.
            # Also, some catalog feeds incorrectly include author names in series-like categories.
            is_series_hint = self._is_series_scheme(scheme) or any("series" in value.lower() for value in values if value)
            if not is_series_hint:
                continue

            for value in values:
                if not value:
                    continue
                candidate_name, candidate_index = self._parse_series_value(value)
                if candidate_name and candidate_name.casefold() in author_set:
                    # Guardrail: avoid mapping the author name into series.
                    continue
                if candidate_name and not name:
                    name = candidate_name
                if candidate_index is not None and index is None:
                    index = candidate_index
                if name and index is not None:
                    return name, index
        return name, index

    @staticmethod
    def _is_series_scheme(scheme: str) -> bool:
        cleaned = (scheme or "").strip().lower()
        if not cleaned:
            return False
        if "author" in cleaned:
            return False
        return bool(re.search(r"(^|[/#:\-])series([/#:\-]|$)", cleaned))

    def _parse_series_value(self, value: str) -> tuple[Optional[str], Optional[float]]:
        cleaned = re.sub(r"\s+", " ", value or "").strip()
        if not cleaned:
            return None, None
        cleaned = _SERIES_PREFIX_RE.sub("", cleaned)
        working = cleaned
        number: Optional[float] = None

        bracket_match = _SERIES_NUMBER_BRACKET_RE.search(working)
        if bracket_match:
            number = self._coerce_series_index(bracket_match.group(1))
            start, end = bracket_match.span()
            working = (working[:start] + working[end:]).strip()

        if number is None:
            hash_match = _SERIES_NUMBER_HASH_RE.search(working)
            if hash_match:
                number = self._coerce_series_index(hash_match.group(1))
                start, end = hash_match.span()
                working = (working[:start] + working[end:]).strip()

        if number is None:
            book_match = _SERIES_NUMBER_BOOK_RE.search(working)
            if book_match:
                number = self._coerce_series_index(book_match.group(1))
                start, end = book_match.span()
                working = (working[:start] + working[end:]).strip()

        name = working.strip(" -–—,:")
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            name = None
        return name, number

    @staticmethod
    def _extract_text(node: Optional[ET.Element]) -> Optional[str]:
        if node is None:
            return None
        # Prefer itertext to capture nested XHTML content
        parts = list(node.itertext())
        if not parts:
            return (node.text or "").strip() or None
        combined = "".join(parts).strip()
        return combined or None

    def _extract_series_from_text(self, text: str) -> tuple[Optional[str], Optional[float]]:
        for line in text.splitlines():
            match = _SERIES_LINE_TEXT_RE.match(line)
            if not match:
                continue
            candidate = match.group(1).strip()
            if not candidate:
                continue
            name, number = self._parse_series_value(candidate)
            if name or number is not None:
                return name, number
        return None, None

    def _split_summary_metadata(self, text: Optional[str]) -> tuple[Dict[str, str], Optional[str]]:
        metadata: Dict[str, str] = {}
        if text is None:
            return metadata, None
        lines = text.splitlines()
        index = 0
        total = len(lines)
        while index < total and not lines[index].strip():
            index += 1
        while index < total:
            stripped = lines[index].strip()
            if not stripped:
                break
            match = _SUMMARY_METADATA_LINE_RE.match(stripped)
            if not match:
                break
            key = match.group(1).strip().upper()
            value = match.group(2).strip()
            if key and value:
                metadata[key] = value
            index += 1
        remainder = "\n".join(lines[index:]).strip()
        return metadata, (remainder or None)

    @staticmethod
    def _parse_tags(value: str) -> List[str]:
        if not value:
            return []
        tokens = re.split(r"[;,\n]\s*", value)
        cleaned: List[str] = []
        seen: set[str] = set()
        for token in tokens:
            entry = token.strip()
            if not entry:
                continue
            key = entry.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(entry)
        return cleaned

    @staticmethod
    def _parse_rating(value: str) -> tuple[Optional[float], Optional[float]]:
        if not value:
            return None, None
        text = value.strip()
        if not text:
            return None, None
        stars = text.count("★")
        half = 0.5 if "½" in text else 0.0
        if stars or half:
            rating = stars + half
            return (rating if rating > 0 else None, 5.0)
        match = re.search(r"\d+(?:\.\d+)?", text.replace(",", "."))
        if match:
            try:
                rating_value = float(match.group(0))
            except ValueError:
                return None, None
            return rating_value, 5.0
        return None, None

    @staticmethod
    def _coerce_series_index(value: str) -> Optional[float]:
        text = value.strip().replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _extract_position(self, node: ET.Element) -> Optional[int]:
        candidates = [
            node.findtext("opds:position", default=None, namespaces=NS),
            node.findtext("opds:groupPosition", default=None, namespaces=NS),
            node.findtext("opds:order", default=None, namespaces=NS),
            node.findtext("dc:identifier", default=None, namespaces=NS),
        ]
        for value in candidates:
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            try:
                return int(float(text))
            except (TypeError, ValueError):
                continue
        return None

    def _extract_links(self, link_nodes: List[ET.Element], base_url: str) -> List[OPDSLink]:
        links: List[OPDSLink] = []
        for link in link_nodes:
            href = link.attrib.get("href")
            if not href:
                continue
            rel = link.attrib.get("rel")
            link_type = link.attrib.get("type")
            title = link.attrib.get("title")
            base_for_join = base_url or self._base_url
            absolute_href = urljoin(base_for_join, href)
            links.append(OPDSLink(href=absolute_href, rel=rel, type=link_type, title=title))
        return links

    def _links_to_dict(self, links: List[OPDSLink]) -> Dict[str, OPDSLink]:
        results: Dict[str, OPDSLink] = {}
        for entry in links:
            key = entry.rel or entry.href
            if not key:
                continue
            
            # Prioritize search links with template parameters
            if key == "search" and key in results:
                existing = results[key]
                if "{searchTerms}" in (existing.href or ""):
                    continue
                if "{searchTerms}" in (entry.href or ""):
                    results[key] = entry
                    continue
            
            results[key] = entry
        return results

    @staticmethod
    def _is_supported_download(link: OPDSLink) -> bool:
        mime = (link.type or "").split(";")[0].strip().lower()
        if mime in _SUPPORTED_DOWNLOAD_MIME_TYPES:
            return True
        href = (link.href or "").strip()
        if not href:
            return False
        parsed_path = urlparse(href).path or ""
        extension = PurePosixPath(parsed_path).suffix.lower()
        return extension in _SUPPORTED_DOWNLOAD_EXTENSIONS

    @staticmethod
    def _select_download_link(links: Mapping[str, OPDSLink] | Iterable[OPDSLink]) -> Optional[OPDSLink]:
        if isinstance(links, Mapping):
            iterable: List[OPDSLink] = list(links.values())
        else:
            iterable = list(links)
        supported = [link for link in iterable if CalibreOPDSClient._is_supported_download(link)]
        best: Optional[OPDSLink] = None
        for link in supported:
            rel = (link.rel or "").lower()
            if "acquisition" not in rel:
                continue
            mime = (link.type or "").lower()
            if mime in _EPUB_MIME_TYPES:
                return link
            if best is None:
                best = link
        if best:
            return best
        if supported:
            return supported[0]
        # No valid acquisition-style link exposed
        return None

    @staticmethod
    def _resolve_link(links: Optional[Mapping[str, OPDSLink]], rel: str) -> Optional[OPDSLink]:
        if not links:
            return None
        if rel in links:
            return links[rel]
        rel_lower = rel.lower()
        for key, link in links.items():
            key_lower = (key or "").strip().lower()
            if key_lower == rel_lower or key_lower.endswith(rel_lower):
                return link
        return None

    @staticmethod
    def _is_navigation_link(link: OPDSLink) -> bool:
        href = (link.href or "").strip()
        if not href:
            return False
        rel = (link.rel or "").strip().lower()
        link_type = (link.type or "").strip().lower()
        if "acquisition" in rel:
            return False
        if rel == "self":
            return False
        if "opds-catalog" in link_type:
            return True
        if rel.endswith("navigation") or rel.endswith("collection"):
            return True
        if rel.startswith("http://opds-spec.org/sort") or rel.startswith("http://opds-spec.org/group"):
            return True
        return False

    @staticmethod
    def _has_navigation_link(entry: OPDSEntry) -> bool:
        return any(CalibreOPDSClient._is_navigation_link(link) for link in entry.links)

    @staticmethod
    def _browse_mode_for_title(title: Optional[str]) -> str:
        if not title:
            return "generic"
        lowered = title.lower()
        if "author" in lowered:
            return "author"
        if "series" in lowered:
            return "series"
        if "title" in lowered or "book" in lowered:
            return "title"
        return "generic"

    @staticmethod
    def _strip_leading_article(text: str) -> str:
        working = text.strip()
        lowered = working.lower()
        for article in ("the ", "a ", "an "):
            if lowered.startswith(article):
                return working[len(article):].strip()
        return working

    @staticmethod
    def _alphabet_source(entry: OPDSEntry, mode: str) -> str:
        if mode == "author" and entry.authors:
            candidate = entry.authors[0] or ""
            if "," in candidate:
                return candidate.split(",", 1)[0].strip()
            parts = candidate.split()
            if len(parts) > 1:
                return parts[-1].strip()
            return candidate.strip()
        if mode == "series" and entry.series:
            return entry.series.strip()
        if entry.title:
            return entry.title.strip()
        if entry.series:
            return entry.series.strip()
        for link in entry.links:
            if link.title:
                return link.title.strip()
        return ""

    @staticmethod
    def _normalize_text(text: str) -> str:
        if not text:
            return ""
        # Normalize unicode characters to their base form (e.g. é -> e)
        normalized = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
        return normalized.lower().strip()

    @staticmethod
    def _alphabet_letter_for_entry(entry: OPDSEntry, mode: str) -> Optional[str]:
        source = CalibreOPDSClient._alphabet_source(entry, mode)
        if not source:
            return None
        if mode == "title":
            source = CalibreOPDSClient._strip_leading_article(source)
        
        # Normalize to handle accents (É -> E)
        normalized_source = unicodedata.normalize('NFKD', source).encode('ASCII', 'ignore').decode('utf-8')
        
        cleaned = re.sub(r"^[^0-9A-Za-z]+", "", normalized_source)
        if not cleaned:
            return "#"
        initial = cleaned[0]
        if initial.isalpha():
            return initial.upper()
        if initial.isdigit():
            return "#"
        return "#"

    @staticmethod
    def _entry_matches_query(entry: OPDSEntry, tokens: List[str]) -> bool:
        if not tokens:
            return True
        search_fragments: List[str] = []
        
        if entry.title:
            search_fragments.append(CalibreOPDSClient._normalize_text(entry.title))
        if entry.series:
            search_fragments.append(CalibreOPDSClient._normalize_text(entry.series))
            
        for author in entry.authors:
            cleaned = (author or "").strip()
            if not cleaned:
                continue
            normalized_author = CalibreOPDSClient._normalize_text(cleaned)
            search_fragments.append(normalized_author)
            for part in re.split(r"[\s,]+", normalized_author):
                part = part.strip()
                if part:
                    search_fragments.append(part)
                    
        if not search_fragments:
            return False
            
        # Check if all tokens match at least one fragment
        # Tokens are already normalized in _filter_feed_entries
        return all(any(token in fragment for fragment in search_fragments) for token in tokens)

    def _filter_feed_entries(self, feed: OPDSFeed, query: str) -> OPDSFeed:
        normalized_query = CalibreOPDSClient._normalize_text(query)
        if not normalized_query:
            return feed
        tokens = [token for token in re.split(r"\s+", normalized_query) if token]
        if not tokens:
            return feed
            
        scored_entries = []
        for entry in feed.entries:
            if not self._entry_matches_query(entry, tokens):
                continue
            score = self._calculate_match_score(entry, tokens)
            # Require a minimum score to avoid weak matches (e.g. single word in summary)
            if score >= 10:
                scored_entries.append((score, entry))
                
        # Sort by score descending
        scored_entries.sort(key=lambda x: x[0], reverse=True)
        
        filtered = [e for s, e in scored_entries]
        return dataclasses.replace(feed, entries=filtered)

    def _estimate_letter_position(self, letter: str) -> float:
        """Estimate the relative position (0.0-1.0) of a letter in an alphabetical list."""
        if letter == "#":
            return 0.0
        if not letter or not letter.isalpha():
            return 0.0
        
        # Approximate cumulative distribution of starting letters in English book titles
        # This is a heuristic to jump closer to the target
        weights = {
            'A': 0.00, 'B': 0.08, 'C': 0.15, 'D': 0.22, 'E': 0.28,
            'F': 0.33, 'G': 0.38, 'H': 0.43, 'I': 0.49, 'J': 0.53,
            'K': 0.55, 'L': 0.58, 'M': 0.63, 'N': 0.68, 'O': 0.71,
            'P': 0.75, 'Q': 0.80, 'R': 0.81, 'S': 0.85, 'T': 0.92,
            'U': 0.97, 'V': 0.98, 'W': 0.99, 'X': 0.995, 'Y': 0.997, 'Z': 0.999
        }
        return weights.get(letter.upper(), 0.0)

    def _attempt_smart_jump(self, feed: OPDSFeed, letter: str) -> Optional[OPDSFeed]:
        """
        Attempt to jump to a page closer to the target letter by analyzing pagination links.
        Returns a new OPDSFeed if a jump was successful, or None.
        """
        first_link = self._resolve_link(feed.links, "first")
        last_link = self._resolve_link(feed.links, "last")
        next_link = self._resolve_link(feed.links, "next")
        
        if not (first_link and last_link and next_link):
            return None
            
        # Try to extract offsets from URLs to determine page size and total items
        # Common Calibre pattern: .../offset/0, .../offset/50
        def extract_offset(href: str) -> Optional[int]:
            match = re.search(r"/(\d+)/?$", href)
            if match:
                return int(match.group(1))
            # Try query param
            parsed = urlparse(href)
            qs = dict(pair.split('=') for pair in parsed.query.split('&') if '=' in pair)
            if 'offset' in qs:
                try:
                    return int(qs['offset'])
                except ValueError:
                    pass
            return None

        start_offset = extract_offset(first_link.href)
        next_offset = extract_offset(next_link.href)
        last_offset = extract_offset(last_link.href)
        
        if start_offset is None or next_offset is None or last_offset is None:
            return None
            
        page_size = next_offset - start_offset
        if page_size <= 0:
            return None
            
        # Estimate total items (last_offset is the start of the last page)
        # We assume the last page is roughly half full for estimation
        total_items = last_offset + (page_size // 2)
        
        target_ratio = self._estimate_letter_position(letter)
        # Aim slightly early (subtract 1-2 pages worth) to ensure we don't miss the start
        target_offset = int(total_items * target_ratio)
        target_offset = max(0, target_offset - (page_size * 2))
        
        # Round to nearest page boundary
        target_offset = (target_offset // page_size) * page_size
        
        # If the jump is too small (e.g. we are already near the start), don't bother
        if target_offset < (page_size * 3):
            return None
            
        # Construct the new URL
        # We assume the URL structure is consistent and we can just replace the offset
        # This is risky but works for standard Calibre OPDS
        base_href = first_link.href
        if str(start_offset) in base_href:
            # Path based replacement
            # Replace the last occurrence of the offset
            parts = base_href.rsplit(str(start_offset), 1)
            if len(parts) == 2:
                new_href = f"{parts[0]}{target_offset}{parts[1]}"
                try:
                    return self.fetch_feed(new_href)
                except Exception:
                    return None
                    
        return None

    def browse_letter(
        self,
        letter: str,
        *,
        start_href: Optional[str] = None,
        max_pages: int = 40,
    ) -> OPDSFeed:
        normalized = (letter or "").strip()
        if not normalized:
            return self.fetch_feed(start_href)
        key = normalized.upper()
        if key in {"ALL", "*"}:
            return self.fetch_feed(start_href)
        if key in {"0-9", "NUMERIC"}:
            key = "#"
        if len(key) > 1:
            key = key[0]
        if key != "#" and not key.isalpha():
            key = "#"
        base_feed = self.fetch_feed(start_href)
        
        # Ensure we start from the beginning of the feed if possible
        first_link = self._resolve_link(base_feed.links, "first") or self._resolve_link(base_feed.links, "start")
        if first_link and first_link.href:
            try:
                # Only switch if the href is different to avoid redundant fetch
                if not start_href or first_link.href != start_href:
                    base_feed = self.fetch_feed(first_link.href)
            except CalibreOPDSError:
                pass

        mode = self._browse_mode_for_title(base_feed.title)

        def letter_matches(entry: OPDSEntry, active_mode: str) -> bool:
            letter_value = self._alphabet_letter_for_entry(entry, active_mode)
            if not letter_value:
                return False
            if key == "#":
                return letter_value == "#"
            return letter_value == key

        collected: List[OPDSEntry] = []
        seen_ids: Set[str] = set()
        letter_href: Optional[str] = None

        def add_entry(entry: OPDSEntry) -> None:
            entry_id = (entry.id or "").strip()
            if entry_id:
                if entry_id in seen_ids:
                    return
                seen_ids.add(entry_id)
            collected.append(entry)

        # Check the first page for navigation links before attempting any jumps
        # This handles the case where "By Title" has "A", "B", "C" folders
        has_nav_links = False
        for entry in base_feed.entries:
            if self._has_navigation_link(entry):
                has_nav_links = True
                if letter_matches(entry, mode):
                    for link in entry.links:
                        if self._is_navigation_link(link):
                            href = (link.href or "").strip()
                            if href:
                                letter_href = href
                                break
            if letter_href:
                break
        
        # If we didn't find a direct link, and it looks like a flat list (no nav links matching criteria),
        # try to jump closer to the target letter if we are in a sorted mode
        if not letter_href and mode in {"title", "author", "series"}:
            jump_feed = self._attempt_smart_jump(base_feed, key)
            if jump_feed:
                base_feed = jump_feed

        for page in self._iter_paginated_feeds(base_feed, max_pages=max_pages):
            for entry in page.entries:
                if not letter_matches(entry, mode):
                    continue
                if self._has_navigation_link(entry):
                    if letter_href is None:
                        for link in entry.links:
                            if self._is_navigation_link(link):
                                href = (link.href or "").strip()
                                if href:
                                    letter_href = href
                                    break
                else:
                    add_entry(entry)

        letter_feed: Optional[OPDSFeed] = None
        if letter_href:
            try:
                letter_feed = self.fetch_feed(letter_href)
            except CalibreOPDSError:
                letter_feed = None
            else:
                letter_mode = self._browse_mode_for_title(letter_feed.title)
                for page in self._iter_paginated_feeds(letter_feed, max_pages=max_pages):
                    for entry in page.entries:
                        if not letter_matches(entry, letter_mode):
                            continue
                        if self._has_navigation_link(entry):
                            continue
                        add_entry(entry)

        template = letter_feed or base_feed
        if collected:
            return dataclasses.replace(template, entries=collected)
        return dataclasses.replace(template, entries=[])

    def _resolve_search_url(self, feed: OPDSFeed, query: str) -> Optional[str]:
        link = self._resolve_link(feed.links, "search")
        if not link:
            link = self._resolve_link(feed.links, "http://opds-spec.org/search")
        
        if not link or not link.href:
            return None
            
        href = link.href.strip()
        if "{searchTerms}" in href:
            return href.replace("{searchTerms}", quote(query))
            
        return href

    def _calculate_match_score(self, entry: OPDSEntry, tokens: List[str]) -> int:
        if not tokens:
            return 0
            
        score = 0
        
        # Prepare normalized text
        title = self._normalize_text(entry.title)
        authors = [self._normalize_text(a) for a in entry.authors]
        series = self._normalize_text(entry.series) if entry.series else ""
        summary = self._normalize_text(entry.summary) if entry.summary else ""
        tags = [self._normalize_text(t) for t in entry.tags]
        
        # 1. Exact/Phrase matches
        query_phrase = " ".join(tokens)
        if query_phrase == title:
            score += 1000
        elif query_phrase in title:
            score += 500
        
        for author in authors:
            if query_phrase in author:
                score += 300
                
        if query_phrase in series:
            score += 200
            
        for tag in tags:
            if query_phrase == tag:
                score += 100
            elif query_phrase in tag:
                score += 50

        # 2. Token matches
        # Filter out stop words unless the query is only stop words
        significant_tokens = [t for t in tokens if t not in _STOP_WORDS]
        if not significant_tokens:
            significant_tokens = tokens

        for token in significant_tokens:
            token_score = 0
            # Use regex for word boundary matching
            # Escape token to handle special chars
            token_regex = r"\b" + re.escape(token) + r"\b"
            
            # Title: High weight
            if re.search(token_regex, title):
                token_score = max(token_score, 50)
            elif token in title:
                token_score = max(token_score, 5)

            # Author: Medium-High weight
            for author in authors:
                if re.search(token_regex, author):
                    token_score = max(token_score, 40)
                elif token in author:
                    token_score = max(token_score, 5)
            
            # Series: Medium weight
            if token in series:
                if re.search(token_regex, series):
                    token_score = max(token_score, 30)
                else:
                    token_score = max(token_score, 5)
                
            # Tags: Medium weight
            for tag in tags:
                if re.search(token_regex, tag):
                    token_score = max(token_score, 30)
                elif token in tag:
                    token_score = max(token_score, 5)
                
            # Summary: Low weight
            if token in summary:
                if re.search(token_regex, summary):
                    # Only add if not found elsewhere? Or just add small amount?
                    if token_score == 0: 
                        token_score = 15
                    else:
                        token_score += 5 # Small boost if also in description
                elif token_score == 0:
                    token_score = 2 # Very low for substring in summary
            
            score += token_score
            
        return score
