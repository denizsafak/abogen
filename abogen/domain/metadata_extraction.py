"""Metadata extraction and processing utilities.

This module provides functions for extracting metadata from text content,
formatting metadata tags for TTS embedding, and generating ffmpeg metadata arguments.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


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


def format_metadata_tags(
    metadata: Dict[str, Any],
    filename: str,
    chapter_count: int,
    file_type: str,
    cover_bytes: Optional[bytes] = None,
    cache_dir: Optional[str] = None,
) -> str:
    """Format metadata tags for insertion into TTS text.

    Builds <<METADATA_KEY:value>> tags that are later parsed by
    extract_metadata_from_text() and fed to ffmpeg.

    Args:
        metadata: Dict with keys like 'title', 'authors' (list),
            'publication_year', 'description', 'cover_image' (bytes).
        filename: Fallback filename (without extension) for title/album.
        chapter_count: Number of chapters/pages.
        file_type: 'epub', 'pdf', or 'markdown'.
        cover_bytes: Optional cover image bytes to save to cache.
        cache_dir: Directory for cover cache (uses default if None).

    Returns:
        Newline-joined string of <<METADATA_KEY:value>> tags.
    """
    title = metadata.get("title") or filename
    authors = metadata.get("authors") or ["Unknown"]
    authors_text = ", ".join(authors) if isinstance(authors, list) else str(authors)
    year = metadata.get("publication_year") or str(datetime.datetime.now().year)

    chapter_label = "Chapters" if file_type in ("epub", "markdown") else "Pages"
    chapter_text = f"{chapter_count} {chapter_label}"

    tags = [
        f"<<METADATA_TITLE:{title}>>",
        f"<<METADATA_ARTIST:{authors_text}>>",
        f"<<METADATA_ALBUM:{title} ({chapter_text})>>",
        f"<<METADATA_YEAR:{year}>>",
        f"<<METADATA_ALBUM_ARTIST:{authors_text}>>",
        f"<<METADATA_COMPOSER:Narrator>>",
        f"<<METADATA_GENRE:Audiobook>>",
    ]

    cover_path = _save_cover_to_cache(cover_bytes, cache_dir)
    if cover_path:
        tags.append(f"<<METADATA_COVER_PATH:{cover_path}>>")

    return "\n".join(tags)


def _save_cover_to_cache(
    cover_bytes: Optional[bytes],
    cache_dir: Optional[str] = None,
) -> Optional[str]:
    """Save cover image bytes to cache directory.

    Args:
        cover_bytes: Raw image bytes (e.g. JPEG/PNG).
        cache_dir: Directory to save to. If None, returns None.

    Returns:
        Normalized path to saved cover file, or None on failure.
    """
    if not cover_bytes:
        return None
    if cache_dir is None:
        return None

    try:
        cover_path = os.path.join(cache_dir, f"cover_{uuid.uuid4()}.jpg")
        cover_path = os.path.normpath(cover_path)
        with open(cover_path, "wb") as f:
            f.write(cover_bytes)
        return cover_path
    except Exception as e:
        logger.warning("Failed to save cover image: %s", e)
        return None


def extract_book_metadata_epub(book: Any) -> Dict[str, Any]:
    """Extract metadata from an opened ebooklib EPUB book.

    Args:
        book: An opened ebooklib EPUB book object.

    Returns:
        Dict with keys: title, authors, description, publisher,
        publication_year, cover_image (bytes or None).
    """
    import ebooklib

    metadata: Dict[str, Any] = {
        "title": None,
        "authors": [],
        "description": None,
        "cover_image": None,
        "publisher": None,
        "publication_year": None,
    }

    try:
        title_items = book.get_metadata("DC", "title")
        if title_items and len(title_items) > 0:
            metadata["title"] = title_items[0][0]
    except Exception as e:
        logger.warning("Error extracting title metadata: %s", e)

    try:
        author_items = book.get_metadata("DC", "creator")
        if author_items:
            metadata["authors"] = [
                author[0] for author in author_items if len(author) > 0
            ]
    except Exception as e:
        logger.warning("Error extracting author metadata: %s", e)

    try:
        desc_items = book.get_metadata("DC", "description")
        if desc_items and len(desc_items) > 0:
            metadata["description"] = desc_items[0][0]
    except Exception as e:
        logger.warning("Error extracting description metadata: %s", e)

    try:
        publisher_items = book.get_metadata("DC", "publisher")
        if publisher_items and len(publisher_items) > 0:
            metadata["publisher"] = publisher_items[0][0]
    except Exception as e:
        logger.warning("Error extracting publisher metadata: %s", e)

    try:
        date_items = book.get_metadata("DC", "date")
        if date_items and len(date_items) > 0:
            date_str = date_items[0][0]
            year_match = re.search(r"\b(19|20)\d{2}\b", date_str)
            if year_match:
                metadata["publication_year"] = year_match.group(0)
            else:
                metadata["publication_year"] = date_str
    except Exception as e:
        logger.warning("Error extracting publication date metadata: %s", e)

    for item in book.get_items_of_type(ebooklib.ITEM_COVER):
        metadata["cover_image"] = item.get_content()
        break

    if not metadata["cover_image"]:
        for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
            if "cover" in item.get_name().lower():
                metadata["cover_image"] = item.get_content()
                break

    return metadata


def extract_book_metadata_pdf(pdf_doc: Any) -> Dict[str, Any]:
    """Extract metadata from an opened PyMuPDF document.

    Args:
        pdf_doc: An opened fitz.Document object.

    Returns:
        Dict with keys: title, authors, description, publisher,
        publication_year, cover_image (bytes or None).
    """
    metadata: Dict[str, Any] = {
        "title": None,
        "authors": [],
        "description": None,
        "cover_image": None,
        "publisher": None,
        "publication_year": None,
    }

    pdf_info = pdf_doc.metadata
    if pdf_info:
        metadata["title"] = pdf_info.get("title", None)
        author = pdf_info.get("author", None)
        if author:
            metadata["authors"] = [author]
        metadata["description"] = pdf_info.get("subject", None)
        keywords = pdf_info.get("keywords", None)
        if keywords:
            if metadata["description"]:
                metadata["description"] += f"\n\nKeywords: {keywords}"
            else:
                metadata["description"] = f"Keywords: {keywords}"
        metadata["publisher"] = pdf_info.get("creator", None)

        if "creationDate" in pdf_info:
            date_str = pdf_info["creationDate"]
            year_match = re.search(r"D:(\d{4})", date_str)
            if year_match:
                metadata["publication_year"] = year_match.group(1)
        elif "modDate" in pdf_info:
            date_str = pdf_info["modDate"]
            year_match = re.search(r"D:(\d{4})", date_str)
            if year_match:
                metadata["publication_year"] = year_match.group(1)

    if len(pdf_doc) > 0:
        try:
            import fitz
            pix = pdf_doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
            metadata["cover_image"] = pix.tobytes("png")
        except Exception:
            pass

    return metadata


def extract_book_metadata_markdown(
    markdown_text: str,
    markdown_toc: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Extract metadata from markdown frontmatter and first heading.

    Args:
        markdown_text: Raw markdown text content.
        markdown_toc: Optional table of contents list (each item has
            'level' and 'name' keys).

    Returns:
        Dict with keys: title, authors, description, publication_year.
        cover_image is always None for markdown.
    """
    metadata: Dict[str, Any] = {
        "title": None,
        "authors": [],
        "description": None,
        "cover_image": None,
        "publisher": None,
        "publication_year": None,
    }

    if not markdown_text:
        return metadata

    frontmatter_match = re.match(
        r"^---\s*\n(.*?)\n---\s*\n", markdown_text, re.DOTALL
    )
    if frontmatter_match:
        try:
            frontmatter = frontmatter_match.group(1)
            title_match = re.search(
                r"^title:\s*(.+)$", frontmatter, re.MULTILINE | re.IGNORECASE
            )
            if title_match:
                metadata["title"] = title_match.group(1).strip().strip("\"'")

            author_match = re.search(
                r"^author:\s*(.+)$", frontmatter, re.MULTILINE | re.IGNORECASE
            )
            if author_match:
                metadata["authors"] = [
                    author_match.group(1).strip().strip("\"'")
                ]

            desc_match = re.search(
                r"^description:\s*(.+)$", frontmatter, re.MULTILINE | re.IGNORECASE
            )
            if desc_match:
                metadata["description"] = (
                    desc_match.group(1).strip().strip("\"'")
                )

            date_match = re.search(
                r"^date:\s*(.+)$", frontmatter, re.MULTILINE | re.IGNORECASE
            )
            if date_match:
                date_str = date_match.group(1).strip().strip("\"'")
                year_match = re.search(r"\b(19|20)\d{2}\b", date_str)
                if year_match:
                    metadata["publication_year"] = year_match.group(0)
        except Exception as e:
            logger.warning("Error parsing markdown frontmatter: %s", e)

    if not metadata["title"] and markdown_toc:
        first_h1 = next(
            (h for h in markdown_toc if h.get("level") == 1), None
        )
        if first_h1:
            metadata["title"] = first_h1.get("name")

    return metadata
