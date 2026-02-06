import os
import re
import logging
import textwrap
import urllib.parse
from abc import ABC, abstractmethod

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, NavigableString
import fitz  # PyMuPDF
import markdown

from abogen.utils import detect_encoding
from abogen.subtitle_utils import clean_text, calculate_text_length

# Pre-compile frequently used regex patterns
_BRACKETED_NUMBERS_PATTERN = re.compile(r"\[\s*\d+\s*\]")
_STANDALONE_PAGE_NUMBERS_PATTERN = re.compile(r"^\s*\d+\s*$", re.MULTILINE)
_PAGE_NUMBERS_AT_END_PATTERN = re.compile(r"\s+\d+\s*$", re.MULTILINE)
_PAGE_NUMBERS_WITH_DASH_PATTERN = re.compile(
    r"\s+[-–—]\s*\d+\s*[-–—]?\s*$", re.MULTILINE
)


class BaseBookParser(ABC):
    """
    Abstract base class for parsing different book formats.
    """

    def __init__(self, book_path):
        self.book_path = os.path.normpath(os.path.abspath(book_path))
        self.content_texts = {}
        self.content_lengths = {}
        self.book_metadata = {}
        # Unified structure for navigation: list of dicts
        # { 'title': str, 'src': str, 'children': [], 'has_content': bool }
        self.processed_nav_structure = []
        self.load()

    @abstractmethod
    def load(self):
        """Load the book file."""
        pass

    def close(self):
        """Close any open file handles."""
        pass

    def __enter__(self):
        # Already loaded in __init__, or lazily.
        # Just ensure we have resources if needed, or do nothing.
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @abstractmethod
    def process_content(self, replace_single_newlines=True):
        """Process the book content to extract text and structure."""
        pass

    @property
    @abstractmethod
    def file_type(self):
        """Return the type of the file (pdf, epub, markdown)."""
        pass

    def get_chapters(self):
        """Return a list of chapter IDs and Names."""
        chapters = []
        if self.processed_nav_structure:

            def flatten_nav(nodes):
                for node in nodes:
                    if node.get("has_content"):
                        chapters.append((node["src"], node["title"]))
                    if node.get("children"):
                        flatten_nav(node["children"])

            flatten_nav(self.processed_nav_structure)
        else:
            # Fallback for simple content without nav structure
            for ch_id, content in self.content_texts.items():
                # This could be improved, but serves as a generic fallback
                chapters.append((ch_id, ch_id))
        return chapters

    def get_formatted_text(self):
        """
        Returns the full text of the book formatted with chapter markers.
        """
        chapters = self.get_chapters()
        full_text = []

        for chapter_id, chapter_name in chapters:
            text = self.content_texts.get(chapter_id, "")
            if text:
                full_text.append(f"\n<<CHAPTER_MARKER:{chapter_name}>>\n")
                full_text.append(text)

        return "\n".join(full_text)

    def get_metadata(self):
        """Return extracted metadata."""
        return self.book_metadata


