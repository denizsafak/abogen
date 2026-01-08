import re
import platform
from abogen.utils import detect_encoding, load_config
from abogen.constants import SAMPLE_VOICE_TEXTS

# Pre-compile frequently used regex patterns for better performance
_METADATA_TAG_PATTERN = re.compile(r"<<METADATA_[^:]+:[^>]*>>")
_WHITESPACE_PATTERN = re.compile(r"[^\S\n]+")
_MULTIPLE_NEWLINES_PATTERN = re.compile(r"\n{3,}")
_SINGLE_NEWLINE_PATTERN = re.compile(r"(?<!\n)\n(?!\n)")
_CHAPTER_MARKER_PATTERN = re.compile(r"<<CHAPTER_MARKER:[^>]*>>")
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_VOICE_TAG_PATTERN = re.compile(r"{[^}]+}")
_ASS_STYLING_PATTERN = re.compile(r"\{[^}]+\}")
_ASS_NEWLINE_N_PATTERN = re.compile(r"\\N")
_ASS_NEWLINE_LOWER_N_PATTERN = re.compile(r"\\n")
_CHAPTER_MARKER_SEARCH_PATTERN = re.compile(r"<<CHAPTER_MARKER:(.*?)>>")
_WEBVTT_HEADER_PATTERN = re.compile(r"^WEBVTT.*?\n", re.MULTILINE)
_VTT_STYLE_PATTERN = re.compile(r"STYLE\s*\n.*?(?=\n\n|$)", re.DOTALL)
_VTT_NOTE_PATTERN = re.compile(r"NOTE\s*\n.*?(?=\n\n|$)", re.DOTALL)
_DOUBLE_NEWLINE_SPLIT_PATTERN = re.compile(r"\n\s*\n")
_VTT_TIMESTAMP_PATTERN = re.compile(r"([\d:.]+)\s*-->\s*([\d:.]+)")
_TIMESTAMP_ONLY_PATTERN = re.compile(r"^(\d{1,2}:\d{2}:\d{2}(?:[.,]\d{1,3})?)$")
_WINDOWS_ILLEGAL_CHARS_PATTERN = re.compile(r'[<>:"/\\|?*]')
_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1f]")
_LINUX_CONTROL_CHARS_PATTERN = re.compile(
    r"[\x01-\x1f]"
)  # Linux: exclude \x00 for separate handling
_MACOS_ILLEGAL_CHARS_PATTERN = re.compile(r"[:]")
_LINUX_ILLEGAL_CHARS_PATTERN = re.compile(r"[/\x00]")


def clean_subtitle_text(text):
    """Remove chapter markers and metadata tags from subtitle text."""
    # Use pre-compiled patterns for better performance
    text = _METADATA_TAG_PATTERN.sub("", text)
    text = _CHAPTER_MARKER_PATTERN.sub("", text)
    return text.strip()


def calculate_text_length(text):
    # Use pre-compiled patterns for better performance
    # Ignore chapter markers and metadata patterns in a single pass
    text = _CHAPTER_MARKER_PATTERN.sub("", text)
    text = _METADATA_TAG_PATTERN.sub("", text)
    # Ignore newlines and leading/trailing spaces
    text = text.replace("\n", "").strip()
    # Calculate character count
    char_count = len(text)
    return char_count


