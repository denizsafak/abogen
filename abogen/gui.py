import os
import time
import tempfile
import platform
import base64
import re
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QLabel,
    QProgressBar,
    QSlider,
    QComboBox,
    QSizePolicy,
    QTextEdit,
    QFileIconProvider,
    QMessageBox,
    QDialog,
    QCheckBox,
    QMenu,
    QAction,
)
from PyQt5.QtCore import (
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
)
from PyQt5.QtGui import (
    QTextCursor,
    QDesktopServices,
    QIcon,
    QPixmap,
    QPainter,
    QPolygon,
    QColor,
    QMovie,
)
from utils import (
    load_config,
    save_config,
    get_gpu_acceleration,
    clean_text,
    prevent_sleep_start,
    prevent_sleep_end,
    calculate_text_length,
    get_resource_path,
    LoadPipelineThread,
)
from conversion import ConversionThread, VoicePreviewThread, PlayAudioThread
from book_handler import HandlerDialog
from constants import (
    PROGRAM_NAME,
    VERSION,
    GITHUB_URL,
    PROGRAM_DESCRIPTION,
    LANGUAGE_DESCRIPTIONS,
    VOICES_INTERNAL,
    SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION,
)
from threading import Thread
from voice_formula_gui import VoiceFormulaDialog
from platformdirs import user_desktop_dir
from voice_profiles import load_profiles

# Import ctypes for Windows-specific taskbar icon
if platform.system() == "Windows":
    import ctypes


class ThreadSafeLogSignal(QObject):
    log_signal = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

    def emit_log(self, message):
        self.log_signal.emit(message)


class IconProvider(QFileIconProvider):
    def icon(self, fileInfo):
        return super().icon(fileInfo)