class PdfParser(BaseBookParser):
    def __init__(self, book_path):
        self.pdf_doc = None
        super().__init__(book_path)

    @property
    def file_type(self):
        return "pdf"

    def load(self):
        try:
            self.pdf_doc = fitz.open(self.book_path)
        except Exception as e:
            logging.error(f"Error loading PDF {self.book_path}: {e}")
            raise

    def close(self):
        if self.pdf_doc:
            self.pdf_doc.close()
            self.pdf_doc = None

    def _extract_book_metadata(self):
        # PDF metadata extraction can be added here if needed
        # For now, base class metadata is empty dict
        pass

    def process_content(self, replace_single_newlines=True):
        if not self.pdf_doc:
            self.load()

        # 1. Extract text from all pages first
        for page_num in range(len(self.pdf_doc)):
            text = clean_text(self.pdf_doc[page_num].get_text())
            
            # Clean up common PDF artifacts:
            text = _BRACKETED_NUMBERS_PATTERN.sub("", text)
            text = _STANDALONE_PAGE_NUMBERS_PATTERN.sub("", text)
            text = _PAGE_NUMBERS_AT_END_PATTERN.sub("", text)
            text = _PAGE_NUMBERS_WITH_DASH_PATTERN.sub("", text)

            page_id = f"page_{page_num + 1}"
            self.content_texts[page_id] = text
            self.content_lengths[page_id] = calculate_text_length(text)

        # 2. Build Navigation Structure
        toc = self.pdf_doc.get_toc()
        
        if not toc:
            # Fallback: Flat list of pages if no TOC
            self.processed_nav_structure = []
            pages_node = {
                "title": "Pages",
                "src": None,
                "children": [],
                "has_content": False
            }
            # Add all pages as children
            for page_num in range(len(self.pdf_doc)):
               page_id = f"page_{page_num + 1}"
               title = self._get_page_title(page_num, self.content_texts.get(page_id, ""))
               pages_node["children"].append({
                   "title": title,
                   "src": page_id,
                   "children": [],
                   "has_content": True
               })
            self.processed_nav_structure.append(pages_node)
        else:
            self.processed_nav_structure = self._build_structure_from_toc(toc)

        return self.content_texts, self.content_lengths

    def _get_page_title(self, page_num, text):
        title = f"Page {page_num + 1}"
        if text:
            first_line = text.split("\n", 1)[0].strip()
            if first_line and len(first_line) < 100:
                title += f" - {first_line}"
        return title

    def _build_structure_from_toc(self, toc):
        # 1. Flatten TOC to easier list (page_num, title, level)
        # fitz TOC is [[lvl, title, page, dest], ...]
        
        bookmarks = []
        for entry in toc:
            lvl, title, page = entry[:3]
            if isinstance(page, int):
                page_idx = page - 1
            else:
                 # Handle potential complex destinations if necessary, but usually simple int
                 # PyMuPDF docs say int.
                 page_idx = -1 
            
            if page_idx >= 0:
                bookmarks.append({"level": lvl, "title": title, "page": page_idx})

        
        root_children = []
        stack = [] # Stack of (level, list_to_append_to)
        stack.append((0, root_children)) 

        # Step 1: Build the Skeleton Tree from TOC
        # And keep a flat list of these nodes to associate with pages.
        
        processed_nodes = [] # List of (page_idx, node_dict)
        
        for entry in bookmarks:
            node = {
                "title": entry["title"],
                "src": f"page_{entry['page'] + 1}",
                "children": [],
                "has_content": True
            }
            
            # Find parent
            level = entry["level"]
            
            # Adjust stack
            while stack and stack[-1][0] >= level:
                stack.pop()
            
            parent_list = stack[-1][1]
            parent_list.append(node)
            
            stack.append((level, node["children"]))
            processed_nodes.append((entry["page"], node))
            
        # Step 3: Add gap pages.
        # Sort processed_nodes by page index to find ranges.
        sorted_bookmarks = sorted(processed_nodes, key=lambda x: x[0])
        
        # Set of pages that are "bookmarks"
        bookmarked_pages = set(p for p, n in sorted_bookmarks)
        
        current_node = None
        # We need a way to look up bookmarks starting at p
        bookmarks_by_page = {}
        for p, node in processed_nodes:
            if p not in bookmarks_by_page:
                bookmarks_by_page[p] = []
            bookmarks_by_page[p].append(node)

        
        # Let's iterate.
        for page_num in range(len(self.pdf_doc)):
            page_id = f"page_{page_num + 1}"
            
            # Check if this page STARTS bookmarks
            if page_num in bookmarks_by_page:
                
                starts = bookmarks_by_page[page_num]
                current_node = starts[-1] 
                
                continue

            # If page is NOT a bookmark, it's a "gap page".
            # Add as child to current_node
            title = self._get_page_title(page_num, self.content_texts.get(page_id, ""))
            page_node = {
                "title": title,
                "src": page_id,
                "children": [],
                "has_content": True
            }
            
            if current_node:
                current_node["children"].append(page_node)
            else:
                # No preceding bookmark. Add to root.
                root_children.append(page_node)
                
        return root_children


