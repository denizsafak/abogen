import re
import base64
from bs4 import BeautifulSoup, NavigableString
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import (
    QDialog,
    QTreeWidget,
    QTreeWidgetItem,
    QTextEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QDialogButtonBox,
    QSplitter,
    QWidget,
    QCheckBox,
    QTreeWidgetItemIterator,
    QLabel,
    QMenu,
)
from PyQt6.QtCore import (
    Qt,
    QThread,
    pyqtSignal,
    QSize,
)
from abogen.utils import (
    detect_encoding,
    get_resource_path,
)
from abogen.book_parser import get_book_parser

from abogen.subtitle_utils import (
    clean_text,
    calculate_text_length,
)

import os
import logging
import urllib.parse
import textwrap

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_LEADING_DASH_PATTERN = re.compile(r"^\s*[-–—]\s*")
_LEADING_SIMPLE_DASH_PATTERN = re.compile(r"^\s*-\s*")


class HandlerDialog(QDialog):
    # Class variables to remember checkbox states between dialog instances
    _save_chapters_separately = False
    _merge_chapters_at_end = True
    _save_as_project = False  # New class variable for save_as_project option

    # Cache for processed book content to avoid reprocessing
    # Key: (book_path, modification_time, file_type)
    # Value: dict with content_texts, content_lengths, doc_content (for epub), markdown_toc (for markdown)
    _content_cache = {}

    class _LoaderThread(QThread):
        """Minimal QThread that runs a callable and emits an error string on exception."""

        error = pyqtSignal(str)

        def __init__(self, target_callable):
            super().__init__()
            self._target = target_callable

        def run(self):
            try:
                self._target()
            except Exception as e:
                self.error.emit(str(e))

    @classmethod
    def clear_content_cache(cls, book_path=None):
        """Clear the content cache. If book_path is provided, only clear that book's cache."""
        if book_path is None:
            cls._content_cache.clear()
            logging.info("Cleared all content cache")
        else:
            keys_to_remove = [
                key for key in cls._content_cache.keys() if key[0] == book_path
            ]
            for key in keys_to_remove:
                del cls._content_cache[key]
            if keys_to_remove:
                logging.info(f"Cleared content cache for {os.path.basename(book_path)}")

    def __init__(self, book_path, file_type=None, checked_chapters=None, parent=None):
        super().__init__(parent)

        # Normalize path
        book_path = os.path.normpath(os.path.abspath(book_path))
        self.book_path = book_path

        # Initialize Parser
        try:
            # Factory handles file type detection if file_type is None
            self.parser = get_book_parser(book_path, file_type=file_type)
            # Parser loads automatically in init now
        except Exception as e:
            logging.error(f"Failed to initialize parser for {book_path}: {e}")
            raise

        # Extract book name from file path
        book_name = os.path.splitext(os.path.basename(book_path))[0]

        # Set window title based on file type and book name
        item_type = "Chapters" if self.parser.file_type in ["epub", "markdown"] else "Pages"
        self.setWindowTitle(f"Select {item_type} - {book_name}")
        self.resize(1200, 900)
        self._block_signals = False  # Flag to prevent recursive signals
        # Configure window: remove help button and allow resizing
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)
        # Initialize save chapters flags from class variables
        self.save_chapters_separately = HandlerDialog._save_chapters_separately
        self.merge_chapters_at_end = HandlerDialog._merge_chapters_at_end
        self.save_as_project = HandlerDialog._save_as_project

        # Initialize metadata dict; will be populated in _preprocess_content by the background loader
        self.book_metadata = {}

        # Initialize UI elements that are used in other methods
        self.save_chapters_checkbox = None
        self.merge_chapters_checkbox = None

        # Build treeview
        self.treeWidget = QTreeWidget(self)
        self.treeWidget.setHeaderHidden(True)
        self.treeWidget.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.treeWidget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.treeWidget.customContextMenuRequested.connect(self.on_tree_context_menu)

        # Initialize checked_chapters set
        self.checked_chapters = set(checked_chapters) if checked_chapters else set()

        # For storing content and lengths (will be filled by background loader)
        self.content_texts = {}
        self.content_lengths = {}
        # Also maintain refs for structure
        self.processed_nav_structure = []

        # Add a placeholder "Information" item so the tree isn't empty immediately
        info_item = QTreeWidgetItem(self.treeWidget, ["Information"])
        info_item.setData(0, Qt.ItemDataRole.UserRole, "info:bookinfo")
        info_item.setFlags(info_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        font = info_item.font(0)
        font.setBold(True)
        info_item.setFont(0, font)

        # Setup UI now so dialog appears immediately
        self._setup_ui()

        # Create a centered loading overlay and show it while background load runs
        self._create_loading_overlay()
        # Hide the main UI so only the overlay is visible initially
        if getattr(self, "splitter", None) is not None:
            self.splitter.setVisible(False)
        self._show_loading_overlay("Loading...")

        # Start background loading of book content so the dialog opens immediately
        self._start_background_load()

        # Hide expand/collapse decoration if there are no parent items
        has_parents = False
        for i in range(self.treeWidget.topLevelItemCount()):
            if self.treeWidget.topLevelItem(i).childCount() > 0:
                has_parents = True
                break
        self.treeWidget.setRootIsDecorated(has_parents)

    def _create_loading_overlay(self):
        """Create a centered loading indicator with a GIF on the left and text on the right.

        The indicator is added to the dialog's main layout above the splitter so
        when the splitter is hidden only the indicator is visible.
        """
        try:
            # Container to hold gif + text and allow centering via stretches
            container = QWidget(self)
            container.setVisible(False)
            h = QHBoxLayout(container)
            h.setContentsMargins(0, 8, 0, 8)
            h.setSpacing(10)

            # Left: GIF label (animated)
            gif_label = QLabel(container)
            gif_label.setVisible(False)

            loading_gif_path = get_resource_path("abogen.assets", "loading.gif")
            movie = None
            if loading_gif_path:
                try:
                    movie = QMovie(loading_gif_path)
                    # Make GIF smaller so it doesn't dominate the text
                    movie.setScaledSize(QSize(25, 25))
                    gif_label.setMovie(movie)
                    gif_label.setFixedSize(25, 25)
                    gif_label.setVisible(True)
                except Exception:
                    movie = None

            # Right: Text label
            text_label = QLabel(container)
            text_label.setStyleSheet("font-size: 14pt;")

            # Add stretches to center the content horizontally
            h.addStretch(1)
            h.addWidget(gif_label, 0, Qt.AlignmentFlag.AlignVCenter)
            h.addWidget(text_label, 0, Qt.AlignmentFlag.AlignVCenter)
            h.addStretch(1)

            # Insert at top of main layout if present, otherwise keep as child
            try:
                layout = self.layout()
                if layout is not None:
                    layout.insertWidget(0, container)
            except Exception:
                pass

            # Store refs
            self._loading_container = container
            self._loading_gif_label = gif_label
            self._loading_text_label = text_label
            self._loading_movie = movie
        except Exception:
            self._loading_container = None
            self._loading_gif_label = None
            self._loading_text_label = None
            self._loading_movie = None

    def _show_loading_overlay(self, text: str):
        container = getattr(self, "_loading_container", None)
        text_lbl = getattr(self, "_loading_text_label", None)
        movie = getattr(self, "_loading_movie", None)
        gif_lbl = getattr(self, "_loading_gif_label", None)
        if container is None or text_lbl is None:
            return
        text_lbl.setText(text)
        if movie is not None and gif_lbl is not None:
            try:
                movie.start()
                gif_lbl.setVisible(True)
            except Exception:
                pass
        container.setVisible(True)

    def _hide_loading_overlay(self):
        container = getattr(self, "_loading_container", None)
        movie = getattr(self, "_loading_movie", None)
        if container is None:
            return
        if movie is not None:
            try:
                movie.stop()
            except Exception:
                pass
        container.setVisible(False)

    def _start_background_load(self):
        """Start a QThread that runs the preprocessing in background."""
        # Start a minimal QThread which executes _preprocess_content
        self._loader_thread = HandlerDialog._LoaderThread(self._preprocess_content)
        self._loader_thread.finished.connect(self._on_load_finished)
        self._loader_thread.error.connect(self._on_load_error)
        # ensure thread instance is deleted when done
        self._loader_thread.finished.connect(self._loader_thread.deleteLater)
        self._loader_thread.start()

    def _on_load_error(self, err_msg):
        logging.error(f"Error loading book in background: {err_msg}")
        if getattr(self, "previewEdit", None) is not None:
            self.previewEdit.setPlainText(f"Error loading book: {err_msg}")
        if getattr(self, "splitter", None) is not None:
            self.splitter.setVisible(True)
        self._hide_loading_overlay()

    def _on_load_finished(self):
        """Called in the main thread when background loading finished."""
        # Build the tree now that content_texts/content_lengths/etc. are ready
        try:
            # Rebuild tree based on file type
            self._build_tree()

            # Run auto-check if no provided checks are relevant
            if not self._are_provided_checks_relevant():
                self._run_auto_check()

            # Connect signals (after tree exists)
            self.treeWidget.currentItemChanged.connect(self.update_preview)
            self.treeWidget.itemChanged.connect(self.handle_item_check)
            self.treeWidget.itemChanged.connect(
                lambda _: self._update_checkbox_states()
            )
            self.treeWidget.itemDoubleClicked.connect(self.handle_item_double_click)

            # Expand and select first item
            self.treeWidget.expandAll()
            if self.treeWidget.topLevelItemCount() > 0:
                self.treeWidget.setCurrentItem(self.treeWidget.topLevelItem(0))
                self.treeWidget.setFocus()

            # Update checkbox states
            self._update_checkbox_states()

            # Update preview for the current selection
            current = self.treeWidget.currentItem()
            self.update_preview(current)

        except Exception as e:
            logging.error(f"Error finalizing book load: {e}")
        # Show the main UI and hide loading text
        if getattr(self, "splitter", None) is not None:
            self.splitter.setVisible(True)
        self._hide_loading_overlay()

    def _preprocess_content(self):
        """Pre-process content from the document"""
        # Create cache key from file path, modification time, file type, and replace_single_newlines setting
        try:
            mod_time = os.path.getmtime(self.book_path)
        except Exception:
            mod_time = 0

        # Include replace_single_newlines in cache key since it affects text cleaning
        from abogen.utils import load_config

        cfg = load_config()
        replace_single_newlines = cfg.get("replace_single_newlines", True)

        cache_key = (self.book_path, mod_time, self.parser.file_type, replace_single_newlines)

        # Check if content is already cached
        if cache_key in HandlerDialog._content_cache:
            cached_data = HandlerDialog._content_cache[cache_key]
            self.content_texts = cached_data["content_texts"]
            self.content_lengths = cached_data["content_lengths"]
            if "processed_nav_structure" in cached_data:
                self.processed_nav_structure = cached_data["processed_nav_structure"]
            if "book_metadata" in cached_data:
                self.book_metadata = cached_data["book_metadata"]
            
            # Apply to parser so it stays in sync if used elsewhere
            self.parser.content_texts = self.content_texts
            self.parser.content_lengths = self.content_lengths
            self.parser.processed_nav_structure = self.processed_nav_structure
            self.parser.book_metadata = self.book_metadata

            logging.info(f"Using cached content for {os.path.basename(self.book_path)}")
            return

        # Process content if not cached
        try:
            self.parser.process_content(replace_single_newlines=replace_single_newlines)
            self.content_texts = self.parser.content_texts
            self.content_lengths = self.parser.content_lengths
            self.processed_nav_structure = self.parser.processed_nav_structure
            self.book_metadata = self.parser.get_metadata()
        except Exception as e:
            logging.error(f"Error processing content: {e}", exc_info=True)
            # Handle empty/failure case
            self.content_texts = {}
            self.content_lengths = {}

        # Cache the processed content
        cache_data = {
            "content_texts": self.content_texts,
            "content_lengths": self.content_lengths,
            "processed_nav_structure": self.processed_nav_structure,
            "book_metadata": self.book_metadata,
        }

        HandlerDialog._content_cache[cache_key] = cache_data
        logging.info(f"Cached content for {os.path.basename(self.book_path)}")


    def _build_tree(self):
        self.treeWidget.clear()

        info_item = QTreeWidgetItem(self.treeWidget, ["Information"])
        info_item.setData(0, Qt.ItemDataRole.UserRole, "info:bookinfo")
        info_item.setFlags(info_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        font = info_item.font(0)
        font.setBold(True)
        info_item.setFont(0, font)

        if self.processed_nav_structure:
            self._build_tree_from_nav(
                self.processed_nav_structure, self.treeWidget
            )
        else:
             # If no structure found but content exists (rare fallback), list flat
             for ch_id, ch_len in self.content_lengths.items():
                 # Simple flat list
                 item = QTreeWidgetItem(self.treeWidget, [ch_id])
                 item.setData(0, Qt.ItemDataRole.UserRole, ch_id)
                 item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                 if self.content_texts.get(ch_id):
                     item.setCheckState(0, Qt.CheckState.Checked if ch_id in self.checked_chapters else Qt.CheckState.Unchecked)

        has_parents = False
        iterator = QTreeWidgetItemIterator(
            self.treeWidget, QTreeWidgetItemIterator.IteratorFlag.HasChildren
        )
        if iterator.value():
            has_parents = True
        self.treeWidget.setRootIsDecorated(has_parents)

    def _update_checkbox_states(self):
        """Update the checkbox states based on the current checked chapters."""
        for i in range(self.treeWidget.topLevelItemCount()):
            item = self.treeWidget.topLevelItem(i)
            self._update_item_checkbox_state(item)

    def _build_tree_from_nav(
        self, nav_nodes, parent_item, seen_content_hashes=None
    ):
        if seen_content_hashes is None:
            seen_content_hashes = set()
        for node in nav_nodes:
            title = node.get("title", "Unknown")
            src = node.get("src")
            children = node.get("children", [])

            item = QTreeWidgetItem(parent_item, [title])
            item.setData(0, Qt.ItemDataRole.UserRole, src)

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
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                is_checked = src in self.checked_chapters
                item.setCheckState(
                    0, Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked
                )
            elif is_duplicate:
                # Mark as duplicate and remove checkbox
                item.setText(0, f"{title} (Duplicate)")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            elif children:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)

            if children:
                self._build_tree_from_nav(children, item, seen_content_hashes)


    def _are_provided_checks_relevant(self):
        if not self.checked_chapters:
            return False

        all_identifiers = set()
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                identifier = item.data(0, Qt.ItemDataRole.UserRole)
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

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        item_type = "chapters" if self.parser.file_type in ["epub", "markdown"] else "pages"

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
            if self.parser.file_type in ["epub", "markdown"]
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

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
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
            self.parser.file_type == "pdf"
            and hasattr(self, "has_pdf_bookmarks")
            and not self.has_pdf_bookmarks
        ):
            self.save_chapters_checkbox.setEnabled(False)
            self.merge_chapters_checkbox.setEnabled(False)
            return

        checked_count = 0

        if self.parser.file_type in ["epub", "markdown"]:
            iterator = QTreeWidgetItemIterator(self.treeWidget)
            while iterator.value():
                item = iterator.value()
                if (
                    item.flags() & Qt.ItemFlag.ItemIsUserCheckable
                    and item.checkState(0) == Qt.CheckState.Checked
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
                    item.flags() & Qt.ItemFlag.ItemIsUserCheckable
                    and item.checkState(0) == Qt.CheckState.Checked
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
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(0, Qt.CheckState.Checked)
            iterator += 1
        self._block_signals = False
        self._update_checked_set_from_tree()

    def deselect_all_chapters(self):
        self._block_signals = True
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(0, Qt.CheckState.Unchecked)
            iterator += 1
        self._block_signals = False
        self._update_checked_set_from_tree()

    def select_parent_chapters(self):
        self._block_signals = True
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable and item.childCount() > 0:
                item.setCheckState(0, Qt.CheckState.Checked)
            iterator += 1
        self._block_signals = False
        self._update_checked_set_from_tree()

    def deselect_parent_chapters(self):
        self._block_signals = True
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable and item.childCount() > 0:
                item.setCheckState(0, Qt.CheckState.Unchecked)
            iterator += 1
        self._block_signals = False
        self._update_checked_set_from_tree()

    def auto_select_chapters(self):
        self._run_auto_check()

    def _run_auto_check(self):
        self._block_signals = True

        if self.parser.file_type == "epub":
            self._run_epub_auto_check()
        elif self.parser.file_type == "markdown":
            self._run_markdown_auto_check()
        else:
            self._run_pdf_auto_check()

        self._block_signals = False
        self._update_checked_set_from_tree()

    def _run_epub_auto_check(self):
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                iterator += 1
                continue

            src = item.data(0, Qt.ItemDataRole.UserRole)

            has_significant_content = src and self.content_lengths.get(src, 0) > 1000
            is_parent = item.childCount() > 0

            if has_significant_content or is_parent:
                item.setCheckState(0, Qt.CheckState.Checked)
                if is_parent:
                    for i in range(item.childCount()):
                        child = item.child(i)
                        if child.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                            child_src = child.data(0, Qt.ItemDataRole.UserRole)
                            child_has_content = (
                                child_src and self.content_lengths.get(child_src, 0) > 0
                            )
                            child_is_parent = child.childCount() > 0
                            if child_has_content or child_is_parent:
                                child.setCheckState(0, Qt.CheckState.Checked)
            else:
                item.setCheckState(0, Qt.CheckState.Unchecked)

            iterator += 1

    def _run_markdown_auto_check(self):
        """Auto-select markdown chapters with significant content"""
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                iterator += 1
                continue

            identifier = item.data(0, Qt.ItemDataRole.UserRole)

            # Select chapters with content > 500 characters or parent items
            has_significant_content = (
                identifier and self.content_lengths.get(identifier, 0) > 500
            )
            is_parent = item.childCount() > 0

            if has_significant_content or is_parent:
                item.setCheckState(0, Qt.CheckState.Checked)
                # Also check children if this is a parent
                if is_parent:
                    for i in range(item.childCount()):
                        child = item.child(i)
                        if child.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                            child_identifier = child.data(0, Qt.ItemDataRole.UserRole)
                            child_has_content = (
                                child_identifier
                                and self.content_lengths.get(child_identifier, 0) > 0
                            )
                            child_is_parent = child.childCount() > 0
                            if child_has_content or child_is_parent:
                                child.setCheckState(0, Qt.CheckState.Checked)
            else:
                item.setCheckState(0, Qt.CheckState.Unchecked)

            iterator += 1

    def _run_pdf_auto_check(self):
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                iterator += 1
                continue

            identifier = item.data(0, Qt.ItemDataRole.UserRole)
            if not identifier:
                 iterator += 1
                 continue
                 
            # Logic: Check item if it has content (already handled by ItemIsUserCheckable flag really)
            # But duplicate logic from previous implementation:
            item.setCheckState(0, Qt.CheckState.Checked)

            iterator += 1

    def _update_checked_set_from_tree(self):
        self.checked_chapters.clear()
        iterator = QTreeWidgetItemIterator(self.treeWidget)
        while iterator.value():
            item = iterator.value()
            if item.checkState(0) == Qt.CheckState.Checked:
                identifier = item.data(0, Qt.ItemDataRole.UserRole)
                if identifier:
                    self.checked_chapters.add(identifier)
            iterator += 1
        if hasattr(self, "save_chapters_checkbox") and self.save_chapters_checkbox:
            self._update_checkbox_states()

    def handle_item_check(self, item):
        if self._block_signals:
            return

        self._block_signals = True

        if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            for i in range(item.childCount()):
                child = item.child(i)
                if child.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    child.setCheckState(0, item.checkState(0))

        self._block_signals = False
        self._update_checked_set_from_tree()

    def handle_item_double_click(self, item, column=0):
        if item.flags() & Qt.ItemFlag.ItemIsUserCheckable and item.childCount() == 0:
            rect = self.treeWidget.visualItemRect(item)
            checkbox_width = 20

            mouse_pos = self.treeWidget.mapFromGlobal(self.treeWidget.cursor().pos())

            if mouse_pos.x() > rect.x() + checkbox_width:
                new_state = (
                    Qt.CheckState.Unchecked
                    if item.checkState(0) == Qt.CheckState.Checked
                    else Qt.CheckState.Checked
                )
                item.setCheckState(0, new_state)

    def update_preview(self, current):
        if not current:
            self.previewEdit.clear()
            return

        identifier = current.data(0, Qt.ItemDataRole.UserRole)

        if identifier == "info:bookinfo":
            self._display_book_info()
            return

        text = None
        if self.parser.file_type == "epub":
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
            # Apply clean_text to preview so replace_single_newlines setting is respected
            cleaned_text = clean_text(text)
            self.previewEdit.setPlainText(cleaned_text)

    def _display_book_info(self):
        self.previewEdit.clear()
        html_content = "<html><body style='font-family: Arial, sans-serif;'>"

        cover_image = self.book_metadata.get("cover_image")
        if cover_image:
            try:
                image_data = base64.b64encode(cover_image).decode("utf-8")

                image_type = "jpeg"
                if cover_image.startswith(b"\x89PNG"):
                    image_type = "png"
                elif cover_image.startswith(b"GIF"):
                    image_type = "gif"

                html_content += (
                    f"<div style='text-align: center; margin-bottom: 20px;'>"
                )
                html_content += (
                    f"<img src='data:image/{image_type};base64,{image_data}' "
                )
                html_content += "width='300' style='object-fit: contain;' /></div>"
            except Exception as e:
                html_content += f"<p>Error displaying cover image: {str(e)}</p>"

        title = self.book_metadata.get("title")
        if title:
            html_content += (
                f"<h2 style='text-align: center;'>{title}</h2>"
            )

        authors = self.book_metadata.get("authors")
        if authors:
            authors_text = ", ".join(authors)
            html_content += f"<p style='text-align: center; font-style: italic;'>By {authors_text}</p>"

        publisher = self.book_metadata.get("publisher")
        pub_year = self.book_metadata.get("publication_year")

        if publisher or pub_year:
            pub_info = []
            if publisher:
                pub_info.append(f"Published by {publisher}")
            if pub_year:
                pub_info.append(f"Year: {pub_year}")
            html_content += f"<p style='text-align: center;'>{' | '.join(pub_info)}</p>"

        html_content += "<hr/>"

        description = self.book_metadata.get("description")
        if description:
            # Use pre-compiled pattern for better performance
            desc = _HTML_TAG_PATTERN.sub("", description)
            html_content += f"<h3>Description:</h3><p>{desc}</p>"

        if self.parser.file_type == "pdf":
            # Access pdf_doc from parser if available
            pdf_doc = getattr(self.parser, "pdf_doc", None)
            page_count = len(pdf_doc) if pdf_doc else 0
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

        if self.parser.file_type == "epub":
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
        elif self.parser.file_type == "markdown":
            # Extract metadata from markdown frontmatter or first heading
            if self.markdown_text:
                # Try to extract YAML frontmatter
                frontmatter_match = re.match(
                    r"^---\s*\n(.*?)\n---\s*\n", self.markdown_text, re.DOTALL
                )
                if frontmatter_match:
                    try:
                        frontmatter = frontmatter_match.group(1)
                        # Simple YAML-like parsing for common fields
                        title_match = re.search(
                            r"^title:\s*(.+)$",
                            frontmatter,
                            re.MULTILINE | re.IGNORECASE,
                        )
                        if title_match:
                            metadata["title"] = (
                                title_match.group(1).strip().strip("\"'")
                            )

                        author_match = re.search(
                            r"^author:\s*(.+)$",
                            frontmatter,
                            re.MULTILINE | re.IGNORECASE,
                        )
                        if author_match:
                            metadata["authors"] = [
                                author_match.group(1).strip().strip("\"'")
                            ]

                        desc_match = re.search(
                            r"^description:\s*(.+)$",
                            frontmatter,
                            re.MULTILINE | re.IGNORECASE,
                        )
                        if desc_match:
                            metadata["description"] = (
                                desc_match.group(1).strip().strip("\"'")
                            )

                        date_match = re.search(
                            r"^date:\s*(.+)$", frontmatter, re.MULTILINE | re.IGNORECASE
                        )
                        if date_match:
                            date_str = date_match.group(1).strip().strip("\"'")
                            year_match = re.search(r"\b(19|20)\d{2}\b", date_str)
                            if year_match:
                                metadata["publication_year"] = year_match.group(0)
                    except Exception as e:
                        logging.warning(f"Error parsing markdown frontmatter: {e}")

                # Fallback: use first H1 header as title if no frontmatter title
                if not metadata["title"] and self.markdown_toc:
                    # Find the first level 1 header
                    first_h1 = next(
                        (h for h in self.markdown_toc if h["level"] == 1), None
                    )
                    if first_h1:
                        metadata["title"] = first_h1["name"]
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
        # If a background loader thread is running, wait for it to finish to
        # preserve compatibility with callers that expect content to be ready
        # when they create a HandlerDialog and immediately request selected text.
        try:
            if (
                hasattr(self, "_loader_thread")
                and getattr(self, "_loader_thread") is not None
            ):
                # Wait for thread to finish (blocks until done)
                if self._loader_thread.isRunning():
                    self._loader_thread.wait()
        except Exception:
            pass

        if self.parser.file_type == "epub":
            return self._get_epub_selected_text()
        elif self.parser.file_type == "markdown":
            return self._get_markdown_selected_text()
        else:
            return self._get_pdf_selected_text()

    def _format_metadata_tags(self):
        """Format metadata tags for insertion at the beginning of the text"""
        import datetime
        from abogen.utils import get_user_cache_path

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
            f"{total_chapters} {'Chapters' if self.parser.file_type == 'epub' else 'Pages'}"
        )

        # Handle cover image
        cover_tag = ""
        if metadata.get("cover_image"):
            try:
                import uuid

                cache_dir = get_user_cache_path()
                cover_path = os.path.join(cache_dir, f"cover_{uuid.uuid4()}.jpg")
                cover_path = os.path.normpath(cover_path)
                with open(cover_path, "wb") as f:
                    f.write(metadata["cover_image"])
                cover_tag = f"<<METADATA_COVER_PATH:{cover_path}>>"
            except Exception as e:
                logging.warning(f"Failed to save cover image: {e}")

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

        if cover_tag:
            metadata_tags.append(cover_tag)

        return "\n".join(metadata_tags)

    def _get_markdown_selected_text(self):
        """Get selected text from markdown chapters"""
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
            if item.checkState(0) == Qt.CheckState.Checked:
                identifier = item.data(0, Qt.ItemDataRole.UserRole)

                if identifier and identifier != "info:bookinfo":
                    all_checked_identifiers.add(identifier)
                    ordered_checked_items.append((item_order_counter, item, identifier))
            iterator += 1

        ordered_checked_items.sort(key=lambda x: x[0])

        for order, item, identifier in ordered_checked_items:
            text = self.content_texts.get(identifier)
            if text and text.strip():
                title = item.text(0)
                # Remove leading dashes from title using pre-compiled pattern
                title = _LEADING_DASH_PATTERN.sub("", title).strip()
                marker = f"<<CHAPTER_MARKER:{title}>>"
                chapter_texts.append(marker + "\n" + text)

        full_text = metadata_tags + "\n\n" + "\n\n".join(chapter_texts)
        return full_text, all_checked_identifiers

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
            if item.checkState(0) == Qt.CheckState.Checked:
                identifier = item.data(0, Qt.ItemDataRole.UserRole)
                if identifier and identifier != "info:bookinfo":
                    all_checked_identifiers.add(identifier)
                    ordered_checked_items.append((item_order_counter, item, identifier))
            iterator += 1

        ordered_checked_items.sort(key=lambda x: x[0])

        for order, item, identifier in ordered_checked_items:
            text = self.content_texts.get(identifier)
            if text and text.strip():
                title = item.text(0)
                # Use pre-compiled pattern for better performance
                title = _LEADING_DASH_PATTERN.sub("", title).strip()
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
            if item.checkState(0) == Qt.CheckState.Checked:
                identifier = item.data(0, Qt.ItemDataRole.UserRole)
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
                parent_checked = item.checkState(0) == Qt.CheckState.Checked
                parent_id = item.data(0, Qt.ItemDataRole.UserRole)
                parent_title = item.text(0)
                checked_children = []
                for i in range(item.childCount()):
                    child = item.child(i)
                    child_id = child.data(0, Qt.ItemDataRole.UserRole)
                    if (
                        child.checkState(0) == Qt.CheckState.Checked
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
                        # Use pre-compiled pattern for better performance
                        title = _LEADING_SIMPLE_DASH_PATTERN.sub(
                            "", parent_title
                        ).strip()
                        marker = f"<<CHAPTER_MARKER:{title}>>"
                        section_titles.append((title, marker + "\n" + combined_text))
                        included_text_ids.add(parent_id)
                elif not parent_checked and checked_children:
                    # Use pre-compiled pattern for better performance
                    title = _LEADING_SIMPLE_DASH_PATTERN.sub("", parent_title).strip()
                    marker = f"<<CHAPTER_MARKER:{title}>>"
                    for idx, (child, child_id) in enumerate(checked_children):
                        text = self.content_texts.get(child_id, "")
                        if text:
                            if idx == 0:
                                section_titles.append((title, marker + "\n" + text))
                            else:
                                section_titles.append((title, text))
                        included_text_ids.add(child_id)
            elif item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                identifier = item.data(0, Qt.ItemDataRole.UserRole)
                if (
                    identifier
                    and identifier not in included_text_ids
                    and item.checkState(0) == Qt.CheckState.Checked
                ):
                    text = self.content_texts.get(identifier, "")
                    if text:
                        title = item.text(0)
                        # Use pre-compiled pattern for better performance
                        title = _LEADING_SIMPLE_DASH_PATTERN.sub("", title).strip()
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
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(
                    0, Qt.CheckState.Checked if state else Qt.CheckState.Unchecked
                )
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
            menu.exec(self.treeWidget.mapToGlobal(pos))
            return

        if (
            not item
            or item.childCount() == 0
            or not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        ):
            return

        menu = QMenu(self)
        checked = item.checkState(0) == Qt.CheckState.Checked
        text = "Unselect only this" if checked else "Select only this"
        action = menu.addAction(text)

        def do_toggle():
            self.treeWidget.blockSignals(True)
            new_state = Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked
            item.setCheckState(0, new_state)
            self.treeWidget.blockSignals(False)
            self._update_checked_set_from_tree()

        action.triggered.connect(do_toggle)
        menu.exec(self.treeWidget.mapToGlobal(pos))


