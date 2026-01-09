import unittest
import os
import shutil
import fitz  # PyMuPDF
from abogen.book_parser import PdfParser

class TestPdfStructure(unittest.TestCase):

    def setUp(self):
        self.test_dir = "tests/test_data_pdf"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        self.pdf_path = os.path.join(self.test_dir, "structure_test.pdf")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_pdf_structure_with_toc(self):
        # Create PDF
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text((50,50), "Page 1 Content")
        p2 = doc.new_page()
        p2.insert_text((50,50), "Page 2 Content")
        p3 = doc.new_page() # Chapter 2 start
        p3.insert_text((50,50), "Page 3 Content")
        p4 = doc.new_page()
        p4.insert_text((50,50), "Page 4 Content")
        
        # Add TOC:
        # 1. "Chap 1" -> Page 1
        # 2. "Chap 2" -> Page 3
        doc.set_toc([[1, "Chap 1", 1], [1, "Chap 2", 3]])
        doc.save(self.pdf_path)
        doc.close()

        parser = PdfParser(self.pdf_path)
        parser.process_content()
        
        nav = parser.processed_nav_structure
        
        # Expect 2 top level items
        self.assertEqual(len(nav), 2)
        self.assertEqual(nav[0]['title'], "Chap 1")
        self.assertEqual(nav[0]['src'], "page_1")
        self.assertEqual(nav[1]['title'], "Chap 2")
        self.assertEqual(nav[1]['src'], "page_3")
        
        # Check children of Chap 1 (Page 2 should be there)
        children_c1 = nav[0]['children']
        self.assertEqual(len(children_c1), 1)
        # The child should likely be titled "Page 2 - Page 2 Content" or similar
        self.assertIn("Page 2", children_c1[0]['title'])
        self.assertEqual(children_c1[0]['src'], "page_2")

        # Check children of Chap 2 (Page 4 should be there)
        children_c2 = nav[1]['children']
        self.assertEqual(len(children_c2), 1)
        self.assertIn("Page 4", children_c2[0]['title'])
        self.assertEqual(children_c2[0]['src'], "page_4")

    def test_pdf_structure_without_toc(self):
        # Create PDF without TOC
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text((50,50), "Start")
        p2 = doc.new_page()
        p2.insert_text((50,50), "End")
        doc.save(self.pdf_path)
        doc.close()

        parser = PdfParser(self.pdf_path)
        parser.process_content()
        
        nav = parser.processed_nav_structure
        
        # Expect 1 top level item (Pages)
        self.assertEqual(len(nav), 1)
        self.assertEqual(nav[0]['title'], "Pages")
        
        # Check children (all pages)
        children = nav[0]['children']
        self.assertEqual(len(children), 2)
        self.assertIn("Page 1", children[0]['title'])
        self.assertIn("Page 2", children[1]['title'])

    def test_pdf_structure_nested_toc(self):
        # Create PDF
        doc = fitz.open()
        p1 = doc.new_page() # Chap 1
        p2 = doc.new_page() # Sec 1.1
        p3 = doc.new_page() # Chap 2
        
        doc.set_toc([
            [1, "Chap 1", 1],
            [2, "Sec 1.1", 2],
            [1, "Chap 2", 3]
        ])
        doc.save(self.pdf_path)
        doc.close()

        parser = PdfParser(self.pdf_path)
        parser.process_content()
        nav = parser.processed_nav_structure

        self.assertEqual(len(nav), 2) # Chap 1, Chap 2
        self.assertEqual(nav[0]['title'], "Chap 1")
        
        # Chap 1 should have child Sec 1.1
        self.assertEqual(len(nav[0]['children']), 1)
        self.assertEqual(nav[0]['children'][0]['title'], "Sec 1.1")
        self.assertEqual(nav[0]['children'][0]['src'], "page_2")

if __name__ == "__main__":
    unittest.main()
