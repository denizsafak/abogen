import unittest
import os
import shutil
import zipfile
import sys
import logging
from ebooklib import epub

# Ensure import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.book_parser import get_book_parser


class TestEpubMissingFileErrorHandling(unittest.TestCase):
    """
    Tests for robust error handling and recovery in the book parser.
    """

    def setUp(self):
        self.test_dir = "tests/test_data_errors"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        self.broken_epub_path = os.path.join(self.test_dir, "missing_file.epub")

        # Suppress logging during tests to keep output clean,
        # or capture it if we want to assert on warnings.
        # For now, we just let it be or set level to ERROR.
        logging.getLogger().setLevel(logging.ERROR)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def _create_broken_epub(self):
        """
        Creates an EPUB where a file listed in the manifest is missing from the ZIP archive.
        """
        book = epub.EpubBook()
        book.set_identifier("broken123")
        book.set_title("Broken Book")

        # 1. Add a valid chapter
        c1 = epub.EpubHtml(title="Chapter 1", file_name="chap1.xhtml", lang="en")
        c1.content = "<h1>Chapter 1</h1><p>Survivable content.</p>"
        book.add_item(c1)

        # 2. Add a 'ghost' chapter that we will delete later
        c2 = epub.EpubHtml(title="Ghost Chapter", file_name="ghost.xhtml", lang="en")
        c2.content = "<h1>Ghost</h1><p>I will disappear.</p>"
        book.add_item(c2)

        book.spine = ["nav", c1, c2]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        temp_path = os.path.join(self.test_dir, "temp.epub")
        epub.write_epub(temp_path, book)

        # 3. Physically remove 'ghost.xhtml' from the ZIP
        with zipfile.ZipFile(temp_path, "r") as zin:
            with zipfile.ZipFile(self.broken_epub_path, "w") as zout:
                for item in zin.infolist():
                    # Copy everything EXCEPT the ghost file
                    # Note: ebooklib might put files in OEPS/ or EPUB/ folders depending on version,
                    # so checking "ghost.xhtml" presence in filename is safer.
                    if "ghost.xhtml" not in item.filename:
                        zout.writestr(item, zin.read(item.filename))

    def test_missing_file_recovery(self):
        """
        Verify that the parser recovers gracefully when a referenced file is missing.
        Should log a warning instead of raising KeyError.
        """
        self._create_broken_epub()

        try:
            parser = get_book_parser(self.broken_epub_path)
            parser.process_content()

            # 1. Ensure process didn't crash
            self.assertTrue(True, "Parser should not crash on missing file")

            # 2. Ensure valid content was extracted
            # Identify the ID for chap1.xhtml (usually file path based)
            # Since IDs can vary, we check if ANY content contains our known string
            chap1_found = False
            for text in parser.content_texts.values():
                if "Survivable content" in text:
                    chap1_found = True
                    break
            self.assertTrue(chap1_found, "The valid chapter should still be processed")

        except KeyError:
            self.fail("Parser raised KeyError instead of handling the missing file!")
        except Exception as e:
            self.fail(f"Parser raised unexpected exception: {e}")


if __name__ == "__main__":
    unittest.main()
