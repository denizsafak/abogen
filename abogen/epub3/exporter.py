from __future__ import annotations

import html
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, Iterable, List, Optional, Pattern, Sequence, Tuple
import zipfile

from abogen.text_extractor import ExtractedChapter, ExtractionResult


@dataclass(slots=True)
class ChunkOverlay:
    id: str
    text: str
    original_text: Optional[str]
    start: Optional[float]
    end: Optional[float]
    speaker_id: str
    voice: Optional[str]
    level: Optional[str] = None
    group_id: Optional[str] = None


@dataclass(slots=True)
class ChapterDocument:
    index: int  # zero-based
    title: str
    xhtml_name: str
    smil_name: str
    chunks: List[ChunkOverlay]
    start: Optional[float]
    end: Optional[float]


class EPUB3PackageBuilder:
    """Constructs an EPUB 3 package with media overlays."""

    def __init__(
        self,
        *,
        output_path: Path,
        book_id: str,
        extraction: ExtractionResult,
        metadata_tags: Dict[str, Any],
        chapter_markers: Sequence[Dict[str, Any]],
        chunk_markers: Sequence[Dict[str, Any]],
        chunks: Iterable[Dict[str, Any]],
        audio_path: Path,
        speaker_mode: str = "single",
        cover_image_path: Optional[Path] = None,
        cover_image_mime: Optional[str] = None,
    ) -> None:
        self.output_path = output_path
        self.book_id = book_id or str(uuid.uuid4())
        self.extraction = extraction
        self.metadata_tags = _normalize_metadata(metadata_tags)
        self.chapter_markers = list(chapter_markers or [])
        self.chunk_markers = list(chunk_markers or [])
        self.chunks = list(chunks or [])
        self.audio_path = audio_path
        self.speaker_mode = speaker_mode or "single"
        self.cover_image_path = cover_image_path if cover_image_path and cover_image_path.exists() else None
        self.cover_image_mime = cover_image_mime

        self._combined_metadata = _combine_metadata(extraction.metadata, self.metadata_tags)
        self._title = self._combined_metadata.get("title") or self._fallback_title()
        self._authors = _split_authors(self._combined_metadata)
        self._language = self._determine_language()
        self._publisher = self._combined_metadata.get("publisher") or ""
        self._description = self._combined_metadata.get("comment")
        self._duration = _calculate_total_duration(self.chunk_markers, self.chapter_markers)
        self._modified = _utc_now_iso()

    def build(self) -> Path:
        if not self.audio_path or not self.audio_path.exists():
            raise FileNotFoundError(f"Audio asset missing: {self.audio_path}")

        chapter_documents = self._build_chapter_documents()

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            oebps = root / "OEBPS"
            text_dir = oebps / "text"
            smil_dir = oebps / "smil"
            audio_dir = oebps / "audio"
            image_dir = oebps / "images"
            stylesheet_dir = oebps / "styles"

            for directory in (oebps, text_dir, smil_dir, audio_dir, stylesheet_dir):
                directory.mkdir(parents=True, exist_ok=True)
            if self.cover_image_path:
                image_dir.mkdir(parents=True, exist_ok=True)

            _write_mimetype(root)
            _write_container_xml(root)

            audio_filename = self.audio_path.name
            embedded_audio = audio_dir / audio_filename
            shutil.copy2(self.audio_path, embedded_audio)

            if self.cover_image_path:
                shutil.copy2(self.cover_image_path, image_dir / self.cover_image_path.name)

            stylesheet_path = stylesheet_dir / "style.css"
            stylesheet_path.write_text(_DEFAULT_STYLESHEET, encoding="utf-8")

            for chapter in chapter_documents:
                chapter_path = text_dir / chapter.xhtml_name
                chapter_path.write_text(
                    self._render_chapter_xhtml(chapter),
                    encoding="utf-8",
                )
                smil_path = smil_dir / chapter.smil_name
                smil_path.write_text(
                    self._render_chapter_smil(chapter, f"audio/{audio_filename}"),
                    encoding="utf-8",
                )

            nav_path = oebps / "nav.xhtml"
            nav_path.write_text(self._render_nav(chapter_documents), encoding="utf-8")

            opf_path = oebps / "content.opf"
            opf_path.write_text(
                self._render_opf(
                    chapter_documents,
                    audio_filename,
                    has_cover=self.cover_image_path is not None,
                    stylesheet_path=stylesheet_path.relative_to(oebps),
                ),
                encoding="utf-8",
            )

            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(self.output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                # Ensure mimetype is the first entry and stored without compression
                mimetype_path = root / "mimetype"
                info = zipfile.ZipInfo("mimetype")
                info.compress_type = zipfile.ZIP_STORED
                archive.writestr(info, mimetype_path.read_bytes())

                for file_path in sorted(root.rglob("*")):
                    if file_path == mimetype_path or file_path.is_dir():
                        continue
                    archive.write(file_path, file_path.relative_to(root))

        return self.output_path

    # ------------------------------------------------------------------
    def _build_chapter_documents(self) -> List[ChapterDocument]:
        chunk_lookup = _build_chunk_lookup(self.chunks)
        markers_by_chapter = _group_markers_by_chapter(self.chunk_markers)
        chapter_meta = {int(entry.get("index", idx + 1)) - 1: dict(entry) for idx, entry in enumerate(self.chapter_markers)}

        documents: List[ChapterDocument] = []
        for chapter_index, chapter in enumerate(self.extraction.chapters):
            markers = markers_by_chapter.get(chapter_index, [])
            if not markers and chunk_lookup.by_chapter.get(chapter_index):
                markers = [
                    {
                        "id": item.get("id"),
                        "chapter_index": chapter_index,
                        "chunk_index": item.get("chunk_index"),
                        "start": None,
                        "end": None,
                        "speaker_id": item.get("speaker_id", "narrator"),
                        "voice": item.get("voice"),
                    }
                    for item in chunk_lookup.by_chapter.get(chapter_index, [])
                ]

            if not markers:
                markers = [
                    {
                        "id": f"chap{chapter_index:04d}_auto0000",
                        "chapter_index": chapter_index,
                        "chunk_index": 0,
                        "start": chapter_meta.get(chapter_index, {}).get("start"),
                        "end": chapter_meta.get(chapter_index, {}).get("end"),
                        "speaker_id": "narrator",
                        "voice": None,
                    }
                ]

            overlays = self._build_overlays_for_chapter(
                chapter_index,
                markers,
                chunk_lookup,
            )

            xhtml_name = f"chapter_{chapter_index + 1:04d}.xhtml"
            smil_name = f"chapter_{chapter_index + 1:04d}.smil"

            chapter_start = chapter_meta.get(chapter_index, {}).get("start")
            chapter_end = chapter_meta.get(chapter_index, {}).get("end")

            documents.append(
                ChapterDocument(
                    index=chapter_index,
                    title=chapter.title or f"Chapter {chapter_index + 1}",
                    xhtml_name=xhtml_name,
                    smil_name=smil_name,
                    chunks=overlays,
                    start=chapter_start,
                    end=chapter_end,
                )
            )

        return documents

    def _build_overlays_for_chapter(
        self,
        chapter_index: int,
        markers: Sequence[Dict[str, Any]],
        chunk_lookup: "ChunkLookup",
    ) -> List[ChunkOverlay]:
        overlays: List[ChunkOverlay] = []
        used_ids: set[str] = set()

        chapter_chunks = list(chunk_lookup.by_chapter.get(chapter_index, []))
        chapter_chunks.sort(key=lambda entry: _safe_int(entry.get("chunk_index")))

        for position, marker in enumerate(markers):
            chunk_id = marker.get("id")
            chunk_entry = None
            if chunk_id and chunk_id in chunk_lookup.by_id:
                chunk_entry = chunk_lookup.by_id[chunk_id]
            else:
                candidate_index = _safe_int(marker.get("chunk_index"))
                chunk_entry = _find_chunk_by_index(chapter_chunks, candidate_index)
                if chunk_entry is None and chapter_chunks and position < len(chapter_chunks):
                    chunk_entry = chapter_chunks[position]

            level = None
            if chunk_entry is None:
                text = self.extraction.chapters[chapter_index].text
                speaker_id = str(marker.get("speaker_id") or "narrator")
                voice = marker.get("voice")
            else:
                display_text = chunk_entry.get("display_text")
                text = str(chunk_entry.get("text") or "")
                speaker_id = str(chunk_entry.get("speaker_id") or marker.get("speaker_id") or "narrator")
                voice = chunk_entry.get("voice") or chunk_entry.get("resolved_voice") or marker.get("voice")
                level = chunk_entry.get("level") or None
            if chunk_entry is None:
                level = None

            normalized_id = _normalize_chunk_id(chunk_id) if chunk_id else None
            if not normalized_id:
                normalized_id = f"chap{chapter_index:04d}_chunk{position:04d}"
            while normalized_id in used_ids:
                normalized_id = f"{normalized_id}_dup"
            used_ids.add(normalized_id)

            raw_group_key = chunk_entry.get("id") if chunk_entry else chunk_id
            group_id = _derive_group_id(raw_group_key, level)
            normalized_group_id = _normalize_chunk_id(group_id) if group_id else None

            original_text = None
            if chunk_entry is not None:
                original_text = chunk_entry.get("original_text") or chunk_entry.get("display_text")

            overlays.append(
                ChunkOverlay(
                    id=normalized_id,
                    text=text or self.extraction.chapters[chapter_index].text,
                    original_text=str(original_text) if original_text is not None else None,
                    start=_safe_float(marker.get("start")),
                    end=_safe_float(marker.get("end")),
                    speaker_id=speaker_id,
                    voice=str(voice) if voice else None,
                    level=str(level) if level else None,
                    group_id=normalized_group_id,
                )
            )

        chapter_text = ""
        if 0 <= chapter_index < len(self.extraction.chapters):
            chapter_entry = self.extraction.chapters[chapter_index]
            chapter_text = getattr(chapter_entry, "text", "") or ""

        _restore_original_chunk_text(chapter_text, overlays)

        return overlays

    def _render_chapter_xhtml(self, chapter: ChapterDocument) -> str:
        language = html.escape(self._language or "en")
        title = html.escape(chapter.title)
        grouped_chunks = _group_chunks_for_render(chapter.chunks)
        chunk_html = "\n".join(
            _render_chunk_group_html(group_id, items) for group_id, items in grouped_chunks
        )
        if not chunk_html:
            chunk_html = "<p></p>"
        original_block = ""
        if chapter.chunks:
            original_text = "".join((chunk.original_text if chunk.original_text is not None else (chunk.text or "")) for chunk in chapter.chunks)
            if original_text:
                safe_original = html.escape(original_text)
                original_block = (
                    "      <pre class=\"chapter-original\" hidden=\"hidden\" aria-hidden=\"true\">\n"
                    f"{safe_original}\n"
                    "      </pre>"
                )

        return (
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
            "<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\" xml:lang=\"{lang}\" lang=\"{lang}\">\n"
            "  <head>\n"
            "    <title>{title}</title>\n"
            "    <meta charset=\"utf-8\"/>\n"
            "    <link rel=\"stylesheet\" type=\"text/css\" href=\"styles/style.css\"/>\n"
            "  </head>\n"
            "  <body>\n"
            "    <section epub:type=\"chapter\" id=\"chapter-{index:04d}\">\n"
            "      <h1>{title}</h1>\n"
            "      {chunks}\n"
            "{original_block}"
            "    </section>\n"
            "  </body>\n"
            "</html>\n"
        ).format(
            lang=language,
            title=title,
            index=chapter.index + 1,
            chunks=chunk_html,
            original_block=("" if not original_block else f"{original_block}\n"),
        )

    def _render_chapter_smil(self, chapter: ChapterDocument, audio_href: str) -> str:
        par_lines = []
        for chunk in chapter.chunks:
            par_lines.append(
                "      <par id=\"par-{chunk_id}\">\n"
                "        <text src=\"text/{xhtml}#{chunk_id}\"/>\n"
                "        <audio src=\"{audio}\" clipBegin=\"{start}\" clipEnd=\"{end}\"/>\n"
                "      </par>".format(
                    chunk_id=html.escape(chunk.id),
                    xhtml=html.escape(chapter.xhtml_name),
                    audio=html.escape(audio_href),
                    start=_format_smil_time(chunk.start),
                    end=_format_smil_time(chunk.end),
                )
            )

        return (
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
            "<smil xmlns=\"http://www.w3.org/2001/SMIL20/Language\" xmlns:epub=\"http://www.idpf.org/2007/ops\">\n"
            "  <head>\n"
            "    <meta name=\"dc:title\" content=\"{title}\"/>\n"
            "    <meta name=\"dtb:uid\" content=\"{book_id}\"/>\n"
            "    <meta name=\"dtb:generator\" content=\"Abogen\"/>\n"
            "  </head>\n"
            "  <body>\n"
            "    <seq id=\"seq-{index:04d}\" epub:textref=\"text/{xhtml}\">\n"
            "{pars}\n"
            "    </seq>\n"
            "  </body>\n"
            "</smil>\n"
        ).format(
            title=html.escape(chapter.title),
            book_id=html.escape(self.book_id),
            index=chapter.index + 1,
            xhtml=html.escape(chapter.xhtml_name),
            pars="\n".join(par_lines) if par_lines else "      <par/>",
        )

    def _render_nav(self, chapters: Sequence[ChapterDocument]) -> str:
        items = []
        for chapter in chapters:
            href = f"text/{chapter.xhtml_name}"
            items.append(
                "        <li><a href=\"{href}\">{title}</a></li>".format(
                    href=html.escape(href),
                    title=html.escape(chapter.title),
                )
            )

        return (
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
            "<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\" xml:lang=\"{lang}\">\n"
            "  <head>\n"
            "    <title>Navigation</title>\n"
            "    <meta charset=\"utf-8\"/>\n"
            "  </head>\n"
            "  <body>\n"
            "    <nav epub:type=\"toc\" id=\"toc\">\n"
            "      <h1>{title}</h1>\n"
            "      <ol>\n"
            "{items}\n"
            "      </ol>\n"
            "    </nav>\n"
            "  </body>\n"
            "</html>\n"
        ).format(
            lang=html.escape(self._language or "en"),
            title=html.escape(self._title),
            items="\n".join(items) if items else "        <li><a href=\"text/chapter_0001.xhtml\">Chapter 1</a></li>",
        )

    def _render_opf(
        self,
        chapters: Sequence[ChapterDocument],
        audio_filename: str,
        *,
        has_cover: bool,
        stylesheet_path: Path,
    ) -> str:
        manifest_items = []
        spine_refs = []
        for chapter in chapters:
            item_id = f"chap{chapter.index + 1:04d}"
            overlay_id = f"mo-{chapter.index + 1:04d}"
            manifest_items.append(
                "    <item id=\"{item_id}\" href=\"text/{href}\" media-type=\"application/xhtml+xml\" media-overlay=\"{overlay_id}\"/>".format(
                    item_id=item_id,
                    href=html.escape(chapter.xhtml_name),
                    overlay_id=overlay_id,
                )
            )
            manifest_items.append(
                "    <item id=\"{overlay_id}\" href=\"smil/{smil}\" media-type=\"application/smil+xml\"/>".format(
                    overlay_id=overlay_id,
                    smil=html.escape(chapter.smil_name),
                )
            )
            spine_refs.append(f"    <itemref idref=\"{item_id}\"/>")

        audio_item_id = "primary-audio"
        manifest_items.append(
            "    <item id=\"{item_id}\" href=\"audio/{href}\" media-type=\"{mime}\"/>".format(
                item_id=audio_item_id,
                href=html.escape(audio_filename),
                mime=_detect_audio_mime(audio_filename),
            )
        )

        manifest_items.append(
            "    <item id=\"nav\" href=\"nav.xhtml\" media-type=\"application/xhtml+xml\" properties=\"nav\"/>"
        )

        manifest_items.append(
            "    <item id=\"style\" href=\"{href}\" media-type=\"text/css\"/>".format(
                href=html.escape(str(stylesheet_path).replace("\\", "/")),
            )
        )

        if has_cover and self.cover_image_path:
            cover_id = "cover-image"
            manifest_items.append(
                "    <item id=\"{item_id}\" href=\"images/{href}\" media-type=\"{mime}\" properties=\"cover-image\"/>".format(
                    item_id=cover_id,
                    href=html.escape(self.cover_image_path.name),
                    mime=self.cover_image_mime or _detect_image_mime(self.cover_image_path.suffix),
                )
            )

        metadata_elements = _render_metadata_xml(
            self._title,
            self._authors,
            self._language,
            self.book_id,
            duration=self._duration,
            publisher=self._publisher,
            description=self._description,
            speaker_mode=self.speaker_mode,
            modified=self._modified,
        )

        return (
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
            "<package xmlns=\"http://www.idpf.org/2007/opf\" version=\"3.0\" unique-identifier=\"book-id\">\n"
            "  <metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:opf=\"http://www.idpf.org/2007/opf\" xmlns:media=\"http://www.idpf.org/epub/vocab/mediaoverlays/#\" xmlns:abogen=\"https://abogen.app/ns#\" xmlns:dcterms=\"http://purl.org/dc/terms/\">\n"
            "{metadata}\n"
            "  </metadata>\n"
            "  <manifest>\n"
            "{manifest}\n"
            "  </manifest>\n"
            "  <spine>\n"
            "{spine}\n"
            "  </spine>\n"
            "</package>\n"
        ).format(
            metadata="\n".join(metadata_elements),
            manifest="\n".join(manifest_items),
            spine="\n".join(spine_refs) if spine_refs else "    <itemref idref=\"chap0001\"/>",
        )

    def _fallback_title(self) -> str:
        if self.extraction.chapters:
            first_title = self.extraction.chapters[0].title
            if first_title:
                return first_title
        return "Generated Audiobook"

    def _determine_language(self) -> str:
        language = self._combined_metadata.get("language")
        if language:
            return language
        return "en"


def build_epub3_package(
    *,
    output_path: Path,
    book_id: str,
    extraction: ExtractionResult,
    metadata_tags: Dict[str, Any],
    chapter_markers: Sequence[Dict[str, Any]],
    chunk_markers: Sequence[Dict[str, Any]],
    chunks: Iterable[Dict[str, Any]],
    audio_path: Path,
    speaker_mode: str = "single",
    cover_image_path: Optional[Path] = None,
    cover_image_mime: Optional[str] = None,
) -> Path:
    builder = EPUB3PackageBuilder(
        output_path=output_path,
        book_id=book_id,
        extraction=extraction,
        metadata_tags=metadata_tags,
        chapter_markers=chapter_markers,
        chunk_markers=chunk_markers,
        chunks=chunks,
        audio_path=audio_path,
        speaker_mode=speaker_mode,
        cover_image_path=cover_image_path,
        cover_image_mime=cover_image_mime,
    )
    return builder.build()


# ---------------------------------------------------------------------------
# Helpers


@dataclass
class ChunkLookup:
    by_id: Dict[str, Dict[str, Any]]
    by_chapter: Dict[int, List[Dict[str, Any]]]


def _normalize_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for key, value in (metadata or {}).items():
        if value is None:
            continue
        normalized[str(key).lower()] = str(value)
    return normalized


def _combine_metadata(*sources: Dict[str, Any]) -> Dict[str, str]:
    combined: Dict[str, str] = {}
    for source in sources:
        for key, value in (source or {}).items():
            if value is None:
                continue
            combined[str(key).lower()] = str(value)
    return combined


def _split_authors(metadata: Dict[str, str]) -> List[str]:
    candidates = []
    for key in ("artist", "author", "authors", "album_artist", "creator"):
        value = metadata.get(key)
        if value:
            candidates.extend(part.strip() for part in value.replace(";", ",").split(","))
    return [author for author in candidates if author]


def _calculate_total_duration(
    chunk_markers: Sequence[Dict[str, Any]],
    chapter_markers: Sequence[Dict[str, Any]],
) -> Optional[float]:
    candidates: List[float] = []
    for marker in chunk_markers or []:
        end_value = _safe_float(marker.get("end"))
        if end_value is not None:
            candidates.append(end_value)
    for marker in chapter_markers or []:
        end_value = _safe_float(marker.get("end"))
        if end_value is not None:
            candidates.append(end_value)
    if not candidates:
        return None
    return max(candidates)


def _write_mimetype(root: Path) -> None:
    (root / "mimetype").write_text("application/epub+zip", encoding="utf-8")


def _write_container_xml(root: Path) -> None:
    meta_inf = root / "META-INF"
    meta_inf.mkdir(parents=True, exist_ok=True)
    container = meta_inf / "container.xml"
    container.write_text(
        (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<container version=\"1.0\" xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\">\n"
            "  <rootfiles>\n"
            "    <rootfile full-path=\"OEBPS/content.opf\" media-type=\"application/oebps-package+xml\"/>\n"
            "  </rootfiles>\n"
            "</container>\n"
        ),
        encoding="utf-8",
    )


def _build_chunk_lookup(chunks: Iterable[Dict[str, Any]]) -> ChunkLookup:
    by_id: Dict[str, Dict[str, Any]] = {}
    by_chapter: Dict[int, List[Dict[str, Any]]] = {}
    for entry in chunks or []:
        if not isinstance(entry, dict):
            continue
        chunk_id = entry.get("id")
        if chunk_id:
            by_id[str(chunk_id)] = dict(entry)
        chapter_index = _safe_int(entry.get("chapter_index"))
        by_chapter.setdefault(chapter_index, []).append(dict(entry))
    return ChunkLookup(by_id=by_id, by_chapter=by_chapter)


def _group_markers_by_chapter(markers: Iterable[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for entry in markers or []:
        if not isinstance(entry, dict):
            continue
        chapter_index = _safe_int(entry.get("chapter_index"))
        grouped.setdefault(chapter_index, []).append(dict(entry))
    for chapter_index, items in grouped.items():
        items.sort(key=lambda payload: (_safe_int(payload.get("chunk_index")), _safe_float(payload.get("start")) or 0.0))
    return grouped


def _find_chunk_by_index(
    chapter_chunks: Sequence[Dict[str, Any]],
    chunk_index: Optional[int],
) -> Optional[Dict[str, Any]]:
    if chunk_index is None:
        return None
    for entry in chapter_chunks:
        if _safe_int(entry.get("chunk_index")) == chunk_index:
            return entry
    return None


def _normalize_chunk_id(chunk_id: Optional[Any]) -> Optional[str]:
    if chunk_id is None:
        return None
    text = str(chunk_id).strip()
    if not text:
        return None
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text)
    return safe[:120]


def _derive_group_id(chunk_id: Optional[Any], level: Optional[Any]) -> Optional[str]:
    if chunk_id is None:
        return None
    text = str(chunk_id).strip()
    if not text:
        return None
    if str(level or "").lower() == "sentence":
        match = re.match(r"(.+?)_s\d+(?:_.*)?$", text)
        if match:
            return match.group(1)
    return text


def _group_chunks_for_render(chunks: Sequence[ChunkOverlay]) -> List[Tuple[Optional[str], List[ChunkOverlay]]]:
    groups: List[Tuple[Optional[str], List[ChunkOverlay]]] = []
    current_key: Optional[str] = None
    current_items: List[ChunkOverlay] = []

    for chunk in chunks:
        key = chunk.group_id or chunk.id
        if current_items and key != current_key:
            groups.append((current_key, current_items))
            current_items = []
        if not current_items:
            current_key = key
        current_items.append(chunk)

    if current_items:
        groups.append((current_key, current_items))

    return groups


def _render_chunk_inline(chunk: ChunkOverlay) -> str:
    escaped_id = html.escape(chunk.id)
    speaker_attr = f" data-speaker=\"{html.escape(chunk.speaker_id)}\"" if chunk.speaker_id else ""
    voice_attr = f" data-voice=\"{html.escape(chunk.voice)}\"" if chunk.voice else ""
    level_attr = f" data-level=\"{html.escape(chunk.level)}\"" if chunk.level else ""
    raw_text = chunk.text or ""
    escaped_text = html.escape(raw_text)
    if not escaped_text:
        escaped_text = "&nbsp;"
    return (
        f"<span class=\"chunk\" id=\"{escaped_id}\"{speaker_attr}{voice_attr}{level_attr}>"
        f"{escaped_text}"
        "</span>"
    )


def _render_chunk_group_html(group_id: Optional[str], chunks: Sequence[ChunkOverlay]) -> str:
    if not chunks:
        return ""
    group_attr = f" data-group=\"{html.escape(group_id)}\"" if group_id else ""
    inline_html = "".join(_render_chunk_inline(chunk) for chunk in chunks)
    if not inline_html:
        inline_html = "&nbsp;"
    return f"      <p class=\"chunk-group\"{group_attr}>{inline_html}</p>"


def _format_smil_time(value: Optional[float]) -> str:
    if value is None or value < 0:
        value = 0.0
    total_ms = int(round(value * 1000))
    hours, remainder = divmod(total_ms, 3600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _restore_original_chunk_text(chapter_text: str, overlays: List[ChunkOverlay]) -> None:
    if not chapter_text or not overlays:
        return

    cursor = 0
    for chunk in overlays:
        if chunk.original_text is not None:
            prepared = _prepare_display_text(chunk.original_text)
            chunk.text = prepared
            continue
        candidate = chunk.text or ""
        if not candidate:
            continue
        match = _search_original_span(chapter_text, candidate, cursor)
        if match is None and cursor:
            match = _search_original_span(chapter_text, candidate, 0)
        if match is None:
            if chunk.original_text is None:
                chunk.original_text = chunk.text
            chunk.text = _prepare_display_text(chunk.text or "")
            continue
        start, end = match
        segment = chapter_text[start:end]
        chunk.original_text = segment
        chunk.text = _prepare_display_text(segment)
        cursor = end


def _prepare_display_text(value: str) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"(?:[ \t]*\r?\n)+\Z", "", value)
    return cleaned if cleaned else ""


def _search_original_span(source: str, normalized: str, start: int) -> Optional[Tuple[int, int]]:
    if not normalized:
        return None
    pattern = _build_chunk_pattern(normalized)
    match = pattern.search(source, start)
    if not match:
        return None
    return match.start(1), match.end(1)


_CHUNK_REGEX_CACHE: Dict[str, Pattern[str]] = {}


def _build_chunk_pattern(text: str) -> Pattern[str]:
    cached = _CHUNK_REGEX_CACHE.get(text)
    if cached is not None:
        return cached
    escaped = re.escape(text)
    escaped = escaped.replace(r"\ ", r"\s+")
    pattern = re.compile(r"(\s*" + escaped + r"\s*)", re.DOTALL)
    _CHUNK_REGEX_CACHE[text] = pattern
    return pattern


def _render_metadata_xml(
    title: str,
    authors: Sequence[str],
    language: str,
    book_id: str,
    *,
    duration: Optional[float],
    publisher: Optional[str],
    description: Optional[str],
    speaker_mode: Optional[str],
    modified: Optional[str],
) -> List[str]:
    elements = [
        f"    <dc:identifier id=\"book-id\">{html.escape(book_id)}</dc:identifier>",
        f"    <dc:title>{html.escape(title)}</dc:title>",
        f"    <dc:language>{html.escape(language or 'en')}</dc:language>",
    ]

    for author in authors or ["Unknown"]:
        elements.append(f"    <dc:creator>{html.escape(author)}</dc:creator>")

    if publisher:
        elements.append(f"    <dc:publisher>{html.escape(publisher)}</dc:publisher>")

    if description:
        elements.append(f"    <dc:description>{html.escape(description)}</dc:description>")

    if duration is not None:
        elements.append(f"    <meta property=\"media:duration\">{_format_iso_duration(duration)}</meta>")

    if speaker_mode:
        elements.append(
            "    <meta property=\"abogen:speakerMode\">{}</meta>".format(
                html.escape(str(speaker_mode))
            )
        )

    if modified:
        elements.append(f"    <meta property=\"dcterms:modified\">{html.escape(modified)}</meta>")
    return elements


def _format_iso_duration(value: float) -> str:
    total_seconds = int(value)
    remainder = value - total_seconds
    hours, remainder_seconds = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder_seconds, 60)
    seconds_with_fraction = seconds + remainder
    if seconds_with_fraction.is_integer():
        seconds_text = f"{int(seconds_with_fraction)}"
    else:
        seconds_text = f"{seconds_with_fraction:.3f}".rstrip("0").rstrip(".")
    return f"PT{hours}H{minutes}M{seconds_text}S"


def _detect_audio_mime(audio_filename: str) -> str:
    suffix = Path(audio_filename).suffix.lower()
    return {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".m4b": "audio/mp4",
        ".aac": "audio/aac",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
    }.get(suffix, "audio/mpeg")


def _detect_image_mime(suffix: str) -> str:
    normalized = suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(normalized, "image/jpeg")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_DEFAULT_STYLESHEET = """
body {
  font-family: 'Georgia', serif;
  line-height: 1.6;
  margin: 1.5em;
}

h1 {
  font-size: 1.5em;
  margin-bottom: 0.5em;
}

.chunk-group {
    margin: 0.5em 0;
}

.chunk-group .chunk {
    white-space: pre-wrap;
}
"""