class MarkdownParser(BaseBookParser):
    def __init__(self, book_path):
        self.markdown_text = None
        super().__init__(book_path)

    @property
    def file_type(self):
        return "markdown"

    def load(self):
        try:
            encoding = detect_encoding(self.book_path)
            with open(self.book_path, "r", encoding=encoding, errors="replace") as f:
                self.markdown_text = f.read()
        except Exception as e:
            logging.error(f"Error reading markdown file: {e}")
            self.markdown_text = ""

    def process_content(self, replace_single_newlines=True):
        if self.markdown_text is None:
            self.load()

        self._process_markdown_content()
        return self.content_texts, self.content_lengths

    def _convert_markdown_toc_to_nav(self, toc_tokens):
        nav_nodes = []
        for token in toc_tokens:
            node = {
                "title": token["name"],
                "src": token["id"],
                "children": self._convert_markdown_toc_to_nav(
                    token.get("children", [])
                ),
                "has_content": True,
            }
            nav_nodes.append(node)
        return nav_nodes

    def _process_markdown_content(self):
        if not self.markdown_text:
            return

        original_text = textwrap.dedent(self.markdown_text)
        md = markdown.Markdown(extensions=["toc", "fenced_code"])
        html = md.convert(original_text)
        markdown_toc = md.toc_tokens

        # Convert markdown TOC tokens to our unified navigation structure
        self.processed_nav_structure = self._convert_markdown_toc_to_nav(markdown_toc)

        cleaned_full_text = clean_text(original_text)

        # If no TOC found, treat as single chapter
        if not self.processed_nav_structure:
            chapter_id = "markdown_content"
            self.content_texts[chapter_id] = cleaned_full_text
            self.content_lengths[chapter_id] = calculate_text_length(cleaned_full_text)
            return

        soup = BeautifulSoup(html, "html.parser")

        all_headers = []

        def flatten_nav_internal(nodes):
            for node in nodes:
                all_headers.append(node)
                if node.get("children"):
                    flatten_nav_internal(node["children"])

        flatten_nav_internal(self.processed_nav_structure)

        header_positions = []
        for node in all_headers:
            header_id = node["src"]
            id_pattern = f'id="{header_id}"'
            pos = html.find(id_pattern)
            if pos != -1:
                tag_start = html.rfind("<", 0, pos)
                header_positions.append(
                    {"id": header_id, "start": tag_start, "name": node["title"]}
                )
        header_positions.sort(key=lambda x: x["start"])

        for i, header_pos in enumerate(header_positions):
            header_id = header_pos["id"]
            header_name = header_pos["name"]
            content_start = header_pos["start"]

            content_end = (
                header_positions[i + 1]["start"]
                if i + 1 < len(header_positions)
                else len(html)
            )
            section_html = html[content_start:content_end]
            section_soup = BeautifulSoup(section_html, "html.parser")

            header_tag = section_soup.find(attrs={"id": header_id})
            if header_tag:
                header_tag.decompose()

            section_text = clean_text(section_soup.get_text()).strip()
            chapter_id = header_id
            if section_text:
                full_content = f"{header_name}\n\n{section_text}"
                self.content_texts[chapter_id] = full_content
                self.content_lengths[chapter_id] = calculate_text_length(full_content)
            else:
                self.content_texts[chapter_id] = header_name
                self.content_lengths[chapter_id] = calculate_text_length(header_name)

    def get_chapters(self):
        chapters = super().get_chapters()
        if not chapters and "markdown_content" in self.content_texts:
            chapters.append(("markdown_content", "Content"))
        return chapters


