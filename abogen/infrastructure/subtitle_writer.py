from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, TextIO

from abogen.subtitle_utils import clean_subtitle_text


class SubtitleFormat(Enum):
    SRT = "srt"
    ASS = "ass"
    VTT = "vtt"


class SubtitleMode(Enum):
    DISABLED = "Disabled"
    LINE = "Line"
    SENTENCE = "Sentence"
    SENTENCE_COMMA = "Sentence + Comma"
    SENTENCE_HIGHLIGHT = "Sentence + Highlighting"


class SubtitleAlignment(Enum):
    LEFT = "left"
    CENTER = "center"
    NARROW = "narrow"
    CENTER_NARROW = "center_narrow"


@dataclass
class SubtitleConfig:
    """Configuration for subtitle writer."""
    format: SubtitleFormat
    mode: SubtitleMode
    alignment: SubtitleAlignment = SubtitleAlignment.LEFT
    max_words: int = 50
    highlight_color: str = "&H00FFFF00"  # ASS highlight color


class SubtitleWriter(ABC):
    """Abstract base class for subtitle writers."""
    
    def __init__(self, path: Path, config: SubtitleConfig):
        self.path = path
        self.config = config
        self._file: Optional[TextIO] = None
        self._index = 0
        self._opened = False
    
    def open(self) -> None:
        """Open the subtitle file and write header."""
        if self._opened:
            return
        self._file = open(self.path, "w", encoding="utf-8", errors="replace")
        self._write_header()
        self._opened = True
    
    @abstractmethod
    def _write_header(self) -> None:
        pass
    
    def write_entry(
        self,
        start: float,
        end: float,
        text: str,
        voice: Optional[str] = None,
    ) -> None:
        """Write a subtitle entry."""
        if not self._opened:
            self.open()
        
        text = clean_subtitle_text(text)
        if not text:
            return
        
        self._index += 1
        self._write_entry(self._index, start, end, text, voice)
    
    @abstractmethod
    def _write_entry(
        self,
        index: int,
        start: float,
        end: float,
        text: str,
        voice: Optional[str],
    ) -> None:
        pass
    
    def close(self) -> None:
        """Close the subtitle file."""
        if self._file:
            self._file.close()
            self._file = None
            self._opened = False
    
    def __enter__(self) -> "SubtitleWriter":
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


