# represents a queued item - book, chapters, voice, etc.
from dataclasses import dataclass


@dataclass
class QueuedItem:
    file_name: str
    lang_code: str
    speed: float
    voice: str
    save_option: str
    output_folder: str
    subtitle_mode: str
    output_format: str
    total_char_count: int
    replace_single_newlines: bool = False
