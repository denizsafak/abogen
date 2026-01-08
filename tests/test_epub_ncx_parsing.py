import unittest
import os
import shutil
import sys
from ebooklib import epub

# Ensure we can import the module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.book_parser import get_book_parser, EpubParser


class TestEpubNcxParsing(unittest.TestCase):
    """
    Focused tests for NCX navigation scenarios, ensuring legacy/compatibility
    modes work when HTML5 Navigation is missing.
    """

    def setUp(self):
        self.test_dir = "tests/test_data_ncx"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        self.ncx_only_epub_path = os.path.join(self.test_dir, "ncx_only.epub")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def _create_ncx_only_epub(self, chapters):
        """
        Helper to create an EPUB with ONLY NCX table of contents (no HTML nav).
        """
        book = epub.EpubBook()
        book.set_identifier("ncx_test_123")
        book.set_title("NCX Only Book")
        book.set_language("en")

        epub_chapters = []
        for i, (title, content) in enumerate(chapters):
            filename = f"chap{i+1}.xhtml"
            c = epub.EpubHtml(title=title, file_name=filename, lang="en")
            # Ensure content is substantial enough to not be skipped
            c.content = f"<h1>{title}</h1><p>{content}</p>"
            book.add_item(c)
            epub_chapters.append(c)

        # Define Table of Contents
        book.toc = tuple(epub_chapters)

        # Add default NCX and generic spine
        book.add_item(epub.EpubNcx())
        # IMPORTANT: Do NOT add EpubNav() here, that's what we are testing!

        book.spine = ["nav"] + epub_chapters

        epub.write_epub(self.ncx_only_epub_path, book)

    def test_ncx_only_parsing(self):
        """
        Verify that an EPUB with only an NCX file (no HTML nav) is parsed correctly.
        Logic tested: _process_epub_content_nav (NCX branch), _parse_ncx_navpoint
        """
        # 1. Setup Data
        chapters_data = [
            ("Chapter 1", "This is the first chapter."),
            ("Chapter 2", "This is the second chapter."),
        ]
        self._create_ncx_only_epub(chapters_data)

        # 2. Run Parser
        parser = get_book_parser(self.ncx_only_epub_path)
        parser.process_content()

        # 3. Verify Breakdown
        # We expect detailed breakdown based on NCX
        chapters = parser.get_chapters()

        # Should find exactly 2 chapters based on the Toc
        self.assertEqual(len(chapters), 2, "Should have 2 chapters extracted from NCX")

        # Check Titles and Sequence
        self.assertEqual(chapters[0][1], "Chapter 1")
        self.assertEqual(chapters[1][1], "Chapter 2")

        # Verify content was extracted
        # Note: 'src' in chapters usually points to file_name if no fragments
        id_1 = chapters[0][0]
        self.assertIn("This is the first chapter", parser.content_texts[id_1])

    def test_nested_ncx_parsing(self):
        """
        Verify parsing of nested NCX structures (Chapters with Subchapters).
        """
        book = epub.EpubBook()
        book.set_identifier("nested_ncx")
        book.set_title("Nested NCX")

        # Create one big file with sections
        c1 = epub.EpubHtml(title="Main Chapter", file_name="main.xhtml", lang="en")
        c1.content = """
            <h1 id="intro">Introduction</h1>
            <p>Intro text.</p>
            <h2 id="sect1">Section 1</h2>
            <p>Section 1 text.</p>
        """
        book.add_item(c1)

        # Manually construct nested TOC because ebooklib's default helpers are simple
        # EbookLib automatically builds NCX from book.toc
        # Nested tuple structure: (Section, (Subsection, Sub-subsection))

        # We need to link to Fragments for this to really test nested NCX pointing to same file
        # EbookLib Link object: epub.Link(href, title, uid)

        link_root = epub.Link("main.xhtml#intro", "Introduction", "intro")
        link_sect = epub.Link("main.xhtml#sect1", "Section 1", "sect1")

        # Structure: Intro -> Section 1 (as child)
        book.toc = ((link_root, (link_sect,)),)

        book.add_item(epub.EpubNcx())
        book.spine = ["nav", c1]

        epub.write_epub(self.ncx_only_epub_path, book)

        # Parse
        parser = get_book_parser(self.ncx_only_epub_path)
        parser.process_content()

        chapters = parser.get_chapters()

        # Depending on how the parser flattens, we should see both entries
        titles = [node[1] for node in chapters]
        self.assertIn("Introduction", titles)
        self.assertIn("Section 1", titles)


if __name__ == "__main__":
    unittest.main()