def clean_text(text, *args, **kwargs):
    # Remove metadata tags first
    text = _METADATA_TAG_PATTERN.sub("", text)
    # Load replace_single_newlines from config
    cfg = load_config()
    replace_single_newlines = cfg.get("replace_single_newlines", True)
    # Collapse all whitespace (excluding newlines) into single spaces per line and trim edges
    # Use pre-compiled pattern for better performance
    lines = [_WHITESPACE_PATTERN.sub(" ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    # Standardize paragraph breaks (multiple newlines become exactly two) and trim overall whitespace
    # Use pre-compiled pattern for better performance
    text = _MULTIPLE_NEWLINES_PATTERN.sub("\n\n", text).strip()
    # Optionally replace single newlines with spaces, but preserve double newlines
    if replace_single_newlines:
        # Use pre-compiled pattern for better performance
        text = _SINGLE_NEWLINE_PATTERN.sub(" ", text)
    return text


def parse_srt_file(file_path):
    """
    Parse an SRT subtitle file and return a list of subtitle entries.

    Args:
        file_path: Path to the SRT file

    Returns:
        List of tuples: [(start_time_seconds, end_time_seconds, text), ...]
    """
    encoding = detect_encoding(file_path)
    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        content = f.read()

    # Split by double newlines to get individual subtitle blocks
    blocks = re.split(r"\n\s*\n", content.strip())

    subtitles = []
    for block in blocks:
        if not block.strip():
            continue

        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue

        # First line is index, second line is timestamp, rest is text
        try:
            timestamp_line = lines[1]
            match = re.match(
                r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})",
                timestamp_line,
            )
            if not match:
                continue

            start_str = match.group(1)
            end_str = match.group(2)
            text = "\n".join(lines[2:])

            # Convert timestamp to seconds
            def time_to_seconds(t):
                h, m, s_ms = t.split(":")
                s, ms = s_ms.split(",")
                return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

            start_sec = time_to_seconds(start_str)
            end_sec = time_to_seconds(end_str)

            # Clean text of any styling tags using pre-compiled pattern
            text = _HTML_TAG_PATTERN.sub("", text)
            # Remove chapter markers and metadata tags
            text = clean_subtitle_text(text)

            if text:  # Only add non-empty subtitles
                subtitles.append((start_sec, end_sec, text))
        except (ValueError, IndexError):
            continue

    return subtitles


def parse_vtt_file(file_path):
    """
    Parse a VTT (WebVTT) subtitle file and return a list of subtitle entries.

    Args:
        file_path: Path to the VTT file

    Returns:
        List of tuples: [(start_time_seconds, end_time_seconds, text), ...]
    """
    encoding = detect_encoding(file_path)
    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        content = f.read()

    # Remove WEBVTT header and any style/note blocks using pre-compiled patterns
    content = _WEBVTT_HEADER_PATTERN.sub("", content)
    content = _VTT_STYLE_PATTERN.sub("", content)
    content = _VTT_NOTE_PATTERN.sub("", content)

    # Split by double newlines to get individual subtitle blocks using pre-compiled pattern
    blocks = _DOUBLE_NEWLINE_SPLIT_PATTERN.split(content.strip())

    subtitles = []
    for block in blocks:
        if not block.strip():
            continue

        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        # VTT can have optional identifier on first line, timestamp on second or first
        timestamp_line = None
        text_start_idx = 0

        # Check if first line is timestamp
        if "-->" in lines[0]:
            timestamp_line = lines[0]
            text_start_idx = 1
        elif len(lines) > 1 and "-->" in lines[1]:
            timestamp_line = lines[1]
            text_start_idx = 2
        else:
            continue

        try:
            # VTT format: 00:00:00.000 --> 00:00:05.000 or 00:00.000 --> 00:05.000
            # Use pre-compiled pattern
            match = _VTT_TIMESTAMP_PATTERN.match(timestamp_line)
            if not match:
                continue

            start_str = match.group(1)
            end_str = match.group(2)
            text = "\n".join(lines[text_start_idx:])

            # Convert timestamp to seconds
            def time_to_seconds(t):
                parts = t.split(":")
                if len(parts) == 3:  # HH:MM:SS.mmm
                    h, m, s = parts
                    s, ms = s.split(".")
                    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
                elif len(parts) == 2:  # MM:SS.mmm
                    m, s = parts
                    s, ms = s.split(".")
                    return int(m) * 60 + int(s) + int(ms) / 1000.0
                return 0

            start_sec = time_to_seconds(start_str)
            end_sec = time_to_seconds(end_str)

            # Clean text of any styling tags and cue settings using pre-compiled patterns
            text = _HTML_TAG_PATTERN.sub("", text)
            text = _VOICE_TAG_PATTERN.sub("", text)  # Remove voice tags
            # Remove chapter markers and metadata tags
            text = clean_subtitle_text(text)

            if text:  # Only add non-empty subtitles
                subtitles.append((start_sec, end_sec, text))
        except (ValueError, IndexError, AttributeError):
            continue

    return subtitles


