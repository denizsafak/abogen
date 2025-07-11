import re
import html
import ebooklib
import base64
import fitz  # PyMuPDF for PDF support
from ebooklib import epub
from bs4 import BeautifulSoup, NavigableString
from PyQt5.QtWidgets import (
    QDialog,
    QTreeWidget,
    QTreeWidgetItem,
    QDialogButtonBox,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QTreeWidgetItemIterator,
    QSplitter,
    QWidget,
    QPushButton,
    QCheckBox,
    QMenu,
    QLabel,
)
from PyQt5.QtCore import Qt
from utils import clean_text, calculate_text_length
import os
import logging  # Add logging
import urllib.parse

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class HandlerDialog(QDialog):
    # Class variables to remember checkbox states between dialog instances
    _save_chapters_separately = False
    _merge_chapters_at_end = True
    _save_as_project = False  # New class variable for save_as_project option

    def __init__(self, book_path, file_type=None, checked_chapters=None, parent=None):
        super().__init__(parent)

        # Determine file type if not explicitly provided
        self.file_type = file_type or (
            "pdf" if book_path.lower().endswith(".pdf") else "epub"
        )
        self.book_path = book_path

        # Extract book name from file path
        book_name = os.path.splitext(os.path.basename(book_path))[0]

        # Set window title based on file type and book name
        self.setWindowTitle(
            f'Select {"Chapters" if self.file_type == "epub" else "Pages"} - {book_name}'
        )
        self.resize(1200, 900)
        self._block_signals = False  # Flag to prevent recursive signals
        # Configure window: remove help button and allow resizing
        self.setWindowFlags(
            Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMaximizeButtonHint
        )
        self.setWindowModality(Qt.NonModal)
        # Initialize save chapters flags from class variables
        self.save_chapters_separately = HandlerDialog._save_chapters_separately
        self.merge_chapters_at_end = HandlerDialog._merge_chapters_at_end
        self.save_as_project = HandlerDialog._save_as_project

        # Load the book based on file type
        try:
            self.book = epub.read_epub(book_path) if self.file_type == "epub" else None
        except KeyError as e:
            logging.error(
                f"EPUB file is missing a referenced file: {e}. Skipping missing file."
            )
            # Try to patch ebooklib to skip missing files (monkey-patch read_file)
            import types

            orig_read_file = None
            try:
                from ebooklib import epub as _epub_module

                reader_class = _epub_module.EpubReader
                orig_read_file = reader_class.read_file

                def safe_read_file(self, name):
                    try:
                        return orig_read_file(self, name)
                    except KeyError:
                        logging.warning(
                            f"Missing file in EPUB: {name}. Returning empty bytes."
                        )
                        return b""

                reader_class.read_file = safe_read_file
                self.book = epub.read_epub(book_path)
                reader_class.read_file = orig_read_file  # Restore
            except Exception as patch_e:
                logging.error(f"Failed to patch ebooklib for missing files: {patch_e}")
                raise e
        self.pdf_doc = fitz.open(book_path) if self.file_type == "pdf" else None

        # Extract book metadata
        self.book_metadata = self._extract_book_metadata()

        # Initialize UI elements that are used in other methods
        self.save_chapters_checkbox = None
        self.merge_chapters_checkbox = None

        # Build treeview
        self.treeWidget = QTreeWidget(self)
        self.treeWidget.setHeaderHidden(True)
        self.treeWidget.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.treeWidget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.treeWidget.customContextMenuRequested.connect(self.on_tree_context_menu)

        # Initialize checked_chapters set
        self.checked_chapters = set(checked_chapters) if checked_chapters else set()

        # For storing content and lengths
        self.content_texts = {}
        self.content_lengths = {}

        # Pre-process content based on file type
        self._preprocess_content()

        # Add "Information" item at the beginning of the tree
        info_item = QTreeWidgetItem(self.treeWidget, ["Information"])
        info_item.setData(0, Qt.UserRole, "info:bookinfo")
        info_item.setFlags(info_item.flags() & ~Qt.ItemIsUserCheckable)
        font = info_item.font(0)
        font.setBold(True)
        info_item.setFont(0, font)

        # Build tree based on file type
        self._build_tree()

        # Hide expand/collapse decoration if there are no parent items
        has_parents = False
        for i in range(self.treeWidget.topLevelItemCount()):
            if self.treeWidget.topLevelItem(i).childCount() > 0:
                has_parents = True
                break
        self.treeWidget.setRootIsDecorated(has_parents)

        # Setup UI (creates save_chapters_checkbox and other UI elements)
        self._setup_ui()

        # Run auto-check after UI is setup
        if not self._are_provided_checks_relevant():
            self._run_auto_check()

        # Connect signals
        self.treeWidget.currentItemChanged.connect(self.update_preview)
        self.treeWidget.itemChanged.connect(self.handle_item_check)
        self.treeWidget.itemChanged.connect(lambda _: self._update_checkbox_states())
        self.treeWidget.itemDoubleClicked.connect(self.handle_item_double_click)

        # Select first item and expand all
        self.treeWidget.expandAll()
        if self.treeWidget.topLevelItemCount() > 0:
            self.treeWidget.setCurrentItem(self.treeWidget.topLevelItem(0))
            self.treeWidget.setFocus()

        # Update checkbox states
        self._update_checkbox_states()

    def _preprocess_content(self):
        """Pre-process content from the document"""
        if self.file_type == "epub":
            try:
                self._process_epub_content_nav()  # Use the new navigation-based method
            except Exception as e:
                logging.error(
                    f"Error processing EPUB with navigation: {e}. Falling back to TOC/spine.",
                    exc_info=True,
                )
                # Fallback to a simpler spine-based processing if nav fails
                self._process_epub_content_spine_fallback()
        else:
            self._preprocess_pdf_content()

    def _preprocess_pdf_content(self):
        """Pre-process all page contents from PDF document"""
        for page_num in range(len(self.pdf_doc)):
            text = clean_text(self.pdf_doc[page_num].get_text())
            # Remove bracketed numbers (citations, footnotes)
            text = re.sub(r"\[\s*\d+\s*\]", "", text)

            # Remove standalone page numbers (numbers alone on a line)
            text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)

            # Remove page numbers at the end of paragraphs
            # This pattern looks for digits surrounded by whitespace at the end of paragraphs
            text = re.sub(r"\s+\d+\s*$", "", text, flags=re.MULTILINE)

            # Also remove page numbers followed by a hyphen or dash at paragraph end
            # (common in headers/footers like "- 42 -")
            text = re.sub(r"\s+[-–—]\s*\d+\s*[-–—]?\s*$", "", text, flags=re.MULTILINE)

            page_id = f"page_{page_num+1}"
            self.content_texts[page_id] = text
            self.content_lengths[page_id] = calculate_text_length(text)

    def _process_epub_content_spine_fallback(self):
        """Fallback EPUB processing based purely on spine order."""
        logging.info("Using spine fallback for EPUB processing.")
        self.doc_content = {}
        spine_docs = []
        for spine_item_tuple in self.book.spine:
            item_id = spine_item_tuple[0]
            item = self.book.get_item_with_id(item_id)
            if item:
                spine_docs.append(item.get_name())
            else:
                logging.warning(f"Spine item with id '{item_id}' not found.")

        # Cache content
        for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            href = item.get_name()
            if href in spine_docs:
                try:
                    html_content = item.get_content().decode("utf-8", errors="ignore")
                    self.doc_content[href] = html_content
                except Exception as e:
                    logging.error(f"Error decoding content for {href}: {e}")
                    self.doc_content[href] = ""

        # Create a simple TOC based on spine order
        synthetic_toc = []
        self.content_texts = {}
        self.content_lengths = {}
        for i, doc_href in enumerate(spine_docs):
            html_content = self.doc_content.get(doc_href, "")
            if html_content:
                soup = BeautifulSoup(html_content, "html.parser")
                # Remove sup and sub tags
                for tag in soup.find_all(["sup", "sub"]):
                    tag.decompose()
                text = clean_text(soup.get_text()).strip()
                if text:
                    # Use doc_href as the identifier
                    self.content_texts[doc_href] = text
                    self.content_lengths[doc_href] = len(text)
                    # Create a synthetic TOC entry
                    title = f"Chapter {i+1}: {doc_href}"
                    # Try to get a better title from <h1> or <title>
                    h1 = soup.find("h1")
                    if h1 and h1.get_text(strip=True):
                        title = h1.get_text(strip=True)
                    else:
                        title_tag = soup.find("title")
                        if title_tag and title_tag.get_text(strip=True):
                            title = title_tag.get_text(strip=True)

                    synthetic_toc.append(
                        (epub.Link(doc_href, title, doc_href), [])
                    )  # Wrap in tuple and empty list for compatibility

        # Replace book.toc with the synthetic one if it was empty or fallback was triggered
        if not self.book.toc or not hasattr(
            self, "processed_nav_structure"
        ):  # Check if nav processing failed
            self.book.toc = synthetic_toc
            logging.info(f"Generated synthetic TOC with {len(synthetic_toc)} entries.")

    def _process_epub_content_nav(self):
        """
        Process EPUB content using ITEM_NAVIGATION (NAV HTML) or ITEM_NCX.
        Globally orders navigation entries and slices content between them.
        """
        logging.info(
            "Attempting to process EPUB using navigation document (NAV/NCX)..."
        )
        nav_item = None
        nav_type = None

        # 1. Check ITEM_NAVIGATION for actual NAV HTML (.xhtml/.html)
        nav_items = list(self.book.get_items_of_type(ebooklib.ITEM_NAVIGATION))
        if nav_items:
            # Prefer files explicitly named 'nav.xhtml' or similar
            preferred_nav = next(
                (
                    item
                    for item in nav_items
                    if "nav" in item.get_name().lower()
                    and item.get_name().lower().endswith((".xhtml", ".html"))
                ),
                None,
            )
            if preferred_nav:
                nav_item = preferred_nav
                nav_type = "html"
                logging.info(f"Found preferred NAV HTML item: {nav_item.get_name()}")
            else:
                # Check if any ITEM_NAVIGATION is actually HTML
                html_nav = next(
                    (
                        item
                        for item in nav_items
                        if item.get_name().lower().endswith((".xhtml", ".html"))
                    ),
                    None,
                )
                if html_nav:
                    nav_item = html_nav
                    nav_type = "html"
                    logging.info(
                        f"Found NAV HTML item in ITEM_NAVIGATION: {html_nav.get_name()}"
                    )

        # 2. If no NAV HTML found via ITEM_NAVIGATION, check if ITEM_NAVIGATION points to NCX
        if not nav_item and nav_items:
            ncx_in_nav = next(
                (
                    item
                    for item in nav_items
                    if item.get_name().lower().endswith(".ncx")
                ),
                None,
            )
            if ncx_in_nav:
                nav_item = ncx_in_nav
                nav_type = "ncx"
                logging.info(
                    f"Found NCX item via ITEM_NAVIGATION: {ncx_in_nav.get_name()}"
                )

        # 3. If still no nav_item, check for ITEM_NCX directly
        if not nav_item:
            ncx_items = list(self.book.get_items_of_type(ebooklib.ITEM_NCX))
            if ncx_items:
                nav_item = ncx_items[0]  # Take the first one
                nav_type = "ncx"
                logging.info(f"Found NCX item via ITEM_NCX: {ncx_items[0].get_name()}")

        # 4. If no navigation item found by any method, trigger fallback
        if not nav_item or not nav_type:
            logging.warning(
                "No suitable EPUB navigation document (NAV HTML or NCX) found. Falling back."
            )
            raise ValueError("No navigation document found")  # Trigger fallback

        # Determine parser based on the confirmed nav_type
        parser_type = "html.parser" if nav_type == "html" else "xml"
        logging.info(f"Using parser: '{parser_type}' for {nav_item.get_name()}")
        try:
            nav_content = nav_item.get_content().decode("utf-8", errors="ignore")
            nav_soup = BeautifulSoup(nav_content, parser_type)
        except Exception as e:
            logging.error(
                f"Failed to parse navigation content ({nav_item.get_name()}) using {parser_type}: {e}",
                exc_info=True,
            )
            raise ValueError(
                f"Failed to parse navigation content: {e}"
            )  # Trigger fallback

        # --- Rest of the processing logic ---
        # 1. Cache all document HTML and determine spine order (no changes needed here)
        self.doc_content = {}
        spine_docs = []
        for spine_item_tuple in self.book.spine:
            item_id = spine_item_tuple[0]
            item = self.book.get_item_with_id(item_id)
            if item:
                spine_docs.append(item.get_name())
            else:
                logging.warning(f"Spine item with id '{item_id}' not found.")
        doc_order = {href: i for i, href in enumerate(spine_docs)}
        # Add a mapping for unquoted (decoded) hrefs as well
        doc_order_decoded = {
            urllib.parse.unquote(href): i for href, i in doc_order.items()
        }

        # Clear previous content/lengths before processing
        self.content_texts = {}
        self.content_lengths = {}

        for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            href = item.get_name()
            if href in doc_order or any(
                href in nav_point.get("src", "")
                for nav_point in nav_soup.find_all(["content", "a"])
            ):
                try:
                    html_content = item.get_content().decode("utf-8", errors="ignore")
                    self.doc_content[href] = html_content
                except Exception as e:
                    logging.error(f"Error decoding content for {href}: {e}")
                    self.doc_content[href] = ""

        # 2. Extract and order navigation entries globally
        ordered_nav_entries = []

        # Define find_position locally or ensure self._find_position_robust is used correctly
        # Using self._find_position_robust is preferred as it's a method of the class
        find_position_func = self._find_position_robust

        # Store the parsed structure for tree building later
        self.processed_nav_structure = []

        # Call the correct parsing function based on confirmed nav_type
        parse_successful = False
        if nav_type == "ncx":
            nav_map = nav_soup.find("navMap")
            if nav_map:
                logging.info("Parsing NCX <navMap>...")
                for nav_point in nav_map.find_all("navPoint", recursive=False):
                    self._parse_ncx_navpoint(
                        nav_point,
                        ordered_nav_entries,
                        doc_order,
                        doc_order_decoded,
                        self.processed_nav_structure,
                        find_position_func,
                    )
                parse_successful = bool(
                    ordered_nav_entries
                )  # Success if entries were added
            else:
                logging.warning("Could not find <navMap> in NCX file.")
        elif nav_type == "html":
            logging.info("Parsing NAV HTML...")
            toc_nav = nav_soup.find("nav", attrs={"epub:type": "toc"})
            if not toc_nav:
                # Fallback: look for any <nav> element containing an <ol>
                all_navs = nav_soup.find_all("nav")
                for nav in all_navs:
                    if nav.find("ol"):
                        toc_nav = nav
                        logging.info("Found fallback TOC structure in <nav> with <ol>.")
                        break
            if toc_nav:
                top_ol = toc_nav.find("ol", recursive=False)
                if top_ol:
                    for li in top_ol.find_all("li", recursive=False):
                        self._parse_html_nav_li(
                            li,
                            ordered_nav_entries,
                            doc_order,
                            doc_order_decoded,
                            self.processed_nav_structure,
                            find_position_func,
                        )
                    parse_successful = bool(
                        ordered_nav_entries
                    )  # Success if entries were added
                else:
                    logging.warning("Found <nav> for TOC but no top-level <ol> inside.")
            else:
                logging.warning(
                    "Could not find TOC structure (<nav epub:type='toc'> or <nav><ol>) in NAV HTML."
                )

        # Handle case where parsing ran but found no valid entries OR parsing failed
        if not parse_successful:
            logging.warning(
                "Navigation parsing completed but found no valid entries, or parsing failed. Falling back."
            )
            raise ValueError("No valid navigation entries found after parsing")

        # Sort entries globally by document order and position within the document
        ordered_nav_entries.sort(key=lambda x: (x["doc_order"], x["position"]))
        logging.info(f"Sorted {len(ordered_nav_entries)} navigation entries.")

        # 3. Slice content ONLY between sorted TOC entries
        num_entries = len(ordered_nav_entries)
        for i in range(num_entries):
            current_entry = ordered_nav_entries[i]
            current_src = current_entry["src"]
            current_doc = current_entry["doc_href"]
            current_pos = current_entry["position"]
            current_doc_html = self.doc_content.get(current_doc, "")

            start_slice_pos = current_pos
            slice_html = ""

            next_entry = ordered_nav_entries[i + 1] if (i + 1) < num_entries else None

            if next_entry:
                next_doc = next_entry["doc_href"]
                next_pos = next_entry["position"]

                # Always include all content from current position to next position, even if next_doc is before current_doc
                if current_doc == next_doc:
                    slice_html = current_doc_html[start_slice_pos:next_pos]
                else:
                    # Collect all content from current_doc (from start_slice_pos to end),
                    # then all intermediate docs (in spine order),
                    # then up to next_pos in next_doc (even if next_doc is before current_doc in spine)
                    slice_html = current_doc_html[start_slice_pos:]
                    docs_between = []
                    try:
                        idx_current = spine_docs.index(current_doc)
                        idx_next = spine_docs.index(next_doc)
                        if idx_current < idx_next:
                            for doc_idx in range(idx_current + 1, idx_next):
                                docs_between.append(spine_docs[doc_idx])
                        elif idx_current > idx_next:
                            for doc_idx in range(idx_current + 1, len(spine_docs)):
                                docs_between.append(spine_docs[doc_idx])
                            for doc_idx in range(0, idx_next):
                                docs_between.append(spine_docs[doc_idx])
                    except Exception:
                        pass
                    for doc_href in docs_between:
                        slice_html += self.doc_content.get(doc_href, "")
                    next_doc_html = self.doc_content.get(next_doc, "")
                    slice_html += next_doc_html[:next_pos]
            else:
                # Last TOC entry: include all content from current position to end of book
                slice_html = current_doc_html[start_slice_pos:]
                try:
                    idx_current = spine_docs.index(current_doc)
                    for doc_idx in range(idx_current + 1, len(spine_docs)):
                        intermediate_doc_href = spine_docs[doc_idx]
                        slice_html += self.doc_content.get(intermediate_doc_href, "")
                except Exception:
                    pass

            if slice_html.strip():
                slice_soup = BeautifulSoup(slice_html, "html.parser")
                # Add double newlines after <p> and <div> tags
                for tag in slice_soup.find_all(["p", "div"]):
                    tag.append("\n\n")
                for tag in slice_soup.find_all(["sup", "sub"]):
                    tag.decompose()
                text = clean_text(slice_soup.get_text()).strip()
                if text:
                    self.content_texts[current_src] = text
                    self.content_lengths[current_src] = len(text)
                else:
                    self.content_texts[current_src] = ""
                    self.content_lengths[current_src] = 0
            else:
                self.content_texts[current_src] = ""
                self.content_lengths[current_src] = 0

        # 4. Extract text and store using the original TOC entry src as the key
        if ordered_nav_entries:
            first_entry = ordered_nav_entries[0]
            first_doc_href = first_entry["doc_href"]
            first_pos = first_entry["position"]
            first_doc_order = first_entry["doc_order"]
            prefix_html = ""

            for doc_idx in range(first_doc_order):
                if doc_idx < len(spine_docs):
                    intermediate_doc_href = spine_docs[doc_idx]
                    prefix_html += self.doc_content.get(intermediate_doc_href, "")
                else:
                    logging.warning(
                        f"Document index {doc_idx} out of bounds for spine (length {len(spine_docs)})."
                    )

            first_doc_html = self.doc_content.get(first_doc_href, "")
            prefix_html += first_doc_html[:first_pos]

            if prefix_html.strip():
                prefix_soup = BeautifulSoup(prefix_html, "html.parser")
                for tag in prefix_soup.find_all(["sup", "sub"]):
                    tag.decompose()
                prefix_text = clean_text(prefix_soup.get_text()).strip()

                if prefix_text:
                    prefix_chapter_src = "internal:prefix_content"
                    self.content_texts[prefix_chapter_src] = prefix_text
                    self.content_lengths[prefix_chapter_src] = len(prefix_text)
                    self.processed_nav_structure.insert(
                        0,
                        {
                            "src": prefix_chapter_src,
                            "title": "Introduction",
                            "children": [],
                        },
                    )
                    logging.info(
                        f"Added prefix content chapter '{prefix_chapter_src}'."
                    )

        logging.info(
            f"Finished processing EPUB navigation. Found {len(self.content_texts)} content sections linked to TOC."
        )

    def _parse_ncx_navpoint(
        self,
        nav_point,
        ordered_entries,
        doc_order,
        doc_order_decoded,
        tree_structure_list,
        find_position_func,
    ):
        nav_label = nav_point.find("navLabel")
        content = nav_point.find("content")
        title = (
            nav_label.find("text").get_text(strip=True)
            if nav_label and nav_label.find("text")
            else "Untitled Section"
        )
        src = content["src"] if content and "src" in content.attrs else None

        current_entry_node = {"title": title, "src": src, "children": []}

        if src:
            base_href, fragment = src.split("#", 1) if "#" in src else (src, None)
            # Try both original and decoded hrefs
            doc_key = None
            if base_href in doc_order:
                doc_key = base_href
                doc_idx = doc_order[base_href]
            elif urllib.parse.unquote(base_href) in doc_order:
                doc_key = urllib.parse.unquote(base_href)
                doc_idx = doc_order[doc_key]
            elif base_href in doc_order_decoded:
                doc_key = base_href
                doc_idx = doc_order_decoded[base_href]
            elif urllib.parse.unquote(base_href) in doc_order_decoded:
                doc_key = urllib.parse.unquote(base_href)
                doc_idx = doc_order_decoded[doc_key]
            else:
                logging.warning(
                    f"Navigation entry '{title}' points to '{base_href}', which is not in the spine or document list."
                )
                current_entry_node["has_content"] = False
                doc_key = None
            if doc_key is not None:
                position = find_position_func(doc_key, fragment)
                entry_data = {
                    "src": src,
                    "title": title,
                    "doc_href": doc_key,
                    "position": position,
                    "doc_order": doc_idx,
                }
                ordered_entries.append(entry_data)
                current_entry_node["has_content"] = True
        else:
            logging.warning(f"Navigation entry '{title}' has no 'src' attribute.")
            current_entry_node["has_content"] = False

        child_navpoints = nav_point.find_all("navPoint", recursive=False)
        if child_navpoints:
            for child_np in child_navpoints:
                # Pass find_position_func down recursively
                self._parse_ncx_navpoint(
                    child_np,
                    ordered_entries,
                    doc_order,
                    doc_order_decoded,
                    current_entry_node["children"],
                    find_position_func,
                )

        if title and (
            current_entry_node.get("has_content", False)
            or current_entry_node["children"]
        ):
            tree_structure_list.append(current_entry_node)

    def _parse_html_nav_li(
        self,
        li_element,
        ordered_entries,
        doc_order,
        doc_order_decoded,
        tree_structure_list,
        find_position_func,
    ):
        link = li_element.find("a", recursive=False)
        span_text = li_element.find("span", recursive=False)
        title = "Untitled Section"
        src = None
        current_entry_node = {"children": []}

        if link and "href" in link.attrs:
            src = link["href"]
            title = link.get_text(strip=True) or title
            if not title.strip() and span_text:
                title = span_text.get_text(strip=True) or title
            if not title.strip():
                li_text = "".join(
                    t for t in li_element.contents if isinstance(t, NavigableString)
                ).strip()
                title = li_text or title
        elif span_text:
            title = span_text.get_text(strip=True) or title
            if not title.strip():
                li_text = "".join(
                    t for t in li_element.contents if isinstance(t, NavigableString)
                ).strip()
                title = li_text or title
        else:
            li_text = "".join(
                t for t in li_element.contents if isinstance(t, NavigableString)
            ).strip()
            title = li_text or title

        current_entry_node["title"] = title
        current_entry_node["src"] = src

        if src:
            base_href, fragment = src.split("#", 1) if "#" in src else (src, None)
            # Try both original and decoded hrefs
            doc_key = None
            if base_href in doc_order:
                doc_key = base_href
                doc_idx = doc_order[base_href]
            elif urllib.parse.unquote(base_href) in doc_order:
                doc_key = urllib.parse.unquote(base_href)
                doc_idx = doc_order[doc_key]
            elif base_href in doc_order_decoded:
                doc_key = base_href
                doc_idx = doc_order_decoded[base_href]
            elif urllib.parse.unquote(base_href) in doc_order_decoded:
                doc_key = urllib.parse.unquote(base_href)
                doc_idx = doc_order_decoded[doc_key]
            else:
                logging.warning(
                    f"Navigation entry '{title}' points to '{base_href}', which is not in the spine or document list."
                )
                current_entry_node["has_content"] = False
                doc_key = None
            if doc_key is not None:
                position = find_position_func(doc_key, fragment)
                entry_data = {
                    "src": src,
                    "title": title,
                    "doc_href": doc_key,
                    "position": position,
                    "doc_order": doc_idx,
                }
                ordered_entries.append(entry_data)
                current_entry_node["has_content"] = True
        else:
            current_entry_node["has_content"] = False

        child_ol = li_element.find("ol", recursive=False)
        if child_ol:
            for child_li in child_ol.find_all("li", recursive=False):
                # Pass find_position_func down recursively
                self._parse_html_nav_li(
                    child_li,
                    ordered_entries,
                    doc_order,
                    doc_order_decoded,
                    current_entry_node["children"],
                    find_position_func,
                )

        if title and (
            current_entry_node.get("has_content", False)
            or current_entry_node["children"]
        ):
            tree_structure_list.append(current_entry_node)

    def _find_position_robust(self, doc_href, fragment_id):
        if doc_href not in self.doc_content:
            logging.warning(f"Document '{doc_href}' not found in cached content.")
            return 0
        html_content = self.doc_content[doc_href]
        if not fragment_id:
            return 0

        try:
            temp_soup = BeautifulSoup(f"<div>{html_content}</div>", "html.parser")
            target_element = temp_soup.find(id=fragment_id)
            if target_element:
                tag_str = str(target_element)
                pos = html_content.find(tag_str[: min(len(tag_str), 200)])
                if pos != -1:
                    logging.debug(
                        f"Found position for id='{fragment_id}' in {doc_href} using BeautifulSoup: {pos}"
                    )
                    return pos
        except Exception as e:
            logging.warning(
                f"BeautifulSoup failed to find id='{fragment_id}' in {doc_href}: {e}"
            )

        safe_fragment_id = re.escape(fragment_id)
        id_name_pattern = re.compile(
            f"<[^>]+(?:id|name)\\s*=\\s*[\"']{safe_fragment_id}[\"']", re.IGNORECASE
        )
        match = id_name_pattern.search(html_content)
        if match:
            pos = match.start()
            logging.debug(
                f"Found position for id/name='{fragment_id}' in {doc_href} using regex: {pos}"
            )
            return pos

        id_match_str = f'id="{fragment_id}"'
        name_match_str = f'name="{fragment_id}"'
        id_pos = html_content.find(id_match_str)
        name_pos = html_content.find(name_match_str)

        pos = -1
        if id_pos != -1 and name_pos != -1:
            pos = min(id_pos, name_pos)
        elif id_pos != -1:
            pos = id_pos
        elif name_pos != -1:
            pos = name_pos

        if pos != -1:
            tag_start_pos = html_content.rfind("<", 0, pos)
            final_pos = tag_start_pos if tag_start_pos != -1 else 0
            logging.debug(
                f"Found position for id/name='{fragment_id}' in {doc_href} using string search: {final_pos}"
            )
            return final_pos

        logging.warning(
            f"Anchor '{fragment_id}' not found in {doc_href}. Defaulting to position 0."
        )
        return 0

    def _build_tree(self):
        self.treeWidget.clear()

        info_item = QTreeWidgetItem(self.treeWidget, ["Information"])
        info_item.setData(0, Qt.UserRole, "info:bookinfo")
        info_item.setFlags(info_item.flags() & ~Qt.ItemIsUserCheckable)
        font = info_item.font(0)
        font.setBold(True)
        info_item.setFont(0, font)

        if self.file_type == "epub":
            if (
                hasattr(self, "processed_nav_structure")
                and self.processed_nav_structure
            ):
                self._build_epub_tree_from_nav(
                    self.processed_nav_structure, self.treeWidget
                )
            else:
                logging.warning("Building EPUB tree using fallback book.toc.")
                self._build_epub_tree_fallback(self.book.toc, self.treeWidget)
        else:
            self._build_pdf_tree()

        has_parents = False
        iterator = QTreeWidgetItemIterator(
            self.treeWidget, QTreeWidgetItemIterator.HasChildren
        )
        if iterator.value():
            has_parents = True
        self.treeWidget.setRootIsDecorated(has_parents)

    def _update_checkbox_states(self):
        """Update the checkbox states based on the current checked chapters."""
        for i in range(self.treeWidget.topLevelItemCount()):
            item = self.treeWidget.topLevelItem(i)
            self._update_item_checkbox_state(item)

    def _build_epub_tree_from_nav(
        self, nav_nodes, parent_item, seen_content_hashes=None
    ):
        if seen_content_hashes is None:
            seen_content_hashes = set()
        for node in nav_nodes:
            title = node.get("title", "Unknown")
            src = node.get("src")
            children = node.get("children", [])

            item = QTreeWidgetItem(parent_item, [title])
            item.setData(0, Qt.UserRole, src)

            is_empty = (
                src
                and (src in self.content_texts)
                and (not self.content_texts[src].strip())
            )
            is_duplicate = False
            if src and src in self.content_texts and self.content_texts[src].strip():
                content_hash = hash(self.content_texts[src])
                if content_hash in seen_content_hashes:
                    is_duplicate = True
                else:
                    seen_content_hashes.add(content_hash)

            if src and not is_empty and not is_duplicate:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                is_checked = src in self.checked_chapters
                item.setCheckState(0, Qt.Checked if is_checked else Qt.Unchecked)
            elif is_duplicate:
                # Mark as duplicate and remove checkbox
                item.setText(0, f"{title} (Duplicate)")
                item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            elif children:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Unchecked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)

            if children:
                self._build_epub_tree_from_nav(children, item, seen_content_hashes)

    def _build_epub_tree_fallback(self, toc_entries, parent_item):
        for entry in toc_entries:
            href, title, children = None, "Unknown", []
            entry_obj = None
            if isinstance(entry, ebooklib.epub.Link):
                href, title = entry.href, entry.title or entry.href
                entry_obj = entry
            elif isinstance(entry, tuple) and len(entry) >= 1:
                section_or_link = entry[0]
                entry_obj = section_or_link
                if isinstance(section_or_link, ebooklib.epub.Section):
                    title = section_or_link.title
                    href = getattr(section_or_link, "href", None)
                elif isinstance(section_or_link, ebooklib.epub.Link):
                    href, title = (
                        section_or_link.href,
                        section_or_link.title or section_or_link.href,
                    )

                if len(entry) > 1 and isinstance(entry[1], list):
                    children = entry[1]
            else:
                continue

            item = QTreeWidgetItem(parent_item, [title])
            item.setData(0, Qt.UserRole, href)

            has_content = (
                href and href in self.content_texts and self.content_texts[href].strip()
            )

            if has_content or children:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                is_checked = href and href in self.checked_chapters
                item.setCheckState(0, Qt.Checked if is_checked else Qt.Unchecked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)

            if children:
                self._build_epub_tree_fallback(children, item)

    def _build_pdf_tree(self):
        outline = self.pdf_doc.get_toc()
        self.has_pdf_bookmarks = bool(outline)
        self.bookmark_items_map = {}

        if not outline:
            self._build_pdf_pages_tree()
            return

        bookmark_pages = []
        page_to_bookmark = {}
        next_page_boundaries = {}
        added_pages = set()

        def extract_page_numbers(entries):
            for entry in entries:
                if len(entry) >= 3:
                    _, title, page = entry[:3]
                    page_num = (
                        page - 1
                        if isinstance(page, int)
                        else self.pdf_doc.resolve_link(page)[0]
                    )
                    bookmark_pages.append((page_num, title))

                    if len(entry) > 3 and isinstance(entry[3], list):
                        extract_page_numbers(entry[3])

        extract_page_numbers(outline)
        bookmark_pages.sort()

        for i, (page_num, title) in enumerate(bookmark_pages):
            if i < len(bookmark_pages) - 1:
                next_page_boundaries[page_num] = bookmark_pages[i + 1][0]
            page_to_bookmark[page_num] = title

        def build_outline_tree(entries, parent_item):
            for entry in entries:
                if len(entry) >= 3:
                    entry_level, title, page = entry[:3]
                    page_num = (
                        page - 1
                        if isinstance(page, int)
                        else self.pdf_doc.resolve_link(page)[0]
                    )
                    page_id = f"page_{page_num+1}"
                    # attach chapters on same page under original
                    if page_num in self.bookmark_items_map:
                        orig = self.bookmark_items_map[page_num]
                        child = QTreeWidgetItem(orig, [f"{title} (Same page)"])
                        child.setData(0, Qt.UserRole, page_id)
                        child.setFlags(child.flags() & ~Qt.ItemIsUserCheckable)
                        continue
                    bookmark_item = QTreeWidgetItem(parent_item, [title])
                    bookmark_item.setData(0, Qt.UserRole, page_id)
                    # only allow checking if this chapter has content
                    if self.content_lengths.get(page_id, 0) > 0:
                        bookmark_item.setFlags(
                            bookmark_item.flags() | Qt.ItemIsUserCheckable
                        )
                        bookmark_item.setCheckState(
                            0,
                            (
                                Qt.Checked
                                if page_id in self.checked_chapters
                                else Qt.Unchecked
                            ),
                        )
                    else:
                        bookmark_item.setFlags(
                            bookmark_item.flags() & ~Qt.ItemIsUserCheckable
                        )
                    # map for uncategorized pages
                    self.bookmark_items_map[page_num] = bookmark_item

                    added_pages.add(page_num)

                    next_page = next_page_boundaries.get(page_num, len(self.pdf_doc))
                    for sub_page_num in range(page_num + 1, next_page):
                        if (
                            sub_page_num in page_to_bookmark
                            or sub_page_num in added_pages
                        ):
                            continue

                        page_id = f"page_{sub_page_num+1}"
                        page_title = f"Page {sub_page_num+1}"

                        page_text = self.content_texts.get(page_id, "").strip()
                        if page_text:
                            first_line = page_text.split("\n", 1)[0].strip()
                            if first_line and len(first_line) < 100:
                                page_title += f" - {first_line}"

                        page_item = QTreeWidgetItem(bookmark_item, [page_title])
                        page_item.setData(0, Qt.UserRole, page_id)
                        # only allow checking if this sub-page has content
                        if self.content_lengths.get(page_id, 0) > 0:
                            page_item.setFlags(
                                page_item.flags() | Qt.ItemIsUserCheckable
                            )
                            page_item.setCheckState(
                                0,
                                (
                                    Qt.Checked
                                    if page_id in self.checked_chapters
                                    else Qt.Unchecked
                                ),
                            )
                        else:
                            page_item.setFlags(
                                page_item.flags() & ~Qt.ItemIsUserCheckable
                            )

                        added_pages.add(sub_page_num)

        build_outline_tree(outline, self.treeWidget)

        covered_pages = set(added_pages)
        # attach any pages without direct bookmarks under nearest preceding chapter
        uncategorized_pages = [
            i for i in range(len(self.pdf_doc)) if i not in covered_pages
        ]
        for page_num in uncategorized_pages:
            # find nearest previous bookmark
            prev_nums = [n for n in sorted(self.bookmark_items_map) if n < page_num]
            parent_item = (
                self.bookmark_items_map[prev_nums[-1]] if prev_nums else self.treeWidget
            )
            page_id = f"page_{page_num+1}"
            title = f"Page {page_num+1}"
            text = self.content_texts.get(page_id, "").strip()
            if text:
                first = text.split("\n", 1)[0].strip()
                if first and len(first) < 100:
                    title += f" - {first}"
            page_item = QTreeWidgetItem(parent_item, [title])
            page_item.setData(0, Qt.UserRole, page_id)
            # only allow checking if uncategorized page has content
            if self.content_lengths.get(page_id, 0) > 0:
                page_item.setFlags(page_item.flags() | Qt.ItemIsUserCheckable)
                page_item.setCheckState(
                    0, Qt.Checked if page_id in self.checked_chapters else Qt.Unchecked
                )
            else:
                page_item.setFlags(page_item.flags() & ~Qt.ItemIsUserCheckable)

    def _build_pdf_pages_tree(self):
        pages_item = QTreeWidgetItem(self.treeWidget, ["Pages"])
        pages_item.setFlags(pages_item.flags() & ~Qt.ItemIsUserCheckable)
        font = pages_item.font(0)
        font.setBold(True)
        pages_item.setFont(0, font)

        for page_num in range(len(self.pdf_doc)):
            page_id = f"page_{page_num+1}"
            page_title = f"Page {page_num+1}"

            page_text = self.content_texts.get(page_id, "").strip()
            if page_text:
                first_line = page_text.split("\n", 1)[0].strip()
                if first_line and len(first_line) < 100:
                    page_title += f" - {first_line}"

            page_item = QTreeWidgetItem(pages_item, [page_title])
            page_item.setData(0, Qt.UserRole, page_id)
            # only allow checking if standalone page has content
            if self.content_lengths.get(page_id, 0) > 0:
                page_item.setFlags(page_item.flags() | Qt.ItemIsUserCheckable)
                page_item.setCheckState(
                    0, Qt.Checked if page_id in self.checked_chapters else Qt.Unchecked
                )
            else:
                page_item.setFlags(page_item.flags() & ~Qt.ItemIsUserCheckable)

    def _are_provided_checks_relevant(self):
        if not self.checked_chapters:
            return False

        all_identifiers = set()
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if item.flags() & Qt.ItemIsUserCheckable:
                identifier = item.data(0, Qt.UserRole)
                if identifier:
                    all_identifiers.add(identifier)
            iterator += 1

        return bool(self.checked_chapters.intersection(all_identifiers))

    def _setup_ui(self):
        self.previewEdit = QTextEdit(self)
        self.previewEdit.setReadOnly(True)
        self.previewEdit.setMinimumWidth(300)
        self.previewEdit.setStyleSheet("QTextEdit { border: none; }")

        self.previewInfoLabel = QLabel(
            '*Note: You can modify the content later using the "Edit" button in the input box or by accessing the temporary files directory through settings (if not saved in a project folder).',
            self,
        )
        self.previewInfoLabel.setWordWrap(True)
        self.previewInfoLabel.setStyleSheet(
            "QLabel { color: #666; font-style: italic; }"
        )

        previewLayout = QVBoxLayout()
        previewLayout.setContentsMargins(0, 0, 0, 0)
        previewLayout.addWidget(self.previewEdit, 1)
        previewLayout.addWidget(self.previewInfoLabel, 0)

        rightWidget = QWidget()
        rightWidget.setLayout(previewLayout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        item_type = "chapters" if self.file_type == "epub" else "pages"

        self.auto_select_btn = QPushButton(f"Auto-select {item_type}", self)
        self.auto_select_btn.clicked.connect(self.auto_select_chapters)
        self.auto_select_btn.setToolTip(f"Automatically select main {item_type}")

        buttons_layout = QVBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)

        auto_select_layout = QHBoxLayout()
        auto_select_layout.addWidget(self.auto_select_btn)
        buttons_layout.addLayout(auto_select_layout)

        select_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select all", self)
        self.select_all_btn.clicked.connect(self.select_all_chapters)
        self.deselect_all_btn = QPushButton("Clear all", self)
        self.deselect_all_btn.clicked.connect(self.deselect_all_chapters)
        select_layout.addWidget(self.select_all_btn)
        select_layout.addWidget(self.deselect_all_btn)
        buttons_layout.addLayout(select_layout)

        parent_layout = QHBoxLayout()
        self.select_parents_btn = QPushButton("Select parents", self)
        self.select_parents_btn.clicked.connect(self.select_parent_chapters)
        self.deselect_parents_btn = QPushButton("Unselect parents", self)
        self.deselect_parents_btn.clicked.connect(self.deselect_parent_chapters)
        parent_layout.addWidget(self.select_parents_btn)
        parent_layout.addWidget(self.deselect_parents_btn)
        buttons_layout.addLayout(parent_layout)

        expand_layout = QHBoxLayout()
        self.expand_all_btn = QPushButton("Expand All", self)
        self.expand_all_btn.clicked.connect(self.treeWidget.expandAll)
        self.collapse_all_btn = QPushButton("Collapse All", self)
        self.collapse_all_btn.clicked.connect(self.treeWidget.collapseAll)
        expand_layout.addWidget(self.expand_all_btn)
        expand_layout.addWidget(self.collapse_all_btn)
        buttons_layout.addLayout(expand_layout)

        leftLayout = QVBoxLayout()
        leftLayout.setContentsMargins(0, 0, 5, 0)
        leftLayout.addLayout(buttons_layout)
        leftLayout.addWidget(self.treeWidget)

        checkbox_text = (
            "Save each chapter separately"
            if self.file_type == "epub"
            else "Save each page separately"
        )
        self.save_chapters_checkbox = QCheckBox(checkbox_text, self)
        self.save_chapters_checkbox.setChecked(self.save_chapters_separately)
        self.save_chapters_checkbox.stateChanged.connect(self.on_save_chapters_changed)
        leftLayout.addWidget(self.save_chapters_checkbox)
        self.merge_chapters_checkbox = QCheckBox(
            "Create a merged version at the end", self
        )
        self.merge_chapters_checkbox.setChecked(self.merge_chapters_at_end)
        self.merge_chapters_checkbox.stateChanged.connect(
            self.on_merge_chapters_changed
        )
        leftLayout.addWidget(self.merge_chapters_checkbox)

        self.save_as_project_checkbox = QCheckBox(
            "Save in a project folder with metadata", self
        )
        self.save_as_project_checkbox.setToolTip(
            "Save the converted item in a project folder with metadata files. "
            "(Useful if you want to work with converted items in the future.)"
        )
        self.save_as_project_checkbox.setChecked(self.save_as_project)
        self.save_as_project_checkbox.stateChanged.connect(
            self.on_save_as_project_changed
        )
        leftLayout.addWidget(self.save_as_project_checkbox)

        leftLayout.addWidget(buttons)

        leftWidget = QWidget()
        leftWidget.setLayout(leftLayout)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(leftWidget)
        self.splitter.addWidget(rightWidget)
        self.splitter.setSizes([280, 420])

        mainLayout = QVBoxLayout(self)
        mainLayout.addWidget(self.splitter)
        self.setLayout(mainLayout)

    def _update_checkbox_states(self):
        if (
            not hasattr(self, "save_chapters_checkbox")
            or not self.save_chapters_checkbox
        ):
            return

        if (
            self.file_type == "pdf"
            and hasattr(self, "has_pdf_bookmarks")
            and not self.has_pdf_bookmarks
        ):
            self.save_chapters_checkbox.setEnabled(False)
            self.merge_chapters_checkbox.setEnabled(False)
            return

        checked_count = 0

        if self.file_type == "epub":
            iterator = QTreeWidgetItemIterator(self.treeWidget)
            while iterator.value():
                item = iterator.value()
                if (
                    item.flags() & Qt.ItemIsUserCheckable
                    and item.checkState(0) == Qt.Checked
                ):
                    checked_count += 1
                    if checked_count >= 2:
                        break
                iterator += 1

        else:
            parent_groups = set()

            iterator = QTreeWidgetItemIterator(self.treeWidget)
            while iterator.value():
                item = iterator.value()
                if (
                    item.flags() & Qt.ItemIsUserCheckable
                    and item.checkState(0) == Qt.Checked
                ):
                    parent = item.parent()
                    if parent and parent != self.treeWidget.invisibleRootItem():
                        parent_groups.add(id(parent))
                    else:
                        parent_groups.add(id(item))
                iterator += 1

            checked_count = len(parent_groups)

        min_groups_required = 2
        self.save_chapters_checkbox.setEnabled(checked_count >= min_groups_required)

        self.merge_chapters_checkbox.setEnabled(
            self.save_chapters_checkbox.isEnabled()
            and self.save_chapters_checkbox.isChecked()
        )

    def select_all_chapters(self):
        self._block_signals = True
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(0, Qt.Checked)
            iterator += 1
        self._block_signals = False
        self._update_checked_set_from_tree()

    def deselect_all_chapters(self):
        self._block_signals = True
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(0, Qt.Unchecked)
            iterator += 1
        self._block_signals = False
        self._update_checked_set_from_tree()

    def select_parent_chapters(self):
        self._block_signals = True
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if item.flags() & Qt.ItemIsUserCheckable and item.childCount() > 0:
                item.setCheckState(0, Qt.Checked)
            iterator += 1
        self._block_signals = False
        self._update_checked_set_from_tree()

    def deselect_parent_chapters(self):
        self._block_signals = True
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if item.flags() & Qt.ItemIsUserCheckable and item.childCount() > 0:
                item.setCheckState(0, Qt.Unchecked)
            iterator += 1
        self._block_signals = False
        self._update_checked_set_from_tree()

    def auto_select_chapters(self):
        self._run_auto_check()

    def _run_auto_check(self):
        self._block_signals = True

        if self.file_type == "epub":
            self._run_epub_auto_check()
        else:
            self._run_pdf_auto_check()

        self._block_signals = False
        self._update_checked_set_from_tree()

    def _run_epub_auto_check(self):
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if not (item.flags() & Qt.ItemIsUserCheckable):
                iterator += 1
                continue

            src = item.data(0, Qt.UserRole)

            has_significant_content = src and self.content_lengths.get(src, 0) > 1000
            is_parent = item.childCount() > 0

            if has_significant_content or is_parent:
                item.setCheckState(0, Qt.Checked)
                if is_parent:
                    for i in range(item.childCount()):
                        child = item.child(i)
                        if child.flags() & Qt.ItemIsUserCheckable:
                            child_src = child.data(0, Qt.UserRole)
                            child_has_content = (
                                child_src and self.content_lengths.get(child_src, 0) > 0
                            )
                            child_is_parent = child.childCount() > 0
                            if child_has_content or child_is_parent:
                                child.setCheckState(0, Qt.Checked)
            else:
                item.setCheckState(0, Qt.Unchecked)

            iterator += 1

    def _run_pdf_auto_check(self):
        if hasattr(self, "has_pdf_bookmarks") and not self.has_pdf_bookmarks:
            iterator = QTreeWidgetItemIterator(self.treeWidget)
            while iterator.value():
                item = iterator.value()
                if item.flags() & Qt.ItemIsUserCheckable:
                    item.setCheckState(0, Qt.Checked)
                iterator += 1
            return

        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if not (item.flags() & Qt.ItemIsUserCheckable):
                iterator += 1
                continue

            identifier = item.data(0, Qt.UserRole)

            if not identifier:
                iterator += 1
                continue

            if (
                not identifier.startswith("page_")
                or self.content_lengths.get(identifier, 0) > 0
            ):
                item.setCheckState(0, Qt.Checked)

            iterator += 1

    def _update_checked_set_from_tree(self):
        self.checked_chapters.clear()
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if item.checkState(0) == Qt.Checked:
                identifier = item.data(0, Qt.UserRole)
                if identifier:
                    self.checked_chapters.add(identifier)
            iterator += 1
        if hasattr(self, "save_chapters_checkbox") and self.save_chapters_checkbox:
            self._update_checkbox_states()

    def handle_item_check(self, item):
        if self._block_signals:
            return

        self._block_signals = True

        if item.flags() & Qt.ItemIsUserCheckable:
            for i in range(item.childCount()):
                child = item.child(i)
                if child.flags() & Qt.ItemIsUserCheckable:
                    child.setCheckState(0, item.checkState(0))

        self._block_signals = False
        self._update_checked_set_from_tree()

    def handle_item_double_click(self, item, column=0):
        if item.flags() & Qt.ItemIsUserCheckable and item.childCount() == 0:
            rect = self.treeWidget.visualItemRect(item)
            checkbox_width = 20

            mouse_pos = self.treeWidget.mapFromGlobal(self.treeWidget.cursor().pos())

            if mouse_pos.x() > rect.x() + checkbox_width:
                new_state = (
                    Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked
                )
                item.setCheckState(0, new_state)

    def update_preview(self, current):
        if not current:
            self.previewEdit.clear()
            return

        identifier = current.data(0, Qt.UserRole)

        if identifier == "info:bookinfo":
            self._display_book_info()
            return

        text = None
        if self.file_type == "epub":
            text = self.content_texts.get(identifier)
        else:
            text = self.content_texts.get(identifier)

        if text is None:
            title = current.text(0)
            self.previewEdit.setPlainText(
                f"{title}\n\n(No content available for this item)"
            )
        elif not text.strip():
            title = current.text(0)
            self.previewEdit.setPlainText(f"{title}\n\n(This item is empty)")
        else:
            self.previewEdit.setPlainText(text)

    def _display_book_info(self):
        self.previewEdit.clear()
        html_content = "<html><body style='font-family: Arial, sans-serif;'>"

        if self.book_metadata["cover_image"]:
            try:
                image_data = base64.b64encode(self.book_metadata["cover_image"]).decode(
                    "utf-8"
                )

                image_type = "jpeg"
                if self.book_metadata["cover_image"].startswith(b"\x89PNG"):
                    image_type = "png"
                elif self.book_metadata["cover_image"].startswith(b"GIF"):
                    image_type = "gif"

                html_content += (
                    f"<div style='text-align: center; margin-bottom: 20px;'>"
                )
                html_content += (
                    f"<img src='data:image/{image_type};base64,{image_data}' "
                )
                html_content += f"width='300' style='object-fit: contain;' /></div>"
            except Exception as e:
                html_content += f"<p>Error displaying cover image: {str(e)}</p>"

        if self.book_metadata["title"]:
            html_content += (
                f"<h2 style='text-align: center;'>{self.book_metadata['title']}</h2>"
            )

        if self.book_metadata["authors"]:
            authors_text = ", ".join(self.book_metadata["authors"])
            html_content += f"<p style='text-align: center; font-style: italic;'>By {authors_text}</p>"

        if self.book_metadata["publisher"] or self.book_metadata.get(
            "publication_year"
        ):
            pub_info = []
            if self.book_metadata["publisher"]:
                pub_info.append(f"Published by {self.book_metadata['publisher']}")
            if self.book_metadata.get("publication_year"):
                pub_info.append(f"Year: {self.book_metadata['publication_year']}")
            html_content += f"<p style='text-align: center;'>{' | '.join(pub_info)}</p>"

        html_content += "<hr/>"

        if self.book_metadata["description"]:
            desc = re.sub(r"<[^>]+>", "", self.book_metadata["description"])
            html_content += f"<h3>Description:</h3><p>{desc}</p>"

        if self.file_type == "pdf":
            page_count = len(self.pdf_doc) if self.pdf_doc else 0
            html_content += f"<p>File type: PDF<br>Page count: {page_count}</p>"

        html_content += "</body></html>"
        self.previewEdit.setHtml(html_content)

    def _extract_book_metadata(self):
        metadata = {
            "title": None,
            "authors": [],
            "description": None,
            "cover_image": None,
            "publisher": None,
            "publication_year": None,
        }

        if self.file_type == "epub":
            try:
                title_items = self.book.get_metadata("DC", "title")
                if title_items and len(title_items) > 0:
                    metadata["title"] = title_items[0][0]
            except Exception as e:
                logging.warning(f"Error extracting title metadata: {e}")

            try:
                author_items = self.book.get_metadata("DC", "creator")
                if author_items:
                    metadata["authors"] = [
                        author[0] for author in author_items if len(author) > 0
                    ]
            except Exception as e:
                logging.warning(f"Error extracting author metadata: {e}")

            try:
                desc_items = self.book.get_metadata("DC", "description")
                if desc_items and len(desc_items) > 0:
                    metadata["description"] = desc_items[0][0]
            except Exception as e:
                logging.warning(f"Error extracting description metadata: {e}")

            try:
                publisher_items = self.book.get_metadata("DC", "publisher")
                if publisher_items and len(publisher_items) > 0:
                    metadata["publisher"] = publisher_items[0][0]
            except Exception as e:
                logging.warning(f"Error extracting publisher metadata: {e}")

            # Try to extract publication year
            try:
                date_items = self.book.get_metadata("DC", "date")
                if date_items and len(date_items) > 0:
                    date_str = date_items[0][0]
                    # Try to extract just the year from the date string
                    year_match = re.search(r"\b(19|20)\d{2}\b", date_str)
                    if year_match:
                        metadata["publication_year"] = year_match.group(0)
                    else:
                        metadata["publication_year"] = date_str
            except Exception as e:
                logging.warning(f"Error extracting publication date metadata: {e}")

            for item in self.book.get_items_of_type(ebooklib.ITEM_COVER):
                metadata["cover_image"] = item.get_content()
                break

            if not metadata["cover_image"]:
                for item in self.book.get_items_of_type(ebooklib.ITEM_IMAGE):
                    if "cover" in item.get_name().lower():
                        metadata["cover_image"] = item.get_content()
                        break
        else:
            pdf_info = self.pdf_doc.metadata
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

                # Try to extract publication date from PDF metadata
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

            if len(self.pdf_doc) > 0:
                try:
                    pix = self.pdf_doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
                    metadata["cover_image"] = pix.tobytes("png")
                except Exception:
                    pass

        return metadata

    def get_selected_text(self):
        if self.file_type == "epub":
            return self._get_epub_selected_text()
        else:
            return self._get_pdf_selected_text()

    def _format_metadata_tags(self):
        """Format metadata tags for insertion at the beginning of the text"""
        import datetime

        metadata = self.book_metadata
        filename = os.path.splitext(os.path.basename(self.book_path))[0]
        current_year = str(datetime.datetime.now().year)

        # Get values with fallbacks
        title = metadata.get("title") or filename
        authors = metadata.get("authors") or ["Unknown"]
        authors_text = ", ".join(authors)
        album_artist = authors_text or "Unknown"
        year = (
            metadata.get("publication_year") or current_year
        )  # Use publication year if available

        # Count chapters/pages
        total_chapters = len(self.checked_chapters)
        chapter_text = (
            f"{total_chapters} {'Chapters' if self.file_type == 'epub' else 'Pages'}"
        )

        # Format metadata tags
        metadata_tags = [
            f"<<METADATA_TITLE:{title}>>",
            f"<<METADATA_ARTIST:{authors_text}>>",
            f"<<METADATA_ALBUM:{title} ({chapter_text})>>",
            f"<<METADATA_YEAR:{year}>>",
            f"<<METADATA_ALBUM_ARTIST:{album_artist}>>",
            f"<<METADATA_COMPOSER:Narrator>>",
            f"<<METADATA_GENRE:Audiobook>>",
        ]

        return "\n".join(metadata_tags)

    def _get_epub_selected_text(self):
        all_checked_identifiers = set()
        chapter_texts = []

        # Add metadata tags at the beginning
        metadata_tags = self._format_metadata_tags()

        item_order_counter = 0
        ordered_checked_items = []

        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            item_order_counter += 1
            if item.checkState(0) == Qt.Checked:
                identifier = item.data(0, Qt.UserRole)
                if identifier and identifier != "info:bookinfo":
                    all_checked_identifiers.add(identifier)
                    ordered_checked_items.append((item_order_counter, item, identifier))
            iterator += 1

        ordered_checked_items.sort(key=lambda x: x[0])

        for order, item, identifier in ordered_checked_items:
            text = self.content_texts.get(identifier)
            if text and text.strip():
                title = item.text(0)
                title = re.sub(r"^\s*[-–—]\s*", "", title).strip()
                marker = f"<<CHAPTER_MARKER:{title}>>"
                chapter_texts.append(marker + "\n" + text)

        full_text = metadata_tags + "\n\n" + "\n\n".join(chapter_texts)
        return full_text, all_checked_identifiers

    def _get_pdf_selected_text(self):
        all_checked_identifiers = set()
        included_text_ids = set()
        section_titles = []
        all_content = []

        # Add metadata tags at the beginning
        metadata_tags = self._format_metadata_tags()

        pdf_has_no_bookmarks = (
            hasattr(self, "has_pdf_bookmarks") and not self.has_pdf_bookmarks
        )

        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if item.checkState(0) == Qt.Checked:
                identifier = item.data(0, Qt.UserRole)
                if identifier:
                    all_checked_identifiers.add(identifier)
            iterator += 1

        if pdf_has_no_bookmarks:
            sorted_page_ids = sorted(
                [id for id in all_checked_identifiers if id.startswith("page_")],
                key=lambda x: int(x.split("_")[1]) if x.split("_")[1].isdigit() else 0,
            )
            for page_id in sorted_page_ids:
                if page_id not in included_text_ids:
                    text = self.content_texts.get(page_id, "")
                    if text:
                        all_content.append(text)
                        included_text_ids.add(page_id)
            return (
                metadata_tags + "\n\n" + "\n\n".join(all_content),
                all_checked_identifiers,
            )

        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if item.childCount() > 0:
                parent_checked = item.checkState(0) == Qt.Checked
                parent_id = item.data(0, Qt.UserRole)
                parent_title = item.text(0)
                checked_children = []
                for i in range(item.childCount()):
                    child = item.child(i)
                    child_id = child.data(0, Qt.UserRole)
                    if (
                        child.checkState(0) == Qt.Checked
                        and child_id
                        and child_id not in included_text_ids
                    ):
                        checked_children.append((child, child_id))
                if parent_checked and parent_id and parent_id not in included_text_ids:
                    combined_text = self.content_texts.get(parent_id, "")
                    for child, child_id in checked_children:
                        child_text = self.content_texts.get(child_id, "")
                        if child_text:
                            combined_text += "\n\n" + child_text
                        included_text_ids.add(child_id)
                    if combined_text.strip():
                        title = re.sub(r"^\s*-\s*", "", parent_title).strip()
                        marker = f"<<CHAPTER_MARKER:{title}>>"
                        section_titles.append((title, marker + "\n" + combined_text))
                        included_text_ids.add(parent_id)
                elif not parent_checked and checked_children:
                    title = re.sub(r"^\s*-\s*", "", parent_title).strip()
                    marker = f"<<CHAPTER_MARKER:{title}>>"
                    for idx, (child, child_id) in enumerate(checked_children):
                        text = self.content_texts.get(child_id, "")
                        if text:
                            if idx == 0:
                                section_titles.append((title, marker + "\n" + text))
                            else:
                                section_titles.append((title, text))
                        included_text_ids.add(child_id)
            elif item.flags() & Qt.ItemIsUserCheckable:
                identifier = item.data(0, Qt.UserRole)
                if (
                    identifier
                    and identifier not in included_text_ids
                    and item.checkState(0) == Qt.Checked
                ):
                    text = self.content_texts.get(identifier, "")
                    if text:
                        title = item.text(0)
                        title = re.sub(r"^\s*-\s*", "", title).strip()
                        marker = f"<<CHAPTER_MARKER:{title}>>"
                        section_titles.append((title, marker + "\n" + text))
                        included_text_ids.add(identifier)
            iterator += 1

        return (
            metadata_tags + "\n\n" + "\n\n".join([t[1] for t in section_titles]),
            all_checked_identifiers,
        )

    def on_save_chapters_changed(self, state):
        self.save_chapters_separately = bool(state)
        self.merge_chapters_checkbox.setEnabled(self.save_chapters_separately)
        HandlerDialog._save_chapters_separately = self.save_chapters_separately

    def on_merge_chapters_changed(self, state):
        self.merge_chapters_at_end = bool(state)
        HandlerDialog._merge_chapters_at_end = self.merge_chapters_at_end

    def on_save_as_project_changed(self, state):
        self.save_as_project = bool(state)
        HandlerDialog._save_as_project = self.save_as_project

    def get_save_chapters_separately(self):
        return (
            self.save_chapters_separately
            if self.save_chapters_checkbox.isEnabled()
            else False
        )

    def get_merge_chapters_at_end(self):
        return self.merge_chapters_at_end

    def get_save_as_project(self):
        return self.save_as_project

    def check_selected_items(self):
        self.set_selected_items_checked(True)

    def uncheck_selected_items(self):
        self.set_selected_items_checked(False)

    def set_selected_items_checked(self, state: bool):
        print(f"Checking selected items: {state}")
        self.treeWidget.blockSignals(True)
        for item in self.treeWidget.selectedItems():
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(0, Qt.Checked if state else Qt.Unchecked)
        self.treeWidget.blockSignals(False)
        self._update_checked_set_from_tree()

    def on_tree_context_menu(self, pos):
        item = self.treeWidget.itemAt(pos)
        # multi-select context menu
        if self.treeWidget.selectedItems() and len(self.treeWidget.selectedItems()) > 1:
            menu = QMenu(self)
            action = menu.addAction("Select")
            action.triggered.connect(self.check_selected_items)
            action = menu.addAction("Clear")
            action.triggered.connect(self.uncheck_selected_items)
            menu.exec_(self.treeWidget.mapToGlobal(pos))
            return

        if (
            not item
            or item.childCount() == 0
            or not (item.flags() & Qt.ItemIsUserCheckable)
        ):
            return

        menu = QMenu(self)
        checked = item.checkState(0) == Qt.Checked
        text = "Unselect only this" if checked else "Select only this"
        action = menu.addAction(text)

        def do_toggle():
            self.treeWidget.blockSignals(True)
            new_state = Qt.Unchecked if checked else Qt.Checked
            item.setCheckState(0, new_state)
            self.treeWidget.blockSignals(False)
            self._update_checked_set_from_tree()

        action.triggered.connect(do_toggle)
        menu.exec_(self.treeWidget.mapToGlobal(pos))

    def closeEvent(self, event):
        if self.pdf_doc is not None:
            self.pdf_doc.close()
        event.accept()
