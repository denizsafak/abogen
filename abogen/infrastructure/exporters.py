from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Mapping, Sequence

import static_ffmpeg

from abogen.domain.metadata_helpers import (
    normalize_metadata_casefold,
    split_people_field,
    split_simple_list,
    first_nonempty,
    extract_year,
    normalize_series_sequence,
    build_audiobookshelf_metadata as _build_abs_metadata,
    load_audiobookshelf_chapters as _load_abs_chapters,
    _SERIES_SEQUENCE_TAG_KEYS,
)
from abogen.epub3.exporter import build_epub3_package
from abogen.integrations.audiobookshelf import (
    AudiobookshelfClient,
    AudiobookshelfConfig,
    AudiobookshelfUploadError,
)
from abogen.utils import create_process

logger = logging.getLogger(__name__)


@dataclass
class ExportConfig:
    """Configuration for export operations."""
    ffmpeg_path: str = "ffmpeg"
    verify_ssl: bool = True


class ExportService:
    """Unified service for audiobook exports (M4B, FFMETADATA, EPUB3, Audiobookshelf)."""
    
    def __init__(self, config: Optional[ExportConfig] = None):
        self.config = config or ExportConfig()
        static_ffmpeg.add_paths()
    
    # ----------------------------------------------------------------------
    # FFMETADATA
    # ----------------------------------------------------------------------
    
    def render_ffmetadata(
        self,
        metadata: Dict[str, Any],
        chapters: List[Dict[str, Any]],
    ) -> str:
        """Render FFMETADATA content."""
        lines = [";FFMETADATA1"]
        
        for key, value in (metadata or {}).items():
            if value is None:
                continue
            key_str = str(key).strip()
            if not key_str:
                continue
            lines.append(f"{key_str}={self._escape_ffmetadata_value(value)}")
        
        for chapter in chapters or []:
            start = chapter.get("start")
            end = chapter.get("end")
            if start is None or end is None:
                continue
            try:
                start_ms = max(0, int(round(float(start) * 1000)))
                end_ms = int(round(float(end) * 1000))
            except (TypeError, ValueError):
                continue
            if end_ms <= start_ms:
                end_ms = start_ms + 1
            lines.append("[CHAPTER]")
            lines.append("TIMEBASE=1/1000")
            lines.append(f"START={start_ms}")
            lines.append(f"END={end_ms}")
            title = chapter.get("title")
            if title:
                lines.append(f"title={self._escape_ffmetadata_value(title)}")
            voice = chapter.get("voice")
            if voice:
                lines.append(f"voice={self._escape_ffmetadata_value(voice)}")
        
        return "\n".join(lines) + "\n"
    
    @staticmethod
    def _escape_ffmetadata_value(value: Any) -> str:
        escaped = str(value).replace("\\", "\\\\").replace("\n", "\\n")
        escaped = escaped.replace("=", "\\=").replace(";", "\\;").replace("#", "\\#")
        return escaped
    
    def write_ffmetadata_file(
        self,
        audio_path: Path,
        metadata: Dict[str, Any],
        chapters: List[Dict[str, Any]],
    ) -> Optional[Path]:
        """Write FFMETADATA file to temp location."""
        content = self.render_ffmetadata(metadata, chapters)
        if content.strip() == ";FFMETADATA1":
            return None
        
        directory = audio_path.parent if audio_path.parent.exists() else Path(tempfile.gettempdir())
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".ffmeta",
            delete=False,
            dir=str(directory),
        ) as handle:
            handle.write(content)
            return Path(handle.name)
    
    # ----------------------------------------------------------------------
    # M4B Export
    # ----------------------------------------------------------------------
    
    def embed_m4b_metadata(
        self,
        audio_path: Path,
        metadata: Dict[str, Any],
        chapters: List[Dict[str, Any]],
        cover_path: Optional[Path] = None,
        cover_mime: Optional[str] = None,
        log_callback: Optional[callable] = None,
    ) -> None:
        """Embed metadata and chapters into M4B file using FFmpeg + Mutagen."""
        ffmetadata_path = self.write_ffmetadata_file(audio_path, metadata, chapters)
        
        metadata_args = self._metadata_to_ffmpeg_args(metadata)
        
        cmd = ["ffmpeg", "-y", "-i", str(audio_path)]
        
        if ffmetadata_path:
            cmd.extend(["-f", "ffmetadata", "-i", str(ffmetadata_path)])
        
        if cover_path and cover_path.exists():
            cmd.extend(["-i", str(cover_path)])
            cmd.extend(["-map", "0:a"])
            cmd.extend(["-map", "1:v:0", "-c:v:0", "mjpeg", "-disposition:v:0", "attached_pic"])
            if cover_mime:
                cmd.extend(["-metadata:s:v:0", f"mimetype={cover_mime}"])
            cmd.extend(["-metadata:s:v:0", "title=Cover Art"])
        else:
            cmd.extend(["-map", "0:a"])
        
        cmd.extend(["-c:a", "copy"])
        
        if ffmetadata_path:
            cmd.extend(["-map_metadata", "1", "-map_chapters", "1"])
        else:
            cmd.extend(["-map_metadata", "0"])
        
        if metadata_args:
            cmd.extend(metadata_args)
        
        cmd.extend(["-movflags", "+faststart+use_metadata_tags"])
        
        temp_output = audio_path.with_suffix(audio_path.suffix + ".tmp")
        if audio_path.suffix.lower() in {".m4b", ".mp4", ".m4a"}:
            cmd.extend(["-f", "mp4"])
        cmd.append(str(temp_output))
        
        if log_callback:
            log_callback("Embedding metadata into M4B output")
        
        process = create_process(cmd, text=True)
        return_code = process.wait()
        
        if ffmetadata_path and ffmetadata_path.exists():
            try:
                ffmetadata_path.unlink()
            except OSError:
                pass
        
        if return_code != 0:
            if temp_output.exists():
                temp_output.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg failed to embed metadata (exit code {return_code})")
        
        temp_output.replace(audio_path)
        
        if log_callback:
            log_callback("Embedded metadata and chapters into M4B output", "info")
        
        # Apply chapters via Mutagen for better compatibility
        self._apply_m4b_chapters_mutagen(audio_path, chapters, log_callback)
    
    @staticmethod
    def _metadata_to_ffmpeg_args(metadata: Dict[str, Any]) -> List[str]:
        args = []
        for key, value in (metadata or {}).items():
            if value in (None, ""):
                continue
            key_str = str(key).strip()
            if not key_str:
                continue
            normalized_key = key_str.lower()
            if normalized_key == "year":
                ffmpeg_key = "date"
            else:
                ffmpeg_key = key_str
            args.extend(["-metadata", f"{ffmpeg_key}={value}"])
        return args
    
    def _apply_m4b_chapters_mutagen(
        self,
        audio_path: Path,
        chapters: List[Dict[str, Any]],
        log_callback: Optional[callable] = None,
    ) -> bool:
        """Apply chapter atoms using Mutagen."""
        if not chapters:
            return False
        
        try:
            from fractions import Fraction
            from mutagen.mp4 import MP4, MP4Chapter
        except ImportError:
            if log_callback:
                log_callback("Unable to write MP4 chapter atoms because mutagen is not installed.", "warning")
            return False
        
        try:
            mp4 = MP4(str(audio_path))
        except Exception as exc:
            if log_callback:
                log_callback(f"Failed to open m4b for chapter embedding: {exc}", "warning")
            return False
        
        chapter_objects = []
        for index, entry in enumerate(sorted(chapters, key=lambda item: float(item.get("start") or 0.0))):
            start_raw = entry.get("start")
            if start_raw is None:
                continue
            try:
                start_seconds = max(0.0, float(start_raw))
            except (TypeError, ValueError):
                continue
            
            title_value = entry.get("title")
            title_text = str(title_value) if title_value else f"Chapter {index + 1}"
            
            start_fraction = Fraction(int(round(start_seconds * 1000)), 1000)
            chapter_atom = MP4Chapter(start_fraction, title_text)
            
            end_raw = entry.get("end")
            if end_raw is not None:
                try:
                    end_seconds = float(end_raw)
                except (TypeError, ValueError):
                    end_seconds = None
                if end_seconds is not None and end_seconds > start_seconds:
                    chapter_atom.end = Fraction(int(round(end_seconds * 1000)), 1000)
            
            chapter_objects.append(chapter_atom)
        
        if not chapter_objects:
            return False
        
        try:
            mp4.chapters = chapter_objects
            mp4.save()
        except Exception as exc:
            if log_callback:
                log_callback(f"Failed to persist MP4 chapter atoms: {exc}", "warning")
            return False
        
        if log_callback:
            log_callback(f"Applied {len(chapter_objects)} chapter markers via mutagen", "info")
        return True
    
    # ----------------------------------------------------------------------
    # EPUB3 Export
    # ----------------------------------------------------------------------
    
    def export_epub3(
        self,
        output_path: Path,
        book_id: str,
        extraction: Any,  # ExtractionResult
        metadata_tags: Dict[str, Any],
        chapter_markers: Sequence[Dict[str, Any]],
        chunk_markers: Sequence[Dict[str, Any]],
        chunks: Iterable[Dict[str, Any]],
        audio_path: Path,
        speaker_mode: str = "single",
        cover_path: Optional[Path] = None,
        cover_mime: Optional[str] = None,
    ) -> Path:
        """Export EPUB3 with media overlays."""
        return build_epub3_package(
            output_path=output_path,
            book_id=book_id,
            extraction=extraction,
            metadata_tags=metadata_tags,
            chapter_markers=chapter_markers,
            chunk_markers=chunk_markers,
            chunks=chunks,
            audio_path=audio_path,
            speaker_mode=speaker_mode,
            cover_image_path=cover_path,
            cover_image_mime=cover_mime,
        )
    
    # ----------------------------------------------------------------------
    # Audiobookshelf Integration
    # ----------------------------------------------------------------------
    
    def build_audiobookshelf_metadata(self, job: Any) -> Dict[str, Any]:
        """Build Audiobookshelf metadata from job."""
        filename = Path(getattr(job, "original_filename", "") or "").stem or "Audiobook"
        return _build_abs_metadata(
            getattr(job, "metadata_tags", {}),
            language=getattr(job, "language", "") or "",
            filename=filename,
        )

    def load_audiobookshelf_chapters(self, job: Any) -> Optional[List[Dict[str, Any]]]:
        """Load chapters from job artifacts for Audiobookshelf."""
        metadata_ref = job.result.artifacts.get("metadata") if getattr(job, "result", None) else None
        if not metadata_ref:
            return None
        metadata_path = metadata_ref if isinstance(metadata_ref, Path) else Path(str(metadata_ref))
        return _load_abs_chapters(metadata_path)
    
    def upload_audiobookshelf(
        self,
        job: Any,
        audio_path: Path,
        subtitle_paths: List[Path],
        chapters: List[Dict[str, Any]],
        metadata: Dict[str, Any],
        cover_path: Optional[Path] = None,
        config: Optional[AudiobookshelfConfig] = None,
        log_callback: Optional[callable] = None,
    ) -> None:
        """Upload to Audiobookshelf."""
        if config is None:
            cfg = getattr(job, "_abs_config", None)
            if cfg is None:
                from abogen.utils import load_config
                global_cfg = load_config() or {}
                abs_cfg = global_cfg.get("audiobookshelf")
                if isinstance(abs_cfg, Mapping):
                    config = AudiobookshelfConfig(
                        base_url=str(abs_cfg.get("base_url") or "").strip(),
                        api_token=str(abs_cfg.get("api_token") or "").strip(),
                        library_id=str(abs_cfg.get("library_id") or "").strip(),
                        collection_id=(str(abs_cfg.get("collection_id") or "").strip() or None),
                        folder_id=str(abs_cfg.get("folder_id") or "").strip(),
                        verify_ssl=self._coerce_bool(abs_cfg.get("verify_ssl"), True),
                        send_cover=self._coerce_bool(abs_cfg.get("send_cover"), True),
                        send_chapters=self._coerce_bool(abs_cfg.get("send_chapters"), True),
                        send_subtitles=self._coerce_bool(abs_cfg.get("send_subtitles"), False),
                        timeout=float(abs_cfg.get("timeout", 3600.0)),
                    )
                else:
                    if log_callback:
                        log_callback("Audiobookshelf upload skipped: not configured", "warning")
                    return

        if not config.base_url or not config.api_token or not config.library_id:
            if log_callback:
                log_callback("Audiobookshelf upload skipped: configure base URL, API token, and library ID first", "warning")
            return
        if not config.folder_id:
            if log_callback:
                log_callback("Audiobookshelf upload skipped: enter folder name or ID in settings", "warning")
            return

        if not audio_path.exists():
            if log_callback:
                log_callback("Audiobookshelf upload skipped: audio output not found", "warning")
            return
        
        existing_subtitles = [p for p in subtitle_paths if p.exists()] if config.send_subtitles else None
        chapters_to_send = chapters if config.send_chapters else None
        
        client = AudiobookshelfClient(config)
        
        display_title = metadata.get("title") or audio_path.stem
        try:
            existing_items = client.find_existing_items(display_title, folder_id=config.folder_id)
        except AudiobookshelfUploadError as exc:
            if log_callback:
                log_callback(f"Audiobookshelf lookup failed: {exc}", "error")
            return
        
        if existing_items:
            if log_callback:
                log_callback(f"Removing existing Audiobookshelf item(s) for '{display_title}' before upload.", "info")
            try:
                client.delete_items(existing_items)
            except Exception as exc:
                if log_callback:
                    log_callback(f"Failed to remove existing item(s): {exc}", "warning")
        
        cover_to_send = cover_path
        if config.send_cover and cover_to_send:
            if isinstance(cover_to_send, str):
                cover_to_send = Path(cover_to_send)
            if not cover_to_send.exists():
                cover_to_send = None
        
        client.upload_audiobook(
            audio_path,
            metadata=metadata,
            cover_path=cover_to_send,
            chapters=chapters_to_send,
            subtitles=existing_subtitles,
        )
        
        if log_callback:
            log_callback("Audiobookshelf upload queued.", "info")
    
    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------
    
    @staticmethod
    def _coerce_bool(value: Any, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
            return default
        if value is None:
            return default
        return bool(value)


__all__ = [
    "ExportConfig",
    "ExportService",
]