class EpubParser(BaseBookParser):
    def __init__(self, book_path):
        self.book = None
        self.doc_content = {}
        super().__init__(book_path)

    @property
    def file_type(self):
        return "epub"

    def load(self):
        try:
            self.book = epub.read_epub(self.book_path)
        except KeyError as e:
            # TODO: should we just patch the ebooklib pre-emptively to avoid the need to catch this exception?
            logging.warning(f"EPUB missing referenced file: {e}. Attempting to patch.")
            # Patch ebooklib to skip missing files
            import types
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
            try:
                self.book = epub.read_epub(self.book_path)
            finally:
                reader_class.read_file = orig_read_file

    def process_content(self, replace_single_newlines=True):
        if not self.book:
            self.load()

        self.book_metadata = self._extract_book_metadata()
        try:
            nav_item, nav_type = self._identify_nav_item()
            self._execute_nav_parsing_logic(nav_item, nav_type)
        except Exception as e:
            logging.warning(f"EPUB nav processing failed: {e}. Falling back to spine.")
            self._process_epub_content_spine_fallback()

        return self.content_texts, self.content_lengths

    def _extract_book_metadata(self):
        metadata = {}
        if not self.book:
            return metadata

        try:
            metadata["title"] = self.book.get_metadata("DC", "title")[0][0]
        except Exception:
            metadata["title"] = os.path.splitext(os.path.basename(self.book_path))[0]

        try:
            metadata["author"] = self.book.get_metadata("DC", "creator")[0][0]
        except Exception:
            metadata["author"] = "Unknown Author"

        try:
            metadata["language"] = self.book.get_metadata("DC", "language")[0][0]
        except Exception:
            metadata["language"] = "en"

        return metadata

    def _find_doc_key(self, base_href, doc_order, doc_order_decoded):
        candidates = [
            base_href,
            urllib.parse.unquote(base_href),
        ]
        base_name = os.path.basename(base_href).lower()
        for k in list(doc_order.keys()) + list(doc_order_decoded.keys()):
            if os.path.basename(k).lower() == base_name:
                candidates.append(k)
        for candidate in candidates:
            if candidate in doc_order:
                return candidate, doc_order[candidate]
            elif candidate in doc_order_decoded:
                return candidate, doc_order_decoded[candidate]
        return None, None

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
                    return pos
        except Exception as e:
            logging.warning(f"BeautifulSoup failed to find id='{fragment_id}': {e}")

        safe_fragment_id = re.escape(fragment_id)
        id_name_pattern = re.compile(
            f"<[^>]+(?:id|name)\\s*=\\s*[\"']{safe_fragment_id}[\"']", re.IGNORECASE
        )
        match = id_name_pattern.search(html_content)
        if match:
            return match.start()

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
            return final_pos

        logging.warning(
            f"Anchor '{fragment_id}' not found in {doc_href}. Defaulting to position 0."
        )
        return 0

    def _parse_ncx_navpoint(
        self,
        nav_point,
        ordered_entries,
        doc_order,
        doc_order_decoded,
        tree_structure_list,
        find_position_func,
    ):
        """
        Recursive parsing of NCX navigation nodes.

        Logic tested by: tests/test_epub_ncx_parsing.py
        """
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
            doc_key, doc_idx = self._find_doc_key(
                base_href, doc_order, doc_order_decoded
            )
            if not doc_key:
                current_entry_node["has_content"] = False
            else:
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

        child_navpoints = nav_point.find_all("navPoint", recursive=False)
        if child_navpoints:
            for child_np in child_navpoints:
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

    def _extract_nav_li_title(self, li_element, link_element=None, span_element=None):
        """Helper to extract title from a nav <li> element, handling various structures."""
        title = "Untitled Section"

        if link_element:
            title = link_element.get_text(strip=True) or title
        elif span_element:
            title = span_element.get_text(strip=True) or title

        # Fallback to direct text if title is empty or default
        # If we used link/span but got empty string, we try fallback.
        # If we didn't use link/span, we try fallback.
        if not title.strip() or title == "Untitled Section":
            li_text = "".join(
                t for t in li_element.contents if isinstance(t, NavigableString)
            ).strip()
            if li_text:
                title = li_text

        # Second fallback: if we have a span but title is still empty, try span text again
        # (covered by logic above mostly, but mirroring original logic's intense fallback)
        if (not title.strip() or title == "Untitled Section") and span_element:
            title = span_element.get_text(strip=True) or title

        return title

    def _parse_html_nav_li(
        self,
        li_element,
        ordered_entries,
        doc_order,
        doc_order_decoded,
        tree_structure_list,
        find_position_func,
    ):
        """
        Recursive parsing of HTML5 Navigation (li) nodes.

        Logic tested by: tests/test_epub_html_nav_parsing.py
        """
        link = li_element.find("a", recursive=False)
        span_text = li_element.find("span", recursive=False)
        src = None
        current_entry_node = {"children": []}

        if link and "href" in link.attrs:
            src = link["href"]

        title = self._extract_nav_li_title(li_element, link, span_text)

        current_entry_node["title"] = title
        current_entry_node["src"] = src

        doc_key = None
        doc_idx = None
        position = 0
        fragment = None
        if src:
            base_href, fragment = src.split("#", 1) if "#" in src else (src, None)
            doc_key, doc_idx = self._find_doc_key(
                base_href, doc_order, doc_order_decoded
            )
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
        else:
            current_entry_node["has_content"] = False

        for child_ol in li_element.find_all("ol", recursive=False):
            for child_li in child_ol.find_all("li", recursive=False):
                self._parse_html_nav_li(
                    child_li,
                    ordered_entries,
                    doc_order,
                    doc_order_decoded,
                    current_entry_node["children"],
                    find_position_func,
                )
        tree_structure_list.append(current_entry_node)

    def _identify_nav_item(self):
        """Identify the navigation item (HTML Nav or NCX) and its type."""
        nav_item = None
        nav_type = None

        # 1. Check ITEM_NAVIGATION
        nav_items = list(self.book.get_items_of_type(ebooklib.ITEM_NAVIGATION))

        # 1.1 Support for EPUB 3 EpubNav which might be ITEM_DOCUMENT (9) but with properties=['nav']
        if not nav_items:
            # Look in ITEM_DOCUMENT for items with 'nav' property
            for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                if (
                    hasattr(item, "get_type")
                    and item.get_type() == ebooklib.ITEM_DOCUMENT
                ):
                    # Check properties - ebooklib stores opf properties in list
                    # Some versions use item.properties, some need checking
                    props = getattr(item, "properties", [])
                    if "nav" in props:
                        nav_items.append(item)

        if nav_items:
            nav_item = next(
                (
                    item
                    for item in nav_items
                    if "nav" in item.get_name().lower()
                    and item.get_name().lower().endswith((".xhtml", ".html"))
                ),
                None,
            ) or next(
                (
                    item
                    for item in nav_items
                    if item.get_name().lower().endswith((".xhtml", ".html"))
                ),
                None,
            )
            if nav_item:
                nav_type = "html"

        # 2. NCX in NAV
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

        # 3. ITEM_NCX or Fallback
        # If no explicit navigation item found, try to find a standard NCX file
        if not nav_item:
            ncx_constant = getattr(epub, "ITEM_NCX", None)
            if ncx_constant is not None:
                ncx_items = list(self.book.get_items_of_type(ncx_constant))
                if ncx_items:
                    nav_item = ncx_items[0]
                    nav_type = "ncx"

        # 4. Heuristic Search
        # Scan documents for something that looks like a TOC if standard methods fail
        if not nav_item:
            for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                try:
                    html_content = item.get_content().decode("utf-8", errors="ignore")
                    if "<nav" in html_content and 'epub:type="toc"' in html_content:
                        nav_item = item
                        nav_type = "html"
                        break
                except Exception:
                    continue

        if not nav_item or not nav_type:
            raise ValueError("No navigation document found")

        return nav_item, nav_type

    def _execute_nav_parsing_logic(self, nav_item, nav_type):
        """Parse the identified navigation item and slice content accordingly."""

        parser_type = "html.parser" if nav_type == "html" else "xml"
        try:
            nav_content = nav_item.get_content().decode("utf-8", errors="ignore")
            nav_soup = BeautifulSoup(nav_content, parser_type)
        except Exception as e:
            raise ValueError(f"Failed to parse navigation content: {e}")

        self.doc_content = {}
        spine_docs = []
        for spine_item_tuple in self.book.spine:
            item_id = spine_item_tuple[0]
            item = self.book.get_item_with_id(item_id)
            if item:
                spine_docs.append(item.get_name())
        doc_order = {href: i for i, href in enumerate(spine_docs)}
        doc_order_decoded = {
            urllib.parse.unquote(href): i for href, i in doc_order.items()
        }

        self.content_texts = {}
        self.content_lengths = {}

        for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            href = item.get_name()
            if href in doc_order or any(
                href in nav_point.get("src", "")
                for nav_point in nav_soup.find_all(["content", "a"])
            ):
                try:
                    self.doc_content[href] = item.get_content().decode(
                        "utf-8", errors="ignore"
                    )
                except Exception:
                    self.doc_content[href] = ""

        ordered_nav_entries = []
        parse_successful = False

        if nav_type == "ncx":
            nav_map = nav_soup.find("navMap")
            if nav_map:
                for nav_point in nav_map.find_all("navPoint", recursive=False):
                    self._parse_ncx_navpoint(
                        nav_point,
                        ordered_nav_entries,
                        doc_order,
                        doc_order_decoded,
                        self.processed_nav_structure,
                        self._find_position_robust,
                    )
                parse_successful = bool(ordered_nav_entries)
        elif nav_type == "html":
            toc_nav = nav_soup.find("nav", attrs={"epub:type": "toc"})
            if not toc_nav:
                for nav in nav_soup.find_all("nav"):
                    if nav.find("ol"):
                        toc_nav = nav
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
                            self._find_position_robust,
                        )
                    parse_successful = bool(ordered_nav_entries)

        if not parse_successful:
            raise ValueError("No valid navigation entries found after parsing")

        ordered_nav_entries.sort(key=lambda x: (x["doc_order"], x["position"]))

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

                if current_doc == next_doc:
                    slice_html = current_doc_html[start_slice_pos:next_pos]
                else:
                    slice_html = current_doc_html[start_slice_pos:]
                    docs_between = []
                    try:
                        idx_current = spine_docs.index(current_doc)
                        idx_next = spine_docs.index(next_doc)
                        if idx_current < idx_next:
                            docs_between = [
                                spine_docs[k] for k in range(idx_current + 1, idx_next)
                            ]
                        elif idx_current > idx_next:
                            docs_between = [
                                spine_docs[k]
                                for k in range(idx_current + 1, len(spine_docs))
                            ]
                            docs_between.extend(
                                [spine_docs[k] for k in range(0, idx_next)]
                            )
                    except ValueError:
                        pass

                    for doc_href in docs_between:
                        slice_html += self.doc_content.get(doc_href, "")
                    next_doc_html = self.doc_content.get(next_doc, "")
                    slice_html += next_doc_html[:next_pos]
            else:
                slice_html = current_doc_html[start_slice_pos:]
                try:
                    idx_current = spine_docs.index(current_doc)
                    for doc_idx in range(idx_current + 1, len(spine_docs)):
                        slice_html += self.doc_content.get(spine_docs[doc_idx], "")
                except ValueError:
                    pass

            if not slice_html.strip() and current_doc_html:
                slice_html = current_doc_html

            if slice_html.strip():
                slice_soup = BeautifulSoup(slice_html, "html.parser")
                for tag in slice_soup.find_all(["p", "div"]):
                    tag.append("\n\n")

                for ol in slice_soup.find_all("ol"):
                    start = int(ol.get("start", 1))
                    for idx, li in enumerate(ol.find_all("li", recursive=False)):
                        number_text = f"{start + idx}) "
                        if li.string:
                            li.string.replace_with(number_text + li.string)
                        else:
                            li.insert(0, NavigableString(number_text))

                for tag in slice_soup.find_all(["sup", "sub"]):
                    tag.decompose()

                text = clean_text(slice_soup.get_text()).strip()
                if text:
                    self.content_texts[current_src] = text
                    self.content_lengths[current_src] = calculate_text_length(text)
                else:
                    self.content_texts[current_src] = ""
                    self.content_lengths[current_src] = 0
            else:
                self.content_texts[current_src] = ""
                self.content_lengths[current_src] = 0

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
                            "has_content": True,
                        },
                    )

    def _process_epub_content_spine_fallback(self):
        """
        Process EPUB content using the spine (linear reading order)
        when navigation processing fails.
        """
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

        for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            href = item.get_name()
            if href in spine_docs:
                try:
                    html_content = item.get_content().decode("utf-8", errors="ignore")
                    self.doc_content[href] = html_content
                except Exception:
                    self.doc_content[href] = ""

        self.content_texts = {}
        self.content_lengths = {}
        for i, doc_href in enumerate(spine_docs):
            html_content = self.doc_content.get(doc_href, "")
            if html_content:
                soup = BeautifulSoup(html_content, "html.parser")

                # Handle ordered lists
                for ol in soup.find_all("ol"):
                    start = int(ol.get("start", 1))
                    for idx, li in enumerate(ol.find_all("li", recursive=False)):
                        number_text = f"{start + idx}) "
                        if li.string:
                            li.string.replace_with(number_text + li.string)
                        else:
                            li.insert(0, NavigableString(number_text))

                # Remove sup/sub
                for tag in soup.find_all(["sup", "sub"]):
                    tag.decompose()

                text = clean_text(soup.get_text()).strip()
                if text:
                    self.content_texts[doc_href] = text
                    self.content_lengths[doc_href] = calculate_text_length(text)

    def get_chapters(self):
        chapters = super().get_chapters()
        if not chapters:
            # Use spine order fallback if no Nav structure
            if self.book:
                for spine_item_tuple in self.book.spine:
                    item_id = spine_item_tuple[0]
                    item = self.book.get_item_with_id(item_id)
                    if item:
                        href = item.get_name()
                        if href in self.content_texts:
                            chapters.append((href, href))
        return chapters


def get_book_parser(book_path, file_type=None):
    """
    Factory function to get the appropriate parser instance.
    """
    book_path = os.path.normpath(os.path.abspath(book_path))

    if not file_type:
        if book_path.lower().endswith(".pdf"):
            file_type = "pdf"
        elif book_path.lower().endswith((".md", ".markdown")):
            file_type = "markdown"
        else:
            file_type = "epub"

    if file_type == "pdf":
        return PdfParser(book_path)
    elif file_type == "markdown":
        return MarkdownParser(book_path)
    elif file_type == "epub":
        return EpubParser(book_path)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")