def detect_timestamps_in_text(file_path):
    """Detect if text file contains timestamp markers (HH:MM:SS or HH:MM:SS,ms format) on separate lines."""
    try:
        encoding = detect_encoding(file_path)
        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            lines = [
                line.strip() for line in f.readlines()[:50] if line.strip()
            ]  # Check first 50 non-empty lines

        # Count lines that are ONLY timestamps (no other text)
        # Supports HH:MM:SS or HH:MM:SS,ms format
        # Use pre-compiled pattern for better performance
        timestamp_lines = sum(
            1 for line in lines if _TIMESTAMP_ONLY_PATTERN.match(line)
        )

        # Must have at least 2 timestamp-only lines and they should be >5% of total lines
        return timestamp_lines >= 2 and (timestamp_lines / max(len(lines), 1)) > 0.05
    except Exception:
        return False


def parse_timestamp_text_file(file_path):
    """Parse text file with timestamps. Returns list of (start_time, end_time, text) tuples.
    Supports HH:MM:SS or HH:MM:SS,ms format. Returns time in seconds as float."""
    encoding = detect_encoding(file_path)
    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        content = f.read()

    # Split by timestamp pattern (supports HH:MM:SS or HH:MM:SS,ms)
    pattern = r"^(\d{1,2}:\d{2}:\d{2}(?:[.,]\d{1,3})?)$"
    lines = content.split("\n")

    def parse_time(time_str):
        """Convert HH:MM:SS or HH:MM:SS,ms to seconds as float."""
        time_str = time_str.replace(",", ".")
        parts = time_str.split(":")
        return float(int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2]))

    entries = []
    current_time = None
    current_text = []
    pre_timestamp_text = []  # Text before first timestamp

    for line in lines:
        match = re.match(pattern, line.strip())
        if match:
            # Save previous entry
            if current_time is not None and current_text:
                text = "\n".join(current_text).strip()
                if text:
                    entries.append((current_time, text))
            elif current_time is None and pre_timestamp_text:
                # First timestamp found, save pre-timestamp text with time 0
                text = "\n".join(pre_timestamp_text).strip()
                if text:
                    entries.append((0.0, text))
                pre_timestamp_text = []

            # Start new entry
            time_str = match.group(1)
            current_time = parse_time(time_str)
            current_text = []
        elif current_time is not None:
            current_text.append(line)
        else:
            # Text before first timestamp
            pre_timestamp_text.append(line)

    # Save last entry
    if current_time is not None and current_text:
        text = "\n".join(current_text).strip()
        if text:
            entries.append((current_time, text))
    elif not entries and pre_timestamp_text:
        # No timestamps found at all, treat entire file as starting at 0
        text = "\n".join(pre_timestamp_text).strip()
        if text:
            entries.append((0.0, text))

    # Convert to subtitle format with end times
    subtitles = []
    for i, (start_time, text) in enumerate(entries):
        end_time = entries[i + 1][0] if i + 1 < len(entries) else None
        # Remove chapter markers and metadata tags
        text = clean_subtitle_text(text)
        if text:  # Only add non-empty entries
            subtitles.append((start_time, end_time, text))

    return subtitles


