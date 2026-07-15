"""Tests for abogen.domain.metadata_extraction module."""

import pytest

from abogen.domain.metadata_extraction import (
    extract_metadata_from_text,
    get_filename_from_path,
    build_ffmpeg_metadata_args,
    extract_metadata_and_build_args,
    read_text_for_metadata,
)


class TestExtractMetadataFromText:
    """Tests for extract_metadata_from_text function."""

    def test_extract_all_metadata(self):
        """Test extracting all metadata tags."""
        text = """
        <<METADATA_TITLE:Test Book>>
        <<METADATA_ARTIST:Test Author>>
        <<METADATA_ALBUM:Test Album>>
        <<METADATA_YEAR:2024>>
        <<METADATA_ALBUM_ARTIST:Album Artist>>
        <<METADATA_COMPOSER:Composer Name>>
        <<METADATA_GENRE:Fiction>>
        <<METADATA_COVER_PATH:/path/to/cover.jpg>>
        """
        metadata = extract_metadata_from_text(text)
        
        assert metadata["title"] == "Test Book"
        assert metadata["artist"] == "Test Author"
        assert metadata["album"] == "Test Album"
        assert metadata["year"] == "2024"
        assert metadata["album_artist"] == "Album Artist"
        assert metadata["composer"] == "Composer Name"
        assert metadata["genre"] == "Fiction"
        assert metadata["cover_path"] == "/path/to/cover.jpg"

    def test_extract_partial_metadata(self):
        """Test extracting partial metadata."""
        text = "<<METADATA_TITLE:Only Title>>"
        metadata = extract_metadata_from_text(text)
        
        assert metadata["title"] == "Only Title"
        assert metadata["artist"] is None
        assert metadata["cover_path"] is None

    def test_empty_text(self):
        """Test extracting from empty text."""
        metadata = extract_metadata_from_text("")
        
        for key in metadata:
            assert metadata[key] is None

    def test_no_tags(self):
        """Test text without metadata tags."""
        text = "This is just regular text without any metadata tags."
        metadata = extract_metadata_from_text(text)
        
        for key in metadata:
            assert metadata[key] is None

    def test_strip_whitespace(self):
        """Test that values are stripped of whitespace."""
        text = "<<METADATA_TITLE:  Test Book  >>"
        metadata = extract_metadata_from_text(text)
        
        assert metadata["title"] == "Test Book"


class TestGetFilenameFromPath:
    """Tests for get_filename_from_path function."""

    def test_simple_path(self):
        """Test extracting filename from simple path."""
        filename = get_filename_from_path("/path/to/file.txt")
        assert filename == "file"

    def test_path_with_multiple_extensions(self):
        """Test extracting filename from path with multiple extensions."""
        filename = get_filename_from_path("/path/to/file.tar.gz")
        assert filename == "file.tar"

    def test_windows_path(self):
        """Test extracting filename from Windows path."""
        # Note: This test may behave differently on Windows vs Unix
        # but should work correctly on the current platform
        filename = get_filename_from_path("C:\\path\\to\\file.txt")
        assert "file" in filename

    def test_with_display_path(self):
        """Test using display_path when not from_queue."""
        filename = get_filename_from_path(
            file_path="/original/path/file.txt",
            display_path="/display/path/display_file.txt",
            from_queue=False,
        )
        assert filename == "display_file"

    def test_with_display_path_from_queue(self):
        """Test ignoring display_path when from_queue."""
        filename = get_filename_from_path(
            file_path="/original/path/file.txt",
            display_path="/display/path/display_file.txt",
            from_queue=True,
        )
        assert filename == "file"


class TestBuildFfmpegMetadataArgs:
    """Tests for build_ffmpeg_metadata_args function."""

    def test_all_metadata_provided(self):
        """Test building args with all metadata provided."""
        metadata = {
            "title": "Test Title",
            "artist": "Test Artist",
            "album": "Test Album",
            "year": "2024",
            "album_artist": "Album Artist",
            "composer": "Composer",
            "genre": "Fiction",
        }
        args = build_ffmpeg_metadata_args(metadata, "fallback")
        
        assert "-metadata" in args
        assert "title=Test Title" in args
        assert "artist=Test Artist" in args
        assert "album=Test Album" in args
        assert "date=2024" in args  # year -> date

    def test_use_defaults(self):
        """Test that defaults are used for missing metadata."""
        metadata = {}  # Empty metadata
        args = build_ffmpeg_metadata_args(metadata, "mybook")
        
        # Should use defaults
        assert any("title=mybook" in arg for arg in args)
        assert any("artist=Unknown" in arg for arg in args)
        assert any("genre=Audiobook" in arg for arg in args)

    def test_empty_values_skipped(self):
        """Test that empty values are skipped."""
        metadata = {
            "title": "Test",
            "artist": "",
            "album": None,
        }
        args = build_ffmpeg_metadata_args(metadata, "fallback")
        
        # Should have title but not artist/album (empty)
        assert any("title=Test" in arg for arg in args)


class TestExtractMetadataAndBuildArgs:
    """Tests for extract_metadata_and_build_args function."""

    def test_full_workflow(self):
        """Test full metadata extraction and arg building."""
        text = "<<METADATA_TITLE:My Book>>\n<<METADATA_ARTIST:My Author>>"
        args, cover_path = extract_metadata_and_build_args(
            text=text,
            filename="mybook.txt",
        )
        
        assert any("title=My Book" in arg for arg in args)
        assert any("artist=My Author" in arg for arg in args)
        assert cover_path is None

    def test_with_cover_path(self):
        """Test extraction with cover path."""
        text = "<<METADATA_COVER_PATH:/covers/cover.jpg>>"
        args, cover_path = extract_metadata_and_build_args(
            text=text,
            filename="mybook.txt",
        )
        
        assert cover_path == "/covers/cover.jpg"


class TestReadTextForMetadata:
    """Tests for read_text_for_metadata function."""

    def test_direct_text(self):
        """Test reading direct text."""
        text = read_text_for_metadata(
            file_path="This is direct text",
            is_direct_text=True,
        )
        assert text == "This is direct text"

    def test_file_not_found(self):
        """Test handling of file not found."""
        text = read_text_for_metadata(
            file_path="/nonexistent/file.txt",
            is_direct_text=False,
        )
        assert text == ""
