"""Domain enums — typed constants for values tied to business logic.

Using Enum instead of bare strings ensures:
- Invalid values are caught at construction time
- IDE autocomplete and type checking work
- Adding new values is explicit (must update Enum)
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class SubtitleMode(str, Enum):
    """Subtitle generation mode."""
    DISABLED = "Disabled"
    LINE = "Line"
    SENTENCE = "Sentence"
    SENTENCE_COMMA = "Sentence + Comma"
    SENTENCE_HIGHLIGHT = "Sentence + Highlighting"

    @classmethod
    def from_str(cls, value: str) -> SubtitleMode:
        """Parse from user input: case-insensitive, strips whitespace."""
        normalized = value.strip()
        for member in cls:
            if member.value.lower() == normalized.lower():
                return member
        raise ValueError(f"Invalid SubtitleMode: {value!r}. Valid: {[m.value for m in cls]}")


class OutputFormat(str, Enum):
    """Audio output format."""
    WAV = "wav"
    MP3 = "mp3"
    FLAC = "flac"
    OPUS = "opus"
    M4B = "m4b"

    @property
    def dot_ext(self) -> str:
        """File extension with dot: '.wav', '.mp3', etc."""
        return f".{self.value}"

    @property
    def is_lossless(self) -> bool:
        """True for lossless formats."""
        return self in (self.WAV, self.FLAC)

    @classmethod
    def from_str(cls, value: str) -> OutputFormat:
        """Parse from user input: strips dot prefix, case-insensitive."""
        normalized = value.strip().lstrip(".").lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"Invalid OutputFormat: {value!r}. Valid: {[m.value for m in cls]}")


class SaveMode(str, Enum):
    """Where to save the output file."""
    SAVE_NEXT_TO_INPUT = "save_next_to_input"
    SAVE_TO_DESKTOP = "save_to_desktop"
    CHOOSE_OUTPUT_FOLDER = "choose_output_folder"
    DEFAULT_OUTPUT = "default_output"
    CUSTOM_FOLDER = "custom_folder"


class SubtitleFormat(str, Enum):
    """Subtitle file format."""
    SRT = "srt"
    ASS = "ass"
    VTT = "vtt"

    @property
    def dot_ext(self) -> str:
        """File extension with dot: '.srt', '.ass'."""
        return f".{self.value}"

    @classmethod
    def from_str(cls, value: str) -> SubtitleFormat:
        """Parse from user input: strips dot prefix, case-insensitive."""
        normalized = value.strip().lstrip(".").lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"Invalid SubtitleFormat: {value!r}. Valid: {[m.value for m in cls]}")


class InputFormat(str, Enum):
    """Input file format."""
    EPUB = "epub"
    PDF = "pdf"
    TXT = "txt"
    MD = "md"
    SRT = "srt"
    ASS = "ass"
    VTT = "vtt"

    @property
    def is_book(self) -> bool:
        """True for book/document formats (epub, pdf, txt, md)."""
        return self in (self.EPUB, self.PDF, self.TXT, self.MD)

    @property
    def is_subtitle(self) -> bool:
        """True for subtitle formats (srt, ass, vtt)."""
        return self in (self.SRT, self.ASS, self.VTT)

    @property
    def dot_ext(self) -> str:
        """File extension with dot: '.epub', '.srt', etc."""
        return f".{self.value}"

    @classmethod
    def from_path(cls, path: Path) -> InputFormat:
        """Detect format from file path extension."""
        suffix = path.suffix.lower().lstrip(".")
        if suffix == "markdown":
            return cls.MD
        try:
            return cls(suffix)
        except ValueError:
            raise ValueError(f"Unsupported input format: {path.suffix!r}. Supported: {[m.value for m in cls]}")