class InputBox(QLabel):
    LABEL_CSS = """QLabel { border:2px dashed #aaa; border-radius:5px; padding:20px; background:#f5f9fc; min-height:100px; } QLabel:hover { background:#e5f1fa; border-color:#6ab0de; }"""
    LABEL_CSS_ACTIVE = """QLabel { border:2px dashed #42ad4a; border-radius:5px; padding:20px; background:#e6f7e6;min-height:100px; } QLabel:hover { background:#e5f1fa; border-color:#6ab0de; }"""
    LABEL_CSS_ERROR = """QLabel { border:2px dashed #e74c3c; border-radius:5px; padding:20px; background:#ffeaea; min-height:100px; color:#c0392b; } QLabel:hover { background:#ffeaea; border-color:#e74c3c; }"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setText(
            "Drag and drop your file here or click to browse.\n(.txt, .epub, .pdf)"
        )
        self.setStyleSheet(self.LABEL_CSS)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.clear_btn = QPushButton("✕", self)
        self.clear_btn.setFixedSize(28, 28)
        self.clear_btn.hide()
        self.clear_btn.clicked.connect(self.clear_input)
        self.chapters_btn = QPushButton("Chapters", self)
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

    def set_file_info(self, file_path):
        # get icon without resizing using custom provider
        provider = IconProvider()
        qicon = provider.icon(QFileInfo(file_path))
        size = QSize(32, 32)
        pixmap = qicon.pixmap(size)
        # convert to base64 PNG
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        pixmap.save(buffer, "PNG")
        img_data = base64.b64encode(buffer.data()).decode()

        size_str = self._human_readable_size(os.path.getsize(file_path))
        name = os.path.basename(file_path)
        char_count = "N/A"

        # Format numbers with commas
        def format_num(n):
            try:
                return f"{int(n):,}"
            except Exception:
                return str(n)

        if (
            file_path.lower().endswith(".epub") or file_path.lower().endswith(".pdf")
        ) and hasattr(self.window(), "selected_chapters"):
            # EPUB or PDF: sum character counts for selected chapters
            try:

                book_path = file_path
                dialog = HandlerDialog(
                    book_path,
                    checked_chapters=self.window().selected_chapters,
                    parent=self.window(),
                )
                chapters_text, all_checked_hrefs = dialog.get_selected_text()
                # Clean text before counting characters
                cleaned_text = clean_text(chapters_text)
                char_count = calculate_text_length(cleaned_text)
            except Exception:
                char_count = "N/A"
        else:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                    # Clean text before counting characters
                    cleaned_text = clean_text(text)
                    char_count = calculate_text_length(cleaned_text)
            except Exception:
                char_count = "N/A"
        # Store numeric char_count on window
        try:
            self.window().char_count = int(char_count)
        except Exception:
            self.window().char_count = 0
        # embed icon at native size with word-wrap for the filename
        self.setText(
            f'<img src="data:image/png;base64,{img_data}"><br><span style="display: inline-block; max-width: 100%; word-break: break-all;"><b>{name}</b></span><br>Size: {format_num(size_str)}<br>Characters: {format_num(char_count)}'
        )
        # Set fixed width to force wrapping
        self.setWordWrap(True)
        self.setStyleSheet(self.LABEL_CSS_ACTIVE)
        self.clear_btn.show()
        is_document = self.window().selected_file_type in ["epub", "pdf"]
        self.chapters_btn.setVisible(is_document)
        if is_document:
            chapter_count = len(self.window().selected_chapters)
            file_type = self.window().selected_file_type
            # Adjust button text based on file type
            if file_type == "epub":
                self.chapters_btn.setText(f"Chapters ({chapter_count})")
            else:  # PDF - always use Pages
                self.chapters_btn.setText(f"Pages ({chapter_count})")

        # Hide textbox and show edit only for .txt files
        self.textbox_btn.hide()
        # Show edit button for txt files directly
        # Or for epub/pdf files that have generated a temp txt file
        should_show_edit = file_path.lower().endswith(".txt")

        # For epub/pdf files, show edit if we have a selected_file (temp txt)
        if (
            self.window().selected_file_type in ["epub", "pdf"]
            and self.window().selected_file
        ):
            should_show_edit = True

        self.edit_btn.setVisible(should_show_edit)

    def set_error(self, message):
        self.setText(message)
        self.setStyleSheet(self.LABEL_CSS_ERROR)
        # Show textbox button in error state as well
        self.textbox_btn.show()

    def clear_input(self):
        self.window().selected_file = None
        self.window().displayed_file_path = (
            None  # Reset the displayed file path when clearing input
        )
        self.setText(
            "Drag and drop your file here or click to browse.\n(.txt, .epub, .pdf)"
        )
        self.setStyleSheet(self.LABEL_CSS)
        self.clear_btn.hide()
        self.chapters_btn.hide()
        self.chapters_btn.setText("Chapters")  # Reset text
        # Show textbox and hide edit when input is cleared
        self.textbox_btn.show()
        self.edit_btn.hide()

    def _human_readable_size(self, size, decimal_places=2):
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.{decimal_places}f} {unit}"
            size /= 1024.0
        return f"{size:.{decimal_places}f} PB"

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.window().open_file_dialog()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            ext = event.mimeData().urls()[0].toLocalFile().lower()
            if ext.endswith(".txt") or ext.endswith(".epub") or ext.endswith(".pdf"):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            file_path = event.mimeData().urls()[0].toLocalFile()
            win = self.window()
            if file_path.lower().endswith(".txt"):
                win.selected_file, win.selected_file_type = file_path, "txt"
                win.displayed_file_path = (
                    file_path  # Set the displayed file path for text files
                )
                self.set_file_info(file_path)
                event.acceptProposedAction()
            elif file_path.lower().endswith(".epub") or file_path.lower().endswith(
                ".pdf"
            ):
                # Just store the file path but don't set the file info yet
                win.selected_file_type = (
                    "epub" if file_path.lower().endswith(".epub") else "pdf"
                )
                win.selected_book_path = file_path
                win.open_book_file(
                    file_path  # This will handle the dialog and setting file info
                )
                event.acceptProposedAction()
            else:
                self.set_error("Please drop a .txt, .epub, or .pdf file.")
                event.ignore()
        else:
            event.ignore()

    def on_chapters_clicked(self):
        win = self.window()
        if win.selected_file_type in ["epub", "pdf"] and win.selected_book_path:
            # Call open_book_file which shows the dialog and updates selected_chapters
            if win.open_book_file(win.selected_book_path):
                # Refresh the info label and button text after dialog closes
                self.set_file_info(win.selected_book_path)

    def on_textbox_clicked(self):
        self.window().open_textbox_dialog()

    def on_edit_clicked(self):
        win = self.window()
        # For PDFs and EPUBs, use the temporary text file
        if win.selected_file_type in ["epub", "pdf"] and win.selected_file:
            # Use the temporary .txt file that was generated
            win.open_textbox_dialog(win.selected_file)
        else:
            # For regular txt files
            win.open_textbox_dialog()


class TextboxDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter Text")
        self.setWindowFlags(
            Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMaximizeButtonHint
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
        # If the text hasn't changed, treat as cancel
        if self.text_edit.toPlainText() == self.original_text:
            self.reject()
        else:
            # Check if we need to warn about overwriting a non-temporary file
            if hasattr(self, "is_non_temp_file") and self.is_non_temp_file:
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Warning)
                msg_box.setWindowTitle("File Overwrite Warning")
                msg_box.setText(
                    f"You are about to overwrite the original file:\n{self.non_temp_file_path}"
                )
                msg_box.setInformativeText("Do you want to continue?")
                msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                msg_box.setDefaultButton(QMessageBox.No)

                if msg_box.exec_() != QMessageBox.Yes:
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
            if hasattr(self, "non_temp_file_path") and self.non_temp_file_path:
                initial_path = self.non_temp_file_path

            # For EPUB and PDF files, use the displayed_file_path from the main window
            # This gives a better filename instead of the temporary file path
            main_window = self.parent()
            if (
                hasattr(main_window, "displayed_file_path")
                and main_window.displayed_file_path
            ):
                if main_window.selected_file_type in ["epub", "pdf"]:
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
        cursor.insertText("<<CHAPTER_MARKER:Title>>")
        self.text_edit.setTextCursor(cursor)
        self.update_char_count()


class abogen(QWidget):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.check_updates = self.config.get("check_updates", True)
        self.save_option = self.config.get("save_option", "Save next to input file")
        self.selected_output_folder = self.config.get("selected_output_folder", None)
        self.selected_file = self.selected_file_type = self.selected_book_path = None
        self.displayed_file_path = (
            None  # Add new variable to track the displayed file path
        )
        self.selected_chapters = set()
        self.last_opened_book_path = None  # Track the last opened book path
        self.last_output_path = None
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
        self.selected_format = self.config.get("selected_format", "wav")
        self.use_gpu = self.config.get(
            "use_gpu", True  # Load GPU setting with default True
        )
        self.replace_single_newlines = self.config.get("replace_single_newlines", False)
        self._pending_close_event = None
        self.gpu_ok = False  # Initialize GPU availability status

        # Create thread-safe logging mechanism
        self.log_signal = ThreadSafeLogSignal()
        self.log_signal.log_signal.connect(self._update_log_main_thread)

        # Set application icon
        icon_path = get_resource_path("abogen.assets", "icon.ico")
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))
            # Set taskbar icon for Windows
            if platform.system() == "Windows":
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("abogen")

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
                from voice_profiles import load_profiles

                entry = load_profiles().get(self.selected_profile_name, {})
                if isinstance(entry, dict):
                    self.mixed_voice_state = entry.get("voices", [])
                    self.selected_lang = entry.get("language")
                else:
                    self.mixed_voice_state = entry
                    self.selected_lang = entry[0][0] if entry and entry[0] else None
        if self.save_option == "Choose output folder" and self.selected_output_folder:
            self.save_path_label.setText(self.selected_output_folder)
            self.save_path_label.show()
        self.subtitle_combo.setCurrentText(self.subtitle_mode)
        # Enable/disable subtitle options based on selected language (profile or voice)
        enable = self.selected_lang in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION
        self.subtitle_combo.setEnabled(enable)
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

    def initUI(self):
        self.setWindowTitle(f"{PROGRAM_NAME} v{VERSION}")
        screen = QApplication.primaryScreen().geometry()
        width, height = 500, 800
        x, y = (screen.width() - width) // 2, (screen.height() - height) // 2
        self.setGeometry(x, y, width, height)
        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(15, 15, 15, 15)
        container = QWidget(self)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(15)
        self.input_box = InputBox(self)
        container_layout.addWidget(self.input_box, 1)
        self.log_text = QTextEdit(self)
        self.log_text.setReadOnly(True)
        self.log_text.setFrameStyle(QTextEdit.NoFrame)
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
        self.speed_slider = QSlider(Qt.Horizontal, self)
        self.speed_slider.setMinimum(10)
        self.speed_slider.setMaximum(200)
        self.speed_slider.setValue(100)
        self.speed_slider.setTickPosition(QSlider.TicksBelow)
        self.speed_slider.setTickInterval(5)
        self.speed_slider.setSingleStep(5)
        speed_layout.addWidget(self.speed_slider)
        self.speed_label = QLabel("1.0", self)
        speed_layout.addWidget(self.speed_label)
        controls_layout.addLayout(speed_layout)
        self.speed_slider.valueChanged.connect(self.update_speed_label)
        # Voice selection
        voice_layout = QVBoxLayout()
        voice_layout.setSpacing(7)
        voice_layout.addWidget(QLabel("Select Voice:", self))
        voice_row = QHBoxLayout()
        self.voice_combo = QComboBox(self)
        self.voice_combo.currentIndexChanged.connect(self.on_voice_combo_changed)
        self.voice_combo.setStyleSheet(
            "QComboBox { min-height: 20px; padding: 6px 12px; }"
        )
        self.voice_combo.setToolTip(
            "The first character represents the language:\n"
            '"a" => American English\n"b" => British English\n"e" => Spanish\n"f" => French\n"h" => Hindi\n"i" => Italian\n"j" => Japanese\n"p" => Brazilian Portuguese\n"z" => Mandarin Chinese\nThe second character represents the gender:\n"m" => Male\n"f" => Female'
        )
        voice_row.addWidget(self.voice_combo)

        # Voice formula button
        self.btn_voice_formula_mixer = QPushButton(self)
        mixer_icon_path = get_resource_path("abogen.assets", "voice_mixer.png")
        self.btn_voice_formula_mixer.setIcon(QIcon(mixer_icon_path))
        self.btn_voice_formula_mixer.setToolTip("Mix and match voices")
        self.btn_voice_formula_mixer.setFixedSize(40, 36)
        self.btn_voice_formula_mixer.setStyleSheet("QPushButton { padding: 6px 12px; }")
        self.btn_voice_formula_mixer.clicked.connect(self.show_voice_formula_dialog)
        voice_row.addWidget(self.btn_voice_formula_mixer)

        # Play/Stop icons
        def make_icon(color, shape):
            pix = QPixmap(20, 20)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(QColor(*color))
            p.setPen(Qt.NoPen)
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
        voice_row.addWidget(self.btn_preview)
        self.preview_playing = False
        voice_layout.addLayout(voice_row)
        controls_layout.addLayout(voice_layout)
        # Subtitle mode
        subtitle_layout = QVBoxLayout()
        subtitle_layout.addWidget(QLabel("Generate subtitles:", self))
        self.subtitle_combo = QComboBox(self)
        self.subtitle_combo.setToolTip(
            "Choose how subtitles will be generated:\n"
            "Disabled: No subtitles will be generated.\n"
            "Sentence: Subtitles will be generated for each sentence.\n"
            "Sentence + Comma: Subtitles will be generated for each sentence and comma.\n"
            "1+ word: Subtitles will be generated for each word(s).\n\n"
            "Supported languages for subtitle generation:\n"
            + "\n".join(
                f'"{lang}" => {LANGUAGE_DESCRIPTIONS.get(lang, lang)}'
                for lang in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION
            )
        )
        subtitle_options = ["Disabled", "Sentence", "Sentence + Comma"] + [
            f"{i} word" if i == 1 else f"{i} words" for i in range(1, 11)
        ]
        self.subtitle_combo.addItems(subtitle_options)
        self.subtitle_combo.setStyleSheet(
            "QComboBox { min-height: 20px; padding: 6px 12px; }"
        )
        self.subtitle_combo.setCurrentText(self.subtitle_mode)
        self.subtitle_combo.currentTextChanged.connect(self.on_subtitle_mode_changed)
        # Enable/disable subtitle options based on selected language (profile or voice)
        enable = self.selected_lang in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION
        self.subtitle_combo.setEnabled(enable)
        subtitle_layout.addWidget(self.subtitle_combo)
        controls_layout.addLayout(subtitle_layout)
        # Output format
        format_layout = QVBoxLayout()
        format_layout.addWidget(QLabel("Output Format:", self))
        self.format_combo = QComboBox(self)
        self.format_combo.setStyleSheet(
            "QComboBox { min-height: 20px; padding: 6px 12px; }"
        )
        # Add items with display labels and underlying keys
        for key, label in [
            ("wav", "wav"),
            ("flac", "flac"),
            ("mp3", "mp3"),
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
        # Save location
        save_layout = QVBoxLayout()
        save_layout.addWidget(QLabel("Save Location:", self))
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
        self.save_combo.setCurrentText(self.save_option)
        self.save_combo.currentTextChanged.connect(self.on_save_option_changed)
        save_layout.addWidget(self.save_combo)
        self.save_path_label = QLabel("", self)
        self.save_path_label.hide()
        save_layout.addWidget(self.save_path_label)
        controls_layout.addLayout(save_layout)
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

        # Settings button with icon
        settings_icon_path = get_resource_path("abogen.assets", "settings.png")
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
        self.controls_widget = QWidget()
        self.controls_widget.setLayout(controls_layout)
        self.controls_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        container_layout.addWidget(self.controls_widget)
        # Progress bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        container_layout.addWidget(self.progress_bar)
        # ETR Label
        self.etr_label = QLabel("Estimated time remaining: Calculating...", self)
        self.etr_label.setAlignment(Qt.AlignCenter)
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

    def open_file_dialog(self):
        if self.is_converting:
            return
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Select File", "", "Supported Files (*.txt *.epub *.pdf)"
            )
            if not file_path:
                return
            if file_path.lower().endswith(".epub") or file_path.lower().endswith(
                ".pdf"
            ):
                self.selected_file_type = (
                    "epub" if file_path.lower().endswith(".epub") else "pdf"
                )
                self.selected_book_path = file_path
                # Don't set file info immediately, open_book_file will handle it after dialog is accepted
                if not self.open_book_file(file_path):
                    return
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

        dialog = HandlerDialog(
            book_path, checked_chapters=self.selected_chapters, parent=self
        )
        dialog.setWindowModality(Qt.NonModal)
        dialog.setModal(False)
        dialog.show()

        # We'll handle the dialog result asynchronously
        def on_dialog_finished(result):
            if result != QDialog.Accepted:
                return False
            chapters_text, all_checked_hrefs = dialog.get_selected_text()
            if not all_checked_hrefs:
                file_type = "pdf" if book_path.lower().endswith(".pdf") else "epub"
                error_msg = (
                    f"No {'pages' if file_type == 'pdf' else 'chapters'} selected."
                )
                self._show_error_message_box(f"{file_type.upper()} Error", error_msg)
                return False
            self.selected_chapters = all_checked_hrefs
            self.save_chapters_separately = dialog.get_save_chapters_separately()
            self.merge_chapters_at_end = dialog.get_merge_chapters_at_end()

            # Store if the PDF has bookmarks for button text display
            if book_path.lower().endswith(".pdf"):
                self.pdf_has_bookmarks = getattr(dialog, "has_pdf_bookmarks", False)

            # Use "abogen" prefix for temporary files
            # Extract base name without extension
            base_name = os.path.splitext(os.path.basename(book_path))[0]
            temp_dir = os.path.join(tempfile.gettempdir(), PROGRAM_NAME)
            os.makedirs(temp_dir, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                prefix=f"abogen_{base_name}_", suffix=".txt", dir=temp_dir
            )
            os.close(fd)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(chapters_text)
            self.selected_file = tmp
            self.selected_book_path = book_path
            self.displayed_file_path = book_path
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
        is_temp_file = False
        # If path is explicitly provided, use it
        if file_path and os.path.exists(file_path):
            editing = True
            edit_file = file_path
            # Check if this is a temporary file
            is_temp_file = tempfile.gettempdir() in file_path
        # Otherwise use selected_file if it's a txt file
        elif (
            self.selected_file_type == "txt"
            and self.selected_file
            and os.path.exists(self.selected_file)
        ):
            editing = True
            edit_file = self.selected_file
            # Check if this is a temporary file
            is_temp_file = tempfile.gettempdir() in self.selected_file

        dialog = TextboxDialog(self)
        if editing:
            try:
                with open(edit_file, "r", encoding="utf-8", errors="ignore") as f:
                    dialog.text_edit.setText(f.read())
                dialog.update_char_count()
                dialog.original_text = (
                    dialog.text_edit.toPlainText()
                )  # Store original text

                # If editing a non-temporary file, alert the user
                if not is_temp_file:
                    dialog.is_non_temp_file = True
                    dialog.non_temp_file_path = edit_file
            except Exception:
                pass
        if dialog.exec_() == QDialog.Accepted:
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
                    temp_dir = os.path.join(tempfile.gettempdir(), PROGRAM_NAME)
                    os.makedirs(temp_dir, exist_ok=True)
                    fd, tmp = tempfile.mkstemp(
                        prefix="abogen_", suffix=".txt", dir=temp_dir
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

    def on_voice_changed(self, index):
        voice = self.voice_combo.itemData(index)
        self.selected_voice, self.selected_lang = voice, voice[0]
        self.config["selected_voice"] = voice
        save_config(self.config)
        # Enable/disable subtitle options based on language
        if self.selected_lang in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION:
            self.subtitle_combo.setEnabled(True)
            self.subtitle_mode = self.subtitle_combo.currentText()
        else:
            self.subtitle_combo.setEnabled(False)

    def on_voice_combo_changed(self, index):
        data = self.voice_combo.itemData(index)
        if isinstance(data, str) and data.startswith("profile:"):
            pname = data.split(":", 1)[1]
            self.selected_profile_name = pname
            from voice_profiles import load_profiles

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
            self.subtitle_combo.setEnabled(
                self.selected_lang in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION
            )
        else:
            self.mixed_voice_state = None
            self.selected_profile_name = None
            self.selected_voice, self.selected_lang = data, data[0]
            self.config["selected_voice"] = data
            if "selected_profile_name" in self.config:
                del self.config["selected_profile_name"]
            save_config(self.config)
            if self.selected_lang in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION:
                self.subtitle_combo.setEnabled(True)
                self.subtitle_mode = self.subtitle_combo.currentText()
            else:
                self.subtitle_combo.setEnabled(False)

    def update_subtitle_combo_for_profile(self, profile_name):
        from voice_profiles import load_profiles

        entry = load_profiles().get(profile_name, {})
        lang = entry.get("language") if isinstance(entry, dict) else None
        enable = lang in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION
        self.subtitle_combo.setEnabled(enable)

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

    def color_text(self, message, color):
        return f'<span style="color:{color};">{message.replace(chr(10), "<br>")}</span><br>'

    def update_log(self, message):
        # Use signal-based approach for thread-safe logging
        if QThread.currentThread() != QApplication.instance().thread():
            # We're in a background thread, emit signal for the main thread
            self.log_signal.emit_log(message)
            return

        # Direct update if already on main thread
        self._update_log_main_thread(message)

    def _update_log_main_thread(self, message):
        sb = self.log_text.verticalScrollBar()
        prev_val = sb.value()
        at_bottom = prev_val == sb.maximum()
        # save current text cursor to preserve selection
        old_cursor = self.log_text.textCursor()
        # prepare html
        if isinstance(message, tuple):
            text, spec = message
            color = "green" if spec is True else ("red" if spec is False else spec)
            html = self.color_text(text, color)
        else:
            html = str(message).replace("\n", "<br>") + "<br>"
        # move cursor to end for insertion
        insert_cursor = self.log_text.textCursor()
        insert_cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(insert_cursor)
        self.log_text.insertHtml(html)
        # restore original cursor/selection
        self.log_text.setTextCursor(old_cursor)
        # restore scroll position
        sb.setValue(sb.maximum() if at_bottom else prev_val)
        QApplication.processEvents()

    def update_progress(self, value, etr_str):  # Add etr_str parameter
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat("%p%")  # Keep format as percentage only
        self.etr_label.setText(
            f"Estimated time remaining: {etr_str}"
        )  # Update ETR label
        self.etr_label.show()  # Show only when estimate is ready
        self.progress_bar.repaint()
        QApplication.processEvents()

    def start_conversion(self):
        if not self.selected_file:
            self.input_box.set_error("Please add a file.")
            return
        prevent_sleep_start()
        self.is_converting = True
        self.convert_input_box_to_log()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")  # Reset format initially
        self.etr_label.hide()  # Hide ETR label initially
        self.controls_widget.hide()
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
                self.update_log((f"Error loading numpy or KPipeline: {error}", False))
                prevent_sleep_end()
                return

            self.btn_cancel.setEnabled(True)

            # Override subtitle_mode to "Disabled" if subtitle_combo is disabled
            actual_subtitle_mode = (
                "Disabled"
                if not self.subtitle_combo.isEnabled()
                else self.subtitle_mode
            )

            # if voice formula is not None, use the selected voice
            if self.mixed_voice_state:
                formula_components = [
                    f"{name}*{weight}" for name, weight in self.mixed_voice_state
                ]
                voice_formula = " + ".join(filter(None, formula_components))
            else:
                voice_formula = self.selected_voice
            # determine selected language: use profile setting if profile selected, else voice code
            if self.selected_profile_name:
                from voice_profiles import load_profiles

                entry = load_profiles().get(self.selected_profile_name, {})
                selected_lang = entry.get("language")
            else:
                selected_lang = self.selected_voice[0] if self.selected_voice else None
            # fallback: extract from formula if missing
            if not selected_lang:
                m = re.search(r"\b([a-z])", voice_formula)
                selected_lang = m.group(1) if m else None

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
            )  # Use gpu_ok status
            # Pass the displayed file path to the log_updated signal handler in ConversionThread
            self.conversion_thread.display_path = display_path
            # Pass the file size string
            self.conversion_thread.file_size_str = file_size_str
            # Pass max_subtitle_words from config
            self.conversion_thread.max_subtitle_words = self.max_subtitle_words
            # Pass replace_single_newlines setting
            self.conversion_thread.replace_single_newlines = (
                self.replace_single_newlines
            )
            # Pass chapter count for EPUB or PDF files
            if self.selected_file_type in ["epub", "pdf"] and hasattr(
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

        Thread(target=gpu_and_load, daemon=True).start()

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
            # Check if the file exists before trying to set file info
            if display_path and os.path.exists(display_path):
                self.input_box.set_file_info(display_path)
            else:
                # Clear the input if the file no longer exists
                self.input_box.clear_input()
            return

        self.update_log(message)
        if output_path:
            self.last_output_path = output_path
        self.etr_label.hide()  # Hide ETR label
        self.progress_bar.setValue(100)
        self.progress_bar.hide()
        self.btn_cancel.hide()
        self.is_converting = False
        elapsed = int(time.time() - self.start_time)
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        self.update_log(f"\nTime elapsed: {h:02d}:{m:02d}:{s:02d}")

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

        self.controls_widget.hide()
        self.finish_widget.show()
        self.log_text.moveCursor(QTextCursor.End)
        self.log_text.ensureCursorVisible()
        save_config(self.config)

    def reset_ui(self):
        try:
            self.restore_input_box()
            self.input_box.clear_input()  # Reset text and style
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
            self.finish_widget.hide()
            self.btn_start.setText("Start")
            # Disconnect only if connected, then reconnect
            try:
                self.btn_start.clicked.disconnect()
            except TypeError:
                pass  # Ignore error if not connected
            self.btn_start.clicked.connect(self.start_conversion)
        except Exception as e:
            self._show_error_message_box("Reset Error", f"Could not reset UI:\n{e}")

    def go_back_ui(self):
        self.finish_widget.hide()
        self.controls_widget.show()
        self.progress_bar.hide()
        self.restore_input_box()

        # Use displayed_file_path instead of selected_file for EPUBs or PDFs
        display_path = (
            self.displayed_file_path if self.displayed_file_path else self.selected_file
        )

        # Check if the file exists before trying to set file info
        if display_path and os.path.exists(display_path):
            self.input_box.set_file_info(display_path)
        else:
            # Clear the input if the file no longer exists
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
                    self.save_path_label.show()
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
            self.save_path_label.hide()
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

    def preview_voice(self):
        if self.preview_playing:
            try:
                import pygame

                pygame.mixer.music.stop()
            except Exception:
                pass
            self._preview_cleanup()
            return

        if hasattr(self, "preview_thread") and self.preview_thread.isRunning():
            return

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
                from voice_profiles import load_profiles

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

    def _play_preview_audio(self):
        temp_wav = self.preview_thread.temp_wav
        if not temp_wav:
            self.loading_movie.stop()

            self._show_error_message_box(
                "Preview Error", "Preview error: No audio generated."
            )
            self.btn_preview.setIcon(self.play_icon)
            self.btn_preview.setToolTip("Preview selected voice")
            self.btn_preview.setEnabled(True)
            self.voice_combo.setEnabled(True)
            self.btn_voice_formula_mixer.setEnabled(True)  # Re-enable mixer button
            self.btn_start.setEnabled(True)
            return
        # stop loading animation, switch to stop icon
        self.loading_movie.stop()
        self.preview_playing = True
        self.btn_preview.setIcon(self.stop_icon)
        self.btn_preview.setToolTip("Stop preview")
        self.btn_preview.setEnabled(True)

        def cleanup():
            try:
                os.remove(temp_wav)
            except Exception:
                pass
            self._preview_cleanup()

        try:
            self.audio_thread = PlayAudioThread(temp_wav)
            self.audio_thread.finished.connect(cleanup)
            self.audio_thread.error.connect(
                lambda msg: (self._show_preview_error_box(msg), cleanup())
            )
            self.audio_thread.start()
        except Exception as e:
            self._show_error_message_box(
                "Preview Error", f"Could not play preview audio:\n{e}"
            )
            cleanup()

    def _show_error_message_box(self, title, message):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle(title)
        box.setText(message)
        copy_btn = QPushButton("Copy")
        box.addButton(copy_btn, QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(message))
        box.exec_()

    def _show_preview_error_box(self, msg):
        self._show_error_message_box("Preview Error", f"Preview error: {msg}")

    def _preview_cleanup(self):
        self.preview_playing = False
        self.loading_movie.stop()
        try:
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
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Cancel Conversion")
            box.setText(
                "A conversion is currently running. Are you sure you want to cancel?"
            )
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.setDefaultButton(QMessageBox.No)
            if box.exec_() != QMessageBox.Yes:
                return
        try:
            if (
                hasattr(self, "conversion_thread")
                and self.conversion_thread.isRunning()
            ):
                self.conversion_thread.cancel()
            self.is_converting = False
            self.etr_label.hide()  # Hide ETR label
            self.progress_bar.hide()
            self.btn_cancel.hide()
            self.controls_widget.show()
            self.finish_widget.hide()
            self.restore_input_box()
            display_path = (
                self.displayed_file_path
                if self.displayed_file_path
                else self.selected_file
            )
            # Check if the file exists before trying to set file info
            if display_path and os.path.exists(display_path):
                self.input_box.set_file_info(display_path)
            else:
                # Clear the input if the file no longer exists
                self.input_box.clear_input()
            if (
                hasattr(self, "conversion_thread")
                and self.conversion_thread.isRunning()
            ):
                self.conversion_thread.wait()
            prevent_sleep_end()
        except Exception as e:
            self._show_error_message_box(
                "Cancel Error", f"Could not cancel conversion:\n{e}"
            )

    def on_subtitle_mode_changed(self, mode):
        self.subtitle_mode = mode
        self.config["subtitle_mode"] = mode
        save_config(self.config)

    def on_format_changed(self, fmt):
        self.selected_format = fmt
        self.config["selected_format"] = fmt
        save_config(self.config)

    def on_gpu_setting_changed(self, state):
        self.use_gpu = state == Qt.Checked
        self.config["use_gpu"] = self.use_gpu
        save_config(self.config)

    def closeEvent(self, event):
        if self.is_converting:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Conversion in Progress")
            box.setText(
                "A conversion is currently running. Are you sure you want to exit?"
            )
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.setDefaultButton(QMessageBox.No)
            if box.exec_() == QMessageBox.Yes:
                if (
                    hasattr(self, "conversion_thread")
                    and self.conversion_thread.isRunning()
                ):
                    self.conversion_thread.cancel()
                    self.conversion_thread.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def show_chapter_options_dialog(self, chapter_count):
        """Show dialog to ask user about chapter processing options when chapters are detected in a .txt file"""
        from conversion import ChapterOptionsDialog

        dialog = ChapterOptionsDialog(chapter_count, parent=self)
        dialog.setWindowModality(Qt.ApplicationModal)

        # If dialog is accepted, pass the options to the conversion thread
        if dialog.exec_() == QDialog.Accepted:
            options = dialog.get_options()
            if (
                hasattr(self, "conversion_thread")
                and self.conversion_thread.isRunning()
            ):
                self.conversion_thread.set_chapter_options(options)
        else:
            # If dialog is rejected, cancel the conversion
            self.cancel_conversion()

    def show_settings_menu(self):
        """Show a dropdown menu for settings options."""
        menu = QMenu(self)

        # Add replace single newlines option
        newline_action = QAction("Replace single newlines with spaces", self)
        newline_action.setCheckable(True)
        newline_action.setChecked(self.replace_single_newlines)
        newline_action.triggered.connect(self.toggle_replace_single_newlines)
        menu.addAction(newline_action)

        # Add max words per subtitle option
        max_words_action = QAction("Configure max words per subtitle", self)
        max_words_action.triggered.connect(self.set_max_subtitle_words)
        menu.addAction(max_words_action)

        # Add seperator
        menu.addSeparator()

        # Add shortcut to desktop (Windows only)
        if platform.system() == "Windows":
            add_shortcut_action = QAction("Create desktop shortcut", self)
            add_shortcut_action.triggered.connect(self.add_shortcut_to_desktop)
            menu.addAction(add_shortcut_action)

        # Add reveal config option
        reveal_config_action = QAction("Open configuration directory", self)
        reveal_config_action.triggered.connect(self.reveal_config_in_explorer)
        menu.addAction(reveal_config_action)

        # Add open temp directory option
        open_temp_action = QAction("Open temp directory", self)
        open_temp_action.triggered.connect(self.open_temp_directory)
        menu.addAction(open_temp_action)

        # Add clear temporary files option
        clear_temp_action = QAction("Clear all temporary files", self)
        clear_temp_action.triggered.connect(self.clear_temp_files)
        menu.addAction(clear_temp_action)

        # Add seperator"
        menu.addSeparator()

        # Add check for updates option
        check_updates_action = QAction("Check for updates at startup", self)
        check_updates_action.setCheckable(True)
        check_updates_action.setChecked(self.config.get("check_updates", True))
        check_updates_action.triggered.connect(self.toggle_check_updates)
        menu.addAction(check_updates_action)

        # Add about action
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about_dialog)
        menu.addAction(about_action)

        menu.exec_(self.settings_btn.mapToGlobal(QPoint(0, self.settings_btn.height())))

    def toggle_replace_single_newlines(self, checked):
        self.replace_single_newlines = checked
        self.config["replace_single_newlines"] = checked
        save_config(self.config)

    def reveal_config_in_explorer(self):
        """Open the configuration file location in file explorer."""
        from utils import get_user_config_path

        try:
            config_path = get_user_config_path()
            # Open the directory containing the config file
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(config_path)))
        except Exception as e:
            QMessageBox.critical(
                self, "Config Error", f"Could not open config location:\n{e}"
            )

    def open_temp_directory(self):
        """Open the temporary directory used by the program."""
        try:
            # Get the temp directory path
            temp_dir = os.path.join(tempfile.gettempdir(), PROGRAM_NAME)

            # Create the directory if it doesn't exist
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)

            # Open the directory in file explorer
            QDesktopServices.openUrl(QUrl.fromLocalFile(temp_dir))
        except Exception as e:
            QMessageBox.critical(
                self, "Temp Directory Error", f"Could not open temp directory:\n{e}"
            )

    def add_shortcut_to_desktop(self):
        """Create a desktop shortcut to this program using PowerShell."""
        import sys, subprocess
        from PyQt5.QtWidgets import QMessageBox

        try:
            # where to put the .lnk
            desktop = user_desktop_dir()
            shortcut_path = os.path.join(desktop, "abogen.lnk")

            # target exe
            python_dir = os.path.dirname(sys.executable)
            target = os.path.join(python_dir, "Scripts", "abogen.exe")
            if not os.path.exists(target):
                QMessageBox.critical(
                    self, "Shortcut Error", f"Could not find abogen.exe at:\n{target}"
                )
                return

            # icon (fallback to exe if missing)
            icon = get_resource_path("abogen.assets", "icon.ico")
            if not icon or not os.path.exists(icon):
                icon = target

            # PowerShell command to make the shortcut
            ps_cmd = r"""
                    $s = New-Object -ComObject WScript.Shell
                    $lnk = $s.CreateShortcut('{lnk}')
                    $lnk.TargetPath = '{tgt}'
                    $lnk.WorkingDirectory = '{cwd}'
                    $lnk.IconLocation = '{ico}'
                    $lnk.Save()
                    """.format(
                lnk=shortcut_path.replace("'", "''"),
                tgt=target.replace("'", "''"),
                cwd=os.path.dirname(target).replace("'", "''"),
                ico=icon.replace("'", "''"),
            ).strip()

            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            QMessageBox.information(
                self,
                "Shortcut Created",
                f"Shortcut created on desktop:\n{shortcut_path}",
            )

        except subprocess.CalledProcessError as e:
            QMessageBox.critical(
                self,
                "Shortcut Error",
                f"PowerShell failed:\n{e.stderr.decode(errors='ignore')}",
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Shortcut Error", f"Could not create shortcut:\n{e}"
            )

    def toggle_check_updates(self, checked):
        self.config["check_updates"] = checked
        save_config(self.config)

    def show_voice_formula_dialog(self):
        from voice_profiles import load_profiles

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
            else:
                initial_state = []
        else:
            initial_state = []
        dialog = VoiceFormulaDialog(
            self, initial_state=initial_state, selected_profile=selected_profile
        )
        if dialog.exec_() == QDialog.Accepted:
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

    def show_about_dialog(self):
        """Show an About dialog with program information including GitHub link."""
        # Get application icon for dialog
        icon = self.windowIcon()

        # Create custom dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(f"About {PROGRAM_NAME}")
        dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
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
        title_label.setTextFormat(Qt.RichText)
        header_layout.addWidget(title_label, 1)
        layout.addLayout(header_layout)

        # Description
        desc_label = QLabel(
            f"<p>{PROGRAM_DESCRIPTION}</p>"
            "<p>Visit the GitHub repository for updates, documentation, and to report issues.</p>"
        )
        desc_label.setTextFormat(Qt.RichText)
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

        dialog.exec_()

    def manual_check_for_updates(self):
        """Manually check for updates and always show result"""
        # Set a flag to always show the result message
        self._show_update_check_result = True
        self.check_for_updates_startup()

    def check_for_updates_startup(self):
        import urllib.request

        def show_update_message(remote_version, local_version):
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Information)
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
            msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg_box.setDefaultButton(QMessageBox.Yes)
            if msg_box.exec_() == QMessageBox.Yes:
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

    def clear_temp_files(self):
        """Clear all temporary files created by the program."""
        import glob

        try:
            # Get the abogen temp directory
            temp_dir = os.path.join(tempfile.gettempdir(), PROGRAM_NAME)

            # Find all .txt files in the abogen temp directory
            pattern = os.path.join(temp_dir, "*.txt")
            temp_files = glob.glob(pattern)

            # Count the files
            file_count = len(temp_files)

            if file_count == 0:
                QMessageBox.information(
                    self, "No Temporary Files", "No temporary files were found."
                )
                return

            # Confirm with the user
            confirm = QMessageBox.question(
                self,
                "Clear Temporary Files",
                f"Found {file_count} temporary file{'s' if file_count != 1 else ''} in the {PROGRAM_NAME} temp folder.\n"
                "Do you want to delete them?",
                QMessageBox.Yes | QMessageBox.No,
            )

            if confirm != QMessageBox.Yes:
                return

            # Delete the files
            deleted_count = 0
            for file_path in temp_files:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    print(f"Error deleting {file_path}: {e}")

            # Show results
            QMessageBox.information(
                self,
                "Temporary Files Cleared",
                f"Successfully deleted {deleted_count} temporary file{'s' if deleted_count != 1 else ''}.",
            )

            # If currently selected file is in the temp directory, clear the UI
            if (
                self.selected_file
                and os.path.dirname(self.selected_file) == temp_dir
                and self.selected_file.endswith(".txt")
            ):
                self.input_box.clear_input()

        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"An error occurred while clearing temporary files:\n{e}"
            )

    def set_max_subtitle_words(self):
        """Open a dialog to set the maximum words per subtitle"""
        from PyQt5.QtWidgets import QInputDialog

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
