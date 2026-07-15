"""Metadata extraction and processing utilities.

This module provides functions for extracting metadata from text content
and generating ffmpeg metadata arguments.
"""

from __future__ import annotations

import datetime
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def extract_metadata_from_text(text: str) -> Dict[str, Optional[str]]:
    """Extract metadata tags from text content.
    
    Looks for tags in format: <<METADATA_KEY:value>>
    
    Supported tags:
    - TITLE, ARTIST, ALBUM, YEAR
    - ALBUM_ARTIST, COMPOSER, GENRE
    - COVER_PATH
    
    Args:
        text: Text content to search for metadata tags.
        
    Returns:
        Dictionary with extracted metadata values (None if not found).
    """
    metadata = {}
    
    patterns = {
        "title": r"<<METADATA_TITLE:([^>]*)>>",
        "artist": r"<<METADATA_ARTIST:([^>]*)>>",
        "album": r"<<METADATA_ALBUM:([^>]*)>>",
        "year": r"<<METADATA_YEAR:([^>]*)>>",
        "album_artist": r"<<METADATA_ALBUM_ARTIST:([^>]*)>>",
        "composer": r"<<METADATA_COMPOSER:([^>]*)>>",
        "genre": r"<<METADATA_GENRE:([^>]*)>>",
        "cover_path": r"<<METADATA_COVER_PATH:([^>]*)>>",
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            metadata[key] = match.group(1).strip()
        else:
            metadata[key] = None
    
    return metadata


def get_filename_from_path(
    file_path: str,
    display_path: Optional[str] = None,
    from_queue: bool = False,
) -> str:
    """Extract filename (without extension) from path.
    
    Args:
        file_path: The file path to extract from.
        display_path: Optional display path (used if from_queue is False).
        from_queue: Whether the file is from queue.
        
    Returns:
        Filename without extension.
    """
    if from_queue:
        base_path = file_path
    else:
        base_path = display_path if display_path else file_path
    
    filename = os.path.splitext(os.path.basename(base_path))[0]
    return filename


def build_ffmpeg_metadata_args(
    metadata: Dict[str, Optional[str]],
    filename: str,
) -> List[str]:
    """Build ffmpeg metadata arguments from metadata dictionary.
    
    Args:
        metadata: Dictionary with metadata keys and values.
        filename: Fallback filename for title/album if not specified.
        
    Returns:
        List of ffmpeg metadata arguments.
    """
    args = []
    
    # Default values
    defaults = {
        "title": filename,
        "artist": "Unknown",
        "album": filename,
        "date": str(datetime.datetime.now().year),
        "album_artist": "Unknown",
        "composer": "Narrator",
        "genre": "Audiobook",
    }
    
    # Map of metadata keys to ffmpeg metadata keys
    key_mapping = {
        "title": "title",
        "artist": "artist",
        "album": "album",
        "year": "date",  # year -> date for ffmpeg
        "album_artist": "album_artist",
        "composer": "composer",
        "genre": "genre",
    }
    
    for metadata_key, ffmpeg_key in key_mapping.items():
        value = metadata.get(metadata_key)
        if value is None:
            value = defaults.get(metadata_key, "")
        if value:
            args.extend(["-metadata", f"{ffmpeg_key}={value}"])
    
    return args


def extract_metadata_and_build_args(
    text: str,
    filename: str,
    display_path: Optional[str] = None,
    from_queue: bool = False,
) -> Tuple[List[str], Optional[str]]:
    """Extract metadata from text and build ffmpeg arguments.
    
    Convenience function that combines extract_metadata_from_text and
    build_ffmpeg_metadata_args.
    
    Args:
        text: Text content to search for metadata tags.
        filename: Fallback filename for title/album.
        display_path: Optional display path.
        from_queue: Whether the file is from queue.
        
    Returns:
        Tuple of (ffmpeg_metadata_args, cover_path).
    """
    metadata = extract_metadata_from_text(text)
    cover_path = metadata.get("cover_path")
    
    # Get actual filename from path
    actual_filename = get_filename_from_path(
        file_path=filename,
        display_path=display_path,
        from_queue=from_queue,
    )
    
    args = build_ffmpeg_metadata_args(metadata, actual_filename)
    return args, cover_path


def read_text_for_metadata(
    file_path: str,
    is_direct_text: bool,
    direct_text: Optional[str] = None,
    encoding: Optional[str] = None,
) -> str:
    """Read text content for metadata extraction.
    
    Args:
        file_path: Path to file (or text if is_direct_text).
        is_direct_text: Whether file_path contains direct text.
        direct_text: Optional direct text (used if is_direct_text).
        encoding: File encoding (detected if not provided).
        
    Returns:
        Text content for metadata extraction.
    """
    if is_direct_text:
        return direct_text or file_path
    
    # Read from file
    actual_path = direct_text if direct_text else file_path
    
    try:
        if encoding is None:
            from abogen.utils import detect_encoding
            encoding = detect_encoding(actual_path)
        
        with open(actual_path, "r", encoding=encoding, errors="replace") as f:
            return f.read()
    except Exception:
        return ""
