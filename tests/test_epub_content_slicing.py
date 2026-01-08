import unittest
import os
import shutil
import sys
from ebooklib import epub

# Ensure import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.book_parser import get_book_parser


class TestEpubContentSlicing(unittest.TestCase):
    """
    Tests for the complex content slicing logic in _execute_nav_parsing_logic.
    This covers scenarios where multiple chapters/sections are contained within
    a single physical HTML file, separated by anchors (fragments).
    """

    def setUp(self):
        self.test_dir = "tests/test_data_slicing"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        self.epub_path = os.path.join(self.test_dir, "slicing_test.epub")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_single_file_multiple_chapters(self):
        """
        Test splitting one XHTML file into two chapters using an anchor.
        """
        book = epub.EpubBook()
        book.set_identifier("slice123")
        book.set_title("Slicing Test Book")

        # Create a single content file with two sections
        content_html = """
        <html>
            <body>
                <h1 id="chap1">Chapter 1</h1>
                <p>Text for chapter 1.</p>
                <hr/>
                <h1 id="chap2">Chapter 2</h1>
                <p>Text for chapter 2.</p>
            </body>
        </html>
        """
        c1 = epub.EpubHtml(title="Full Content", file_name="content.xhtml", lang="en")
        c1.content = content_html
        book.add_item(c1)

        # Create Nav that points to anchors in the SAME file
        # We use EpubHtml for Nav to control content exactly without ebooklib interference
        nav_html = """
        <nav epub:type="toc" id="toc">
            <ol>
                <li><a href="content.xhtml#chap1">Chapter 1</a></li>
                <li><a href="content.xhtml#chap2">Chapter 2</a></li>
            </ol>
        </nav>
        """
        nav = epub.EpubHtml(title="Nav", file_name="nav.xhtml")
        nav.content = nav_html
        book.add_item(nav)

        book.spine = [nav, c1]

        epub.write_epub(self.epub_path, book)

        # OPF Patching to valid crash
        import zipfile

        patched = False
        with zipfile.ZipFile(self.epub_path, "r") as zin:
            opf_content = zin.read("EPUB/content.opf").decode("utf-8")
            if 'toc="ncx"' in opf_content:
                opf_content = opf_content.replace('toc="ncx"', "")
                patched = True

            if patched:
                TEMP_EPUB = self.epub_path + ".temp"
                with zipfile.ZipFile(TEMP_EPUB, "w") as zout:
                    for item in zin.infolist():
                        if item.filename == "EPUB/content.opf":
                            zout.writestr(item, opf_content)
                        else:
                            zout.writestr(item, zin.read(item.filename))

        if patched:
            shutil.move(TEMP_EPUB, self.epub_path)

        # Parse
        parser = get_book_parser(self.epub_path)
        parser.process_content()
        chapters = parser.get_chapters()

        # Filter Nav/Intro
        chapters = [c for c in chapters if "Chapter" in c[1]]

        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0][1], "Chapter 1")
        self.assertEqual(chapters[1][1], "Chapter 2")

        # Check content of Chapter 1
        # It should contain "Text for chapter 1" but NOT "Text for chapter 2"
        # The parser logic slices from start_pos to next_pos
        text1 = parser.content_texts[chapters[0][0]]
        self.assertIn("Text for chapter 1", text1)
        self.assertNotIn("Text for chapter 2", text1)

        # Check content of Chapter 2
        text2 = parser.content_texts[chapters[1][0]]
        self.assertIn("Text for chapter 2", text2)

    def test_list_renumbering(self):
        """
        Test that ordered lists are re-numbered when slicing.
        The parser has logic to reset <ol start="..."> or insert numbers.
        """
        book = epub.EpubBook()
        book.set_identifier("list123")
        book.set_title("List Test Book")

        content_html = """
        <html>
            <body>
                <h1 id="part1">Part 1</h1>
                <ol>
                    <li>Item A</li>
                    <li>Item B</li>
                </ol>
                <h1 id="part2">Part 2</h1>
                <ol start="3">
                    <li>Item C</li>
                    <li>Item D</li>
                </ol>
            </body>
        </html>
        """
        c1 = epub.EpubHtml(title="Content", file_name="content.xhtml", lang="en")
        c1.content = content_html
        book.add_item(c1)

        nav_html = """
        <nav epub:type="toc">
            <ol>
                <li><a href="content.xhtml#part1">Part 1</a></li>
                <li><a href="content.xhtml#part2">Part 2</a></li>
            </ol>
        </nav>
        """
        nav = epub.EpubHtml(title="Nav", file_name="nav.xhtml")
        nav.content = nav_html
        book.add_item(nav)
        book.spine = [nav, c1]

        epub.write_epub(self.epub_path, book)

        # Patch
        import zipfile

        patched = False
        with zipfile.ZipFile(self.epub_path, "r") as zin:
            opf_content = zin.read("EPUB/content.opf").decode("utf-8")
            if 'toc="ncx"' in opf_content:
                opf_content = opf_content.replace('toc="ncx"', "")
                patched = True
            if patched:
                TEMP_EPUB = self.epub_path + ".temp"
                with zipfile.ZipFile(TEMP_EPUB, "w") as zout:
                    for item in zin.infolist():
                        if item.filename == "EPUB/content.opf":
                            zout.writestr(item, opf_content)
                        else:
                            zout.writestr(item, zin.read(item.filename))
        if patched:
            shutil.move(TEMP_EPUB, self.epub_path)

        parser = get_book_parser(self.epub_path)
        parser.process_content()
        chapters = parser.get_chapters()
        chapters = [c for c in chapters if "Part" in c[1]]

        self.assertEqual(len(chapters), 2)

        # Check Part 1 text
        text1 = parser.content_texts[chapters[0][0]]
        # The parser explicitly replaces li with "1) Item A" style text
        self.assertIn("1) Item A", text1)
        self.assertIn("2) Item B", text1)

        # Check Part 2 text
        text2 = parser.content_texts[chapters[1][0]]
        # Should convert start="3" to "3) Item C"
        self.assertIn("3) Item C", text2)
        self.assertIn("4) Item D", text2)


if __name__ == "__main__":
    unittest.main()
