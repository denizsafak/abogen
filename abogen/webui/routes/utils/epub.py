import json
import math
import posixpath
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple
from xml.etree import ElementTree as ET

from abogen.webui.service import Job, JobStatus

def _coerce_path(value: Any) -> Optional[Path]:
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        candidate = Path(value)
        return candidate
    return None


def normalize_epub_path(base_dir: str, href: str) -> str:
    if not href:
        return ""
    sanitized = href.split("#", 1)[0].split("?", 1)[0].strip()
    sanitized = sanitized.replace("\\", "/")
    if not sanitized:
        return ""
    if sanitized.startswith("/"):
        sanitized = sanitized[1:]
        base_dir = ""
    normalized_base = base_dir.strip("/")
    sanitized_lower = sanitized.lower()
    if normalized_base:
        base_lower = normalized_base.lower()
        prefix = base_lower + "/"
        if sanitized_lower.startswith(prefix):
            remainder = sanitized[len(prefix):]
            if remainder.lower().startswith(prefix):
                sanitized = remainder
                sanitized_lower = sanitized.lower()
            base_dir = ""
        elif sanitized_lower == base_lower:
            base_dir = ""
    base = base_dir.strip("/")
    combined = posixpath.join(base, sanitized) if base else sanitized
    normalized = posixpath.normpath(combined)
    if normalized in {"", "."}:
        return ""
    normalized = normalized.replace("\\", "/")
    segments = [segment for segment in normalized.split("/") if segment and segment != "."]
    if not segments:
        return ""
    deduped: List[str] = []
    last_lower: Optional[str] = None
    for segment in segments:
        segment_lower = segment.lower()
        if last_lower == segment_lower:
            continue
        deduped.append(segment)
        last_lower = segment_lower
    normalized = "/".join(deduped)
    if normalized.startswith("../") or normalized == "..":
        return ""
    return normalized