class SrtWriter(SubtitleWriter):
    """SRT subtitle writer."""
    
    def _write_header(self) -> None:
        pass  # SRT has no header
    
    def _write_entry(
        self,
        index: int,
        start: float,
        end: float,
        text: str,
        voice: Optional[str],
    ) -> None:
        start_str = self._format_time(start)
        end_str = self._format_time(end)
        
        if voice:
            text = f"[{voice}] {text}"
        
        self._file.write(f"{index}\n")
        self._file.write(f"{start_str} --> {end_str}\n")
        self._file.write(f"{text}\n\n")
    
    @staticmethod
    def _format_time(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


class VttWriter(SubtitleWriter):
    """WebVTT subtitle writer."""
    
    def _write_header(self) -> None:
        self._file.write("WEBVTT\n\n")
    
    def _write_entry(
        self,
        index: int,
        start: float,
        end: float,
        text: str,
        voice: Optional[str],
    ) -> None:
        start_str = self._format_time(start)
        end_str = self._format_time(end)
        
        if voice:
            text = f"[{voice}] {text}"
        
        self._file.write(f"{index}\n")
        self._file.write(f"{start_str} --> {end_str}\n")
        self._file.write(f"{text}\n\n")
    
    @staticmethod
    def _format_time(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}".replace(".", ".")


class AssWriter(SubtitleWriter):
    """ASS subtitle writer with karaoke highlighting support."""
    
    def __init__(self, path: Path, config: SubtitleConfig):
        super().__init__(path, config)
        self._is_centered = config.alignment in (SubtitleAlignment.CENTER, SubtitleAlignment.CENTER_NARROW)
        self._is_narrow = config.alignment in (SubtitleAlignment.NARROW, SubtitleAlignment.CENTER_NARROW)
    
    def _write_header(self) -> None:
        margin = "90" if self._is_narrow else "10"
        alignment = "5" if self._is_centered else "2"
        
        self._file.write("[Script Info]\n")
        self._file.write("Title: Generated by Abogen\n")
        self._file.write("ScriptType: v4.00+\n\n")
        
        # Styles
        self._file.write("[V4+ Styles]\n")
        self._file.write(
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        )
        
        if self.config.mode == SubtitleMode.SENTENCE_HIGHLIGHT:
            # Karaoke style with highlighting
            self._file.write(
                f"Style: Default,Arial,24,&H00FFFFFF,&H00808080,&H00000000,&H00404040,"
                f"0,0,0,0,100,100,0,0,3,2,0,{alignment},{margin},{margin},10,1\n"
            )
            self._file.write(
                f"Style: Highlight,Arial,24,&H0000FFFF,&H00808080,&H00000000,&H00404040,"
                f"0,0,0,0,100,100,0,0,3,2,0,{alignment},{margin},{margin},10,1\n\n"
            )
        else:
            self._file.write(
                f"Style: Default,Arial,24,&H00FFFFFF,&H00808080,&H00000000,&H00404040,"
                f"0,0,0,0,100,100,0,0,3,2,0,{alignment},{margin},{margin},10,1\n\n"
            )
        
        self._file.write("[Events]\n")
        self._file.write(
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )
    
    def _write_entry(
        self,
        index: int,
        start: float,
        end: float,
        text: str,
        voice: Optional[str],
    ) -> None:
        start_str = self._format_time(start)
        end_str = self._format_time(end)
        
        if voice:
            text = f"[{voice}] {text}"
        
        style = "Default"
        if self.config.mode == SubtitleMode.SENTENCE_HIGHLIGHT:
            # Add karaoke tags for highlighting
            text = self._add_karaoke_tags(text)
            style = "Highlight"
        
        alignment_tag = r"{\an5}" if self._is_centered else ""
        self._file.write(
            f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{alignment_tag}{text}\n"
        )
    
    def _add_karaoke_tags(self, text: str) -> str:
        """Add karaoke highlighting tags to text."""
        # Simple word-level karaoke timing
        words = text.split()
        if not words:
            return text
        
        # This is a simplified version - real karaoke needs per-word timing
        # For now, just return the text with the highlight color
        return r"{\k100}" + r"{\k100}".join(words) + r"{\k0}"
    
    @staticmethod
    def _format_time(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}:{minutes:02d}:{secs:05.2f}"


def create_subtitle_writer(
    path: Path,
    format: str,
    mode: str,
    alignment: str = "left",
    max_words: int = 50,
) -> SubtitleWriter:
    """Factory function to create subtitle writer."""
    fmt = SubtitleFormat(format.lower())
    mode = SubtitleMode(mode)
    align = SubtitleAlignment(alignment.lower())

    config = SubtitleConfig(
        format=fmt,
        mode=mode,
        alignment=align,
        max_words=max_words,
    )

    if fmt == SubtitleFormat.SRT:
        return SrtWriter(path, config)
    elif fmt == SubtitleFormat.VTT:
        return VttWriter(path, config)
    elif fmt == SubtitleFormat.ASS:
        return AssWriter(path, config)
    else:
        raise ValueError(f"Unsupported subtitle format: {format}")


def resolve_subtitle_format(
    subtitle_format: str | None,
    subtitle_mode: str,
) -> tuple[str, str]:
    """Resolve a subtitle_format setting string to (file_extension, alignment).

    Handles the PyQt convention where format strings encode alignment
    (e.g. ``"ass_centered_narrow"`` → extension ``"ass"``, alignment
    ``"center_narrow"``).

    Also enforces that ``"Sentence + Highlighting"`` mode requires ASS.

    Returns:
        Tuple of (file_extension, alignment) suitable for
        :func:`create_subtitle_writer`.
    """
    fmt = (subtitle_format or "srt").lower()

    if subtitle_mode == "Sentence + Highlighting" and fmt == "srt":
        fmt = "ass"

    if "ass" in fmt:
        extension = "ass"
        if "centered_narrow" in fmt:
            alignment = "center_narrow"
        elif "centered" in fmt:
            alignment = "center"
        elif "narrow" in fmt:
            alignment = "narrow"
        else:
            alignment = "left"
    else:
        extension = fmt if fmt in ("srt", "vtt") else "srt"
        alignment = "left"

    return extension, alignment


def make_subtitle_writer(
    audio_path: Path,
    subtitle_format: str | None,
    subtitle_mode: str,
    max_words: int = 50,
) -> SubtitleWriter | None:
    """Convenience: resolve format and create a writer, or return None if disabled.

    Returns ``None`` when ``subtitle_mode`` is ``"Disabled"`` or the
    format is unsupported.
    """
    if subtitle_mode == "Disabled":
        return None

    extension, alignment = resolve_subtitle_format(subtitle_format, subtitle_mode)
    try:
        return create_subtitle_writer(
            audio_path.with_suffix(f".{extension}"),
            extension,
            subtitle_mode,
            alignment=alignment,
            max_words=max_words,
        )
    except (ValueError, KeyError):
        return None


__all__ = [
    "SubtitleFormat",
    "SubtitleMode",
    "SubtitleAlignment",
    "SubtitleConfig",
    "SubtitleWriter",
    "SrtWriter",
    "VttWriter",
    "AssWriter",
    "create_subtitle_writer",
    "resolve_subtitle_format",
    "make_subtitle_writer",
]
