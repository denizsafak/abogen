import unittest
import os
import sys
import shutil
import fitz  # PyMuPDF
from ebooklib import epub

# Ensure we can import the module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.book_parser import get_book_parser, PdfParser, EpubParser, MarkdownParser


class TestBookParser(unittest.TestCase):

    def setUp(self):
        self.test_dir = "tests/test_data"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)

        self.sample_pdf_path = os.path.join(self.test_dir, "test_book.pdf")
        self.sample_epub_path = os.path.join(self.test_dir, "test_book.epub")
        self.sample_md_path = os.path.join(self.test_dir, "test_book.md")

        self._create_sample_pdf()
        self._create_sample_epub()
        self._create_sample_md()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def _create_sample_pdf(self):
        doc = fitz.open()

        # Page 1
        page1 = doc.new_page()
        page1.insert_text((50, 50), "Page 1 content")
        # Add pattern to be cleaned
        page1.insert_text((50, 100), "[12]")
        page1.insert_text((50, 200), "1")  # Page number at bottom

        # Page 2
        page2 = doc.new_page()
        page2.insert_text((50, 50), "Page 2 content")

        doc.save(self.sample_pdf_path)
        doc.close()

    def _create_sample_epub(self):
        book = epub.EpubBook()
        book.set_identifier("id123456")
        book.set_title("Sample Book")
        book.set_language("en")
        book.add_author("Test Author")

        c1 = epub.EpubHtml(title="Intro", file_name="intro.xhtml", lang="en")
        c1.content = "<h1>Introduction</h1><p>Welcome to the book.</p>"

        c2 = epub.EpubHtml(title="Chapter 1", file_name="chap1.xhtml", lang="en")
        c2.content = "<h1>Chapter 1</h1><ol><li>Item One</li><li>Item Two</li></ol>"

        book.add_item(c1)
        book.add_item(c2)

        # Basic spine and nav
        book.spine = ["nav", c1, c2]

        # Add NCX and NAV for compatibility
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        epub.write_epub(self.sample_epub_path, book)

    def _create_sample_md(self):
        content = "# Chapter 1\nSome text.\n# Chapter 2\nMore text."
        with open(self.sample_md_path, "w") as f:
            f.write(content)

    def test_factory_returns_correct_class(self):
        """Test that get_book_parser returns the correct subclass based on extension."""
        parser_pdf = get_book_parser(self.sample_pdf_path)
        self.assertIsInstance(parser_pdf, PdfParser)

        parser_md = get_book_parser(self.sample_md_path)
        self.assertIsInstance(parser_md, MarkdownParser)

        parser_epub = get_book_parser(self.sample_epub_path)
        self.assertIsInstance(parser_epub, EpubParser)

    def test_factory_explicit_type(self):
        """Test that explicit file type argument overrides extension."""
        # 1. Copy sample epub to something.pdf
        wrong_ext_path = os.path.join(self.test_dir, "actually_epub.pdf")
        shutil.copy(self.sample_epub_path, wrong_ext_path)

        # 2. Open it telling parser it IS epub
        parser = get_book_parser(wrong_ext_path, file_type="epub")
        self.assertIsInstance(parser, EpubParser)

        # Should load successfully
        parser.load()
        self.assertTrue(parser.book is not None)

    def test_pdf_parser_content(self):
        """Test PdfParser content extraction."""
        parser = get_book_parser(self.sample_pdf_path)
        parser.process_content()

        self.assertIn("page_1", parser.content_texts)
        self.assertIn("page_2", parser.content_texts)

        text1 = parser.content_texts["page_1"]
        self.assertIn("Page 1 content", text1)
        self.assertNotIn("[12]", text1)

    def test_markdown_parser_content(self):
        """Test MarkdownParser splitting logic."""
        parser = get_book_parser(self.sample_md_path)
        parser.process_content()

        # Should have Chapter 1 and Chapter 2 keys (actual keys depend on ID generation)
        # Markdown extensions might slugify IDs: "chapter-1"
        self.assertIn("chapter-1", parser.content_texts)
        self.assertIn("chapter-2", parser.content_texts)

        self.assertIn("Some text", parser.content_texts["chapter-1"])

    def test_epub_parser_content(self):
        """Test EpubParser processing."""
        parser = get_book_parser(self.sample_epub_path)
        parser.process_content()

        self.assertIn("intro.xhtml", parser.content_texts)
        self.assertIn("chap1.xhtml", parser.content_texts)
        self.assertIn("Welcome to the book", parser.content_texts["intro.xhtml"])

    def test_epub_metadata_extraction(self):
        """Test metadata extraction in EpubParser."""
        parser = get_book_parser(self.sample_epub_path)
        # Processing content triggers metadata extraction in current implementation
        parser.process_content()

        metadata = parser.get_metadata()
        self.assertEqual(metadata.get("title"), "Sample Book")
        self.assertEqual(metadata.get("author"), "Test Author")

    def test_ordered_list_handling(self):
        """Test <ol> handling in EpubParser."""
        parser = get_book_parser(self.sample_epub_path)
        parser.process_content()

        text = parser.content_texts.get("chap1.xhtml", "")
        self.assertIn("1) Item One", text)
        self.assertIn("2) Item Two", text)

    def test_find_position_robust_logic(self):
        """Unit test for _find_position_robust on EpubParser."""
        parser = EpubParser(self.sample_epub_path)  # Instantiate directly

        html = '<html><body><p>Start</p><h1 id="target">Heading</h1><p>End</p></body></html>'
        parser.doc_content["dummy.html"] = html

        # Test finding ID
        pos = parser._find_position_robust("dummy.html", "target")
        self.assertGreater(pos, 0)
        self.assertTrue(html[pos:].startswith('<h1 id="target"'))

        # Test missing ID
        pos_missing = parser._find_position_robust("dummy.html", "missing")
        self.assertEqual(pos_missing, 0)

    def test_get_chapters(self):
        """Test get_chapters returns correct list for different parsers."""
        # PDF
        parser_pdf = get_book_parser(self.sample_pdf_path)
        chapters = parser_pdf.get_chapters()
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0], ("page_1", "Page 1"))

        # MD
        parser_md = get_book_parser(self.sample_md_path)
        parser_md.process_content()  # Must process to get structure
        chapters_md = parser_md.get_chapters()
        # Expecting chapter-1, chapter-2
        ids = [c[0] for c in chapters_md]
        self.assertIn("chapter-1", ids)

    def test_get_formatted_text(self):
        """Test formatting of full text via BaseBookParser method."""
        parser = get_book_parser(self.sample_md_path)
        parser.process_content()
        text = parser.get_formatted_text()

        self.assertIn("<<CHAPTER_MARKER:Chapter 1>>", text)
        self.assertIn("Some text", text)

    def test_file_type_property(self):
        """Test that file_type property returns correct string for each parser."""
        pdf_parser = PdfParser(self.sample_pdf_path)
        self.assertEqual(pdf_parser.file_type, "pdf")

        epub_parser = EpubParser(self.sample_epub_path)
        self.assertEqual(epub_parser.file_type, "epub")

        md_parser = MarkdownParser(self.sample_md_path)
        self.assertEqual(md_parser.file_type, "markdown")


if __name__ == "__main__":
    unittest.main()