def parse_ass_file(file_path):
    """
    Parse an ASS/SSA subtitle file and return a list of subtitle entries.

    Args:
        file_path: Path to the ASS/SSA file

    Returns:
        List of tuples: [(start_time_seconds, end_time_seconds, text), ...]
    """
    encoding = detect_encoding(file_path)
    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        lines = f.readlines()

    subtitles = []
    in_events = False
    format_indices = {}

    for line in lines:
        line = line.strip()

        if line.startswith("[Events]"):
            in_events = True
            continue

        if line.startswith("[") and in_events:
            # New section, stop processing
            break

        if in_events and line.startswith("Format:"):
            # Parse format line to know column positions
            parts = line.split(":", 1)[1].strip().split(",")
            for i, part in enumerate(parts):
                format_indices[part.strip().lower()] = i
            continue

        if in_events and (line.startswith("Dialogue:") or line.startswith("Comment:")):
            if line.startswith("Comment:"):
                continue  # Skip comments

            parts = line.split(":", 1)[1].strip().split(",", len(format_indices) - 1)

            if (
                "start" in format_indices
                and "end" in format_indices
                and "text" in format_indices
            ):
                start_str = parts[format_indices["start"]].strip()
                end_str = parts[format_indices["end"]].strip()
                text = parts[format_indices["text"]].strip()

                # Convert timestamp to seconds (ASS format: H:MM:SS.CS where CS is centiseconds)
                def ass_time_to_seconds(t):
                    parts = t.split(":")
                    if len(parts) == 3:
                        h, m, s = parts
                        s_parts = s.split(".")
                        seconds = float(s_parts[0])
                        centiseconds = float(s_parts[1]) if len(s_parts) > 1 else 0
                        return (
                            int(h) * 3600 + int(m) * 60 + seconds + centiseconds / 100.0
                        )
                    return 0

                start_sec = ass_time_to_seconds(start_str)
                end_sec = ass_time_to_seconds(end_str)

                # Clean text of ASS styling tags using pre-compiled patterns
                text = _ASS_STYLING_PATTERN.sub("", text)  # Remove {tags}
                text = _ASS_NEWLINE_N_PATTERN.sub("\n", text)  # Convert \N to newline
                text = _ASS_NEWLINE_LOWER_N_PATTERN.sub(
                    "\n", text
                )  # Convert \n to newline
                # Remove chapter markers and metadata tags
                text = clean_subtitle_text(text)

                if text:  # Only add non-empty subtitles
                    subtitles.append((start_sec, end_sec, text))

    return subtitles


def get_sample_voice_text(lang_code):
    return SAMPLE_VOICE_TEXTS.get(lang_code, SAMPLE_VOICE_TEXTS["a"])


def sanitize_name_for_os(name, is_folder=True):
    """
    Sanitize a filename or folder name based on the operating system.

    Args:
        name: The name to sanitize
        is_folder: Whether this is a folder name (default: True)

    Returns:
        Sanitized name safe for the current OS
    """
    if not name:
        return "audiobook"

    system = platform.system()

    if system == "Windows":
        # Windows illegal characters: < > : " / \ | ? *
        # Also can't end with space or dot
        # Use pre-compiled pattern for better performance
        sanitized = _WINDOWS_ILLEGAL_CHARS_PATTERN.sub("_", name)
        # Remove control characters (0-31)
        sanitized = _CONTROL_CHARS_PATTERN.sub("_", sanitized)
        # Remove trailing spaces and dots
        sanitized = sanitized.rstrip(". ")
        # Windows reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
        reserved = (
            ["CON", "PRN", "AUX", "NUL"]
            + [f"COM{i}" for i in range(1, 10)]
            + [f"LPT{i}" for i in range(1, 10)]
        )
        if sanitized.upper() in reserved or sanitized.upper().split(".")[0] in reserved:
            sanitized = f"_{sanitized}"
    elif system == "Darwin":  # macOS
        # macOS illegal characters: : (colon is converted to / by the system)
        # Also can't start with dot (hidden file) for folders typically
        # Use pre-compiled pattern for better performance
        sanitized = _MACOS_ILLEGAL_CHARS_PATTERN.sub("_", name)
        # Remove control characters
        sanitized = _CONTROL_CHARS_PATTERN.sub("_", sanitized)
        # Avoid leading dot for folders (creates hidden folders)
        if is_folder and sanitized.startswith("."):
            sanitized = "_" + sanitized[1:]
    else:  # Linux and others
        # Linux illegal characters: / and null character
        # Though / is illegal, most other chars are technically allowed
        # Use pre-compiled pattern for better performance
        sanitized = _LINUX_ILLEGAL_CHARS_PATTERN.sub("_", name)
        # Remove other control characters for safety (excluding \x00 which is already handled)
        sanitized = _LINUX_CONTROL_CHARS_PATTERN.sub("_", sanitized)
        # Avoid leading dot for folders (creates hidden folders)
        if is_folder and sanitized.startswith("."):
            sanitized = "_" + sanitized[1:]

    # Ensure the name is not empty after sanitization
    if not sanitized or sanitized.strip() == "":
        sanitized = "audiobook"

    # Limit length to 255 characters (common limit across filesystems)
    if len(sanitized) > 255:
        sanitized = sanitized[:255].rstrip(". ")

    return sanitized
