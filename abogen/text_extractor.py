from __future__ import annotations

import datetime
import logging
import mimetypes
import re
import textwrap
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, cast

import ebooklib  # type: ignore[import]
import fitz  # type: ignore[import]
import markdown  # type: ignore[import]
from bs4 import BeautifulSoup, NavigableString  # type: ignore[import]
from ebooklib import epub  # type: ignore[import]

from .utils import calculate_text_length, clean_text, detect_encoding

logger = logging.getLogger(__name__)

METADATA_PATTERN = re.compile(r"<<METADATA_([A-Z_]+):(.*?)>>", re.DOTALL)
CHAPTER_PATTERN = re.compile(r"<<CHAPTER_MARKER:(.*?)>>", re.IGNORECASE)
METADATA_KEY_MAP: Dict[str, str] = {
    "TITLE": "title",
    "ARTIST": "artist",
    "ALBUM": "album",
    "YEAR": "year",
    "ALBUM_ARTIST": "album_artist",
    "ALBUMARTIST": "album_artist",
    "COMPOSER": "composer",
    "GENRE": "genre",
    "DATE": "date",
    "PUBLISHER": "publisher",
    "COMMENT": "comment",
    "LANGUAGE": "language",
}


@dataclass
class ExtractedChapter:
    title: str
    text: str

    @property
    def characters(self) -> int:
        return calculate_text_length(self.text)


@dataclass
class ExtractionResult:
    chapters: List[ExtractedChapter]
    metadata: Dict[str, str] = field(default_factory=dict)
    cover_image: Optional[bytes] = None
    cover_mime: Optional[str] = None

    @property
    def combined_text(self) -> str:
        return "\n\n".join(chapter.text for chapter in self.chapters)

    @property
    def total_characters(self) -> int:
        return sum(chapter.characters for chapter in self.chapters)


@dataclass
class MetadataSource:
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    description: Optional[str] = None
    publisher: Optional[str] = None
    publication_year: Optional[str] = None
    language: Optional[str] = None
    series: Optional[str] = None
    series_index: Optional[str] = None


@dataclass
class NavEntry:
    src: str
    title: str
    doc_href: str
    position: int
    doc_order: int


def extract_from_path(path: Path) -> ExtractionResult:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return _extract_plaintext(path)
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix in {".md", ".markdown"}:
        return _extract_markdown(path)
    if suffix == ".epub":
        return _extract_epub(path)
    raise ValueError(f"Unsupported input type: {suffix}")


def _extract_plaintext(path: Path) -> ExtractionResult:
    encoding = detect_encoding(str(path))
    raw = path.read_text(encoding=encoding, errors="replace")
    return _extract_from_string(raw, default_title=path.stem)


def _extract_from_string(raw: str, default_title: str) -> ExtractionResult:
    raw_metadata, body = _strip_metadata(raw)
    chapters = _split_chapters(body, default_title)
    normalized_tags = _normalize_metadata_keys(raw_metadata)
    chapter_count = len(chapters)
    artist_value = normalized_tags.get("artist")
    authors = (
        [name.strip() for name in artist_value.split(",") if name.strip()]
        if artist_value
        else []
    )
    metadata_source = MetadataSource(
        title=normalized_tags.get("title") or default_title,
        authors=authors,
        publication_year=normalized_tags.get("year"),
    )
    metadata = _build_metadata_payload(
        metadata_source, chapter_count, "text", default_title
    )
    metadata.update(normalized_tags)
    if not chapters:
        chapters = [ExtractedChapter(title=default_title, text="")]
    return ExtractionResult(chapters=chapters, metadata=metadata)


def _strip_metadata(content: str) -> Tuple[Dict[str, str], str]:
    metadata: Dict[str, str] = {}

    def _replacer(match: re.Match) -> str:
        key = match.group(1).strip().upper()
        value = match.group(2).strip()
        if value:
            metadata[key] = value
        return ""

    stripped = METADATA_PATTERN.sub(_replacer, content)
    return metadata, stripped


