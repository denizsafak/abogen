import unittest
import os
import shutil
import sys
from ebooklib import epub

# Ensure import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.book_parser import get_book_parser


class TestEpubHeuristicNav(unittest.TestCase):
    """
    Tests for the heuristic fallback in _identify_nav_item (Step 4),
    where the parser scans ITEM_DOCUMENTs for <nav epub:type="toc">
    when no explicit ITEM_NAVIGATION is found.
    """

    def setUp(self):
        self.test_dir = "tests/test_data_heuristic"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        self.epub_path = os.path.join(self.test_dir, "heuristic_test.epub")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_heuristic_nav_discovery(self):
        book = epub.EpubBook()
        book.set_identifier("heuristic123")
        book.set_title("Heuristic Test Book")

        # 1. Add Content
        c1 = epub.EpubHtml(title="Chapter 1", file_name="chap1.xhtml", lang="en")
        c1.content = "<h1>Chapter 1</h1><p>Text</p>"
        book.add_item(c1)

        # 2. Add a Nav file BUT as a regular EpubHtml (ITEM_DOCUMENT)
        # We do NOT use EpubNav. We do NOT look like a standard nav file if possible,
        # but content must contain the magical signature.
        nav_content = """
        <html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
        <body>
            <nav epub:type="toc" id="toc">
                <h1>Hidden TOC</h1>
                <ol>
                    <li><a href="chap1.xhtml">Chapter 1</a></li>
                </ol>
            </nav>
        </body>
        </html>
        """
        # Filename intentionally generic/obscure to avoid filename-based heuristics
        # (though current code checks content, not just filename)
        nav_file = epub.EpubHtml(title="Hidden Nav", file_name="content_toc.xhtml")
        nav_file.content = nav_content
        book.add_item(nav_file)

        # 3. Setup Spine
        book.spine = [nav_file, c1]

        # 4. Write EPUB
        epub.write_epub(self.epub_path, book)

        # 5. Patch OPF to ensure ebooklib didn't sneakily add ITEM_NAVIGATION or toc="ncx"
        import zipfile

        patched = False
        with zipfile.ZipFile(self.epub_path, "r") as zin:
            opf_content = zin.read("EPUB/content.opf").decode("utf-8")

            # Remove toc="ncx" attribute if present (causes crash if no NCX)
            if 'toc="ncx"' in opf_content:
                opf_content = opf_content.replace('toc="ncx"', "")
                patched = True

            # Ideally we'd verify properties="nav" isn't there, but EpubHtml shouldn't add it.
            # If ebooklib added it, we might need to strip it to force heuristic.
            if 'properties="nav"' in opf_content:
                opf_content = opf_content.replace('properties="nav"', "")
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

        # 6. Verify our setup: Ensure NO ITEM_NAVIGATION exists
        # We can inspect using ebooklib again
        import ebooklib

        check_book = epub.read_epub(self.epub_path)
        nav_items = list(check_book.get_items_of_type(ebooklib.ITEM_NAVIGATION))
        self.assertEqual(
            len(nav_items), 0, "Setup failed: explicit navigation item found!"
        )

        # 7. Run Parser
        parser = get_book_parser(self.epub_path)
        parser.process_content()
        chapters = parser.get_chapters()

        # 8. Assertions
        # Should have found the nav via content scanning
        chapter_titles = [c[1] for c in chapters]
        self.assertIn("Chapter 1", chapter_titles)

        # Also verify we hit the "html" type in identification
        # We can't easily check private variables, but success implies it worked.


if __name__ == "__main__":
    unittest.main()
