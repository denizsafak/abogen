import unittest
import os
import shutil
import sys
from ebooklib import epub

# Ensure import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.book_parser import get_book_parser


class TestEpubHtmlNavParsing(unittest.TestCase):
    """
    Tests for EPUB 3 HTML5 Navigation Document parsing logic (_parse_html_nav_li).
    """

    def setUp(self):
        self.test_dir = "tests/test_data_nav"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        self.epub_path = os.path.join(self.test_dir, "nav_test.epub")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def _create_epub_with_custom_nav(self, nav_html_content):
        """
        Creates an EPUB with a manually injected HTML Navigation Document.
        """
        book = epub.EpubBook()
        book.set_identifier("navtest123")
        book.set_title("Nav Test Book")

        # Add some content files
        c1 = epub.EpubHtml(title="Chapter 1", file_name="chap1.xhtml", lang="en")
        c1.content = "<h1>Chapter 1</h1><p>Text 1</p>"
        book.add_item(c1)

        c2 = epub.EpubHtml(title="Chapter 2", file_name="chap2.xhtml", lang="en")
        c2.content = "<h1>Chapter 2</h1><p>Text 2</p>"
        book.add_item(c2)

        # Create the Nav item manually to control the HTML structure exactly
        # Use EpubHtml + OPF patching because EpubNav forces auto-generation
        nav = epub.EpubHtml(title="Nav", file_name="nav.xhtml")
        nav.content = nav_html_content
        book.add_item(nav)

        # We must set spine manually
        book.spine = [nav, c1, c2]

        epub.write_epub(self.epub_path, book)

        # Patch the OPF to remove toc="ncx" default which causes crash
        # because we intentionally excluded the legacy NCX file.
        import zipfile

        with zipfile.ZipFile(self.epub_path, "r") as zin:
            opf_content = zin.read("EPUB/content.opf").decode("utf-8")
            opf_content = opf_content.replace('toc="ncx"', "")

            # Repack
            TEMP_EPUB = self.epub_path + ".temp"
            with zipfile.ZipFile(TEMP_EPUB, "w") as zout:
                for item in zin.infolist():
                    if item.filename == "EPUB/content.opf":
                        zout.writestr(item, opf_content)
                    else:
                        zout.writestr(item, zin.read(item.filename))

        shutil.move(TEMP_EPUB, self.epub_path)

    def test_basic_html_nav_parsing(self):
        """
        Test parsing of a standard flat list of links.
        """
        nav_html = """
        <nav epub:type="toc" id="toc">
            <h1>Table of Contents</h1>
            <ol>
                <li><a href="chap1.xhtml">Chapter 1</a></li>
                <li><a href="chap2.xhtml">Chapter 2</a></li>
            </ol>
        </nav>
        """
        self._create_epub_with_custom_nav(nav_html)

        parser = get_book_parser(self.epub_path)
        parser.process_content()
        chapters = parser.get_chapters()

        # Filter out "Nav" or "Introduction" prefix content found from the Nav file itself
        chapters = [c for c in chapters if "Chapter" in c[1] or "Section" in c[1]]

        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0][1], "Chapter 1")
        self.assertEqual(chapters[1][1], "Chapter 2")

    def test_nested_html_nav_parsing(self):
        """
        Test parsing of nested lists (Sub-chapters).
        """
        nav_html = """
        <nav epub:type="toc">
            <ol>
                <li>
                    <a href="chap1.xhtml">Chapter 1</a>
                    <ol>
                        <li><a href="chap2.xhtml">Section 1.1</a></li>
                    </ol>
                </li>
            </ol>
        </nav>
        """
        # Note: In this test setup, chap2 is serving as "Section 1.1" effectively
        self._create_epub_with_custom_nav(nav_html)

        parser = get_book_parser(self.epub_path)
        parser.process_content()
        chapters = parser.get_chapters()

        ids = [c[1] for c in chapters]
        self.assertIn("Chapter 1", ids)
        self.assertIn("Section 1.1", ids)

    def test_span_header_parsing(self):
        """
        Test parsing of <li><span>Header</span><ol>...</ol></li> pattern.
        This represents a grouping header that isn't a link itself.
        """
        nav_html = """
        <nav epub:type="toc">
            <ol>
                <li>
                    <span>Part I</span>
                    <ol>
                        <li><a href="chap1.xhtml">Chapter 1</a></li>
                    </ol>
                </li>
            </ol>
        </nav>
        """
        self._create_epub_with_custom_nav(nav_html)

        parser = get_book_parser(self.epub_path)
        parser.process_content()

        chapters = parser.get_chapters()
        chapter_titles = [c[1] for c in chapters]

        self.assertIn("Chapter 1", chapter_titles)
        self.assertNotIn("Part I", chapter_titles)

        # Check internal structure
        # Find the node named "Part I" in the processed structure
        root_node = next(
            node for node in parser.processed_nav_structure if node["title"] == "Part I"
        )

        self.assertEqual(root_node["title"], "Part I")
        self.assertFalse(root_node["has_content"])
        self.assertEqual(len(root_node["children"]), 1)
        self.assertEqual(root_node["children"][0]["title"], "Chapter 1")

    def test_identify_nav_item(self):
        """Test the _identify_nav_item method specifically."""
        nav_html = """
        <nav epub:type="toc" id="toc"><h1>TOC</h1><ol><li><a href="c1.html">C1</a></li></ol></nav>
        """
        self._create_epub_with_custom_nav(nav_html)
        parser = get_book_parser(self.epub_path)
        # Note: _identify_nav_item relies on self.book being loaded
        # The parser constructor or process_content handles load()
        # But here we can call load directly if needed, or rely on normal flow up until navigation
        parser.load()
        nav_item, nav_type = parser._identify_nav_item()

        self.assertEqual(nav_type, "html")
        self.assertIsNotNone(nav_item)
        self.assertTrue("nav.xhtml" in nav_item.get_name())


if __name__ == "__main__":
    unittest.main()