def _split_chapters(content: str, default_title: str) -> List[ExtractedChapter]:
    matches = list(CHAPTER_PATTERN.finditer(content))
    if not matches:
        cleaned = clean_text(content)
        return [ExtractedChapter(title=default_title, text=cleaned)]

    chapters: List[ExtractedChapter] = []
    last_index = 0
    current_title = default_title

    for match in matches:
        segment = content[last_index : match.start()]
        if segment.strip():
            chapters.append(
                ExtractedChapter(title=current_title, text=clean_text(segment))
            )
        current_title = match.group(1).strip() or default_title
        last_index = match.end()

    tail = content[last_index:]
    if tail.strip():
        chapters.append(ExtractedChapter(title=current_title, text=clean_text(tail)))

    return chapters


def _normalize_metadata_keys(metadata: Dict[str, str]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for key, value in metadata.items():
        if not value:
            continue
        mapped = METADATA_KEY_MAP.get(key.upper(), key.lower())
        normalized[mapped] = value
    return normalized


def _build_metadata_payload(
    metadata_source: MetadataSource,
    chapter_count: int,
    file_type: str,
    default_title: str,
) -> Dict[str, str]:
    now_year = str(datetime.datetime.now().year)
    title = metadata_source.title.strip() if metadata_source.title else default_title
    if not title:
        title = default_title
    authors = [author for author in metadata_source.authors if author.strip()]
    if not authors:
        authors = ["Unknown"]
    authors_text = ", ".join(authors)
    if chapter_count <= 0:
        chapter_count = 1
    chapter_label = "Chapters" if file_type in {"epub", "markdown"} else "Pages"
    metadata = {
        "TITLE": title,
        "ARTIST": authors_text,
        "ALBUM": title,
        "YEAR": metadata_source.publication_year or now_year,
        "ALBUM_ARTIST": authors_text,
        "COMPOSER": authors_text,
        "GENRE": "Audiobook",
        "CHAPTER_COUNT": str(chapter_count),
    }
    if metadata_source.publisher:
        metadata["PUBLISHER"] = metadata_source.publisher
    if metadata_source.description:
        metadata["COMMENT"] = metadata_source.description
    if metadata_source.language:
        metadata["LANGUAGE"] = metadata_source.language
    normalized = _normalize_metadata_keys(metadata)
    # Ensure chapter_count survives normalization even if upstream metadata provided it
    normalized.setdefault("chapter_count", str(chapter_count))
    return normalized


def _extract_pdf(path: Path) -> ExtractionResult:
    metadata_source = MetadataSource()
    chapters: List[ExtractedChapter] = []
    with fitz.open(str(path)) as document:
        metadata_source = _collect_pdf_metadata(document)
        pages = cast(Iterable[fitz.Page], document)
        for index, page in enumerate(pages):
            page_obj = cast(Any, page)
            text = _clean_pdf_text(page_obj.get_text())
            if not text:
                continue
            title = f"Page {index + 1}"
            chapters.append(ExtractedChapter(title=title, text=text))
    if not chapters:
        chapters.append(ExtractedChapter(title=path.stem, text=""))
    metadata = _build_metadata_payload(metadata_source, len(chapters), "pdf", path.stem)
    return ExtractionResult(chapters=chapters, metadata=metadata)


def _collect_pdf_metadata(document: fitz.Document) -> MetadataSource:
    metadata = MetadataSource()
    info = document.metadata or {}
    if info.get("title"):
        metadata.title = info["title"]
    if info.get("author"):
        metadata.authors = [info["author"]]
    if info.get("subject"):
        metadata.description = info["subject"]
    if info.get("keywords"):
        keywords = info["keywords"]
        if metadata.description:
            metadata.description = f"{metadata.description}\n\nKeywords: {keywords}"
        else:
            metadata.description = f"Keywords: {keywords}"
    if info.get("creator"):
        metadata.publisher = info["creator"]
    for key in ("creationDate", "modDate"):
        value = info.get(key)
        if not value:
            continue
        match = re.search(r"D:(\d{4})", value)
        if match:
            metadata.publication_year = match.group(1)
            break
    return metadata


def _clean_pdf_text(text: str) -> str:
    cleaned = clean_text(text)
    cleaned = re.sub(r"\[\s*\d+\s*\]", "", cleaned)
    cleaned = re.sub(r"^\s*\d+\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s+\d+\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s+[-–—]\s*\d+\s*[-–—]?\s*$", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


def _extract_markdown(path: Path) -> ExtractionResult:
    encoding = detect_encoding(str(path))
    raw = path.read_text(encoding=encoding, errors="replace")
    metadata_source, chapters = _parse_markdown(raw, path.stem)
    if not chapters:
        chapters = [
            ExtractedChapter(
                title=metadata_source.title or path.stem, text=clean_text(raw)
            )
        ]
    metadata = _build_metadata_payload(
        metadata_source, len(chapters), "markdown", path.stem
    )
    return ExtractionResult(chapters=chapters, metadata=metadata)


def _parse_markdown(
    raw: str, default_title: str
) -> Tuple[MetadataSource, List[ExtractedChapter]]:
    metadata = MetadataSource()
    text = textwrap.dedent(raw)
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if frontmatter_match:
        frontmatter = frontmatter_match.group(1)
        _parse_markdown_frontmatter(frontmatter, metadata)
        text_body = text[frontmatter_match.end() :]
    else:
        text_body = text

    md = markdown.Markdown(extensions=["toc", "fenced_code"])
    html = md.convert(text_body)
    toc_tokens = getattr(md, "toc_tokens", None) or []

    if not toc_tokens:
        cleaned = clean_text(text_body)
        title = metadata.title or default_title
        chapters = [ExtractedChapter(title=title, text=cleaned)] if cleaned else []
        return metadata, chapters

    headers: List[dict] = []

    def _flatten_tokens(tokens):
        for token in tokens:
            headers.append(token)
            if token.get("children"):
                _flatten_tokens(token["children"])

    _flatten_tokens(toc_tokens)

    header_positions: List[Tuple[str, int, str]] = []
    for header in headers:
        header_id = header.get("id")
        if not header_id:
            continue
        id_pattern = f'id="{header_id}"'
        pos = html.find(id_pattern)
        if pos == -1:
            continue
        tag_start = html.rfind("<", 0, pos)
        name = str(header.get("name", header_id))
        header_positions.append((header_id, tag_start, name))

    header_positions.sort(key=lambda item: item[1])

    chapters: List[ExtractedChapter] = []
    for index, (header_id, start, name) in enumerate(header_positions):
        end = (
            header_positions[index + 1][1]
            if index + 1 < len(header_positions)
            else len(html)
        )
        section_html = html[start:end]
        section_soup = BeautifulSoup(section_html, "html.parser")
        header_tag = section_soup.find(attrs={"id": header_id})
        if header_tag:
            header_tag.decompose()
        section_text = clean_text(section_soup.get_text()).strip()
        if not section_text:
            continue
        chapters.append(ExtractedChapter(title=name.strip(), text=section_text))

    if not metadata.title:
        first_h1 = next(
            (
                header
                for header in headers
                if header.get("level") == 1 and header.get("name")
            ),
            None,
        )
        if first_h1:
            metadata.title = str(first_h1["name"])

    return metadata, chapters


def _parse_markdown_frontmatter(frontmatter: str, metadata: MetadataSource) -> None:
    title_match = re.search(
        r"^title:\s*(.+)$", frontmatter, re.MULTILINE | re.IGNORECASE
    )
    if title_match:
        metadata.title = title_match.group(1).strip().strip("\"'")

    author_match = re.search(
        r"^author:\s*(.+)$", frontmatter, re.MULTILINE | re.IGNORECASE
    )
    if author_match:
        metadata.authors = [author_match.group(1).strip().strip("\"'")]

    desc_match = re.search(
        r"^description:\s*(.+)$", frontmatter, re.MULTILINE | re.IGNORECASE
    )
    if desc_match:
        metadata.description = desc_match.group(1).strip().strip("\"'")

    date_match = re.search(r"^date:\s*(.+)$", frontmatter, re.MULTILINE | re.IGNORECASE)
    if date_match:
        date_str = date_match.group(1).strip().strip("\"'")
        year_match = re.search(r"\b(19|20)\d{2}\b", date_str)
        if year_match:
            metadata.publication_year = year_match.group(0)


def _extract_epub(path: Path) -> ExtractionResult:
    extractor = EpubExtractor(path)
    return extractor.extract()


class EpubExtractor:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.book = epub.read_epub(str(path))
        self.doc_content: Dict[str, str] = {}
        self.spine_docs: List[str] = []

    def extract(self) -> ExtractionResult:
        metadata_source = self._collect_metadata()
        try:
            chapters = self._process_nav()
        except Exception as exc:
            logger.warning(
                "EPUB navigation processing failed for %s: %s. Falling back to spine order.",
                self.path.name,
                exc,
                exc_info=True,
            )
            chapters = self._process_spine_fallback()
        if not chapters:
            chapters = [ExtractedChapter(title=self.path.stem, text="")]
        metadata = _build_metadata_payload(
            metadata_source, len(chapters), "epub", self.path.stem
        )
        metadata.setdefault("chapter_count", str(len(chapters)))
        if metadata_source.series:
            series_text = str(metadata_source.series).strip()
            if series_text:
                metadata.setdefault("series", series_text)
                metadata.setdefault("series_name", series_text)
                metadata.setdefault("seriesname", series_text)
        if metadata_source.series_index:
            idx_text = str(metadata_source.series_index).strip()
            if idx_text:
                metadata.setdefault("series_index", idx_text)
                metadata.setdefault("series_sequence", idx_text)
                metadata.setdefault("book_number", idx_text)
        cover_image, cover_mime = self._extract_cover()
        return ExtractionResult(
            chapters=chapters,
            metadata=metadata,
            cover_image=cover_image,
            cover_mime=cover_mime,
        )

    def _collect_metadata(self) -> MetadataSource:
        metadata = MetadataSource()
        try:
            title_items = self.book.get_metadata("DC", "title")
            if title_items:
                metadata.title = title_items[0][0]
        except Exception as exc:
            logger.debug("Failed to extract EPUB title metadata: %s", exc)

        try:
            author_items = self.book.get_metadata("DC", "creator")
            if author_items:
                metadata.authors = [
                    author[0] for author in author_items if author and author[0]
                ]
        except Exception as exc:
            logger.debug("Failed to extract EPUB author metadata: %s", exc)

        try:
            desc_items = self.book.get_metadata("DC", "description")
            if desc_items:
                metadata.description = desc_items[0][0]
        except Exception as exc:
            logger.debug("Failed to extract EPUB description metadata: %s", exc)

        try:
            publisher_items = self.book.get_metadata("DC", "publisher")
            if publisher_items:
                metadata.publisher = publisher_items[0][0]
        except Exception as exc:
            logger.debug("Failed to extract EPUB publisher metadata: %s", exc)

        try:
            date_items = self.book.get_metadata("DC", "date")
            if date_items:
                date_str = date_items[0][0]
                year_match = re.search(r"\b(19|20)\d{2}\b", date_str)
                metadata.publication_year = (
                    year_match.group(0) if year_match else date_str
                )
        except Exception as exc:
            logger.debug("Failed to extract EPUB publication year metadata: %s", exc)

        try:
            language_items = self.book.get_metadata("DC", "language")
            if language_items:
                metadata.language = language_items[0][0]
        except Exception as exc:
            logger.debug("Failed to extract EPUB language metadata: %s", exc)

        # Series metadata (best-effort). Common sources:
        # - Calibre embeds OPF meta tags: <meta name="calibre:series" content="..." />
        # - EPUB3 collections via: <meta property="belongs-to-collection">...</meta>
        try:
            meta_items = self.book.get_metadata("OPF", "meta")
        except Exception as exc:
            logger.debug("Failed to extract EPUB OPF meta tags: %s", exc)
            meta_items = []

        series_name: Optional[str] = None
        series_index: Optional[str] = None
        for value, attrs in meta_items or []:
            attrs_dict = attrs or {}
            name = str(attrs_dict.get("name") or "").strip().casefold()
            prop = str(attrs_dict.get("property") or "").strip().casefold()
            content = attrs_dict.get("content")
            candidate = content if content is not None else value
            candidate_text = str(candidate or "").strip()
            if not candidate_text:
                continue

            if name in {"calibre:series", "series"} and series_name is None:
                series_name = candidate_text
                continue
            if (
                name
                in {
                    "calibre:series_index",
                    "calibre:seriesindex",
                    "series_index",
                    "seriesindex",
                }
                and series_index is None
            ):
                series_index = candidate_text
                continue

            if prop.endswith("belongs-to-collection") and series_name is None:
                series_name = candidate_text
                continue

        metadata.series = series_name
        metadata.series_index = series_index

        return metadata

    def _extract_cover(self) -> Tuple[Optional[bytes], Optional[str]]:
        try:
            for item in self.book.get_items_of_type(ebooklib.ITEM_COVER):
                data = item.get_content()
                if data:
                    media_type = getattr(item, "media_type", None)
                    return data, media_type
        except Exception as exc:
            logger.debug("Failed to read dedicated EPUB cover image: %s", exc)

        try:
            for item in self.book.get_items_of_type(ebooklib.ITEM_IMAGE):
                name = item.get_name().lower()
                if "cover" not in name and "front" not in name:
                    continue
                data = item.get_content()
                if not data:
                    continue
                media_type = getattr(item, "media_type", None)
                if not media_type:
                    media_type = mimetypes.guess_type(name)[0]
                return data, media_type
        except Exception as exc:
            logger.debug("Failed to locate fallback EPUB cover image: %s", exc)

        return None, None

    def _process_nav(self) -> List[ExtractedChapter]:
        nav_item, nav_type = self._find_navigation_item()
        if not nav_item or not nav_type:
            raise ValueError("No navigation document found")

        parser_type = "html.parser" if nav_type == "html" else "xml"
        nav_content = nav_item.get_content().decode("utf-8", errors="ignore")
        nav_soup = BeautifulSoup(nav_content, parser_type)

        self.spine_docs = self._build_spine_docs()
        doc_order = {href: index for index, href in enumerate(self.spine_docs)}
        doc_order_decoded = {
            urllib.parse.unquote(href): index for href, index in doc_order.items()
        }

        nav_targets = self._collect_nav_targets(nav_soup, nav_type)
        self._cache_relevant_documents(doc_order, nav_targets)

        ordered_entries: List[NavEntry] = []
        if nav_type == "ncx":
            nav_map = nav_soup.find("navMap")
            if not nav_map:
                raise ValueError("NCX navigation missing <navMap>")
            for nav_point in nav_map.find_all("navPoint", recursive=False):
                self._parse_ncx_navpoint(
                    nav_point, ordered_entries, doc_order, doc_order_decoded
                )
        else:
            toc_nav = nav_soup.find("nav", attrs={"epub:type": "toc"})
            if toc_nav is None:
                for nav in nav_soup.find_all("nav"):
                    if nav.find("ol"):
                        toc_nav = nav
                        break
            if toc_nav is None:
                raise ValueError("NAV HTML missing TOC structure")
            top_ol = toc_nav.find("ol", recursive=False)
            if top_ol is None:
                raise ValueError("TOC navigation missing <ol>")
            for li in top_ol.find_all("li", recursive=False):
                self._parse_html_nav_li(
                    li, ordered_entries, doc_order, doc_order_decoded
                )

        if not ordered_entries:
            raise ValueError("No navigation entries found")

        ordered_entries.sort(key=lambda entry: (entry.doc_order, entry.position))
        chapters = self._slice_entries(ordered_entries)
        self._append_prefix_content(ordered_entries, chapters)
        return chapters

    def _process_spine_fallback(self) -> List[ExtractedChapter]:
        chapters: List[ExtractedChapter] = []
        self.spine_docs = self._build_spine_docs()
        self.doc_content = {}

        for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            href = item.get_name()
            if href not in self.spine_docs:
                continue
            try:
                html_content = item.get_content().decode("utf-8", errors="ignore")
            except Exception as exc:
                logger.error("Error decoding EPUB document %s: %s", href, exc)
                html_content = ""
            self.doc_content[href] = html_content

        for index, doc_href in enumerate(self.spine_docs):
            html_content = self.doc_content.get(doc_href, "")
            if not html_content:
                continue
            text = self._html_to_text(html_content)
            if not text:
                continue
            title = self._resolve_document_title(
                html_content, fallback=f"Untitled Chapter {index + 1}"
            )
            chapters.append(ExtractedChapter(title=title, text=text))
        return chapters

    def _find_navigation_item(self) -> Tuple[Optional[epub.EpubItem], Optional[str]]:
        nav_item: Optional[epub.EpubItem] = None
        nav_type: Optional[str] = None

        nav_items = list(self.book.get_items_of_type(ebooklib.ITEM_NAVIGATION))
        if nav_items:
            preferred = next(
                (
                    item
                    for item in nav_items
                    if "nav" in item.get_name().lower()
                    and item.get_name().lower().endswith((".xhtml", ".html"))
                ),
                None,
            )
            if preferred:
                nav_item = preferred
                nav_type = "html"
            else:
                html_nav = next(
                    (
                        item
                        for item in nav_items
                        if item.get_name().lower().endswith((".xhtml", ".html"))
                    ),
                    None,
                )
                if html_nav:
                    nav_item = html_nav
                    nav_type = "html"

        if not nav_item and nav_items:
            ncx_candidate = next(
                (
                    item
                    for item in nav_items
                    if item.get_name().lower().endswith(".ncx")
                ),
                None,
            )
            if ncx_candidate:
                nav_item = ncx_candidate
                nav_type = "ncx"

        if not nav_item:
            ncx_constant = getattr(epub, "ITEM_NCX", None)
            if ncx_constant is not None:
                ncx_items = list(self.book.get_items_of_type(ncx_constant))
                if ncx_items:
                    nav_item = ncx_items[0]
                    nav_type = "ncx"

        if not nav_item:
            for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                try:
                    html_content = item.get_content().decode("utf-8", errors="ignore")
                except Exception:
                    continue
                if "<nav" in html_content and 'epub:type="toc"' in html_content:
                    soup = BeautifulSoup(html_content, "html.parser")
                    if soup.find("nav", attrs={"epub:type": "toc"}):
                        nav_item = item
                        nav_type = "html"
                        break

        return nav_item, nav_type

    def _build_spine_docs(self) -> List[str]:
        docs: List[str] = []
        for spine_entry in self.book.spine:
            item_id = spine_entry[0]
            item = self.book.get_item_with_id(item_id)
            if item:
                docs.append(item.get_name())
        return docs

    def _collect_nav_targets(self, nav_soup: BeautifulSoup, nav_type: str) -> List[str]:
        targets: List[str] = []
        if nav_type == "ncx":
            for content_node in nav_soup.find_all("content"):
                src = content_node.get("src")
                if src:
                    src_value = str(src)
                    targets.append(src_value.split("#", 1)[0])
        else:
            for link in nav_soup.find_all("a"):
                href = link.get("href")
                if href:
                    href_value = str(href)
                    targets.append(href_value.split("#", 1)[0])
        return targets

    def _cache_relevant_documents(
        self, doc_order: Dict[str, int], nav_targets: List[str]
    ) -> None:
        needed: set[str] = set(doc_order.keys())
        for target in nav_targets:
            needed.add(target)
            needed.add(urllib.parse.unquote(target))

        self.doc_content = {}
        for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            href = item.get_name()
            if href not in needed and urllib.parse.unquote(href) not in needed:
                continue
            try:
                html_content = item.get_content().decode("utf-8", errors="ignore")
            except Exception as exc:
                logger.error("Error decoding EPUB document %s: %s", href, exc)
                html_content = ""
            self.doc_content[href] = html_content

    def _parse_ncx_navpoint(
        self,
        nav_point,
        ordered_entries: List[NavEntry],
        doc_order: Dict[str, int],
        doc_order_decoded: Dict[str, int],
    ) -> None:
        nav_label = nav_point.find("navLabel")
        content = nav_point.find("content")
        title = (
            nav_label.find("text").get_text(strip=True)
            if nav_label and nav_label.find("text")
            else "Untitled Section"
        )
        src = content.get("src") if content and content.has_attr("src") else None

        if src:
            base_href, fragment = src.split("#", 1) if "#" in src else (src, None)
            doc_key, doc_idx = self._find_doc_key(
                base_href, doc_order, doc_order_decoded
            )
            if doc_key is not None and doc_idx is not None:
                position = self._find_position_robust(doc_key, fragment)
                ordered_entries.append(
                    NavEntry(
                        src=src,
                        title=title,
                        doc_href=doc_key,
                        position=position,
                        doc_order=doc_idx,
                    )
                )
            else:
                logger.warning(
                    "Navigation entry '%s' points to '%s', which is not in the spine.",
                    title,
                    base_href,
                )

        for child_navpoint in nav_point.find_all("navPoint", recursive=False):
            self._parse_ncx_navpoint(
                child_navpoint, ordered_entries, doc_order, doc_order_decoded
            )

    def _parse_html_nav_li(
        self,
        li_element,
        ordered_entries: List[NavEntry],
        doc_order: Dict[str, int],
        doc_order_decoded: Dict[str, int],
    ) -> None:
        link = li_element.find("a", recursive=False)
        span_text = li_element.find("span", recursive=False)
        title = "Untitled Section"

        if link and link.has_attr("href"):
            src = link["href"]
            title = link.get_text(strip=True) or title
        else:
            src = None
            if span_text:
                title = span_text.get_text(strip=True) or title
            else:
                text = "".join(t for t in li_element.stripped_strings)
                if text:
                    title = text

        title = title.strip() or "Untitled Section"

        if src:
            base_href, fragment = src.split("#", 1) if "#" in src else (src, None)
            doc_key, doc_idx = self._find_doc_key(
                base_href, doc_order, doc_order_decoded
            )
            if doc_key is not None and doc_idx is not None:
                position = self._find_position_robust(doc_key, fragment)
                ordered_entries.append(
                    NavEntry(
                        src=src,
                        title=title,
                        doc_href=doc_key,
                        position=position,
                        doc_order=doc_idx,
                    )
                )
            else:
                logger.warning(
                    "Navigation entry '%s' points to '%s', which is not in the spine.",
                    title,
                    base_href,
                )

        for child_ol in li_element.find_all("ol", recursive=False):
            for child_li in child_ol.find_all("li", recursive=False):
                self._parse_html_nav_li(
                    child_li, ordered_entries, doc_order, doc_order_decoded
                )

    def _find_doc_key(
        self,
        base_href: str,
        doc_order: Dict[str, int],
        doc_order_decoded: Dict[str, int],
    ) -> Tuple[Optional[str], Optional[int]]:
        candidates = {base_href, urllib.parse.unquote(base_href)}
        base_name = urllib.parse.unquote(base_href).split("/")[-1].lower()
        for key in list(doc_order.keys()) + list(doc_order_decoded.keys()):
            if key.split("/")[-1].lower() == base_name:
                candidates.add(key)
        for candidate in candidates:
            if candidate in doc_order:
                return candidate, doc_order[candidate]
            if candidate in doc_order_decoded:
                return candidate, doc_order_decoded[candidate]
        return None, None

    def _find_position_robust(self, doc_href: str, fragment_id: Optional[str]) -> int:
        if doc_href not in self.doc_content:
            logger.warning("Document '%s' not found in cached EPUB content.", doc_href)
            return 0
        html_content = self.doc_content[doc_href]
        if not fragment_id:
            return 0

        try:
            temp_soup = BeautifulSoup(f"<div>{html_content}</div>", "html.parser")
            target_element = temp_soup.find(id=fragment_id)
            if target_element:
                tag_str = str(target_element)
                pos = html_content.find(tag_str[: min(len(tag_str), 200)])
                if pos != -1:
                    return pos
        except Exception:
            logger.debug(
                "BeautifulSoup failed to locate id '%s' in %s", fragment_id, doc_href
            )

        safe_fragment_id = re.escape(fragment_id)
        id_name_pattern = re.compile(
            f"<[^>]+(?:id|name)\\s*=\\s*[\"']{safe_fragment_id}[\"']",
            re.IGNORECASE,
        )
        match = id_name_pattern.search(html_content)
        if match:
            return match.start()

        id_pos = html_content.find(f'id="{fragment_id}"')
        name_pos = html_content.find(f'name="{fragment_id}"')
        candidates = [pos for pos in (id_pos, name_pos) if pos != -1]
        if candidates:
            pos = min(candidates)
            tag_start = html_content.rfind("<", 0, pos)
            return tag_start if tag_start != -1 else pos

        logger.warning(
            "Anchor '%s' not found in %s. Defaulting to start.", fragment_id, doc_href
        )
        return 0

    def _slice_entries(self, ordered_entries: List[NavEntry]) -> List[ExtractedChapter]:
        chapters: List[ExtractedChapter] = []
        for index, entry in enumerate(ordered_entries):
            next_entry = (
                ordered_entries[index + 1] if index + 1 < len(ordered_entries) else None
            )
            slice_html = self._slice_entry(entry, next_entry)
            text = self._html_to_text(slice_html)
            if not text:
                continue
            title = entry.title or "Untitled Section"
            chapters.append(ExtractedChapter(title=title, text=text))
        return chapters

    def _slice_entry(
        self,
        current_entry: NavEntry,
        next_entry: Optional[NavEntry],
    ) -> str:
        current_doc = current_entry.doc_href
        current_pos = current_entry.position
        current_html = self.doc_content.get(current_doc, "")
        if not current_html:
            return ""

        if next_entry and next_entry.doc_href == current_doc:
            return current_html[current_pos : next_entry.position]

        slice_html = current_html[current_pos:]
        if next_entry:
            docs_between = self._docs_between(current_doc, next_entry.doc_href)
            for doc_href in docs_between:
                slice_html += self.doc_content.get(doc_href, "")
            next_doc_html = self.doc_content.get(next_entry.doc_href, "")
            slice_html += next_doc_html[: next_entry.position]
        else:
            for doc_href in self._docs_between(current_doc, None):
                slice_html += self.doc_content.get(doc_href, "")

        if not slice_html.strip():
            logger.warning(
                "No content found for navigation source '%s'. Using full document fallback.",
                current_entry.src,
            )
            return current_html
        return slice_html

    def _docs_between(self, current_doc: str, next_doc: Optional[str]) -> List[str]:
        docs: List[str] = []
        try:
            current_idx = self.spine_docs.index(current_doc)
        except ValueError:
            return docs

        if next_doc is None:
            docs.extend(self.spine_docs[current_idx + 1 :])
            return docs

        try:
            next_idx = self.spine_docs.index(next_doc)
        except ValueError:
            return docs

        if current_idx < next_idx:
            docs.extend(self.spine_docs[current_idx + 1 : next_idx])
        elif current_idx > next_idx:
            docs.extend(self.spine_docs[current_idx + 1 :])
            docs.extend(self.spine_docs[:next_idx])
        return docs

    def _append_prefix_content(
        self,
        ordered_entries: List[NavEntry],
        chapters: List[ExtractedChapter],
    ) -> None:
        if not ordered_entries:
            return
        first_entry = ordered_entries[0]
        first_doc = first_entry.doc_href
        first_pos = first_entry.position
        if first_pos <= 0:
            return

        prefix_html = ""
        try:
            first_idx = self.spine_docs.index(first_doc)
        except ValueError:
            first_idx = -1

        if first_idx > 0:
            for doc_href in self.spine_docs[:first_idx]:
                prefix_html += self.doc_content.get(doc_href, "")
        prefix_html += self.doc_content.get(first_doc, "")[:first_pos]
        prefix_text = self._html_to_text(prefix_html)
        if prefix_text and (not chapters or prefix_text != chapters[0].text):
            chapters.insert(0, ExtractedChapter(title="Introduction", text=prefix_text))

    def _html_to_text(self, html: str) -> str:
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["p", "div"]):
            tag.append("\n\n")
        for ol in soup.find_all("ol"):
            start_attr = ol.get("start")
            try:
                start = int(str(start_attr)) if start_attr is not None else 1
            except (TypeError, ValueError):
                start = 1
            for idx, li in enumerate(ol.find_all("li", recursive=False)):
                number_text = f"{start + idx}) "
                existing = li.string
                if isinstance(existing, NavigableString):
                    existing.replace_with(NavigableString(number_text + str(existing)))
                else:
                    li.insert(0, NavigableString(number_text))
        for tag in soup.find_all(["sup", "sub"]):
            tag.decompose()
        text = clean_text(soup.get_text())
        return text.strip()

    def _resolve_document_title(self, html_content: str, fallback: str) -> str:
        soup = BeautifulSoup(html_content, "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        for heading_tag in ("h1", "h2", "h3"):
            heading = soup.find(heading_tag)
            if heading and heading.get_text(strip=True):
                return heading.get_text(strip=True)
        return fallback
