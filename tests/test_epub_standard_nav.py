import unittest
import os
import shutil
import sys
from ebooklib import epub
import ebooklib
from unittest.mock import MagicMock

# Ensure import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.book_parser import get_book_parser


class TestEpubStandardNav(unittest.TestCase):
    """
    Tests for the standard ITEM_NAVIGATION discovery in _identify_nav_item.
    Refactored to explicitly test different discovery paths defined in the parser.
    """

    def setUp(self):
        self.test_dir = "tests/test_data_standard_nav"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        self.epub_path = os.path.join(self.test_dir, "standard_nav_test.epub")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def _create_and_load_epub(self):
        """Helper to create a basic EPUB and return a loaded parser."""
        book = epub.EpubBook()
        book.set_identifier("stdnav123")
        book.set_title("Standard Nav Test")

        c1 = epub.EpubHtml(title="Chapter 1", file_name="chap1.xhtml", lang="en")
        c1.content = "<h1>Chapter 1</h1><p>Text 1</p>"
        book.add_item(c1)

        # Use Standard EpubNav
        nav = epub.EpubNav()
        book.add_item(nav)
        book.spine = [nav, c1]

        epub.write_epub(self.epub_path, book)

        # "Zip Surgery" Patch:
        # ebooklib unconditionally adds `toc="ncx"` to the spine, even for EPUB 3 files that purely use HTML Nav.
        # This creates a dangling reference to a non-existent "ncx" item, causing ebooklib to crash on read.
        # We manually remove this attribute to ensure the test EPUB is valid and readable.
        # TODO - find real world examples of EPUB 3 files that use HTML Nav
        import zipfile

        patched = False
        with zipfile.ZipFile(self.epub_path, "r") as zin:
            opf_content = zin.read("EPUB/content.opf").decode("utf-8")
            if 'toc="ncx"' in opf_content:
                opf_content = opf_content.replace('toc="ncx"', "")
                patched = True
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
        parser.load()
        return parser

    def test_discovery_by_item_navigation_type(self):
        """
        Scenario 1: The item is explicitly identified as ITEM_NAVIGATION (4).
        This exercises the first branch of _identify_nav_item.
        """
        parser = self._create_and_load_epub()

        # Inject an item that mocks the ITEM_NAVIGATION type behavior
        # (This simulates a library/parser that correctly types the item as 4)
        mock_nav = MagicMock()
        mock_nav.get_name.return_value = "nav.xhtml"
        mock_nav.get_type.return_value = ebooklib.ITEM_NAVIGATION

        # We append this mock to the book items to ensure get_items_of_type(ITEM_NAVIGATION) finds it
        parser.book.items.append(mock_nav)

        nav_item, nav_type = parser._identify_nav_item()

        self.assertEqual(nav_type, "html")
        self.assertEqual(nav_item.get_name(), "nav.xhtml")
        # Verify we are getting the object we expect (implied by success)

    def test_discovery_by_nav_property(self):
        """
        Scenario 2: The item is ITEM_DOCUMENT (9) but has properties=['nav'].
        This is the standard EPUB 3 behavior and exercises the fallback branch.
        """
        parser = self._create_and_load_epub()

        # Locate the generic 'nav' item loaded by ebooklib
        original_nav = parser.book.get_item_with_id("nav")
        self.assertIsNotNone(original_nav)

        # "Fix" the object to match what we expect from a correct EPUB 3 read:
        # It should have properties=['nav'].
        # We use a real EpubNav object to ensure structural correctness.
        proper_nav = epub.EpubNav(uid=original_nav.id, file_name=original_nav.file_name)
        proper_nav.content = original_nav.content
        proper_nav.properties = ["nav"]

        # Swap it into the book items list
        try:
            idx = parser.book.items.index(original_nav)
            parser.book.items[idx] = proper_nav
        except ValueError:
            self.fail("Could not find original nav item to swap")

        nav_item, nav_type = parser._identify_nav_item()

        self.assertEqual(nav_type, "html")
        self.assertEqual(nav_item.get_name(), "nav.xhtml")
        # Check that we actually found the one with properties
        self.assertEqual(getattr(nav_item, "properties", []), ["nav"])


if __name__ == "__main__":
    unittest.main()