def decode_text(payload: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "windows-1252"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", "ignore")


def coerce_positive_time(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric < 0:
        return None
    return numeric


def load_job_metadata(job: Job) -> Dict[str, Any]:
    result = getattr(job, "result", None)
    artifacts = getattr(result, "artifacts", None)
    if not isinstance(artifacts, Mapping):
        return {}
    metadata_ref = artifacts.get("metadata")
    if isinstance(metadata_ref, Path):
        metadata_path = metadata_ref
    elif isinstance(metadata_ref, str):
        metadata_path = Path(metadata_ref)
    else:
        return {}
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def resolve_book_title(job: Job, *metadata_sources: Mapping[str, Any]) -> str:
    for source in metadata_sources:
        if not isinstance(source, Mapping):
            continue
        for key in ("title", "book_title", "name", "album", "album_title"):
            value = source.get(key)
            if isinstance(value, str):
                candidate = value.strip()
                if candidate:
                    return candidate
    filename = job.original_filename or ""
    stem = Path(filename).stem if filename else ""
    return stem or filename


class _NavMapParser(HTMLParser):
    def __init__(self, base_dir: str) -> None:
        super().__init__()
        self._base_dir = base_dir
        self._in_nav = False
        self._nav_depth = 0
        self._current_href: Optional[str] = None
        self._buffer: List[str] = []
        self.links: Dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        if tag_lower == "nav":
            attributes = dict(attrs)
            nav_type = (attributes.get("epub:type") or attributes.get("type") or "").strip().lower()
            nav_role = (attributes.get("role") or "").strip().lower()
            type_tokens = {token.strip() for token in nav_type.split() if token}
            role_tokens = {token.strip() for token in nav_role.split() if token}
            if "toc" in type_tokens or "doc-toc" in role_tokens:
                self._in_nav = True
                self._nav_depth = 1
                return
            if self._in_nav:
                self._nav_depth += 1
            return
        if not self._in_nav:
            return
        if tag_lower == "a":
            attributes = dict(attrs)
            href = attributes.get("href") or ""
            normalized = normalize_epub_path(self._base_dir, href)
            if normalized:
                self._current_href = normalized
                self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower == "nav" and self._in_nav:
            self._nav_depth -= 1
            if self._nav_depth <= 0:
                self._in_nav = False
            return
        if not self._in_nav:
            return
        if tag_lower == "a" and self._current_href:
            text = "".join(self._buffer).strip()
            if text:
                self.links.setdefault(self._current_href, text)
            self._current_href = None
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_nav and self._current_href and data:
            self._buffer.append(data)


def parse_nav_document(payload: bytes, base_dir: str) -> Dict[str, str]:
    parser = _NavMapParser(base_dir)
    parser.feed(decode_text(payload))
    parser.close()
    return parser.links


def parse_ncx_document(payload: bytes, base_dir: str) -> Dict[str, str]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return {}
    nav_map: Dict[str, str] = {}
    for nav_point in root.findall(".//{*}navPoint"):
        content = nav_point.find(".//{*}content")
        if content is None:
            continue
        src = content.attrib.get("src", "")
        normalized = normalize_epub_path(base_dir, src)
        if not normalized:
            continue
        label_el = nav_point.find(".//{*}text")
        label = (label_el.text or "").strip() if label_el is not None and label_el.text else ""
        if not label:
            label = posixpath.basename(normalized) or f"Section {len(nav_map) + 1}"
        nav_map.setdefault(normalized, label)
    return nav_map


def extract_epub_chapters(epub_path: Path) -> List[Dict[str, str]]:
    chapters: List[Dict[str, str]] = []
    if not epub_path or not epub_path.exists():
        return chapters
    try:
        with zipfile.ZipFile(epub_path, "r") as archive:
            container_bytes = archive.read("META-INF/container.xml")
            container_root = ET.fromstring(container_bytes)
            rootfile = container_root.find(".//{*}rootfile")
            if rootfile is None:
                return chapters
            opf_path = (rootfile.attrib.get("full-path") or "").strip()
            if not opf_path:
                return chapters
            opf_dir = posixpath.dirname(opf_path)
            opf_bytes = archive.read(opf_path)
            opf_root = ET.fromstring(opf_bytes)

            manifest: Dict[str, Dict[str, str]] = {}
            for item in opf_root.findall(".//{*}manifest/{*}item"):
                item_id = item.attrib.get("id")
                href = item.attrib.get("href")
                if not item_id or not href:
                    continue
                manifest[item_id] = {
                    "href": normalize_epub_path(opf_dir, href),
                    "properties": item.attrib.get("properties", ""),
                    "media_type": item.attrib.get("media-type", ""),
                }

            spine_hrefs: List[str] = []
            nav_id: Optional[str] = None
            spine = opf_root.find(".//{*}spine")
            if spine is not None:
                nav_id = spine.attrib.get("toc")
                for itemref in spine.findall(".//{*}itemref"):
                    idref = itemref.attrib.get("idref")
                    if not idref:
                        continue
                    entry = manifest.get(idref)
                    if not entry:
                        continue
                    href = entry["href"]
                    if href and href not in spine_hrefs:
                        spine_hrefs.append(href)

            nav_href: Optional[str] = None
            for entry in manifest.values():
                properties = entry.get("properties") or ""
                if "nav" in {token.strip() for token in properties.split() if token}:
                    nav_href = entry["href"]
                    break
            if not nav_href and nav_id:
                toc_entry = manifest.get(nav_id)
                if toc_entry:
                    nav_href = toc_entry["href"]

            nav_titles: Dict[str, str] = {}
            if nav_href:
                nav_base = posixpath.dirname(nav_href)
                try:
                    nav_bytes = archive.read(nav_href)
                except KeyError:
                    nav_bytes = None
                if nav_bytes is not None:
                    if nav_href.lower().endswith(".ncx"):
                        nav_titles = parse_ncx_document(nav_bytes, nav_base)
                    else:
                        nav_titles = parse_nav_document(nav_bytes, nav_base)

            if not nav_titles and nav_id and nav_id in manifest:
                toc_entry = manifest[nav_id]
                nav_base = posixpath.dirname(toc_entry["href"])
                try:
                    nav_bytes = archive.read(toc_entry["href"])
                except KeyError:
                    nav_bytes = None
                if nav_bytes is not None:
                    nav_titles = parse_ncx_document(nav_bytes, nav_base)

            for index, href in enumerate(spine_hrefs, start=1):
                normalized = href
                if not normalized:
                    continue
                title = (
                    nav_titles.get(normalized)
                    or nav_titles.get(normalized.split("#", 1)[0])
                    or posixpath.basename(normalized)
                    or f"Chapter {index}"
                )
                chapters.append({"href": normalized, "title": title})

            if not chapters and nav_titles:
                for index, (href, title) in enumerate(nav_titles.items(), start=1):
                    normalized = href
                    if not normalized:
                        continue
                    label = title or posixpath.basename(normalized) or f"Chapter {index}"
                    chapters.append({"href": normalized, "title": label})

            return chapters
    except (FileNotFoundError, zipfile.BadZipFile, KeyError, ET.ParseError, UnicodeDecodeError):
        return []
    return chapters


def read_epub_bytes(epub_path: Path, raw_href: str) -> bytes:
    normalized = normalize_epub_path("", raw_href)
    if not normalized:
        raise ValueError("Invalid resource path")
    with zipfile.ZipFile(epub_path, "r") as archive:
        return archive.read(normalized)


def iter_job_result_paths(job: Job) -> List[Path]:
    result = getattr(job, "result", None)
    if result is None:
        return []
    resolved_seen: Set[Path] = set()
    collected: List[Path] = []

    def _remember(candidate: Optional[Path]) -> None:
        if not candidate:
            return
        try:
            resolved = candidate.resolve()
        except OSError:
            return
        if resolved in resolved_seen:
            return
        resolved_seen.add(resolved)
        collected.append(candidate)

    artifacts = getattr(result, "artifacts", None)
    if isinstance(artifacts, Mapping):
        for value in artifacts.values():
            candidate = _coerce_path(value)
            if candidate and candidate.exists() and candidate.is_file():
                _remember(candidate)

    for attr in ("audio_path", "epub_path"):
        candidate = _coerce_path(getattr(result, attr, None))
        if candidate and candidate.exists() and candidate.is_file():
            _remember(candidate)

    return collected


def iter_job_artifact_dirs(job: Job) -> List[Path]:
    result = getattr(job, "result", None)
    if result is None:
        return []
    artifacts = getattr(result, "artifacts", None)
    directories: List[Path] = []
    if isinstance(artifacts, Mapping):
        for value in artifacts.values():
            candidate = _coerce_path(value)
            if candidate and candidate.exists() and candidate.is_dir():
                directories.append(candidate)
    return directories


def normalize_suffixes(suffixes: Iterable[str]) -> List[str]:
    normalized: List[str] = []
    for suffix in suffixes:
        if not suffix:
            continue
        cleaned = suffix.lower().strip()
        if not cleaned:
            continue
        if not cleaned.startswith("."):
            cleaned = f".{cleaned.lstrip('.')}"
        normalized.append(cleaned)
    return normalized


def find_job_file(job: Job, suffixes: Iterable[str]) -> Optional[Path]:
    ordered_suffixes = normalize_suffixes(suffixes)
    if not ordered_suffixes:
        return None
    files = iter_job_result_paths(job)
    for suffix in ordered_suffixes:
        for candidate in files:
            if candidate.suffix.lower() == suffix:
                return candidate
    directories = iter_job_artifact_dirs(job)
    for suffix in ordered_suffixes:
        pattern = f"*{suffix}"
        for directory in directories:
            try:
                match = next((path for path in directory.rglob(pattern) if path.is_file()), None)
            except OSError:
                match = None
            if match:
                return match
    return None


def locate_job_epub(job: Job) -> Optional[Path]:
    path = find_job_file(job, [".epub"])
    if path:
        return path
    return None


def locate_job_m4b(job: Job) -> Optional[Path]:
    return find_job_file(job, [".m4b"])


def locate_job_audio(job: Job, preferred_suffixes: Optional[Iterable[str]] = None) -> Optional[Path]:
    suffix_order: List[str] = []
    if preferred_suffixes:
        suffix_order.extend(preferred_suffixes)
    suffix_order.extend([".m4b", ".mp3", ".flac", ".opus", ".ogg", ".m4a", ".wav"])
    path = find_job_file(job, suffix_order)
    if path:
        return path
    files = iter_job_result_paths(job)
    return files[0] if files else None


def job_download_flags(job: Job) -> Dict[str, bool]:
    if job.status != JobStatus.COMPLETED:
        return {"audio": False, "m4b": False, "epub3": False}
    return {
        "audio": locate_job_audio(job) is not None,
        "m4b": locate_job_m4b(job) is not None,
        "epub3": locate_job_epub(job) is not None,
    }
