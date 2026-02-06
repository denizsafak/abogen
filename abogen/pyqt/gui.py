import os
import time
import sys
import tempfile
import platform
import base64
import re
from abogen.pyqt.queue_manager_gui import QueueManager
from abogen.pyqt.queued_item import QueuedItem
import abogen.hf_tracker as hf_tracker
import hashlib  # Added for cache path generation
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QTextEdit,
    QLabel,
    QSlider,
    QMessageBox,
    QFileDialog,
    QProgressBar,
    QFrame,
    QStyleFactory,
    QInputDialog,
    QFileIconProvider,
    QSizePolicy,
    QDialog,
    QCheckBox,
    QMenu,
)
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtCore import (
    Qt,
    QUrl,
    QPoint,
    QFileInfo,
    QThread,
    pyqtSignal,
    QObject,
    QBuffer,
    QIODevice,
    QSize,
    QTimer,
    QEvent,
    QProcess,
)
from PyQt6.QtGui import (
    QTextCursor,
    QDesktopServices,
    QIcon,
    QPixmap,
    QPainter,
    QPolygon,
    QColor,
    QMovie,
    QPalette,
)
from abogen.utils import (
    load_config,
    save_config,
    get_gpu_acceleration,
    prevent_sleep_start,
    prevent_sleep_end,
    get_resource_path,
    get_user_cache_path,
    LoadPipelineThread,
)

from abogen.subtitle_utils import (
    clean_text,
    calculate_text_length,
)

from abogen.conversion import ConversionThread, VoicePreviewThread, PlayAudioThread
from abogen.pyqt.book_handler import HandlerDialog
from abogen.constants import (
    PROGRAM_NAME,
    VERSION,
    GITHUB_URL,
    PROGRAM_DESCRIPTION,
    LANGUAGE_DESCRIPTIONS,
    VOICES_INTERNAL,
    SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION,
    COLORS,
    SUBTITLE_FORMATS,
)
import threading
from abogen.pyqt.voice_formula_gui import VoiceFormulaDialog
from abogen.voice_profiles import load_profiles

# Import ctypes for Windows-specific taskbar icon
if platform.system() == "Windows":
    import ctypes


class DarkTitleBarEventFilter(QObject):
    def __init__(self, is_windows, get_dark_mode_func, set_title_bar_dark_mode_func):
        super().__init__()
        self.is_windows = is_windows
        self.get_dark_mode = get_dark_mode_func
        self.set_title_bar_dark_mode = set_title_bar_dark_mode_func

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show:
            # Only apply to QWidget windows
            if isinstance(obj, QWidget) and obj.isWindow():
                if self.is_windows and self.get_dark_mode():
                    self.set_title_bar_dark_mode(obj, True)
        return super().eventFilter(obj, event)


class ShowWarningSignalEmitter(QObject):  # New class to handle signal emission
    show_warning_signal = pyqtSignal(str, str)

    def emit(self, title, message):
        self.show_warning_signal.emit(title, message)


class ThreadSafeLogSignal(QObject):
    log_signal = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

    def emit_log(self, message):
        self.log_signal.emit(message)


class IconProvider(QFileIconProvider):
    def icon(self, fileInfo):
        return super().icon(fileInfo)


LOG_COLOR_MAP = {
    True: COLORS["GREEN"],
    False: COLORS["RED"],
    "red": COLORS["RED"],
    "green": COLORS["GREEN"],
    "orange": COLORS["ORANGE"],
    "blue": COLORS["BLUE"],
    "grey": COLORS["LIGHT_DISABLED"],
    None: COLORS["LIGHT_DISABLED"],
}


class InputBox(QLabel):
    # Define CSS styles as class constants
    STYLE_DEFAULT = f"border:2px dashed #aaa; border-radius:5px; padding:20px; background:{COLORS['BLUE_BG']}; min-height:100px;"
    STYLE_DEFAULT_HOVER = f"background:{COLORS['BLUE_BG_HOVER']}; border-color:{COLORS['BLUE_BORDER_HOVER']};"

    STYLE_ACTIVE = f"border:2px dashed {COLORS['GREEN']}; border-radius:5px; padding:20px; background:{COLORS['GREEN_BG']}; min-height:100px;"
    STYLE_ACTIVE_HOVER = (
        f"background:{COLORS['GREEN_BG_HOVER']}; border-color:{COLORS['GREEN_BORDER']};"
    )

    STYLE_ERROR = f"border:2px dashed {COLORS['RED']}; border-radius:5px; padding:20px; background:{COLORS['RED_BG']}; min-height:100px; color:{COLORS['RED']};"
    STYLE_ERROR_HOVER = (
        f"background:{COLORS['RED_BG_HOVER']}; border-color:{COLORS['RED']};"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)
        self.setText(
            "Drag and drop your file here or click to browse.\n(.txt, .epub, .pdf, .md, .srt, .ass, .vtt)"
        )
        self.setStyleSheet(
            f"QLabel {{ {self.STYLE_DEFAULT} }} QLabel:hover {{ {self.STYLE_DEFAULT_HOVER} }}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Add clear button
        self.clear_btn = QPushButton("✕", self)
        self.clear_btn.setFixedSize(28, 28)
        self.clear_btn.hide()
        self.clear_btn.clicked.connect(self.clear_input)

        # Add Chapters button
        self.chapters_btn = QPushButton("Chapters", self)
        self.chapters_btn.setStyleSheet("QPushButton { padding: 6px 10px; }")
        self.chapters_btn.hide()
        self.chapters_btn.clicked.connect(self.on_chapters_clicked)

        # Add Textbox button with no padding
        self.textbox_btn = QPushButton("Textbox", self)
        self.textbox_btn.setStyleSheet("QPushButton { padding: 6px 10px; }")
        self.textbox_btn.setToolTip("Input text directly instead of using a file")
        self.textbox_btn.clicked.connect(self.on_textbox_clicked)

        # Add Edit button matching the textbox button
        self.edit_btn = QPushButton("Edit", self)
        self.edit_btn.setStyleSheet("QPushButton { padding: 6px 10px; }")
        self.edit_btn.setToolTip("Edit the current text file")
        self.edit_btn.clicked.connect(self.on_edit_clicked)
        self.edit_btn.hide()

        # Add Go to folder button
        self.go_to_folder_btn = QPushButton("Go to folder", self)
        self.go_to_folder_btn.setStyleSheet("QPushButton { padding: 6px 10px; }")
        self.go_to_folder_btn.setToolTip(
            "Open the folder that contains the converted file"
        )
        self.go_to_folder_btn.clicked.connect(self.on_go_to_folder_clicked)
        self.go_to_folder_btn.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        margin = 12
        self.clear_btn.move(self.width() - self.clear_btn.width() - margin, margin)
        self.chapters_btn.move(
            margin, self.height() - self.chapters_btn.height() - margin
        )
        # Position textbox button at top left
        self.textbox_btn.move(margin, margin)
        self.edit_btn.move(margin, margin)
        # Position go to folder button at bottom right with correct margins
        self.go_to_folder_btn.move(
            self.width() - self.go_to_folder_btn.width() - margin,
            self.height() - self.go_to_folder_btn.height() - margin,
        )

    def set_file_info(self, file_path):
        # get icon without resizing using custom provider
        provider = IconProvider()
        qicon = provider.icon(QFileInfo(file_path))
        size = QSize(32, 32)
        pixmap = qicon.pixmap(size)
        # convert to base64 PNG
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")
        img_data = base64.b64encode(buffer.data()).decode()

        size_str = self._human_readable_size(os.path.getsize(file_path))
        name = os.path.basename(file_path)
        char_count = 0
        window = self.window()
        cache = getattr(window, "_char_count_cache", None)

        def parse_size(size_str):
            # Use regex to extract the numeric part
            match = re.match(r"([\d.]+)", size_str)
            if match:
                return float(match.group(1))
            raise ValueError(f"Invalid size format: {size_str}")

        # Format numbers with commas
        def format_num(n):
            try:
                if isinstance(n, str):
                    size = int(parse_size(n))
                    return f"{size:,}"
                else:
                    return f"{n:,}"
            except Exception:
                return str(n)

        doc_extensions = (".epub", ".pdf", ".md", ".markdown", ".srt", ".ass", ".vtt")
        char_source_path = file_path
        cached_char_count = None

        if file_path.lower().endswith(doc_extensions):
            selected_file_path = getattr(window, "selected_file", None)
            if selected_file_path and os.path.exists(selected_file_path):
                char_source_path = selected_file_path
            else:
                char_source_path = None

        if cache is not None:
            cached_char_count = cache.get(file_path)
            if (
                cached_char_count is None
                and char_source_path
                and char_source_path != file_path
            ):
                cached_char_count = cache.get(char_source_path)

        if cached_char_count is not None:
            char_count = cached_char_count
        elif char_source_path:
            try:
                with open(
                    char_source_path, "r", encoding="utf-8", errors="ignore"
                ) as f:
                    text = f.read()
                    cleaned_text = clean_text(text)
                    char_count = calculate_text_length(cleaned_text)
            except Exception:
                char_count = "N/A"
        else:
            char_count = "N/A"

        if cache is not None and isinstance(char_count, int):
            cache[file_path] = char_count
            if char_source_path and char_source_path != file_path:
                cache[char_source_path] = char_count

        # Store numeric char_count on window
        try:
            window.char_count = int(char_count)
        except Exception:
            window.char_count = 0
        # embed icon at native size with word-wrap for the filename
        self.setText(
            f'<img src="data:image/png;base64,{img_data}"><br><span style="display: inline-block; max-width: 100%; word-break: break-all;"><b>{name}</b></span><br>Size: {size_str}<br>Characters: {format_num(char_count)}'
        )
        # Set fixed width to force wrapping
        self.setWordWrap(True)
        self.setStyleSheet(
            f"QLabel {{ {self.STYLE_ACTIVE} }} QLabel:hover {{ {self.STYLE_ACTIVE_HOVER} }}"
        )
        self.clear_btn.show()
        is_document = window.selected_file_type in ["epub", "pdf", "md", "markdown"]
        self.chapters_btn.setVisible(is_document)
        if is_document:
            chapter_count = len(window.selected_chapters)
            file_type = window.selected_file_type
            # Adjust button text based on file type
            if file_type == "epub" or file_type == "md" or file_type == "markdown":
                self.chapters_btn.setText(f"Chapters ({chapter_count})")
            else:  # PDF - always use Pages
                self.chapters_btn.setText(f"Pages ({chapter_count})")

        # Hide textbox and show edit only for .txt, .srt, .ass, .vtt files
        self.textbox_btn.hide()
        # Show edit button for txt/subtitle files directly
        # Or for epub/pdf files that have generated a temp txt file
        should_show_edit = file_path.lower().endswith((".txt", ".srt", ".ass", ".vtt"))

        # For epub/pdf files, show edit if we have a selected_file (temp txt)
        if (
            window.selected_file_type
            in ["epub", "pdf", "md", "markdown", "md", "markdown"]
            and window.selected_file
        ):
            should_show_edit = True

        self.edit_btn.setVisible(should_show_edit)
        self.go_to_folder_btn.show()

        # Disable subtitle generation for subtitle input files
        is_subtitle_input = file_path.lower().endswith((".srt", ".ass", ".vtt"))
        if hasattr(window, "subtitle_combo"):
            window.subtitle_combo.setEnabled(not is_subtitle_input)

        # Enable add to queue button only when file is accepted (input box is green)
        self.resizeEvent(None)
        if hasattr(window, "btn_add_to_queue"):
            window.btn_add_to_queue.setEnabled(True)

        self.chapters_btn.adjustSize()
        # Reset the input_box_cleared_by_queue flag after setting file info
        if hasattr(window, "input_box_cleared_by_queue"):
            window.input_box_cleared_by_queue = False

    def set_error(self, message):
        self.setText(message)
        self.setStyleSheet(
            f"QLabel {{ {self.STYLE_ERROR} }} QLabel:hover {{ {self.STYLE_ERROR_HOVER} }}"
        )
        # Show textbox button in error state as well
        self.textbox_btn.show()
        # Disable add to queue button on error
        if hasattr(self.window(), "btn_add_to_queue"):
            self.window().btn_add_to_queue.setEnabled(False)

    def clear_input(self):
        self.window().selected_file = None
        self.window().displayed_file_path = (
            None  # Reset the displayed file path when clearing input
        )
        # Reset book handler attributes
        self.window().save_chapters_separately = None
        self.window().merge_chapters_at_end = None
        self.setText(
            "Drag and drop your file here or click to browse.\n(.txt, .epub, .pdf, .md, .srt, .ass, .vtt)"
        )
        self.setStyleSheet(
            f"QLabel {{ {self.STYLE_DEFAULT} }} QLabel:hover {{ {self.STYLE_DEFAULT_HOVER} }}"
        )
        self.clear_btn.hide()
        self.chapters_btn.hide()
        self.chapters_btn.setText("Chapters")  # Reset text
        # Show textbox and hide edit when input is cleared
        self.textbox_btn.show()
        self.edit_btn.hide()
        self.go_to_folder_btn.hide()

        # Re-enable subtitle and replace newlines controls when cleared
        window = self.window()
        if hasattr(window, "subtitle_combo"):
            # Only enable if language supports it
            current_lang = getattr(window, "selected_lang", "a")
            window.subtitle_combo.setEnabled(
                current_lang in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION
            )
        if hasattr(window, "replace_newlines_combo"):
            window.replace_newlines_combo.setEnabled(True)

        # Disable add to queue button when input is cleared
        if hasattr(window, "btn_add_to_queue"):
            window.btn_add_to_queue.setEnabled(False)
        # Reset the input_box_cleared_by_queue flag after setting file info
        if hasattr(self.window(), "input_box_cleared_by_queue"):
            self.window().input_box_cleared_by_queue = True

    def _human_readable_size(self, size, decimal_places=2):
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.{decimal_places}f} {unit}"
            size /= 1024.0
        return f"{size:.{decimal_places}f} PB"

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window().open_file_dialog()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                ext = urls[0].toLocalFile().lower()
                if (
                    ext.endswith(".txt")
                    or ext.endswith(".epub")
                    or ext.endswith(".pdf")
                    or ext.endswith((".md", ".markdown"))
                    or ext.endswith((".srt", ".ass", ".vtt"))
                ):
                    event.acceptProposedAction()
                    # Set hover style based on current state
                    if self.styleSheet().find(self.STYLE_ACTIVE) != -1:
                        self.setStyleSheet(
                            f"QLabel {{ {self.STYLE_ACTIVE} }} QLabel:hover {{ {self.STYLE_ACTIVE_HOVER} }} {self.STYLE_ACTIVE_HOVER}"
                        )
                    elif self.styleSheet().find(self.STYLE_ERROR) != -1:
                        self.setStyleSheet(
                            f"QLabel {{ {self.STYLE_ERROR} }} QLabel:hover {{ {self.STYLE_ERROR_HOVER} }} {self.STYLE_ERROR_HOVER}"
                        )
                    else:
                        self.setStyleSheet(
                            f"QLabel {{ {self.STYLE_DEFAULT} }} QLabel:hover {{ {self.STYLE_DEFAULT_HOVER} }} {self.STYLE_DEFAULT_HOVER}"
                        )
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        # Restore the style based on current state
        if self.styleSheet().find(self.STYLE_ACTIVE) != -1:
            self.setStyleSheet(
                f"QLabel {{ {self.STYLE_ACTIVE} }} QLabel:hover {{ {self.STYLE_ACTIVE_HOVER} }}"
            )
        elif self.styleSheet().find(self.STYLE_ERROR) != -1:
            self.setStyleSheet(
                f"QLabel {{ {self.STYLE_ERROR} }} QLabel:hover {{ {self.STYLE_ERROR_HOVER} }}"
            )
        else:
            self.setStyleSheet(
                f"QLabel {{ {self.STYLE_DEFAULT} }} QLabel:hover {{ {self.STYLE_DEFAULT_HOVER} }}"
            )
        event.accept()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if not urls:
                event.ignore()
                return
            file_path = urls[0].toLocalFile()
            win = self.window()
            if file_path.lower().endswith(".txt"):
                win.selected_file, win.selected_file_type = file_path, "txt"
                win.displayed_file_path = (
                    file_path  # Set the displayed file path for text files
                )
                self.set_file_info(file_path)
                event.acceptProposedAction()
            elif (
                file_path.lower().endswith(".epub")
                or file_path.lower().endswith(".pdf")
                or file_path.lower().endswith((".md", ".markdown"))
                or file_path.lower().endswith((".srt", ".ass", ".vtt"))
            ):
                # Determine file type
                if file_path.lower().endswith(".epub"):
                    file_type = "epub"
                elif file_path.lower().endswith(".pdf"):
                    file_type = "pdf"
                elif file_path.lower().endswith((".srt", ".ass", ".vtt")):
                    # For subtitle files, treat them like txt files (direct processing)
                    win.selected_file, win.selected_file_type = file_path, "txt"
                    win.displayed_file_path = file_path
                    self.set_file_info(file_path)
                    event.acceptProposedAction()
                    return
                else:
                    file_type = "markdown"

                # Just store the file path but don't set the file info yet
                win.selected_file_type = file_type
                win.selected_book_path = file_path
                win.open_book_file(
                    file_path  # This will handle the dialog and setting file info
                )
                event.acceptProposedAction()
            else:
                self.set_error(
                    "Please drop a .txt, .epub, .pdf, .md, .srt, .ass, or .vtt file."
                )
                event.ignore()
        else:
            event.ignore()

    def on_chapters_clicked(self):
        win = self.window()
        if (
            win.selected_file_type in ["epub", "pdf", "md", "markdown"]
            and win.selected_book_path
        ):
            # Call open_book_file which shows the dialog and updates selected_chapters
            if win.open_book_file(win.selected_book_path):
                # Refresh the info label and button text after dialog closes
                self.set_file_info(win.selected_book_path)

    def on_textbox_clicked(self):
        self.window().open_textbox_dialog()

    def on_edit_clicked(self):
        win = self.window()
        # For PDFs and EPUBs, use the temporary text file
        if (
            win.selected_file_type in ["epub", "pdf", "md", "markdown"]
            and win.selected_file
        ):
            # Use the temporary .txt file that was generated
            win.open_textbox_dialog(win.selected_file)
        else:
            # For regular txt files
            win.open_textbox_dialog()

    def on_go_to_folder_clicked(self):
        win = self.window()
        # win.selected_file holds the path to the text that is converted.
        file_to_check = win.selected_file

        # If this is a converted document (epub/pdf/markdown) that was written to the
        # user's cache directory, show a menu letting the user jump to either the
        # processed (cached .txt) file or the original input file (epub/pdf/md).
        try:
            cache_dir = get_user_cache_path()
        except Exception:
            cache_dir = None

        is_cached_doc = False
        if (
            file_to_check
            and os.path.exists(file_to_check)
            and os.path.isfile(file_to_check)
            and cache_dir
        ):
            # Consider it cached when the file is under the cache directory and is a .txt
            if file_to_check.endswith(".txt") and os.path.commonpath(
                [os.path.abspath(file_to_check), os.path.abspath(cache_dir)]
            ) == os.path.abspath(cache_dir):
                # Only treat as document-cache when original type was a document
                if getattr(win, "selected_file_type", None) in [
                    "epub",
                    "pdf",
                    "md",
                    "markdown",
                ]:
                    is_cached_doc = True

        if is_cached_doc:
            menu = QMenu(self)
            act_processed = QAction("Go to processed file", self)

            def open_processed():
                folder_path = os.path.dirname(file_to_check)
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))

            act_processed.triggered.connect(open_processed)
            menu.addAction(act_processed)

            act_input = QAction("Go to input file", self)
            # Prefer displayed_file_path (original input path) then selected_book_path
            input_path = getattr(win, "displayed_file_path", None) or getattr(
                win, "selected_book_path", None
            )
            if input_path and os.path.exists(input_path):

                def open_input():
                    folder_path = os.path.dirname(input_path)
                    QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))

                act_input.triggered.connect(open_input)
            else:
                act_input.setEnabled(False)

            menu.addAction(act_input)
            # Show the menu anchored to the button
            menu.exec(
                self.go_to_folder_btn.mapToGlobal(
                    QPoint(0, self.go_to_folder_btn.height())
                )
            )
        else:
            if (
                file_to_check
                and os.path.exists(file_to_check)
                and os.path.isfile(file_to_check)
            ):
                folder_path = os.path.dirname(file_to_check)
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))
            else:
                QMessageBox.warning(win, "Error", "Converted file not found.")


class TextboxDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter Text")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.resize(700, 500)

        layout = QVBoxLayout(self)

        # Instructions
        instructions = QLabel(
            "Enter or paste the text you want to convert to audio:", self
        )
        layout.addWidget(instructions)

        # Text edit area
        self.text_edit = QTextEdit(self)
        self.text_edit.setAcceptRichText(False)
        self.text_edit.setPlaceholderText("Type or paste your text here...")
        layout.addWidget(self.text_edit)

        # Character count label
        self.char_count_label = QLabel("Characters: 0", self)
        layout.addWidget(self.char_count_label)

        # Connect text changed signal to update character count
        self.text_edit.textChanged.connect(self.update_char_count)

        # Buttons
        button_layout = QHBoxLayout()

        self.save_as_button = QPushButton("Save as text", self)
        self.save_as_button.clicked.connect(self.save_as_text)
        self.save_as_button.setToolTip("Save the current text to a file")

        self.insert_chapter_btn = QPushButton("Insert Chapter Marker", self)
        self.insert_chapter_btn.setToolTip("Insert a chapter marker at the cursor")
        self.insert_chapter_btn.clicked.connect(self.insert_chapter_marker)
        button_layout.addWidget(self.insert_chapter_btn)

        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.clicked.connect(self.reject)

        self.ok_button = QPushButton("OK", self)
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.handle_ok)

        button_layout.addWidget(self.save_as_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.ok_button)
        layout.addLayout(button_layout)

        # Store the original text to detect changes
        self.original_text = ""

    def update_char_count(self):
        text = self.text_edit.toPlainText()
        count = calculate_text_length(text)
        self.char_count_label.setText(f"Characters: {count:,}")

    def get_text(self):
        return self.text_edit.toPlainText()

    def handle_ok(self):
        text = self.text_edit.toPlainText()
        # Check if text is empty based on character count
        if calculate_text_length(text) == 0:
            QMessageBox.warning(self, "Textbox Error", "Text cannot be empty.")
            return

        # If the text hasn't changed, treat as cancel
        if text == self.original_text:
            self.reject()
        else:
            # Check if we need to warn about overwriting a non-temporary file
            if hasattr(self, "is_non_cache_file") and self.is_non_cache_file:
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("File Overwrite Warning")
                msg_box.setText(
                    f"You are about to overwrite the original file:\n{self.non_cache_file_path}"
                )
                msg_box.setInformativeText("Do you want to continue?")
                msg_box.setStandardButtons(
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                msg_box.setDefaultButton(QMessageBox.StandardButton.No)

                if msg_box.exec() != QMessageBox.StandardButton.Yes:
                    # User canceled, don't close the dialog
                    return

            self.accept()

    def save_as_text(self):
        """Save the text content to a file chosen by the user"""
        try:
            text = self.text_edit.toPlainText()
            if not text.strip():
                QMessageBox.warning(self, "Save Error", "There is no text to save.")
                return

            # Get default filename from original file if editing
            initial_path = ""
            if hasattr(self, "non_cache_file_path") and self.non_cache_file_path:
                initial_path = self.non_cache_file_path

            # For EPUB and PDF files, use the displayed_file_path from the main window
            # This gives a better filename instead of the cache file path
            main_window = self.parent()
            if (
                hasattr(main_window, "displayed_file_path")
                and main_window.displayed_file_path
            ):
                if main_window.selected_file_type in ["epub", "pdf", "md", "markdown"]:
                    # Use the base name of the displayed file but change extension to .txt
                    base_name = os.path.splitext(main_window.displayed_file_path)[0]
                    initial_path = base_name + ".txt"

            file_path, _ = QFileDialog.getSaveFileName(
                self, "Save Text As", initial_path, "Text Files (*.txt);;All Files (*)"
            )

            if file_path:
                # Add .txt extension if not specified and no other extension exists
                if not os.path.splitext(file_path)[1]:
                    file_path += ".txt"

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(text)

        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save file:\n{e}")

    def insert_chapter_marker(self):
        # Insert a fixed chapter marker without prompting
        cursor = self.text_edit.textCursor()
        cursor.insertText("\n<<CHAPTER_MARKER:Title>>\n")
        self.text_edit.setTextCursor(cursor)
        self.update_char_count()
        self.text_edit.setFocus()


def migrate_subtitle_format(config):
    """Convert old subtitle_format values to new internal keys."""
    old_to_new = {
        "srt": "srt",
        "ass (wide)": "ass_wide",
        "ass (narrow)": "ass_narrow",
        "ass (centered wide)": "ass_centered_wide",
        "ass (centered narrow)": "ass_centered_narrow",
    }
    val = config.get("subtitle_format")
    if val in old_to_new:
        config["subtitle_format"] = old_to_new[val]
        save_config(config)


class abogen(QWidget):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.apply_theme(self.config.get("theme", "system"))
        migrate_subtitle_format(self.config)
        self.check_updates = self.config.get("check_updates", True)
        self.save_option = self.config.get("save_option", "Save next to input file")
        self.selected_output_folder = self.config.get("selected_output_folder", None)
        self.selected_file = self.selected_file_type = self.selected_book_path = None
        self.displayed_file_path = (
            None  # Add new variable to track the displayed file path
        )
        # Max log lines
        self.log_window_max_lines = self.config.get("log_window_max_lines", 2000)
        self.selected_chapters = set()
        self.last_opened_book_path = None  # Track the last opened book path
        self.last_output_path = None
        self.char_count = 0
        self._char_count_cache = {}
        # Only one of selected_profile_name or selected_voice should be set
        self.selected_profile_name = self.config.get("selected_profile_name")
        self.selected_voice = None
        self.selected_lang = None
        self.mixed_voice_state = None
        if self.selected_profile_name:
            self.selected_voice = None
            self.selected_lang = None
        else:
            self.selected_voice = self.config.get("selected_voice", "af_heart")
            self.selected_lang = self.selected_voice[0] if self.selected_voice else None
        self.is_converting = False
        self.subtitle_mode = self.config.get("subtitle_mode", "Sentence")
        self.max_subtitle_words = self.config.get(
            "max_subtitle_words", 50
        )  # Default max words per subtitle
        self.silence_duration = self.config.get(
            "silence_duration", 2.0
        )  # Default silence duration
        self.selected_format = self.config.get("selected_format", "wav")
        self.separate_chapters_format = self.config.get(
            "separate_chapters_format", "wav"
        )  # Format for individual chapter files
        self.use_gpu = self.config.get(
            "use_gpu", True  # Load GPU setting with default True
        )
        self.replace_single_newlines = self.config.get("replace_single_newlines", True)
        self.use_silent_gaps = self.config.get("use_silent_gaps", True)
        self.subtitle_speed_method = self.config.get("subtitle_speed_method", "tts")
        self.use_spacy_segmentation = self.config.get("use_spacy_segmentation", True)
        self._pending_close_event = None
        self.gpu_ok = False  # Initialize GPU availability status

        # Create thread-safe logging mechanism
        self.log_signal = ThreadSafeLogSignal()
        self.log_signal.log_signal.connect(self._update_log_main_thread)

        # Create warning signal emitter
        self.warning_signal_emitter = ShowWarningSignalEmitter()
        self.warning_signal_emitter.show_warning_signal.connect(
            self.show_model_download_warning
        )
        hf_tracker.set_show_warning_signal_emitter(self.warning_signal_emitter)

        # Set application icon
        icon_path = get_resource_path("abogen.assets", "icon.ico")
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))
            # Set taskbar icon for Windows
            if platform.system() == "Windows":
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("abogen")

        # Queued items list
        self.queued_items = []
        self.current_queue_index = 0

        self.initUI()
        self.speed_slider.setValue(int(self.config.get("speed", 1.00) * 100))
        self.update_speed_label()
        # Set initial selection: prefer profile, else voice
        idx = -1
        if self.selected_profile_name:
            idx = self.voice_combo.findData(f"profile:{self.selected_profile_name}")
        elif self.selected_voice:
            idx = self.voice_combo.findData(self.selected_voice)
        if idx >= 0:
            self.voice_combo.setCurrentIndex(idx)
            # If a profile is selected at startup, load voices and language
            if self.selected_profile_name:
                from abogen.voice_profiles import load_profiles

                entry = load_profiles().get(self.selected_profile_name, {})
                if isinstance(entry, dict):
                    self.mixed_voice_state = entry.get("voices", [])
                    self.selected_lang = entry.get("language")
                else:
                    self.mixed_voice_state = entry
                    self.selected_lang = entry[0][0] if entry and entry[0] else None
        if self.save_option == "Choose output folder" and self.selected_output_folder:
            self.save_path_label.setText(self.selected_output_folder)
            self.save_path_row_widget.show()
        self.subtitle_combo.setCurrentText(self.subtitle_mode)
        # Enable/disable subtitle options based on selected language (profile or voice)
        enable = self.selected_lang in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION
        self.subtitle_combo.setEnabled(enable)
        self.subtitle_format_combo.setEnabled(enable)
        # loading gif for preview button
        loading_gif_path = get_resource_path("abogen.assets", "loading.gif")
        if loading_gif_path:
            self.loading_movie = QMovie(loading_gif_path)
            self.loading_movie.frameChanged.connect(
                lambda: self.btn_preview.setIcon(
                    QIcon(self.loading_movie.currentPixmap())
                )
            )

        # Check for updates at startup if enabled
        if self.check_updates:
            QTimer.singleShot(1000, self.check_for_updates_startup)

        # Set hf_tracker callbacks
        hf_tracker.set_log_callback(self.update_log)

    def initUI(self):
        self.setWindowTitle(f"{PROGRAM_NAME} v{VERSION}")
        screen = QApplication.primaryScreen().geometry()
        width, height = 500, 800
        x = (screen.width() - width) // 2
        # If desired height is larger than screen, fit to screen height
        if height > screen.height() - 65:
            height = screen.height() - 100  # Leave a margin for window borders
        y = max((screen.height() - height) // 2, 0)
        self.setGeometry(x, y, width, height)
        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(15, 15, 15, 15)
        container = QWidget(self)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(15)
        self.input_box = InputBox(self)
        container_layout.addWidget(self.input_box, 1)
        # Manage queue button, start queue button
        self.queue_row_widget = QWidget(self)  # Make queue_row a QWidget
        queue_row = QHBoxLayout(self.queue_row_widget)
        queue_row.setContentsMargins(0, 0, 0, 0)
        self.btn_add_to_queue = QPushButton("Add to Queue", self)
        self.btn_add_to_queue.setFixedHeight(40)
        self.btn_add_to_queue.setEnabled(False)
        self.btn_add_to_queue.clicked.connect(self.add_to_queue)
        queue_row.addWidget(self.btn_add_to_queue)
        self.btn_manage_queue = QPushButton("Manage Queue", self)
        self.btn_manage_queue.setFixedHeight(40)
        self.btn_manage_queue.setEnabled(True)
        self.btn_manage_queue.clicked.connect(self.manage_queue)
        queue_row.addWidget(self.btn_manage_queue)
        self.btn_clear_queue = QPushButton("Clear Queue", self)
        self.btn_clear_queue.setFixedHeight(40)
        self.btn_clear_queue.setEnabled(False)
        self.btn_clear_queue.clicked.connect(self.clear_queue)
        queue_row.addWidget(self.btn_clear_queue)
        container_layout.addWidget(self.queue_row_widget)
        self.log_text = QTextEdit(self)
        self.log_text.setReadOnly(True)
        self.log_text.setUndoRedoEnabled(False)
        self.log_text.setFrameStyle(QFrame.Shape.NoFrame)
        self.log_text.setStyleSheet("QTextEdit { border: none; }")
        self.log_text.hide()
        container_layout.addWidget(self.log_text, 1)
        controls_layout = QVBoxLayout()
        controls_layout.setContentsMargins(0, 10, 0, 0)
        controls_layout.setSpacing(15)
        # Speed controls
        speed_layout = QVBoxLayout()
        speed_layout.setSpacing(2)
        speed_layout.addWidget(QLabel("Speed:", self))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.speed_slider.setMinimum(10)
        self.speed_slider.setMaximum(200)
        self.speed_slider.setValue(100)
        self.speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.speed_slider.setTickInterval(5)
        self.speed_slider.setSingleStep(5)
        speed_layout.addWidget(self.speed_slider)
        self.speed_label = QLabel("1.0", self)
        speed_layout.addWidget(self.speed_label)
        controls_layout.addLayout(speed_layout)
        self.speed_slider.valueChanged.connect(self.update_speed_label)
        # Voice selection
        voice_layout = QHBoxLayout()
        voice_layout.setSpacing(7)
        voice_label = QLabel("Select voice:", self)
        voice_layout.addWidget(voice_label)
        self.voice_combo = QComboBox(self)
        self.voice_combo.currentIndexChanged.connect(self.on_voice_combo_changed)
        self.voice_combo.setStyleSheet(
            "QComboBox { min-height: 20px; padding: 6px 12px; }"
        )
        self.voice_combo.setToolTip(
            "The first character represents the language:\n"
            '"a" => American English\n"b" => British English\n"e" => Spanish\n"f" => French\n"h" => Hindi\n"i" => Italian\n"j" => Japanese\n"p" => Brazilian Portuguese\n"z" => Mandarin Chinese\nThe second character represents the gender:\n"m" => Male\n"f" => Female'
        )
        self.voice_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        voice_layout.addWidget(self.voice_combo)
        # Voice formula button
        self.btn_voice_formula_mixer = QPushButton(self)
        mixer_icon_path = get_resource_path("abogen.assets", "voice_mixer.png")
        self.btn_voice_formula_mixer.setIcon(QIcon(mixer_icon_path))
        self.btn_voice_formula_mixer.setToolTip("Mix and match voices")
        self.btn_voice_formula_mixer.setFixedSize(40, 36)
        self.btn_voice_formula_mixer.setStyleSheet("QPushButton { padding: 6px 12px; }")
        self.btn_voice_formula_mixer.clicked.connect(self.show_voice_formula_dialog)
        voice_layout.addWidget(self.btn_voice_formula_mixer)

        # Play/Stop icons
        def make_icon(color, shape):
            pix = QPixmap(20, 20)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor(*color))
            p.setPen(Qt.PenStyle.NoPen)
            if shape == "play":
                pts = [
                    pix.rect().topLeft() + QPoint(4, 2),
                    pix.rect().bottomLeft() + QPoint(4, -2),
                    pix.rect().center() + QPoint(6, 0),
                ]
                p.drawPolygon(QPolygon(pts))
            else:
                p.drawRect(5, 5, 10, 10)
            p.end()
            return QIcon(pix)

        self.play_icon = make_icon((40, 160, 40), "play")
        self.stop_icon = make_icon((200, 60, 60), "stop")
        self.btn_preview = QPushButton(self)
        self.btn_preview.setIcon(self.play_icon)
        self.btn_preview.setIconSize(QPixmap(20, 20).size())
        self.btn_preview.setToolTip("Preview selected voice")
        self.btn_preview.setFixedSize(40, 36)
        self.btn_preview.setStyleSheet("QPushButton { padding: 6px 12px; }")
        self.btn_preview.clicked.connect(self.preview_voice)
        voice_layout.addWidget(self.btn_preview)
        self.preview_playing = False
        self.play_audio_thread = None  # Keep track of audio playing thread
        controls_layout.addLayout(voice_layout)

        # Generate subtitles
        subtitle_layout = QHBoxLayout()
        subtitle_layout.setSpacing(7)
        subtitle_label = QLabel("Generate subtitles:", self)
        subtitle_layout.addWidget(subtitle_label)
        self.subtitle_combo = QComboBox(self)
        self.subtitle_combo.setToolTip(
            "Choose how subtitles will be generated:\n"
            "Disabled: No subtitles will be generated.\n"
            "Line: Subtitles will be generated for each line.\n"
            "Sentence: Subtitles will be generated for each sentence.\n"
            "Sentence + Comma: Subtitles will be generated for each sentence and comma.\n"
            "Sentence + Highlighting: Subtitles with word-by-word karaoke highlighting.\n"
            "1+ word: Subtitles will be generated for each word(s).\n\n"
            "Supported languages for subtitle generation:\n"
            + "\n".join(
                f'"{lang}" => {LANGUAGE_DESCRIPTIONS.get(lang, lang)}'
                for lang in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION
            )
        )
        subtitle_options = [
            "Disabled",
            "Line",
            "Sentence",
            "Sentence + Comma",
            "Sentence + Highlighting",
        ] + [f"{i} word" if i == 1 else f"{i} words" for i in range(1, 11)]
        self.subtitle_combo.addItems(subtitle_options)
        self.subtitle_combo.setStyleSheet(
            "QComboBox { min-height: 20px; padding: 6px 12px; }"
        )
        self.subtitle_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.subtitle_combo.setCurrentText(self.subtitle_mode)
        self.subtitle_combo.currentTextChanged.connect(self.on_subtitle_mode_changed)
        subtitle_layout.addWidget(self.subtitle_combo)
        controls_layout.addLayout(subtitle_layout)

        # Output voice format
        format_layout = QHBoxLayout()
        format_layout.setSpacing(7)
        format_label = QLabel("Output voice format:", self)
        format_layout.addWidget(format_label)
        self.format_combo = QComboBox(self)
        self.format_combo.setStyleSheet(
            "QComboBox { min-height: 20px; padding: 6px 12px; }"
        )
        self.format_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        # Add items with display labels and underlying keys
        for key, label in [
            ("wav", "wav"),
            ("flac", "flac"),
            ("mp3", "mp3"),
            ("opus", "opus (best compression)"),
            ("m4b", "m4b (with chapters)"),
        ]:
            self.format_combo.addItem(label, key)
        # Initialize selection by matching saved key
        idx = self.format_combo.findData(self.selected_format)
        if idx >= 0:
            self.format_combo.setCurrentIndex(idx)
        # Map selection back to key on change
        self.format_combo.currentIndexChanged.connect(
            lambda i: self.on_format_changed(self.format_combo.itemData(i))
        )
        format_layout.addWidget(self.format_combo)
        controls_layout.addLayout(format_layout)

        # Output subtitle format
        subtitle_format_layout = QHBoxLayout()
        subtitle_format_layout.setSpacing(7)
        subtitle_format_label = QLabel("Output subtitle format:", self)
        subtitle_format_layout.addWidget(subtitle_format_label)
        self.subtitle_format_combo = QComboBox(self)
        self.subtitle_format_combo.setStyleSheet(
            "QComboBox { min-height: 20px; padding: 6px 12px; }"
        )
        self.subtitle_format_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        for value, text in SUBTITLE_FORMATS:
            self.subtitle_format_combo.addItem(text, value)
        subtitle_format = self.config.get("subtitle_format", "ass_centered_narrow")
        idx = self.subtitle_format_combo.findData(subtitle_format)
        if idx >= 0:
            self.subtitle_format_combo.setCurrentIndex(idx)
        self.subtitle_format_combo.currentIndexChanged.connect(
            lambda i: self.set_subtitle_format(self.subtitle_format_combo.itemData(i))
        )
        subtitle_format_layout.addWidget(self.subtitle_format_combo)
        # If subtitle mode requires highlighting, SRT is not supported. Disable SRT item
        # and auto-switch to a compatible ASS format if SRT is currently selected.
        try:
            if (
                hasattr(self, "subtitle_mode")
                and self.subtitle_mode == "Sentence + Highlighting"
            ):
                idx_srt = self.subtitle_format_combo.findData("srt")
                if idx_srt >= 0:
                    item = self.subtitle_format_combo.model().item(idx_srt)
                    if item is not None:
                        item.setEnabled(False)
                # If current selection is SRT, switch to centered narrow ASS
                if self.subtitle_format_combo.currentData() == "srt":
                    new_idx = self.subtitle_format_combo.findData("ass_centered_narrow")
                    if new_idx >= 0:
                        self.subtitle_format_combo.setCurrentIndex(new_idx)
                        # Persist the change
                        self.set_subtitle_format(
                            self.subtitle_format_combo.itemData(new_idx)
                        )
        except Exception:
            # Fail-safe: don't crash UI if model manipulation isn't supported on some platforms
            pass

        # Enable/disable subtitle options based on selected language (profile or voice)
        self.update_subtitle_options_availability()

        controls_layout.addLayout(subtitle_format_layout)

        # Replace single newlines dropdown (acts like checkbox)
        replace_newlines_layout = QHBoxLayout()
        replace_newlines_layout.setSpacing(7)
        replace_newlines_label = QLabel("Replace single newlines:", self)
        replace_newlines_layout.addWidget(replace_newlines_label)
        self.replace_newlines_combo = QComboBox(self)
        self.replace_newlines_combo.addItems(["Disabled", "Enabled"])
        self.replace_newlines_combo.setToolTip(
            "Replace single newlines in the input text with spaces before processing."
        )
        self.replace_newlines_combo.setStyleSheet(
            "QComboBox { min-height: 20px; padding: 6px 12px; }"
        )
        self.replace_newlines_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        # Set initial value based on config
        self.replace_newlines_combo.setCurrentIndex(
            1 if self.replace_single_newlines else 0
        )
        self.replace_newlines_combo.currentIndexChanged.connect(
            lambda idx: self.toggle_replace_single_newlines(idx == 1)
        )
        replace_newlines_layout.addWidget(self.replace_newlines_combo)
        controls_layout.addLayout(replace_newlines_layout)

        # Save location
        save_layout = QHBoxLayout()
        save_layout.setSpacing(7)
        save_label = QLabel("Save location:", self)
        save_layout.addWidget(save_label)
        self.save_combo = QComboBox(self)
        save_options = [
            "Save next to input file",
            "Save to Desktop",
            "Choose output folder",
        ]
        self.save_combo.addItems(save_options)
        self.save_combo.setStyleSheet(
            "QComboBox { min-height: 20px; padding: 6px 12px; }"
        )
        self.save_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.save_combo.setCurrentText(self.save_option)
        self.save_combo.currentTextChanged.connect(self.on_save_option_changed)
        save_layout.addWidget(self.save_combo)
        controls_layout.addLayout(save_layout)

        # Save path label
        self.save_path_row_widget = QWidget(self)
        save_path_row = QHBoxLayout(self.save_path_row_widget)
        save_path_row.setSpacing(7)
        save_path_row.setContentsMargins(0, 0, 0, 0)
        selected_folder_label = QLabel("Selected folder:", self.save_path_row_widget)
        save_path_row.addWidget(selected_folder_label)
        self.save_path_label = QLabel("", self.save_path_row_widget)
        self.save_path_label.setStyleSheet(f"QLabel {{ color: {COLORS['GREEN']}; }}")
        self.save_path_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        save_path_row.addWidget(self.save_path_label)
        self.save_path_row_widget.hide()  # Hide the whole row by default
        controls_layout.addWidget(self.save_path_row_widget)

        # GPU Acceleration Checkbox with Settings button
        gpu_layout = QHBoxLayout()
        gpu_checkbox_layout = QVBoxLayout()
        self.gpu_checkbox = QCheckBox("Use GPU Acceleration (if available)", self)
        self.gpu_checkbox.setChecked(self.use_gpu)
        self.gpu_checkbox.setToolTip(
            "Uncheck to force using CPU even if a compatible GPU is detected."
        )
        self.gpu_checkbox.stateChanged.connect(self.on_gpu_setting_changed)
        gpu_checkbox_layout.addWidget(self.gpu_checkbox)
        gpu_layout.addLayout(gpu_checkbox_layout)

        # Set initial enabled state for subtitle format combo
        if self.subtitle_mode == "Disabled":
            self.subtitle_format_combo.setEnabled(False)
        else:
            self.subtitle_format_combo.setEnabled(True)

        # Settings button with icon
        settings_icon_path = get_resource_path("abogen.assets", "settings.svg")
        self.settings_btn = QPushButton(self)
        if settings_icon_path and os.path.exists(settings_icon_path):
            self.settings_btn.setIcon(QIcon(settings_icon_path))
        else:
            # Fallback text if icon not found
            self.settings_btn.setText("⚙")
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setFixedSize(36, 36)
        self.settings_btn.clicked.connect(self.show_settings_menu)
        gpu_layout.addWidget(self.settings_btn)

        controls_layout.addLayout(gpu_layout)

        # Start button
        self.btn_start = QPushButton("Start", self)
        self.btn_start.setFixedHeight(60)
        self.btn_start.clicked.connect(self.start_conversion)
        controls_layout.addWidget(self.btn_start)
        # Add controls to a container widget
        self.controls_widget = QWidget()
        self.controls_widget.setLayout(controls_layout)
        self.controls_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        container_layout.addWidget(self.controls_widget)
        # Progress bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        container_layout.addWidget(self.progress_bar)
        # ETR Label
        self.etr_label = QLabel("Estimated time remaining: Calculating...", self)
        self.etr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.etr_label.hide()
        container_layout.addWidget(self.etr_label)
        # Cancel button
        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.setFixedHeight(60)
        self.btn_cancel.clicked.connect(self.cancel_conversion)
        self.btn_cancel.hide()
        container_layout.addWidget(self.btn_cancel)
        # Finish buttons
        self.finish_widget = QWidget()
        finish_layout = QVBoxLayout()
        finish_layout.setContentsMargins(0, 0, 0, 0)
        finish_layout.setSpacing(10)
        self.open_file_btn = None  # Store reference to open file button

        # Create buttons with their functions
        finish_buttons = [
            ("Open file", self.open_file, "Open the output file."),
            (
                "Go to folder",
                self.go_to_file,
                "Open the folder containing the output file.",
            ),
            ("New Conversion", self.reset_ui, "Start a new conversion."),
            ("Go back", self.go_back_ui, "Return to the previous screen."),
        ]

        for text, func, tip in finish_buttons:
            btn = QPushButton(text, self)
            btn.setFixedHeight(35)
            btn.setToolTip(tip)
            btn.clicked.connect(func)
            finish_layout.addWidget(btn)
            # Identify the Open file button by its function reference
            if func == self.open_file:
                self.open_file_btn = btn  # Save reference to the open file button

        self.finish_widget.setLayout(finish_layout)
        self.finish_widget.hide()
        container_layout.addWidget(self.finish_widget)
        outer_layout.addWidget(container)
        self.setLayout(outer_layout)
        self.populate_profiles_in_voice_combo()

        # Initialize flag to track if input box was cleared by queue
        self.input_box_cleared_by_queue = False

    def open_file_dialog(self):
        if self.is_converting:
            return
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select File",
                "",
                "Supported Files (*.txt *.epub *.pdf *.md *.srt *.ass *.vtt)",
            )
            if not file_path:
                return
            if (
                file_path.lower().endswith(".epub")
                or file_path.lower().endswith(".pdf")
                or file_path.lower().endswith((".md", ".markdown"))
            ):
                # Determine file type
                if file_path.lower().endswith(".epub"):
                    self.selected_file_type = "epub"
                elif file_path.lower().endswith(".pdf"):
                    self.selected_file_type = "pdf"
                else:
                    self.selected_file_type = "markdown"

                self.selected_book_path = file_path
                # Don't set file info immediately, open_book_file will handle it after dialog is accepted
                if not self.open_book_file(file_path):
                    return
            elif file_path.lower().endswith((".srt", ".ass", ".vtt")):
                # Handle subtitle files like text files
                self.selected_file, self.selected_file_type = file_path, "txt"
                self.displayed_file_path = file_path
                self.input_box.set_file_info(file_path)
            else:
                self.selected_file, self.selected_file_type = file_path, "txt"
                self.displayed_file_path = (
                    file_path  # Set the displayed file path for text files
                )
                self.input_box.set_file_info(file_path)
        except Exception as e:
            self._show_error_message_box(
                "File Dialog Error", f"Could not open file dialog:\n{e}"
            )

    def open_book_file(self, book_path):
        # Clear selected chapters if this is a different book than the last one
        if (
            not hasattr(self, "last_opened_book_path")
            or self.last_opened_book_path != book_path
        ):
            self.selected_chapters = set()
            self.last_opened_book_path = book_path

        # HandlerDialog uses internal caching to avoid reprocessing the same book
        dialog = HandlerDialog(
            book_path,
            file_type=getattr(self, "selected_file_type", None),
            checked_chapters=self.selected_chapters,
            parent=self,
        )
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setModal(False)
        dialog.show()  # We'll handle the dialog result asynchronously

        def on_dialog_finished(result):
            if result != QDialog.DialogCode.Accepted:
                return False
            chapters_text, all_checked_hrefs = dialog.get_selected_text()
            if not all_checked_hrefs:
                # Determine file type for error message
                if book_path.lower().endswith(".pdf"):
                    file_type = "pdf"
                    item_type = "pages"
                elif book_path.lower().endswith((".md", ".markdown")):
                    file_type = "markdown"
                    item_type = "chapters"
                else:
                    file_type = "epub"
                    item_type = "chapters"

                error_msg = f"No {item_type} selected."
                self._show_error_message_box(f"{file_type.upper()} Error", error_msg)
                return False
            self.selected_chapters = all_checked_hrefs
            self.save_chapters_separately = dialog.get_save_chapters_separately()
            self.merge_chapters_at_end = dialog.get_merge_chapters_at_end()
            self.save_as_project = dialog.get_save_as_project()

            # Store if the PDF has bookmarks for button text display
            if book_path.lower().endswith(".pdf"):
                self.pdf_has_bookmarks = getattr(dialog, "has_pdf_bookmarks", False)

            cleaned_text = clean_text(chapters_text)
            computed_char_count = calculate_text_length(cleaned_text)
            self.char_count = computed_char_count
            if isinstance(getattr(self, "_char_count_cache", None), dict):
                self._char_count_cache[book_path] = computed_char_count

            # Use "abogen" prefix for cache files
            # Extract base name without extension
            base_name = os.path.splitext(os.path.basename(book_path))[0]

            if self.save_as_project:
                # Get project directory from user
                project_dir = QFileDialog.getExistingDirectory(
                    self, "Select Project Folder", "", QFileDialog.Option.ShowDirsOnly
                )
                if not project_dir:
                    # User cancelled, fallback to cache
                    self.save_as_project = False
                    cache_dir = get_user_cache_path()
                else:
                    # Create project folder structure
                    project_name = f"{base_name}_project"
                    project_dir = os.path.join(project_dir, project_name)
                    cache_dir = os.path.join(project_dir, "text")
                    os.makedirs(cache_dir, exist_ok=True)

                    # Save metadata if available
                    meta_dir = os.path.join(project_dir, "metadata")
                    os.makedirs(
                        meta_dir, exist_ok=True
                    )  # Save book metadata if available
                    if hasattr(dialog, "book_metadata"):
                        meta_path = os.path.join(meta_dir, "book_info.txt")
                        with open(meta_path, "w", encoding="utf-8") as f:
                            # Clean HTML tags from metadata
                            title = re.sub(
                                r"<[^>]+>",
                                "",
                                str(dialog.book_metadata.get("title", "Unknown")),
                            )
                            publisher = re.sub(
                                r"<[^>]+>",
                                "",
                                str(dialog.book_metadata.get("publisher", "Unknown")),
                            )
                            authors = [
                                re.sub(r"<[^>]+>", "", str(author))
                                for author in dialog.book_metadata.get(
                                    "authors", ["Unknown"]
                                )
                            ]
                            publication_year = re.sub(
                                r"<[^>]+>",
                                "",
                                str(
                                    dialog.book_metadata.get(
                                        "publication_year", "Unknown"
                                    )
                                ),
                            )

                            f.write(f"Title: {title}\n")
                            f.write(f"Authors: {', '.join(authors)}\n")
                            f.write(f"Publisher: {publisher}\n")
                            f.write(f"Publication Year: {publication_year}\n")
                            if dialog.book_metadata.get("description"):
                                description = re.sub(
                                    r"<[^>]+>",
                                    "",
                                    str(dialog.book_metadata.get("description")),
                                )
                                f.write(f"\nDescription:\n{description}\n")

                        # Save cover image if available
                    if dialog.book_metadata.get("cover_image"):
                        cover_path = os.path.join(meta_dir, "cover.png")
                        with open(cover_path, "wb") as f:
                            f.write(dialog.book_metadata["cover_image"])
            else:
                cache_dir = get_user_cache_path()

            fd, tmp = tempfile.mkstemp(
                prefix=f"{base_name}_", suffix=".txt", dir=cache_dir
            )
            os.close(fd)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(chapters_text)
            self.selected_file = tmp
            self.selected_book_path = book_path
            self.displayed_file_path = book_path
            if isinstance(getattr(self, "_char_count_cache", None), dict):
                self._char_count_cache[tmp] = computed_char_count
            # Only set file info if dialog was accepted
            self.input_box.set_file_info(book_path)
            return True

        dialog.finished.connect(on_dialog_finished)
        return True

    def open_textbox_dialog(self, file_path=None):
        """Shows dialog for direct text input or editing and processes the entered text"""
        if self.is_converting:
            return

        editing = False
        is_cache_file = False
        # If path is explicitly provided, use it
        if file_path and os.path.exists(file_path):
            editing = True
            edit_file = file_path
            # Check if this is a cache file
            is_cache_file = get_user_cache_path() in file_path
        # Otherwise use selected_file if it's a txt file
        elif (
            self.selected_file_type == "txt"
            and self.selected_file
            and os.path.exists(self.selected_file)
        ):
            editing = True
            edit_file = self.selected_file
            # Check if this is a cache file
            is_cache_file = get_user_cache_path() in self.selected_file

        dialog = TextboxDialog(self)
        if editing:
            try:
                with open(edit_file, "r", encoding="utf-8", errors="ignore") as f:
                    dialog.text_edit.setText(f.read())
                dialog.update_char_count()
                dialog.original_text = (
                    dialog.text_edit.toPlainText()
                )  # Store original text

                # If editing a non-cache file, alert the user
                if not is_cache_file:
                    dialog.is_non_cache_file = True
                    dialog.non_cache_file_path = edit_file
            except Exception:
                pass
        if dialog.exec() == QDialog.DialogCode.Accepted:
            text = dialog.get_text()
            if not text.strip():
                self._show_error_message_box("Textbox Error", "Text cannot be empty.")
                return
            try:
                if editing:
                    with open(edit_file, "w", encoding="utf-8") as f:
                        f.write(text)
                    # Update the display path to the edited file
                    self.displayed_file_path = edit_file
                    self.input_box.set_file_info(edit_file)
                    # Hide chapters button since we're using custom text now
                    self.input_box.chapters_btn.hide()
                else:
                    cache_dir = get_user_cache_path()
                    fd, tmp = tempfile.mkstemp(
                        prefix="abogen_", suffix=".txt", dir=cache_dir
                    )
                    os.close(fd)
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.write(text)
                    self.selected_file = tmp
                    self.selected_file_type = "txt"
                    self.displayed_file_path = None
                    self.input_box.set_file_info(tmp)
                    # Hide chapters button since we're using custom text now
                    self.input_box.chapters_btn.hide()
                    if hasattr(self, "conversion_thread"):
                        self.conversion_thread.is_direct_text = True
            except Exception as e:
                self._show_error_message_box(
                    "Textbox Error", f"Could not process text input:\n{e}"
                )

    def update_speed_label(self):
        s = self.speed_slider.value() / 100.0
        self.speed_label.setText(f"{s}")
        self.config["speed"] = s
        save_config(self.config)

    def update_subtitle_options_availability(self):
        """
        Update the enabled state of subtitle options based on the selected language.
        For non-English languages, only sentence-based and line-based modes are supported.
        """
        # Check if current file is a subtitle file
        is_subtitle_input = False
        if self.selected_file and self.selected_file.lower().endswith(
            (".srt", ".ass", ".vtt")
        ):
            is_subtitle_input = True

        if self.selected_lang not in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION:
            self.subtitle_combo.setEnabled(False)
            self.subtitle_format_combo.setEnabled(False)
            return

        # Only enable subtitle_combo if it's NOT a subtitle input
        self.subtitle_combo.setEnabled(not is_subtitle_input)
        self.subtitle_format_combo.setEnabled(True)

        is_english = self.selected_lang in ["a", "b"]

        # Items to keep enabled for non-English
        allowed_modes = ["Disabled", "Line", "Sentence", "Sentence + Comma"]

        model = self.subtitle_combo.model()
        for i in range(self.subtitle_combo.count()):
            text = self.subtitle_combo.itemText(i)
            item = model.item(i)
            if not item:
                continue

            if is_english:
                item.setEnabled(True)
            else:
                if text in allowed_modes:
                    item.setEnabled(True)
                else:
                    item.setEnabled(False)

        # If current selection is disabled, switch to a valid one
        current_text = self.subtitle_combo.currentText()
        current_idx = self.subtitle_combo.currentIndex()
        current_item = model.item(current_idx)

        if current_item and not current_item.isEnabled():
            # Switch to "Sentence" if available, else "Disabled"
            sentence_idx = self.subtitle_combo.findText("Sentence")
            if sentence_idx >= 0:
                self.subtitle_combo.setCurrentIndex(sentence_idx)
            else:
                self.subtitle_combo.setCurrentIndex(0)  # Disabled

        self.subtitle_mode = self.subtitle_combo.currentText()

    def on_voice_changed(self, index):
        voice = self.voice_combo.itemData(index)
        self.selected_voice, self.selected_lang = voice, voice[0]
        self.config["selected_voice"] = voice
        save_config(self.config)
        # Enable/disable subtitle options based on language
        self.update_subtitle_options_availability()

    def on_voice_combo_changed(self, index):
        data = self.voice_combo.itemData(index)
        if isinstance(data, str) and data.startswith("profile:"):
            pname = data.split(":", 1)[1]
            self.selected_profile_name = pname
            from abogen.voice_profiles import load_profiles

            entry = load_profiles().get(pname, {})
            # set mixed voices and language
            if isinstance(entry, dict):
                self.mixed_voice_state = entry.get("voices", [])
                self.selected_lang = entry.get("language")
            else:
                self.mixed_voice_state = entry
                self.selected_lang = entry[0][0] if entry and entry[0] else None
            self.selected_voice = None
            self.config["selected_profile_name"] = pname
            self.config.pop("selected_voice", None)
            save_config(self.config)
            # enable subtitles based on profile language
            self.update_subtitle_options_availability()
        else:
            self.mixed_voice_state = None
            self.selected_profile_name = None
            self.selected_voice, self.selected_lang = data, data[0]
            self.config["selected_voice"] = data
            if "selected_profile_name" in self.config:
                del self.config["selected_profile_name"]
            save_config(self.config)
            self.update_subtitle_options_availability()

    def update_subtitle_combo_for_profile(self, profile_name):
        from abogen.voice_profiles import load_profiles

        entry = load_profiles().get(profile_name, {})
        lang = entry.get("language") if isinstance(entry, dict) else None
        enable = lang in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION
        self.subtitle_combo.setEnabled(enable)
        self.subtitle_format_combo.setEnabled(enable)

    def populate_profiles_in_voice_combo(self):
        # preserve current voice or profile
        current = self.voice_combo.currentData()
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        # re-add profiles
        profile_icon = QIcon(get_resource_path("abogen.assets", "profile.png"))
        for pname in load_profiles().keys():
            self.voice_combo.addItem(profile_icon, pname, f"profile:{pname}")
        # re-add voices
        for v in VOICES_INTERNAL:
            icon = QIcon()
            flag_path = get_resource_path("abogen.assets.flags", f"{v[0]}.png")
            if flag_path and os.path.exists(flag_path):
                icon = QIcon(flag_path)
            self.voice_combo.addItem(icon, f"{v}", v)
        # restore selection
        idx = -1
        if self.selected_profile_name:
            idx = self.voice_combo.findData(f"profile:{self.selected_profile_name}")
        elif current:
            idx = self.voice_combo.findData(current)
        if idx >= 0:
            self.voice_combo.setCurrentIndex(idx)
            # Also update subtitle combo for selected profile
            data = self.voice_combo.itemData(idx)
            if isinstance(data, str) and data.startswith("profile:"):
                pname = data.split(":", 1)[1]
                self.update_subtitle_combo_for_profile(pname)
        self.voice_combo.blockSignals(False)
        # If no profiles exist, clear selected_profile_name from config
        if not load_profiles():
            if "selected_profile_name" in self.config:
                del self.config["selected_profile_name"]
                save_config(self.config)

    def convert_input_box_to_log(self):
        self.input_box.hide()
        self.log_text.show()
        self.log_text.clear()
        QApplication.processEvents()

    def restore_input_box(self):
        self.log_text.hide()
        self.input_box.show()

    def update_log(self, message):
        # Use signal-based approach for thread-safe logging
        if QThread.currentThread() != QApplication.instance().thread():
            # We're in a background thread, emit signal for the main thread
            self.log_signal.emit_log(message)
            return

        # Direct update if already on main thread
        self._update_log_main_thread(message)

    def _update_log_main_thread(self, message):
        txt = self.log_text
        sb = txt.verticalScrollBar()
        at_bottom = sb.value() == sb.maximum()

        cursor = txt.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = cursor.charFormat()
        if isinstance(message, tuple):
            text, spec = message
            fmt.setForeground(QColor(LOG_COLOR_MAP.get(spec, COLORS["LIGHT_DISABLED"])))
        else:
            text = str(message)
            fmt.clearForeground()
        cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")

        doc = txt.document()
        excess = doc.blockCount() - self.log_window_max_lines
        if excess > 0:
            start = doc.findBlockByNumber(0).position()
            end = doc.findBlockByNumber(excess).position()
            trim_cursor = QTextCursor(doc)
            trim_cursor.setPosition(start)
            trim_cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            trim_cursor.removeSelectedText()

        if at_bottom:
            sb.setValue(sb.maximum())

    def _get_queue_progress_format(self, value=None):
        """Return the progress bar format string for queue mode."""
        if (
            hasattr(self, "queued_items")
            and self.queued_items
            and hasattr(self, "current_queue_index")
        ):
            N = self.current_queue_index + 1
            M = len(self.queued_items)
            percent = value if value is not None else self.progress_bar.value()
            return f"{percent}% ({N}/{M})"
        else:
            percent = value if value is not None else self.progress_bar.value()
            return f"{percent}%"

    def update_progress(self, value, etr_str):  # Add etr_str parameter
        # Ensure progress doesn't exceed 99%
        if value >= 100:
            value = 99
        self.progress_bar.setValue(value)
        # Show queue progress if in queue mode
        if (
            hasattr(self, "queued_items")
            and self.queued_items
            and hasattr(self, "current_queue_index")
        ):
            N = self.current_queue_index + 1
            M = len(self.queued_items)
            self.progress_bar.setFormat(f"{value}% ({N}/{M})")
        else:
            self.progress_bar.setFormat(f"{value}%")
        self.etr_label.setText(
            f"Estimated time remaining: {etr_str}"
        )  # Update ETR label
        self.etr_label.show()  # Show only when estimate is ready

        # Disable cancel button if progress is >= 98%
        if value >= 98:
            self.btn_cancel.setEnabled(False)

        self.progress_bar.repaint()
        QApplication.processEvents()

    def enable_disable_queue_buttons(self):
        enabled = bool(self.queued_items)
        self.btn_clear_queue.setEnabled(enabled)
        # Update Manage Queue button text with count
        if enabled:
            self.btn_manage_queue.setText(f"Manage Queue ({len(self.queued_items)})")
            self.btn_manage_queue.setStyleSheet(
                f"QPushButton {{ color: {COLORS['GREEN']}; }}"
            )
        else:
            self.btn_manage_queue.setText("Manage Queue")
            self.btn_manage_queue.setStyleSheet("")
        # Change main Start button to 'Start queue' if queue has items
        if enabled:
            self.btn_start.setText(f"Start queue ({len(self.queued_items)})")
            try:
                self.btn_start.clicked.disconnect()
            except Exception:
                pass
            self.btn_start.clicked.connect(self.start_queue)
        else:
            self.btn_start.setText("Start")
            try:
                self.btn_start.clicked.disconnect()
            except Exception:
                pass
            self.btn_start.clicked.connect(self.start_conversion)

    def enqueue(self, item: QueuedItem):
        self.queued_items.append(item)
        # self.update_log((f"Enqueued: {item.file_name}", True))
        # enable start queue button, manage queue button
        self.enable_disable_queue_buttons()

    def get_queue(self):
        return self.queued_items

    def add_to_queue(self):
        # For epub/pdf, always use the converted txt file (selected_file)
        if self.selected_file_type in ["epub", "pdf", "md", "markdown"]:
            file_to_queue = self.selected_file
            # Use the original file path for save location
            save_base_path = (
                self.displayed_file_path if self.displayed_file_path else file_to_queue
            )
        else:
            file_to_queue = (
                self.displayed_file_path
                if self.displayed_file_path
                else self.selected_file
            )
            save_base_path = file_to_queue  # For non-EPUB, it's the same

        if not file_to_queue:
            self.input_box.set_error("Please add a file.")
            return
        actual_subtitle_mode = self.get_actual_subtitle_mode()
        voice_formula = self.get_voice_formula()
        selected_lang = self.get_selected_lang(voice_formula)

        item_queue = QueuedItem(
            file_name=file_to_queue,
            lang_code=selected_lang,
            speed=self.speed_slider.value() / 100.0,
            voice=voice_formula,
            save_option=self.save_option,
            output_folder=self.selected_output_folder,
            subtitle_mode=actual_subtitle_mode,
            output_format=self.selected_format,
            total_char_count=self.char_count,
            replace_single_newlines=self.replace_single_newlines,
            use_silent_gaps=self.use_silent_gaps,
            subtitle_speed_method=self.subtitle_speed_method,
            save_base_path=save_base_path,
            save_chapters_separately=getattr(self, "save_chapters_separately", None),
            merge_chapters_at_end=getattr(self, "merge_chapters_at_end", None),
        )

        # Prevent adding duplicate items to the queue
        for queued_item in self.queued_items:
            if (
                queued_item.file_name == item_queue.file_name
                and queued_item.lang_code == item_queue.lang_code
                and queued_item.speed == item_queue.speed
                and queued_item.voice == item_queue.voice
                and queued_item.save_option == item_queue.save_option
                and queued_item.output_folder == item_queue.output_folder
                and queued_item.subtitle_mode == item_queue.subtitle_mode
                and queued_item.output_format == item_queue.output_format
                and getattr(queued_item, "replace_single_newlines", True)
                == item_queue.replace_single_newlines
                and getattr(queued_item, "save_base_path", None)
                == item_queue.save_base_path
                and getattr(queued_item, "save_chapters_separately", None)
                == item_queue.save_chapters_separately
                and getattr(queued_item, "merge_chapters_at_end", None)
                == item_queue.merge_chapters_at_end
            ):
                QMessageBox.warning(
                    self, "Duplicate Item", "This item is already in the queue."
                )
                return

        self.enqueue(item_queue)
        # Clear input after adding to queue
        self.input_box.clear_input()
        self.input_box_cleared_by_queue = True  # Set flag
        self.enable_disable_queue_buttons()

    def clear_queue(self):
        # Warn user if more than 1 item in the queue before clearing
        if len(self.queued_items) > 1:
            reply = QMessageBox.question(
                self,
                "Confirm Clear Queue",
                f"Are you sure you want to clear {len(self.queued_items)} items from the queue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.queued_items = []
        self.enable_disable_queue_buttons()

    def manage_queue(self):
        # show a dialog to manage the queue
        dialog = QueueManager(self, self.queued_items)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.queued_items = dialog.get_queue()

            # Reload config to capture the new "Override" setting
            # The QueueManager writes to disk, so we must refresh our local copy
            self.config = load_config()
            
            # re-enable/disable buttons based on queue state
            self.enable_disable_queue_buttons()

    def start_queue(self):
        self.current_queue_index = 0  # Start from the first item
        # Set progress bar to 0% (1/M) immediately
        if self.queued_items:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(f"0% (1/{len(self.queued_items)})")
            self.progress_bar.show()
        self.start_next_queued_item()

    def start_next_queued_item(self):
        if self.current_queue_index < len(self.queued_items):
            queued_item = self.queued_items[self.current_queue_index]
            
            self.selected_file = queued_item.file_name
            self.char_count = queued_item.total_char_count
            
            # Restore the original file path for save location (Important for EPUB/PDF)
            self.displayed_file_path = (
                queued_item.save_base_path or queued_item.file_name
            )
            
            # Restore chapter options (Structure specific, must be preserved)
            self.save_chapters_separately = getattr(
                queued_item, "save_chapters_separately", None
            )
            self.merge_chapters_at_end = getattr(
                queued_item, "merge_chapters_at_end", None
            )

            # CHECK GLOBAL OVERRIDE SETTING
            if not self.config.get("queue_override_settings", False):
                self.selected_lang = queued_item.lang_code
                self.speed_slider.setValue(int(queued_item.speed * 100))
                
                # Load the specific voice string
                self.selected_voice = queued_item.voice
                # Clear complex GUI states so the specific voice string is used
                self.mixed_voice_state = None
                self.selected_profile_name = None

                self.save_option = queued_item.save_option
                self.selected_output_folder = queued_item.output_folder
                self.subtitle_mode = queued_item.subtitle_mode
                self.selected_format = queued_item.output_format
                self.replace_single_newlines = getattr(
                    queued_item, "replace_single_newlines", True
                )
                self.use_silent_gaps = getattr(queued_item, "use_silent_gaps", False)
                self.subtitle_speed_method = getattr(
                    queued_item, "subtitle_speed_method", "tts"
                )

                # This ensures that if conversion.py (or utils) reads from config/disk 
                # instead of using passed arguments, it sees the correct queue values.
                self.config["replace_single_newlines"] = self.replace_single_newlines
                self.config["subtitle_mode"] = self.subtitle_mode
                self.config["selected_format"] = self.selected_format
                self.config["use_silent_gaps"] = self.use_silent_gaps
                self.config["subtitle_speed_method"] = self.subtitle_speed_method
                
                # Sync Voice/Profile in config
                self.config["selected_voice"] = self.selected_voice
                if "selected_profile_name" in self.config:
                    del self.config["selected_profile_name"]
                
                # Note: Speed is already synced via self.speed_slider.setValue() -> update_speed_label()
                save_config(self.config)

            self.start_conversion(from_queue=True)
        else:
            # Queue finished, reset index
            self.current_queue_index = 0

    def queue_item_conversion_finished(self):
        # Called after each conversion finishes
        self.current_queue_index += 1
        if self.current_queue_index < len(self.queued_items):
            self.start_next_queued_item()
        else:
            self.current_queue_index = 0  # Reset for next time

    def get_voice_formula(self) -> str:
        if self.mixed_voice_state:
            formula_components = [
                f"{name}*{weight}" for name, weight in self.mixed_voice_state
            ]
            return " + ".join(filter(None, formula_components))
        else:
            return self.selected_voice

    def get_selected_lang(self, voice_formula) -> str:
        if self.selected_profile_name:
            from abogen.voice_profiles import load_profiles

            entry = load_profiles().get(self.selected_profile_name, {})
            selected_lang = entry.get("language")
        else:
            selected_lang = self.selected_voice[0] if self.selected_voice else None
        # fallback: extract from formula if missing
        if not selected_lang:
            m = re.search(r"\b([a-z])", voice_formula)
            selected_lang = m.group(1) if m else None
        return selected_lang

    def get_actual_subtitle_mode(self) -> str:
        return "Disabled" if not self.subtitle_combo.isEnabled() else self.subtitle_mode

    def start_conversion(self, from_queue=False):
        if not self.selected_file:
            self.input_box.set_error("Please add a file.")
            return

        # Ensure we honor the currently selected save option when not running from queue
        if not from_queue:
            current_option = self.save_combo.currentText()
            self.save_option = current_option
            self.config["save_option"] = current_option
            # If user is not choosing a specific folder, clear any residual folder
            if current_option != "Choose output folder":
                self.selected_output_folder = None
                self.config["selected_output_folder"] = None
            save_config(self.config)

        prevent_sleep_start()
        self.is_converting = True
        self.convert_input_box_to_log()
        self.progress_bar.setValue(0)
        # Show queue progress if in queue mode
        if (
            from_queue
            and hasattr(self, "queued_items")
            and self.queued_items
            and hasattr(self, "current_queue_index")
        ):
            N = self.current_queue_index + 1
            M = len(self.queued_items)
            self.progress_bar.setFormat(f"0% ({N}/{M})")
        else:
            self.progress_bar.setFormat("%p%")  # Reset format initially
        self.etr_label.hide()  # Hide ETR label initially
        self.controls_widget.hide()
        self.queue_row_widget.hide()  # Hide queue row when process starts
        self.progress_bar.show()
        self.btn_cancel.show()
        QApplication.processEvents()
        self.btn_cancel.setEnabled(False)
        self.start_time = time.time()
        self.finish_widget.hide()
        speed = self.speed_slider.value() / 100.0

        # Get the display file path for logs
        display_path = (
            self.displayed_file_path if self.displayed_file_path else self.selected_file
        )

        # Get file size string
        try:
            file_size_str = self.input_box._human_readable_size(
                os.path.getsize(self.selected_file)
            )
        except Exception:
            file_size_str = "Unknown"

        # pipeline_loaded_callback remains unchanged
        def pipeline_loaded_callback(np_module, kpipeline_class, error):
            if error:
                self.update_log((f"Error loading numpy or KPipeline: {error}", "red"))
                prevent_sleep_end()
                return

            self.btn_cancel.setEnabled(True)

            # Override subtitle_mode to "Disabled" if subtitle_combo is disabled
            actual_subtitle_mode = self.get_actual_subtitle_mode()

            # if voice formula is not None, use the selected voice
            voice_formula = self.get_voice_formula()
            # determine selected language: use profile setting if profile selected, else voice code
            selected_lang = self.get_selected_lang(voice_formula)

            self.conversion_thread = ConversionThread(
                self.selected_file,
                selected_lang,
                speed,
                voice_formula,
                self.save_option,
                self.selected_output_folder,
                subtitle_mode=actual_subtitle_mode,
                output_format=self.selected_format,
                np_module=np_module,
                kpipeline_class=kpipeline_class,
                start_time=self.start_time,
                total_char_count=self.char_count,
                use_gpu=self.gpu_ok,
                from_queue=from_queue,
                save_base_path=self.displayed_file_path,  # Pass the save base path (original file for EPUB)
            )  # Use gpu_ok status
            # Pass the displayed file path to the log_updated signal handler in ConversionThread
            self.conversion_thread.display_path = display_path
            # Pass the file size string
            self.conversion_thread.file_size_str = file_size_str
            # Pass max_subtitle_words from config
            self.conversion_thread.max_subtitle_words = self.max_subtitle_words
            # Pass silence_duration from config
            self.conversion_thread.silence_duration = self.silence_duration
            # Pass replace_single_newlines setting
            self.conversion_thread.replace_single_newlines = (
                self.replace_single_newlines
            )
            # Pass use_silent_gaps setting
            self.conversion_thread.use_silent_gaps = self.use_silent_gaps
            # Pass subtitle_speed_method setting
            self.conversion_thread.subtitle_speed_method = self.subtitle_speed_method
            # Pass use_spacy_segmentation setting
            self.conversion_thread.use_spacy_segmentation = self.use_spacy_segmentation
            # Pass separate_chapters_format setting
            self.conversion_thread.separate_chapters_format = (
                self.separate_chapters_format
            )
            # Pass subtitle format setting
            self.conversion_thread.subtitle_format = self.config.get(
                "subtitle_format", "ass_centered_narrow"
            )
            # Pass chapter count for EPUB or PDF files
            if self.selected_file_type in ["epub", "pdf", "md", "markdown"] and hasattr(
                self, "selected_chapters"
            ):
                self.conversion_thread.chapter_count = len(self.selected_chapters)
                # Pass save_chapters_separately flag if available
                self.conversion_thread.save_chapters_separately = getattr(
                    self, "save_chapters_separately", False
                )
                # Pass merge_chapters_at_end flag if available
                self.conversion_thread.merge_chapters_at_end = getattr(
                    self, "merge_chapters_at_end", True
                )
            self.conversion_thread.progress_updated.connect(self.update_progress)
            self.conversion_thread.log_updated.connect(self.update_log)
            self.conversion_thread.conversion_finished.connect(
                self.on_conversion_finished
            )

            # Connect chapters_detected signal
            self.conversion_thread.chapters_detected.connect(
                self.show_chapter_options_dialog
            )

            self.conversion_thread.start()
            QApplication.processEvents()

        # Run GPU acceleration and module loading in a background thread
        def gpu_and_load():
            self.update_log("Checking GPU acceleration...")
            # Pass the use_gpu setting from the checkbox
            gpu_msg, gpu_ok = get_gpu_acceleration(self.gpu_checkbox.isChecked())
            # Store gpu_ok status to use when creating the conversion thread
            self.gpu_ok = gpu_ok
            self.update_log((gpu_msg, gpu_ok))
            self.update_log("Loading modules...")
            load_thread = LoadPipelineThread(pipeline_loaded_callback)
            load_thread.start()

        threading.Thread(target=gpu_and_load, daemon=True).start()

    def show_queue_summary(self):
        """Show a summary dialog after queue finishes."""
        if not self.queued_items:
            return

        # Check if override was active (this determines which settings were ACTUALLY used)
        override_active = self.config.get("queue_override_settings", False)

        # If override is ON, capture the global settings that were used for processing
        if override_active:
            g_voice = self.get_voice_formula()
            g_lang = self.get_selected_lang(g_voice)
            g_speed = self.speed_slider.value() / 100.0
            g_sub_mode = self.get_actual_subtitle_mode()
            g_format = self.selected_format
            g_newlines = self.replace_single_newlines
            g_silent_gaps = self.use_silent_gaps
            g_speed_method = self.subtitle_speed_method
        
        # Build HTML summary (Default Styling)
        summary_html = "<html><body>"
        
        header_text = "Queue finished"
        if override_active:
            header_text += " (Global Settings Applied)"
            
        summary_html += (
            f"<h2>{header_text}</h2>"
            f"Processed {len(self.queued_items)} items:<br><br>"
        )

        for idx, item in enumerate(self.queued_items, 1):
            # Resolve Effective Settings
            if override_active:
                eff_lang = g_lang
                eff_voice = g_voice
                eff_speed = g_speed
                eff_sub_mode = g_sub_mode
                eff_format = g_format
                eff_newlines = g_newlines
                eff_silent = g_silent_gaps
                eff_method = g_speed_method
            else:
                eff_lang = item.lang_code
                eff_voice = item.voice
                eff_speed = item.speed
                eff_sub_mode = item.subtitle_mode
                eff_format = item.output_format
                eff_newlines = getattr(item, "replace_single_newlines", True)
                eff_silent = getattr(item, "use_silent_gaps", False)
                eff_method = getattr(item, "subtitle_speed_method", "tts")

            # Retrieve File-Specific Data (Never Overridden)
            eff_chars = item.total_char_count
            eff_input = item.file_name
            eff_output = getattr(item, "output_path", "Unknown") 
            eff_save_sep = getattr(item, "save_chapters_separately", None)
            eff_merge = getattr(item, "merge_chapters_at_end", None)

            # --- Construct Display Block ---
            summary_html += (
                f"<span style='color:{COLORS['GREEN']}; font-weight:bold;'>{idx}) {os.path.basename(eff_input)}</span><br>"
                f"<span style='color:{COLORS['LIGHT_DISABLED']};'>Language:</span> {eff_lang}<br>"
                f"<span style='color:{COLORS['LIGHT_DISABLED']};'>Voice:</span> {eff_voice}<br>"
                f"<span style='color:{COLORS['LIGHT_DISABLED']};'>Speed:</span> {eff_speed}<br>"
                f"<span style='color:{COLORS['LIGHT_DISABLED']};'>Characters:</span> {eff_chars}<br>"
                f"<span style='color:{COLORS['LIGHT_DISABLED']};'>Format:</span> {eff_format}<br>"
                f"<span style='color:{COLORS['LIGHT_DISABLED']};'>Subtitle Mode:</span> {eff_sub_mode}<br>"
                f"<span style='color:{COLORS['LIGHT_DISABLED']};'>Method:</span> {eff_method}<br>"
                f"<span style='color:{COLORS['LIGHT_DISABLED']};'>Silent Gaps:</span> {eff_silent}<br>"
                f"<span style='color:{COLORS['LIGHT_DISABLED']};'>Repl. Newlines:</span> {eff_newlines}<br>"
            )

            # Book/Chapter specific options
            if eff_save_sep is not None:
                summary_html += f"<span style='color:{COLORS['LIGHT_DISABLED']};'>Split Chapters:</span> {eff_save_sep}<br>"
                if eff_save_sep and eff_merge is not None:
                    summary_html += f"<span style='color:{COLORS['LIGHT_DISABLED']};'>Merge End:</span> {eff_merge}<br>"

            summary_html += (
                f"<span style='color:{COLORS['LIGHT_DISABLED']};'>Input:</span> {eff_input}<br>"
                f"<span style='color:{COLORS['LIGHT_DISABLED']};'>Output:</span> {eff_output}<br><br>"
            )

        summary_html += "</body></html>"

        dialog = QDialog(self)
        dialog.setWindowTitle("Queue Summary")
        # Allow resizing
        dialog.resize(550, 650)

        layout = QVBoxLayout(dialog)
        text_edit = QTextEdit(dialog)
        text_edit.setReadOnly(True)
        text_edit.setHtml(summary_html)
        layout.addWidget(text_edit)

        close_btn = QPushButton("Close", dialog)
        close_btn.setFixedHeight(36)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.setLayout(layout)
        dialog.setMinimumSize(400, 300)
        dialog.setSizeGripEnabled(True)
        dialog.exec()

    def on_conversion_finished(self, message, output_path):
        prevent_sleep_end()
        if message == "Cancelled":
            self.etr_label.hide()  # Hide ETR label
            self.progress_bar.hide()
            self.btn_cancel.hide()
            self.is_converting = False
            self.controls_widget.show()
            self.finish_widget.hide()
            self.restore_input_box()
            display_path = (
                self.displayed_file_path
                if self.displayed_file_path
                else self.selected_file
            )
            # Only repopulate if not cleared by queue
            if not getattr(self, "input_box_cleared_by_queue", False):
                if display_path and os.path.exists(display_path):
                    self.input_box.set_file_info(display_path)
                else:
                    self.input_box.clear_input()
            else:
                self.input_box.clear_input()
            return

        self.update_log(message)
        if output_path:
            self.last_output_path = output_path
            # Store output_path in the current queued item if in queue mode
            if self.queued_items and self.current_queue_index < len(self.queued_items):
                self.queued_items[self.current_queue_index].output_path = output_path

        self.etr_label.hide()  # Hide ETR label
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        self.btn_cancel.hide()
        self.is_converting = False
        elapsed = int(time.time() - self.start_time)
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        self.update_log((f"\nTime elapsed: {h:02d}:{m:02d}:{s:02d}", "grey"))

        # Default to showing the button
        show_open_file_button = True
        # Check conditions to hide the button (only if flags exist for the completed conversion)
        save_sep = getattr(self, "save_chapters_separately", False)
        merge_end = getattr(
            self, "merge_chapters_at_end", True
        )  # Default to True if flag doesn't exist
        if save_sep and not merge_end:
            show_open_file_button = False

        if self.open_file_btn:
            self.open_file_btn.setVisible(show_open_file_button)

        # Only show finish_widget if queue is done
        if (
            self.current_queue_index + 1 >= len(self.queued_items)
            or not self.queued_items
        ):
            # Queue finished, show finish screen
            self.controls_widget.hide()
            self.finish_widget.show()
            sb = self.log_text.verticalScrollBar()
            sb.setValue(sb.maximum())
            save_config(self.config)
            # Show queue summary if more than one item
            if len(self.queued_items) > 1:
                self.show_queue_summary()
        else:
            # More items in queue: clear log and reload for next item
            self.log_text.clear()
            QApplication.processEvents()

        # Start new queued item, if we're using a queued conversion
        self.queue_item_conversion_finished()

    def reset_ui(self):
        try:
            self.etr_label.hide()  # Hide ETR label
            self.progress_bar.setValue(0)
            self.progress_bar.hide()
            self.selected_file = self.selected_file_type = self.selected_book_path = (
                None
            )
            self.selected_chapters = set()  # Reset selected chapters

            # Ensure open file button is visible when resetting
            if self.open_file_btn:
                self.open_file_btn.show()
            self.controls_widget.show()
            self.queue_row_widget.show()  # Show queue row on reset
            self.finish_widget.hide()
            self.btn_start.setText("Start")
            # Disconnect only if connected, then reconnect
            try:
                self.btn_start.clicked.disconnect()
            except TypeError:
                pass  # Ignore error if not connected
            self.btn_start.clicked.connect(self.start_conversion)
            self.enable_disable_queue_buttons()
            self.restore_input_box()
            self.input_box.clear_input()  # Reset text and style
            # Trigger the "Clear Queue" button (simulate user click)
            self.btn_clear_queue.click()
        except Exception as e:
            self._show_error_message_box("Reset Error", f"Could not reset UI:\n{e}")

    def go_back_ui(self):
        self.finish_widget.hide()
        self.controls_widget.show()
        self.queue_row_widget.show()  # Show queue row on go back
        self.progress_bar.hide()
        self.restore_input_box()
        self.log_text.clear()

        # Use displayed_file_path instead of selected_file for EPUBs or PDFs
        display_path = (
            self.displayed_file_path if self.displayed_file_path else self.selected_file
        )

        # Only repopulate if not cleared by queue
        if not getattr(self, "input_box_cleared_by_queue", False):
            if display_path and os.path.exists(display_path):
                self.input_box.set_file_info(display_path)
            else:
                self.input_box.clear_input()
        else:
            self.input_box.clear_input()

        # Ensure open file button is visible when going back
        if self.open_file_btn:
            self.open_file_btn.show()

    def on_save_option_changed(self, option):
        self.save_option = option
        self.config["save_option"] = option
        if option == "Choose output folder":
            try:
                folder = QFileDialog.getExistingDirectory(
                    self, "Select Output Folder", ""
                )
                if folder:
                    self.selected_output_folder = folder
                    self.save_path_label.setText(folder)
                    self.save_path_row_widget.show()
                    self.config["selected_output_folder"] = folder
                else:
                    self.save_option = "Save next to input file"
                    self.save_combo.setCurrentText(self.save_option)
                    self.config["save_option"] = self.save_option
            except Exception as e:
                self._show_error_message_box(
                    "Folder Dialog Error", f"Could not open folder dialog:\n{e}"
                )
                self.save_option = "Save next to input file"
                self.save_combo.setCurrentText(self.save_option)
                self.config["save_option"] = self.save_option
        else:
            self.save_path_row_widget.hide()
            self.selected_output_folder = None
            self.config["selected_output_folder"] = None
        save_config(self.config)

    def go_to_file(self):
        path = self.last_output_path
        if not path:
            return
        try:
            # Check if path is a directory (for multiple chapter files)
            if os.path.isdir(path):
                folder = path
            else:
                folder = os.path.dirname(path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        except Exception as e:
            self._show_error_message_box(
                "Open Folder Error", f"Could not open folder:\n{e}"
            )

    def open_file(self):
        path = self.last_output_path
        if not path:
            return
        try:
            # Check if path exists and is a file before opening
            if os.path.exists(path):
                if os.path.isdir(path):
                    self._show_error_message_box(
                        "Open File Error",
                        "Cannot open a directory as a file. Please use 'Go to folder' instead.",
                    )
                    return
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            else:
                self._show_error_message_box(
                    "Open File Error", f"File not found: {path}"
                )
        except Exception as e:
            self._show_error_message_box(
                "Open File Error", f"Could not open file:\n{e}"
            )

    def _get_preview_cache_path(self):
        """Generate the expected cache path for the current voice settings."""
        speed = self.speed_slider.value() / 100.0
        voice_to_cache = ""
        lang_to_cache = ""

        if self.mixed_voice_state:
            components = [f"{name}*{weight}" for name, weight in self.mixed_voice_state]
            voice_formula = " + ".join(filter(None, components))
            voice_to_cache = voice_formula
            if self.selected_profile_name:
                from abogen.voice_profiles import load_profiles

                entry = load_profiles().get(self.selected_profile_name, {})
                lang_to_cache = entry.get("language")
            else:
                lang_to_cache = self.selected_lang
            if not lang_to_cache and self.mixed_voice_state:
                lang_to_cache = (
                    self.mixed_voice_state[0][0][0]
                    if self.mixed_voice_state and self.mixed_voice_state[0][0]
                    else None
                )
        elif self.selected_voice:
            lang_to_cache = self.selected_voice[0]
            voice_to_cache = self.selected_voice
        else:  # No voice or profile selected
            return None

        if not lang_to_cache or not voice_to_cache:  # Not enough info
            return None

        cache_dir = get_user_cache_path("preview_cache")

        if "*" in voice_to_cache:  # Voice formula
            voice_id = (
                f"voice_formula_{hashlib.md5(voice_to_cache.encode()).hexdigest()[:8]}"
            )
        else:  # Single voice
            voice_id = voice_to_cache

        filename = f"{voice_id}_{lang_to_cache}_{speed:.2f}.wav"
        return os.path.join(cache_dir, filename)

    def preview_voice(self):
        if self.preview_playing:
            try:
                if self.play_audio_thread and self.play_audio_thread.isRunning():
                    # Call the stop method on PlayAudioThread to safely handle stopping
                    self.play_audio_thread.stop()
                    self.play_audio_thread.wait(500)  # Wait a bit
            except Exception as e:
                print(f"Error stopping preview audio: {e}")
            self._preview_cleanup()
            return

        if hasattr(self, "preview_thread") and self.preview_thread.isRunning():
            return

        # Check for cache first
        cached_path = self._get_preview_cache_path()
        if cached_path and os.path.exists(cached_path):
            print(f"Cache hit for {cached_path}")
            self.btn_preview.setEnabled(False)  # Disable button briefly
            self.voice_combo.setEnabled(False)
            self.btn_voice_formula_mixer.setEnabled(False)
            self.btn_start.setEnabled(False)

            # Directly play from cache
            self.preview_playing = True
            self.btn_preview.setIcon(self.stop_icon)
            self.btn_preview.setToolTip("Stop preview")
            self.btn_preview.setEnabled(True)

            def cleanup_cached_play():
                self._preview_cleanup()

            try:
                # Ensure pygame mixer is initialized for the audio thread
                import pygame

                if not pygame.mixer.get_init():
                    pygame.mixer.init()

                self.play_audio_thread = PlayAudioThread(cached_path)
                self.play_audio_thread.finished.connect(cleanup_cached_play)
                self.play_audio_thread.error.connect(
                    lambda msg: (
                        self._show_preview_error_box(msg),
                        cleanup_cached_play(),
                    )
                )
                self.play_audio_thread.start()
            except Exception as e:
                self._show_error_message_box(
                    "Preview Error", f"Could not play cached preview audio:\n{e}"
                )
                cleanup_cached_play()
            return

        # If no cache hit, proceed to load pipeline and generate
        self.btn_preview.setEnabled(False)
        self.btn_preview.setToolTip("Loading...")
        self.voice_combo.setEnabled(False)
        self.btn_voice_formula_mixer.setEnabled(False)  # Disable mixer button
        self.btn_start.setEnabled(False)  # Disable start button during preview

        # Start loading animation - ensure signal connection is always active
        if hasattr(self, "loading_movie"):
            # Disconnect previous connections to avoid multiple connections
            try:
                self.loading_movie.frameChanged.disconnect()
            except TypeError:
                pass  # Ignore error if not connected

            # Reconnect the signal
            self.loading_movie.frameChanged.connect(
                lambda: self.btn_preview.setIcon(
                    QIcon(self.loading_movie.currentPixmap())
                )
            )
            self.loading_movie.start()

        def pipeline_loaded_callback(np_module, kpipeline_class, error):
            self._on_pipeline_loaded_for_preview(np_module, kpipeline_class, error)

        load_thread = LoadPipelineThread(pipeline_loaded_callback)
        load_thread.start()

    def _on_pipeline_loaded_for_preview(self, np_module, kpipeline_class, error):
        # stop loading animation and restore icon on error
        if error:
            self.loading_movie.stop()
            self._show_error_message_box(
                "Loading Error", f"Error loading numpy or KPipeline: {error}"
            )
            self.btn_preview.setIcon(self.play_icon)
            self.btn_preview.setEnabled(True)
            self.btn_preview.setToolTip("Preview selected voice")
            self.voice_combo.setEnabled(True)
            self.btn_voice_formula_mixer.setEnabled(True)  # Re-enable mixer button
            self.btn_start.setEnabled(True)  # Re-enable start button on error
            return

        # Support preview for voice profiles
        speed = self.speed_slider.value() / 100.0
        if self.mixed_voice_state:
            # Build voice formula string
            components = [f"{name}*{weight}" for name, weight in self.mixed_voice_state]
            voice = " + ".join(filter(None, components))
            # determine language: use profile setting, else explicit mixer selection, else fallback to first voice code
            if self.selected_profile_name:
                from abogen.voice_profiles import load_profiles

                entry = load_profiles().get(self.selected_profile_name, {})
                lang = entry.get("language")
            else:
                lang = self.selected_lang
            if not lang and self.mixed_voice_state:
                lang = (
                    self.mixed_voice_state[0][0][0]
                    if self.mixed_voice_state and self.mixed_voice_state[0][0]
                    else None
                )
        else:
            lang = self.selected_voice[0]
            voice = self.selected_voice

        # use same gpu/cpu logic as in conversion
        gpu_msg, gpu_ok = get_gpu_acceleration(self.use_gpu)

        self.preview_thread = VoicePreviewThread(
            np_module, kpipeline_class, lang, voice, speed, gpu_ok
        )
        self.preview_thread.finished.connect(self._play_preview_audio)
        self.preview_thread.error.connect(self._preview_error)
        self.preview_thread.start()

    def _play_preview_audio(self, from_cache=True):  # from_cache default is now False
        # If preview_thread is the source, get temp_wav from it
        if hasattr(self, "preview_thread") and not from_cache:
            temp_wav = self.preview_thread.temp_wav
        elif from_cache:  # This case is now handled before calling _play_preview_audio
            cached_path = self._get_preview_cache_path()
            if cached_path and os.path.exists(cached_path):
                temp_wav = cached_path
            else:  # Should not happen if cache check was done
                self._show_error_message_box(
                    "Preview Error",
                    "Cache file expected but not found, please try again.",
                )
                self._preview_cleanup()
                return
        else:  # Should have temp_wav from preview_thread or handled by cache check
            self._show_error_message_box(
                "Preview Error", "Preview audio path not found."
            )
            self._preview_cleanup()
            return

        if not temp_wav:
            if hasattr(self, "loading_movie"):
                self.loading_movie.stop()
            self._show_error_message_box(
                "Preview Error", "Preview error: No audio generated."
            )
            self._preview_cleanup()
            return

        # stop loading animation, switch to stop icon
        if hasattr(self, "loading_movie"):
            self.loading_movie.stop()
        self.preview_playing = True
        self.btn_preview.setIcon(self.stop_icon)
        self.btn_preview.setToolTip("Stop preview")
        self.btn_preview.setEnabled(True)

        def cleanup():
            # Only remove if not from cache AND it's a temp file from VoicePreviewThread
            if (
                not from_cache
                and hasattr(self, "preview_thread")
                and hasattr(self.preview_thread, "temp_wav")
                and self.preview_thread.temp_wav == temp_wav
            ):
                try:
                    if os.path.exists(
                        temp_wav
                    ):  # Ensure it exists before trying to remove
                        os.remove(temp_wav)
                except Exception:
                    pass
            self._preview_cleanup()

        try:
            # Ensure pygame mixer is initialized for the audio thread
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()

            self.play_audio_thread = PlayAudioThread(temp_wav)
            self.play_audio_thread.finished.connect(cleanup)
            self.play_audio_thread.error.connect(
                lambda msg: (self._show_preview_error_box(msg), cleanup())
            )
            self.play_audio_thread.start()
        except Exception as e:
            self._show_error_message_box(
                "Preview Error", f"Could not play preview audio:\n{e}"
            )
            cleanup()

    def _show_error_message_box(self, title, message):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(title)
        box.setText(message)
        copy_btn = QPushButton("Copy")
        box.addButton(copy_btn, QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(message))
        box.exec()

    def _show_preview_error_box(self, msg):
        self._show_error_message_box("Preview Error", f"Preview error: {msg}")

    def _preview_cleanup(self):
        self.preview_playing = False
        if hasattr(self, "loading_movie"):
            self.loading_movie.stop()
        try:
            if hasattr(self, "loading_movie"):
                self.loading_movie.frameChanged.disconnect()
        except Exception:
            pass  # Ignore error if not connected
        self.btn_preview.setIcon(self.play_icon)
        self.btn_preview.setToolTip("Preview selected voice")
        self.btn_preview.setEnabled(True)
        self.voice_combo.setEnabled(True)
        self.btn_voice_formula_mixer.setEnabled(True)  # Re-enable mixer button
        self.btn_start.setEnabled(True)

    def _preview_error(self, msg):
        self._show_error_message_box("Preview Error", f"Preview error: {msg}")
        self._preview_cleanup()

    def cancel_conversion(self):
        if self.is_converting:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Cancel Conversion")
            box.setText(
                "A conversion is currently running. Are you sure you want to cancel?"
            )
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            box.setDefaultButton(QMessageBox.StandardButton.No)
            if box.exec() != QMessageBox.StandardButton.Yes:
                return
        try:
            if (
                hasattr(self, "conversion_thread")
                and self.conversion_thread.isRunning()
            ):
                if not hasattr(self, "_conversion_lock"):
                    self._conversion_lock = threading.Lock()

                def _cancel():
                    with self._conversion_lock:
                        self.conversion_thread.cancel()  # <-- Use cancel() method
                        self.conversion_thread.wait()

                threading.Thread(target=_cancel, daemon=True).start()

            self.is_converting = False
            self.etr_label.hide()  # Hide ETR label
            self.progress_bar.hide()
            self.btn_cancel.hide()
            self.controls_widget.show()
            self.queue_row_widget.show()  # Show queue row on cancel
            self.finish_widget.hide()
            self.restore_input_box()
            self.log_text.clear()
            display_path = (
                self.displayed_file_path
                if self.displayed_file_path
                else self.selected_file
            )
            # Only repopulate if not cleared by queue
            if not getattr(self, "input_box_cleared_by_queue", False):
                if display_path and os.path.exists(display_path):
                    self.input_box.set_file_info(display_path)
                else:
                    self.input_box.clear_input()
            else:
                self.input_box.clear_input()
            prevent_sleep_end()
        except Exception as e:
            self._show_error_message_box(
                "Cancel Error", f"Could not cancel conversion:\n{e}"
            )

    def on_subtitle_mode_changed(self, mode):
        self.subtitle_mode = mode
        self.config["subtitle_mode"] = mode
        save_config(self.config)
        # Disable subtitle format combo if subtitles are disabled
        if mode == "Disabled":
            self.subtitle_format_combo.setEnabled(False)
        else:
            self.subtitle_format_combo.setEnabled(True)
        # If highlighting mode selected, SRT is not supported. Disable SRT option and
        # switch away from it if currently selected.
        try:
            idx_srt = self.subtitle_format_combo.findData("srt")
            if mode == "Sentence + Highlighting":
                if idx_srt >= 0:
                    item = self.subtitle_format_combo.model().item(idx_srt)
                    if item is not None:
                        item.setEnabled(False)
                # If current format is SRT, switch to a compatible ASS format
                if self.subtitle_format_combo.currentData() == "srt":
                    new_idx = self.subtitle_format_combo.findData("ass_centered_narrow")
                    if new_idx >= 0:
                        self.subtitle_format_combo.setCurrentIndex(new_idx)
                        self.set_subtitle_format(
                            self.subtitle_format_combo.itemData(new_idx)
                        )
            else:
                # Re-enable SRT option when not in highlighting mode
                if idx_srt >= 0:
                    item = self.subtitle_format_combo.model().item(idx_srt)
                    if item is not None:
                        item.setEnabled(True)
        except Exception:
            # Ignore errors interacting with model (defensive)
            pass

    def on_format_changed(self, fmt):
        self.selected_format = fmt
        self.config["selected_format"] = fmt
        save_config(self.config)

    def on_gpu_setting_changed(self, state):
        self.use_gpu = state == Qt.CheckState.Checked.value
        self.config["use_gpu"] = self.use_gpu
        save_config(self.config)

    def cleanup_conversion_thread(self):
        # Stop conversion thread
        if (
            hasattr(self, "conversion_thread")
            and self.conversion_thread is not None
            and self.conversion_thread.isRunning()
        ):
            self.conversion_thread.cancel()
            self.conversion_thread.wait()

    def cleanup_preview_threads(self):
        # Stop preview generation thread
        if (
            hasattr(self, "preview_thread")
            and self.preview_thread is not None
            and self.preview_thread.isRunning()
        ):
            self.preview_thread.terminate()
            self.preview_thread.wait()

        # Stop audio playback thread
        if (
            hasattr(self, "play_audio_thread")
            and self.play_audio_thread is not None
            and self.play_audio_thread.isRunning()
        ):
            self.play_audio_thread.stop()
            self.play_audio_thread.wait()

        # Cleanup pygame mixer if initialized
        try:
            pygame = sys.modules.get("pygame")
            if pygame and pygame.mixer.get_init():
                pygame.mixer.quit()
        except Exception:
            pass

    def closeEvent(self, event):
        if self.is_converting:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Conversion in Progress")
            box.setText(
                "A conversion is currently running. Are you sure you want to exit?"
            )
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            box.setDefaultButton(QMessageBox.StandardButton.No)
            if box.exec() == QMessageBox.StandardButton.Yes:
                self.cleanup_conversion_thread()
                self.cleanup_preview_threads()
                event.accept()
            else:
                event.ignore()
        else:
            self.cleanup_conversion_thread()
            self.cleanup_preview_threads()
            event.accept()

    def show_chapter_options_dialog(self, chapter_count):
        """Show dialog to ask user about chapter processing options when chapters are detected in a .txt file"""
        # Check if this is a timestamp detection (-1) or chapter detection
        if chapter_count == -1:
            from abogen.conversion import TimestampDetectionDialog

            dialog = TimestampDetectionDialog(parent=self)
            dialog.setWindowModality(Qt.WindowModality.ApplicationModal)

            # Dialog always accepts (Yes or No), never cancels the conversion
            dialog.exec()
            treat_as_subtitle = dialog.use_timestamps()
            if (
                hasattr(self, "conversion_thread")
                and self.conversion_thread.isRunning()
            ):
                self.conversion_thread.set_timestamp_response(treat_as_subtitle)
            return

        # Normal chapter detection
        from abogen.conversion import ChapterOptionsDialog

        dialog = ChapterOptionsDialog(chapter_count, parent=self)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            options = dialog.get_options()
            if (
                hasattr(self, "conversion_thread")
                and self.conversion_thread.isRunning()
            ):
                self.conversion_thread.set_chapter_options(options)
        else:
            self.cancel_conversion()

    def apply_theme(self, theme):

        app = QApplication.instance()
        is_windows = platform.system() == "Windows"
        available_styles = [s.lower() for s in QStyleFactory.keys()]

        def is_windows_dark_mode():
            try:
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                ) as key:
                    value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                    return value == 0
            except Exception:
                return False

        # --- Theme selection logic ---
        def set_dark_palette():
            palette = QPalette()
            dark_bg = QColor(COLORS["DARK_BG"])
            base_bg = QColor(COLORS["DARK_BASE"])
            alt_bg = QColor(COLORS["DARK_ALT"])
            button_bg = QColor(COLORS["DARK_BUTTON"])
            disabled_fg = QColor(COLORS["DARK_DISABLED"])
            palette.setColor(QPalette.ColorRole.Window, dark_bg)
            palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.Base, base_bg)
            palette.setColor(QPalette.ColorRole.AlternateBase, alt_bg)
            palette.setColor(QPalette.ColorRole.ToolTipBase, dark_bg)
            palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.Button, button_bg)
            palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
            # Disabled roles
            palette.setColor(
                QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_fg
            )
            palette.setColor(
                QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_fg
            )
            palette.setColor(
                QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_fg
            )
            palette.setColor(
                QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, dark_bg
            )
            palette.setColor(
                QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, dark_bg
            )
            app.setPalette(palette)

        def set_light_palette():
            palette = QPalette()
            disabled_fg = QColor(COLORS["LIGHT_DISABLED"])
            palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["LIGHT_BG"]))
            palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.black)
            palette.setColor(QPalette.ColorRole.Base, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.AlternateBase, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.black)
            palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.black)
            palette.setColor(QPalette.ColorRole.Button, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.black)
            # Disabled roles
            palette.setColor(
                QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_fg
            )
            palette.setColor(
                QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_fg
            )
            palette.setColor(
                QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_fg
            )
            palette.setColor(
                QPalette.ColorGroup.Disabled,
                QPalette.ColorRole.Base,
                Qt.GlobalColor.white,
            )
            palette.setColor(
                QPalette.ColorGroup.Disabled,
                QPalette.ColorRole.Button,
                Qt.GlobalColor.white,
            )
            app.setPalette(palette)

        # --- Dark title bar support for Windows ---
        def set_title_bar_dark_mode(window, enable):
            if is_windows:
                try:
                    window.update()
                    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                    set_window_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
                    hwnd = int(window.winId())
                    value = ctypes.c_int(2 if enable else 0)
                    set_window_attribute(
                        hwnd,
                        DWMWA_USE_IMMERSIVE_DARK_MODE,
                        ctypes.byref(value),
                        ctypes.sizeof(value),
                    )
                except Exception:
                    pass

        # Main logic
        dark_mode = theme == "dark" or (
            theme == "system" and is_windows and is_windows_dark_mode()
        )
        if dark_mode:
            app.setStyle("Fusion")
            set_dark_palette()
        elif (theme == "light" or theme == "system") and is_windows:
            if "windowsvista" in available_styles:
                app.setStyle("windowsvista")
            else:
                app.setStyle("Fusion")
            app.setPalette(QPalette())
        elif theme == "light":
            app.setStyle("Fusion")
            set_light_palette()
        else:
            app.setStyle("Fusion")
            app.setPalette(QPalette())

        # Always set the title bar mode according to the current theme for all top-level widgets
        for widget in app.topLevelWidgets():
            set_title_bar_dark_mode(widget, dark_mode)

        # Refresh all top-level widgets
        style_name = app.style().objectName()
        app.setStyle(style_name)
        for widget in app.topLevelWidgets():
            app.style().polish(widget)
            widget.update()

        # Remove old event filter if present, then install a new one for dark title bar on new windows
        if hasattr(app, "_dark_titlebar_event_filter"):
            app.removeEventFilter(app._dark_titlebar_event_filter)
            delattr(app, "_dark_titlebar_event_filter")

        def get_dark_mode():
            return theme == "dark" or (
                theme == "system" and is_windows and is_windows_dark_mode()
            )

        app._dark_titlebar_event_filter = DarkTitleBarEventFilter(
            is_windows, get_dark_mode, set_title_bar_dark_mode
        )
        app.installEventFilter(app._dark_titlebar_event_filter)

        # Save config if changed
        if self.config.get("theme", "system") != theme:
            self.config["theme"] = theme
            save_config(self.config)

    def show_settings_menu(self):
        """Show a dropdown menu for settings options."""
        menu = QMenu(self)

        theme_menu = QMenu("Theme", self)
        theme_menu.setToolTip("Choose the application theme")

        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)

        # Theme options: (internal_value, display_text)
        theme_options = [
            ("system", "System"),
            ("light", "Light"),
            ("dark", "Dark"),
        ]

        # Get current theme from config, default to "system"
        current_theme = self.config.get("theme", "system")
        for value, text in theme_options:
            theme_action = QAction(text, self)
            theme_action.setCheckable(True)
            theme_action.setChecked(current_theme == value)
            theme_action.triggered.connect(lambda checked, v=value: self.apply_theme(v))
            theme_group.addAction(theme_action)
            theme_menu.addAction(theme_action)

        menu.addMenu(theme_menu)

        # Add separate chapters format option
        separate_chapters_format_menu = QMenu("Separate chapters audio format", self)
        separate_chapters_format_menu.setToolTip(
            "Choose the format for individual chapter files"
        )

        format_group = QActionGroup(self)
        format_group.setExclusive(True)

        for format_option in ["wav", "flac", "mp3", "opus"]:
            format_action = QAction(format_option, self)
            format_action.setCheckable(True)
            format_action.setChecked(self.separate_chapters_format == format_option)
            format_action.triggered.connect(
                lambda checked, fmt=format_option: self.set_separate_chapters_format(
                    fmt
                )
            )
            format_group.addAction(format_action)
            separate_chapters_format_menu.addAction(format_action)

        menu.addMenu(separate_chapters_format_menu)

        # Add max words per subtitle option
        max_words_action = QAction("Configure max words per subtitle", self)
        max_words_action.triggered.connect(self.set_max_subtitle_words)
        menu.addAction(max_words_action)

        # Add silence between chapters option
        silence_action = QAction("Configure silence between chapters", self)
        silence_action.triggered.connect(self.set_silence_between_chapters)
        menu.addAction(silence_action)

        max_lines_action = QAction("Configure max lines in log window", self)
        max_lines_action.triggered.connect(self.set_max_log_lines)
        menu.addAction(max_lines_action)

        # Add separator
        menu.addSeparator()

        # Add shortcut to desktop (Windows or Linux)
        if platform.system() == "Windows" or platform.system() == "Linux":
            # Use extended label on Linux
            label = (
                "Create desktop shortcut and install"
                if platform.system() == "Linux"
                else "Create desktop shortcut"
            )
            add_shortcut_action = QAction(label, self)
            add_shortcut_action.triggered.connect(self.add_shortcut_to_desktop)
            menu.addAction(add_shortcut_action)

        # Add reveal config option
        reveal_config_action = QAction("Open configuration directory", self)
        reveal_config_action.triggered.connect(self.reveal_config_in_explorer)
        menu.addAction(reveal_config_action)

        # Add open cache directory option
        open_cache_action = QAction("Open cache directory", self)
        open_cache_action.triggered.connect(self.open_cache_directory)
        menu.addAction(open_cache_action)

        # Add clear cache files option
        clear_cache_action = QAction("Clear cache files", self)
        clear_cache_action.triggered.connect(self.clear_cache_files)
        menu.addAction(clear_cache_action)

        # Add separator
        menu.addSeparator()

        # Add use silent gaps option (for subtitle files)
        self.silent_gaps_action = QAction("Use silent gaps between subtitles", self)
        self.silent_gaps_action.setCheckable(True)
        self.silent_gaps_action.setChecked(self.use_silent_gaps)
        self.silent_gaps_action.triggered.connect(
            lambda checked: self.toggle_use_silent_gaps(checked)
        )
        menu.addAction(self.silent_gaps_action)

        # Subtitle speed adjustment method
        speed_method_menu = menu.addMenu("Subtitle speed adjustment method")
        speed_method_menu.setToolTip(
            "Choose speed adjustment method:\n"
            "TTS Regeneration: Better quality\n"
            "FFmpeg Time-stretch: Faster processing"
        )

        speed_method_group = QActionGroup(self)
        speed_method_group.setExclusive(True)

        for method, label in [
            ("tts", "TTS Regeneration (better quality)"),
            ("ffmpeg", "FFmpeg Time-stretch (better speed)"),
        ]:
            action = QAction(label, speed_method_menu)
            action.setCheckable(True)
            action.setChecked(self.subtitle_speed_method == method)
            action.triggered.connect(
                lambda checked, m=method: self.toggle_subtitle_speed_method(m)
            )
            speed_method_group.addAction(action)
            speed_method_menu.addAction(action)

        self.speed_method_group = speed_method_group

        # Add separator
        menu.addSeparator()

        # Add spaCy sentence segmentation option
        spacy_action = QAction("Use spaCy for sentence segmentation", self)
        spacy_action.setCheckable(True)
        spacy_action.setChecked(self.use_spacy_segmentation)
        spacy_action.triggered.connect(
            lambda checked: self.toggle_spacy_segmentation(checked)
        )
        menu.addAction(spacy_action)

        # Add separator
        menu.addSeparator()

        # Add "Pre-download models and voices for offline use" option
        predownload_action = QAction(
            "Pre-download models and voices for offline use", self
        )
        predownload_action.triggered.connect(self.show_predownload_dialog)
        menu.addAction(predownload_action)

        # Add "Disable Kokoro's internet access" option
        disable_kokoro_action = QAction("Disable Kokoro's internet access", self)
        disable_kokoro_action.setCheckable(True)
        disable_kokoro_action.setChecked(
            self.config.get("disable_kokoro_internet", False)
        )
        disable_kokoro_action.triggered.connect(
            lambda checked: self.toggle_kokoro_internet_access(checked)
        )
        menu.addAction(disable_kokoro_action)

        # Add check for updates option
        check_updates_action = QAction("Check for updates at startup", self)
        check_updates_action.setCheckable(True)
        check_updates_action.setChecked(self.config.get("check_updates", True))
        check_updates_action.triggered.connect(self.toggle_check_updates)
        menu.addAction(check_updates_action)

        # Add "Reset to default settings" option
        reset_defaults_action = QAction("Reset to default settings", self)
        reset_defaults_action.triggered.connect(self.reset_to_default_settings)
        menu.addAction(reset_defaults_action)

        # Add about action
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about_dialog)
        menu.addAction(about_action)

        menu.exec(self.settings_btn.mapToGlobal(QPoint(0, self.settings_btn.height())))

    def toggle_replace_single_newlines(self, enabled):
        self.replace_single_newlines = enabled
        self.config["replace_single_newlines"] = enabled
        save_config(self.config)

    def toggle_use_silent_gaps(self, enabled):
        # Show confirmation dialog with explanation
        action = "enable" if enabled else "disable"
        message = (
            "When enabled, allows speech to continue naturally into the silent periods between subtitles, "
            "preventing unnecessary audio speed-up based on subtitle end timestamps.\n\nWhen disabled, ensures strict subtitle timing where "
            f"audio ends exactly when the subtitle ends.\n\nDo you want to {action} this option?"
        )

        reply = QMessageBox.question(
            self,
            "Use Silent Gaps Between Subtitles",
            message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )

        if reply == QMessageBox.StandardButton.Ok:
            self.use_silent_gaps = enabled
            self.config["use_silent_gaps"] = enabled
            save_config(self.config)
        else:
            # Revert the checkbox state if cancelled
            self.silent_gaps_action.setChecked(not enabled)

    def toggle_subtitle_speed_method(self, method):
        self.subtitle_speed_method = method
        self.config["subtitle_speed_method"] = method
        save_config(self.config)

    def toggle_spacy_segmentation(self, enabled):
        self.use_spacy_segmentation = enabled
        self.config["use_spacy_segmentation"] = enabled
        save_config(self.config)

    def restart_app(self):

        import sys

        exe = sys.executable
        args = sys.argv

        # On Windows, use .exe if available
        if platform.system() == "Windows":
            script_path = args[0]
            if not script_path.lower().endswith(".exe"):
                exe_path = os.path.splitext(script_path)[0] + ".exe"
                if os.path.exists(exe_path):
                    args[0] = exe_path

        QProcess.startDetached(exe, args)
        QApplication.quit()

    def toggle_kokoro_internet_access(self, disabled):
        if disabled:
            message = (
                "Disabling Kokoro's internet access will block downloads of models and voices from Hugging Face Hub. "
                "This can make processing faster when there is no internet connection, since no requests will be made. "
                "The app needs to restart to apply this change.\n\nDo you want to continue?"
            )
        else:
            message = (
                "Enabling Kokoro's internet access will allow it to download models and voices from Hugging Face Hub. "
                "The app needs to restart to apply this change.\n\nDo you want to continue?"
            )
        reply = QMessageBox.question(
            self,
            "Restart Required",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config["disable_kokoro_internet"] = disabled
            save_config(self.config)
            try:
                self.restart_app()
            except Exception as e:
                QMessageBox.critical(
                    self, "Restart Failed", f"Failed to restart the application:\n{e}"
                )

    def reset_to_default_settings(self):
        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "This will reset all settings to their default values and restart the application.\n\nDo you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from abogen.utils import get_user_config_path

            config_path = get_user_config_path()
            try:
                if os.path.exists(config_path):
                    os.remove(config_path)
                self.restart_app()
            except Exception as e:
                QMessageBox.critical(
                    self, "Reset Error", f"Could not reset settings:\n{e}"
                )

    def reveal_config_in_explorer(self):
        """Open the configuration file location in file explorer."""
        from abogen.utils import get_user_config_path

        try:
            config_path = get_user_config_path()
            # Open the directory containing the config file
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(config_path)))
        except Exception as e:
            QMessageBox.critical(
                self, "Config Error", f"Could not open config location:\n{e}"
            )

    def open_cache_directory(self):
        """Open the cache directory used by the program."""
        try:
            # Get the abogen cache directory
            cache_dir = get_user_cache_path()

            # Create the directory if it doesn't exist
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)

            # Open the directory in file explorer
            QDesktopServices.openUrl(QUrl.fromLocalFile(cache_dir))
        except Exception as e:
            QMessageBox.critical(
                self, "Cache Directory Error", f"Could not open cache directory:\n{e}"
            )

    def add_shortcut_to_desktop(self):
        """Create a desktop shortcut to this program using PowerShell."""
        import sys
        from platformdirs import user_desktop_dir
        from abogen.utils import create_process

        try:
            if platform.system() == "Windows":
                # where to put the .lnk
                desktop = user_desktop_dir()
                shortcut_path = os.path.join(desktop, "abogen.lnk")

                # target exe
                python_dir = os.path.dirname(sys.executable)
                target = os.path.join(python_dir, "Scripts", "abogen.exe")
                if not os.path.exists(target):
                    QMessageBox.critical(
                        self,
                        "Shortcut Error",
                        f"Could not find abogen.exe at:\n{target}",
                    )
                    return

                # icon (fallback to exe if missing)
                icon = get_resource_path("abogen.assets", "icon.ico")
                if not icon or not os.path.exists(icon):
                    icon = target  # Create a more direct PowerShell command
                shortcut_ps = shortcut_path.replace("'", "''").replace("\\", "\\\\")
                target_ps = target.replace("'", "''").replace("\\", "\\\\")
                workdir_ps = (
                    os.path.dirname(target).replace("'", "''").replace("\\", "\\\\")
                )
                icon_ps = icon.replace("'", "''").replace("\\", "\\\\")
                # Create PowerShell script as a single line with no line breaks (more reliable)
                ps_cmd = f"$s=New-Object -ComObject WScript.Shell; $lnk=$s.CreateShortcut('{shortcut_ps}'); $lnk.TargetPath='{target_ps}'; $lnk.WorkingDirectory='{workdir_ps}'; $lnk.IconLocation='{icon_ps}'; $lnk.Save()"

                # Run PowerShell with the command directly
                proc = create_process(
                    'powershell -NoProfile -ExecutionPolicy Bypass -Command "'
                    + ps_cmd
                    + '"'
                )
                proc.wait()

                if proc.returncode == 0:
                    QMessageBox.information(
                        self,
                        "Shortcut Created",
                        f"Shortcut created on desktop:\n{shortcut_path}",
                    )
                else:
                    QMessageBox.critical(
                        self,
                        "Shortcut Error",
                        f"PowerShell failed with exit code: {proc.returncode}",
                    )
            elif platform.system() == "Linux":
                desktop = user_desktop_dir()
                if not desktop or not os.path.isdir(desktop):
                    QMessageBox.critical(
                        self, "Shortcut Error", "Could not determine desktop directory."
                    )
                    return

                shortcut_path = os.path.join(desktop, "abogen.desktop")

                import shutil

                found = shutil.which("abogen")
                if found:
                    target = found
                else:
                    local_bin = os.path.expanduser("~/.local/bin/abogen")
                    if os.path.exists(local_bin):
                        target = local_bin
                    else:
                        python_dir = os.path.dirname(sys.executable)
                        target = os.path.join(python_dir, "bin", "abogen")
                        if not os.path.exists(target):
                            target_fallback = os.path.join(python_dir, "abogen")
                            if os.path.exists(target_fallback):
                                target = target_fallback
                            else:
                                QMessageBox.critical(
                                    self,
                                    "Shortcut Error",
                                    "Could not find abogen executable in PATH or common installation directories.",
                                )
                                return

                icon_path = get_resource_path("abogen.assets", "icon.png")

                desktop_entry_content = f"""[Desktop Entry]
Version={VERSION}
Name={PROGRAM_NAME}
Comment={PROGRAM_DESCRIPTION}
Exec={target}
Icon={icon_path}
Terminal=false
Type=Application
Categories=AudioVideo;Audio;Utility;
"""
                with open(shortcut_path, "w", encoding="utf-8") as f:
                    f.write(desktop_entry_content)

                os.chmod(shortcut_path, 0o755)

                QMessageBox.information(
                    self,
                    "Shortcut Created",
                    f"Shortcut created on desktop:\n{shortcut_path}",
                )

                # Offer installation for current user under ~/.local/share/applications
                reply = QMessageBox.question(
                    self,
                    "Install Application Entry",
                    "Install application entry for current user?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    import shutil

                    user_app_dir = os.path.expanduser("~/.local/share/applications")
                    os.makedirs(user_app_dir, exist_ok=True)
                    user_entry = os.path.join(user_app_dir, "abogen.desktop")
                    try:
                        shutil.copyfile(shortcut_path, user_entry)
                        os.chmod(user_entry, 0o644)
                        QMessageBox.information(
                            self,
                            "Installation Complete",
                            f"Desktop entry installed to {user_entry}",
                        )
                    except Exception as e:
                        QMessageBox.warning(
                            self,
                            "Install Error",
                            f"Could not install entry:\n{e}",
                        )
            else:
                QMessageBox.information(
                    self,
                    "Unsupported OS",
                    "Desktop shortcut creation is not supported on this operating system.",
                )

        except Exception as e:
            QMessageBox.critical(
                self, "Shortcut Error", f"Could not create shortcut:\n{e}"
            )

    def toggle_check_updates(self, checked):
        self.config["check_updates"] = checked
        save_config(self.config)

    def show_voice_formula_dialog(self):
        from abogen.voice_profiles import load_profiles

        profiles = load_profiles()
        initial_state = None
        selected_profile = self.selected_profile_name
        if selected_profile:
            entry = profiles.get(selected_profile, {})
            if isinstance(entry, dict):
                initial_state = entry.get("voices", [])
            else:
                initial_state = entry
        elif self.mixed_voice_state is not None:
            initial_state = self.mixed_voice_state
        elif self.selected_voice:
            # If a single voice is selected, default to first profile if available
            if profiles:
                first_profile = next(iter(profiles))
                entry = profiles[first_profile]
                selected_profile = first_profile
                if isinstance(entry, dict):
                    initial_state = entry.get("voices", [])
                else:
                    initial_state = entry
                    self.selected_lang = entry[0][0] if entry and entry[0] else None
        dialog = VoiceFormulaDialog(
            self, initial_state=initial_state, selected_profile=selected_profile
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.current_profile:
                self.selected_profile_name = dialog.current_profile
                self.config["selected_profile_name"] = dialog.current_profile
                if "selected_voice" in self.config:
                    del self.config["selected_voice"]
                save_config(self.config)
                self.populate_profiles_in_voice_combo()
                idx = self.voice_combo.findData(f"profile:{dialog.current_profile}")
                if idx >= 0:
                    self.voice_combo.setCurrentIndex(idx)
            self.mixed_voice_state = dialog.get_selected_voices()

    def show_predownload_dialog(self):
        """Show the pre-download models and voices dialog."""
        from abogen.pyqt.predownload_gui import PreDownloadDialog

        dialog = PreDownloadDialog(self)
        dialog.exec()

    def show_about_dialog(self):
        """Show an About dialog with program information including GitHub link."""
        # Get application icon for dialog
        icon = self.windowIcon()

        # Create custom dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(f"About {PROGRAM_NAME}")
        dialog.setWindowFlags(
            dialog.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        dialog.setFixedSize(400, 320)  # Increased height for new button

        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)

        # Header with icon and title
        header_layout = QHBoxLayout()
        icon_label = QLabel()
        if not icon.isNull():
            icon_label.setPixmap(icon.pixmap(64, 64))
        else:
            # Fallback text if icon not available
            icon_label.setText("📚")
            icon_label.setStyleSheet("font-size: 48px;")

        header_layout.addWidget(icon_label)

        # Fix: Added style to reduce space between h1 and h3
        title_label = QLabel(
            f"<h1 style='margin-bottom: 0;'>{PROGRAM_NAME} <span style='font-size: 12px; font-weight: normal; color: #666;'>v{VERSION}</span></h1><h3 style='margin-top: 5px;'>Audiobook Generator</h3>"
        )
        title_label.setTextFormat(Qt.TextFormat.RichText)
        header_layout.addWidget(title_label, 1)
        layout.addLayout(header_layout)

        # Description
        desc_label = QLabel(
            f"<p>{PROGRAM_DESCRIPTION}</p>"
            "<p>Visit the GitHub repository for updates, documentation, and to report issues.</p>"
        )
        desc_label.setTextFormat(Qt.TextFormat.RichText)
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # GitHub link
        github_btn = QPushButton("Visit GitHub Repository")
        github_btn.setIcon(QIcon(get_resource_path("abogen.assets", "github.png")))
        github_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        github_btn.setFixedHeight(32)
        layout.addWidget(github_btn)

        # Check for updates button
        update_btn = QPushButton("Check for updates")
        update_btn.clicked.connect(self.manual_check_for_updates)
        update_btn.setFixedHeight(32)
        layout.addWidget(update_btn)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        close_btn.setFixedHeight(32)
        layout.addWidget(close_btn)

        dialog.exec()

    def manual_check_for_updates(self):
        """Manually check for updates and always show result"""
        # Set a flag to always show the result message
        self._show_update_check_result = True
        self.check_for_updates_startup()

    def check_for_updates_startup(self):
        import urllib.request

        def show_update_message(remote_version, local_version):
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle("Update Available")
            msg_box.setText(
                f"A new version of {PROGRAM_NAME} is available! ({local_version} > {remote_version})"
            )
            msg_box.setInformativeText(
                f"If you installed via pip, update by running:\n"
                f"pip install --upgrade {PROGRAM_NAME}\n\n"
                f"If you're using the Windows portable version, run 'WINDOWS_INSTALL.bat' again.\n\n"
                "Alternatively, visit the GitHub repository for more information. "
                "Would you like to view the changelog?"
            )
            msg_box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
            if msg_box.exec() == QMessageBox.StandardButton.Yes:
                try:
                    QDesktopServices.openUrl(QUrl(GITHUB_URL + "/releases/latest"))
                except Exception:
                    pass

        # Reset flag to track if we should show "no updates" message
        show_result = (
            hasattr(self, "_show_update_check_result")
            and self._show_update_check_result
        )
        self._show_update_check_result = False

        try:
            update_url = "https://raw.githubusercontent.com/denizsafak/abogen/refs/heads/main/abogen/VERSION"
            with urllib.request.urlopen(update_url) as response:
                remote_raw = response.read().decode().strip()
            local_raw = VERSION

            # Parse version numbers
            remote_version = remote_raw
            local_version = local_raw

            try:
                remote_num = int("".join(remote_version.split(".")))
                local_num = int("".join(local_version.split(".")))
            except ValueError as ve:
                return

            if remote_num > local_num:
                # Use QTimer to ensure UI is ready, then show update message.
                QTimer.singleShot(
                    1000, lambda: show_update_message(remote_version, local_version)
                )
            elif show_result:
                # Show "no updates" message if manually checking
                QMessageBox.information(
                    self,
                    "Up to Date",
                    f"You are running the latest version of {PROGRAM_NAME} ({local_version}).",
                )
        except Exception as e:
            if show_result:
                QMessageBox.warning(
                    self,
                    "Update Check Failed",
                    f"Could not check for updates:\n{str(e)}",
                )
            pass

    def clear_cache_files(self):
        """Clear cache files created by the program."""
        import glob

        try:
            # Get the abogen cache directory
            cache_dir = get_user_cache_path()

            # Find all .txt files and cover images in the abogen cache directory
            cache_files = glob.glob(os.path.join(cache_dir, "*.txt"))
            cache_files.extend(glob.glob(os.path.join(cache_dir, "cover_*.jpg")))

            # Count the files
            file_count = len(cache_files)

            # Check for preview cache files
            preview_cache_dir = os.path.join(cache_dir, "preview_cache")
            preview_files = []
            if os.path.exists(preview_cache_dir):
                preview_pattern = os.path.join(preview_cache_dir, "*.wav")
                preview_files = glob.glob(preview_pattern)

            preview_count = len(preview_files)

            if file_count == 0 and preview_count == 0:
                QMessageBox.information(
                    self, "No Cache Files", "No cache files were found."
                )
                return

            # Create a custom message box with checkbox
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle("Clear Cache Files")

            msg_text = f"Found {file_count} cache file{'s' if file_count != 1 else ''} in the {PROGRAM_NAME} cache folder."
            if preview_count > 0:
                msg_text += f"\nAlso found {preview_count} preview cache file{'s' if preview_count != 1 else ''}."

            msg_box.setText(msg_text + "\nDo you want to delete them?")

            # Add checkbox for preview cache
            preview_cache_checkbox = QCheckBox("Also clean preview cache", msg_box)
            preview_cache_checkbox.setChecked(False)
            # Only enable checkbox if preview files exist
            preview_cache_checkbox.setEnabled(preview_count > 0)

            # Add the checkbox to the layout
            msg_box.setCheckBox(preview_cache_checkbox)

            # Add buttons
            msg_box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)

            if msg_box.exec() != QMessageBox.StandardButton.Yes:
                return

            # Delete the text files
            deleted_count = 0
            for file_path in cache_files:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    print(f"Error deleting {file_path}: {e}")

            # Delete preview cache files if checkbox is checked
            deleted_preview_count = 0
            if preview_cache_checkbox.isChecked() and preview_count > 0:
                for file_path in preview_files:
                    try:
                        os.remove(file_path)
                        deleted_preview_count += 1
                    except Exception as e:
                        print(f"Error deleting preview cache {file_path}: {e}")

            # Build result message
            result_msg = f"Successfully deleted {deleted_count} temporary file{'s' if deleted_count != 1 else ''}."
            if preview_cache_checkbox.isChecked() and deleted_preview_count > 0:
                result_msg += f"\nAlso deleted {deleted_preview_count} preview cache file{'s' if deleted_preview_count != 1 else ''}."

            # Show results
            QMessageBox.information(self, "Cache Files Cleared", result_msg)

            # If currently selected file is in the cache directory, clear the UI
            if (
                self.selected_file
                and os.path.dirname(self.selected_file) == cache_dir
                and self.selected_file.endswith(".txt")
            ):
                self.input_box.clear_input()

        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"An error occurred while clearing temporary files:\n{e}"
            )

    def set_max_log_lines(self):
        """Open a dialog to set the maximum lines in the log window."""
        from PyQt6.QtWidgets import QInputDialog

        value, ok = QInputDialog.getInt(
            self,
            "Max Lines in Log Window",
            "Enter the maximum number of lines to display in the log window:",
            self.log_window_max_lines,
            10,  # min value
            999999999,  # max value
            1,  # step
        )
        if ok:
            self.log_window_max_lines = value
            self.config["log_window_max_lines"] = value
            save_config(self.config)
            QMessageBox.information(
                self,
                "Setting Saved",
                f"Maximum lines in log window set to {value}.",
            )

    def set_max_subtitle_words(self):
        """Open a dialog to set the maximum words per subtitle"""
        from PyQt6.QtWidgets import QInputDialog

        current_value = self.config.get("max_subtitle_words", 50)

        value, ok = QInputDialog.getInt(
            self,
            "Max Words Per Subtitle",
            "Enter the maximum number of words per\nsubtitle (before splitting the subtitle):",
            current_value,
            1,  # min value
            200,  # max value
            1,  # step
        )

        if ok:
            # Save the new value
            self.max_subtitle_words = value
            self.config["max_subtitle_words"] = value
            save_config(self.config)

            # Show confirmation
            QMessageBox.information(
                self,
                "Setting Saved",
                f"Maximum words per subtitle set to {value}.",
            )

    def set_silence_between_chapters(self):
        """Open a dialog to set the silence duration between chapters"""

        current_value = self.config.get("silence_duration", 2.0)

        dlg = QInputDialog(self)
        dlg.setWindowTitle("Silence Duration (seconds)")
        dlg.setLabelText(
            "Enter the duration of silence\nbetween chapters (in seconds):"
        )
        dlg.setInputMode(QInputDialog.InputMode.DoubleInput)
        dlg.setDoubleDecimals(1)
        dlg.setDoubleMinimum(0.0)
        dlg.setDoubleMaximum(60.0)
        dlg.setDoubleValue(current_value)
        dlg.setDoubleStep(0.1)  # <-- set step to 0.1

        if dlg.exec() == QDialog.DialogCode.Accepted:
            value = dlg.doubleValue()
            # Round to one decimal to avoid floating-point representation noise
            value = round(value, 1)

            # Save the new value
            self.silence_duration = value
            self.config["silence_duration"] = value
            save_config(self.config)

            # Show confirmation (format with one decimal)
            QMessageBox.information(
                self,
                "Setting Saved",
                f"Silence duration between chapters set to {value:.1f} seconds.",
            )

    def set_separate_chapters_format(self, fmt):
        """Set the format for separate chapters audio files."""
        self.separate_chapters_format = fmt
        self.config["separate_chapters_format"] = fmt
        save_config(self.config)

    def set_subtitle_format(self, fmt):
        """Set the subtitle format."""
        self.config["subtitle_format"] = fmt
        save_config(self.config)

    def show_model_download_warning(self, title, message):
        QMessageBox.information(self, title, message)
