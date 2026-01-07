# a simple window with a list of items in the queue, no checkboxes
# button to remove an item from the queue
# button to clear the queue

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QDialogButtonBox,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QFileIconProvider,
    QLabel,
    QWidget,
    QSizePolicy,
    QAbstractItemView,
    QCheckBox,
)
from PyQt6.QtCore import QFileInfo, Qt
from abogen.constants import COLORS
from copy import deepcopy
from PyQt6.QtGui import QFontMetrics
from abogen.utils import load_config, save_config

# Define attributes that are safe to override with global settings
OVERRIDE_FIELDS = [
    "lang_code",
    "speed",
    "voice",
    "save_option",
    "output_folder",
    "subtitle_mode",
    "output_format",
    "replace_single_newlines",
    "use_silent_gaps",
    "subtitle_speed_method",
]


class ElidedLabel(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setTextFormat(Qt.TextFormat.PlainText)

    def setText(self, text):
        self._full_text = text
        super().setText(text)
        self.update()

    def resizeEvent(self, event):
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, self.width()
        )
        super().setText(elided)
        super().resizeEvent(event)

    def fullText(self):
        return self._full_text


class QueueListItemWidget(QWidget):
    def __init__(self, file_name, char_count):
        super().__init__()
        layout = QHBoxLayout()
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(0)
        import os

        name_label = ElidedLabel(os.path.basename(file_name))
        char_label = QLabel(f"Chars: {char_count}")
        char_label.setStyleSheet(f"color: {COLORS['LIGHT_DISABLED']};")
        char_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        char_label.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(name_label, 1)
        layout.addWidget(char_label, 0)
        self.setLayout(layout)


class DroppableQueueListWidget(QListWidget):
    def __init__(self, parent_dialog):
        super().__init__()
        self.parent_dialog = parent_dialog
        self.setAcceptDrops(True)
        # Overlay for drag hover
        self.drag_overlay = QLabel("", self)
        self.drag_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drag_overlay.setStyleSheet(
            f"border:2px dashed {COLORS['BLUE_BORDER_HOVER']}; border-radius:5px; padding:20px; background:{COLORS['BLUE_BG_HOVER']};"
        )
        self.drag_overlay.setVisible(False)
        self.drag_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile().lower()
                if url.isLocalFile() and (
                    file_path.endswith(".txt")
                    or file_path.endswith((".srt", ".ass", ".vtt"))
                ):
                    self.drag_overlay.resize(self.size())
                    self.drag_overlay.setVisible(True)
                    event.acceptProposedAction()
                    return
        self.drag_overlay.setVisible(False)
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile().lower()
                if url.isLocalFile() and (
                    file_path.endswith(".txt")
                    or file_path.endswith((".srt", ".ass", ".vtt"))
                ):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.drag_overlay.setVisible(False)
        event.accept()

    def dropEvent(self, event):
        self.drag_overlay.setVisible(False)
        if event.mimeData().hasUrls():
            file_paths = [
                url.toLocalFile()
                for url in event.mimeData().urls()
                if url.isLocalFile()
                and (
                    url.toLocalFile().lower().endswith(".txt")
                    or url.toLocalFile().lower().endswith((".srt", ".ass", ".vtt"))
                )
            ]
            if file_paths:
                self.parent_dialog.add_files_from_paths(file_paths)
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "drag_overlay"):
            self.drag_overlay.resize(self.size())


class QueueManager(QDialog):
    def __init__(self, parent, queue: list, title="Queue Manager", size=(600, 700)):
        super().__init__()
        self.queue = queue
        self._original_queue = deepcopy(
            queue
        )  # Store a deep copy of the original queue
        self.parent = parent
        self.config = load_config()  # Load config for persistence

        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)  # set main layout margins
        layout.setSpacing(12)  # set spacing between widgets in main layout
        # list of queued items
        self.listwidget = DroppableQueueListWidget(self)
        self.listwidget.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.listwidget.setAlternatingRowColors(True)
        self.listwidget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.listwidget.customContextMenuRequested.connect(self.show_context_menu)
        # Add informative instructions at the top
        instructions = QLabel(
            "<h2>How Queue Works?</h2>"
            "You can add text and subtitle files (.txt, .srt, .ass, .vtt) directly using the '<b>Add files</b>' button below. "
            "To add PDF, EPUB or markdown files, use the input box in the main window and click the <b>'Add to Queue'</b> button. "
            "By default, each file in the queue keeps the configuration settings active when they were added. "
            "Enabling the <b>'Override item settings with current selection'</b> option below will force all items to use the configuration currently selected in the main window. "
            "You can view each file's configuration by hovering over them."
        )
        instructions.setAlignment(Qt.AlignmentFlag.AlignLeft)
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        # Override Checkbox
        self.override_chk = QCheckBox("Override item settings with current selection")
        self.override_chk.setToolTip(
            "If checked, all items in the queue will be processed using the \n"
            "settings currently selected in the main window, ignoring their saved state."
        )
        # Load saved state (default to False)
        self.override_chk.setChecked(self.config.get("queue_override_settings", False))
        # Trigger process_queue to update tooltips immediately when toggled
        self.override_chk.stateChanged.connect(self.process_queue)
        self.override_chk.setStyleSheet("margin-bottom: 8px;")
        layout.addWidget(self.override_chk)

        # Overlay label for empty queue
        self.empty_overlay = QLabel(
            "Drag and drop your text or subtitle files here or use the 'Add files' button.",
            self.listwidget,
        )
        self.empty_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_overlay.setStyleSheet(
            f"color: {COLORS['LIGHT_DISABLED']}; background: transparent; padding: 20px;"
        )
        self.empty_overlay.setWordWrap(True)
        self.empty_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.empty_overlay.hide()
        # add queue items to the list
        self.process_queue()

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)  # optional: no margins for button row
        button_row.setSpacing(7)  # set spacing between buttons
        # Add files button
        add_files_button = QPushButton("Add files")
        add_files_button.setFixedHeight(40)
        add_files_button.clicked.connect(self.add_more_files)
        button_row.addWidget(add_files_button)

        # Remove button
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.setFixedHeight(40)
        self.remove_button.clicked.connect(self.remove_item)
        button_row.addWidget(self.remove_button)

        # Clear button
        self.clear_button = QPushButton("Clear Queue")
        self.clear_button.setFixedHeight(40)
        self.clear_button.clicked.connect(self.clear_queue)
        button_row.addWidget(self.clear_button)

        layout.addLayout(button_row)
        layout.addWidget(self.listwidget)

        # Connect selection change to update button state
        self.listwidget.currentItemChanged.connect(self.update_button_states)
        self.listwidget.itemSelectionChanged.connect(self.update_button_states)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(buttons)

        self.setLayout(layout)

        self.setWindowTitle(title)
        self.resize(*size)

        self.update_button_states()

    def process_queue(self):
        """Process the queue items."""
        import os

        self.listwidget.clear()
        if not self.queue:
            self.empty_overlay.show()
            self.update_button_states()
            return
        else:
            self.empty_overlay.hide()

        # Get current global settings and checkbox state for overrides
        current_global_settings = self.get_current_attributes()
        is_override_active = self.override_chk.isChecked()

        icon_provider = QFileIconProvider()
        for item in self.queue:
            # Dynamic Attribute Retrieval Helper
            def get_val(attr, default=""):
                # If override is ON and attr is overrideable, use global setting
                if is_override_active and attr in OVERRIDE_FIELDS:
                    return current_global_settings.get(attr, default)
                # Otherwise return the item's saved attribute
                return getattr(item, attr, default)

            # Determine display file path (prefer save_base_path for original file)
            display_file_path = getattr(item, "save_base_path", None) or item.file_name
            processing_file_path = item.file_name

            # Normalize paths for consistent display (fixes Windows path separator issues)
            display_file_path = (
                os.path.normpath(display_file_path)
                if display_file_path
                else display_file_path
            )
            processing_file_path = (
                os.path.normpath(processing_file_path)
                if processing_file_path
                else processing_file_path
            )

            # Only show the file name, not the full path
            display_name = display_file_path

            if os.path.sep in display_file_path:
                display_name = os.path.basename(display_file_path)
            # Get icon for the display file
            icon = icon_provider.icon(QFileInfo(display_file_path))
            list_item = QListWidgetItem()

            # Tooltip Generation
            tooltip = ""
            # If override is active, add the warning header on its own line
            if is_override_active:
                tooltip += "<b style='color: #ff9900;'>(Global Override Active)</b><br>"

            output_folder = get_val("output_folder")
            # For plain .txt inputs we don't need to show a separate processing file
            show_processing = True
            try:
                if isinstance(
                    display_file_path, str
                ) and display_file_path.lower().endswith(".txt"):
                    show_processing = False
            except Exception:
                show_processing = True

            tooltip += f"<b>Input File:</b> {display_file_path}<br>"
            if (
                show_processing
                and processing_file_path
                and processing_file_path != display_file_path
            ):
                tooltip += f"<b>Processing File:</b> {processing_file_path}<br>"

            tooltip += (
                f"<b>Language:</b> {get_val('lang_code')}<br>"
                f"<b>Speed:</b> {get_val('speed')}<br>"
                f"<b>Voice:</b> {get_val('voice')}<br>"
                f"<b>Save Option:</b> {get_val('save_option')}<br>"
            )
            if output_folder not in (None, "", "None"):
                tooltip += f"<b>Output Folder:</b> {output_folder}<br>"
            tooltip += (
                f"<b>Subtitle Mode:</b> {get_val('subtitle_mode')}<br>"
                f"<b>Output Format:</b> {get_val('output_format')}<br>"
                f"<b>Characters:</b> {getattr(item, 'total_char_count', '')}<br>"
                f"<b>Replace Single Newlines:</b> {get_val('replace_single_newlines', True)}<br>"
                f"<b>Use Silent Gaps:</b> {get_val('use_silent_gaps', False)}<br>"
                f"<b>Speed Method:</b> {get_val('subtitle_speed_method', 'tts')}"
            )
            # Add book handler options if present (Preserve logic: specific to file structure)
            save_chapters_separately = getattr(item, "save_chapters_separately", None)
            merge_chapters_at_end = getattr(item, "merge_chapters_at_end", None)
            if save_chapters_separately is not None:
                tooltip += f"<br><b>Save chapters separately:</b> {'Yes' if save_chapters_separately else 'No'}"
                # Only show merge option if saving chapters separately
                if save_chapters_separately and merge_chapters_at_end is not None:
                    tooltip += f"<br><b>Merge chapters at the end:</b> {'Yes' if merge_chapters_at_end else 'No'}"
            list_item.setToolTip(tooltip)
            list_item.setIcon(icon)
            # Store both paths for context menu
            list_item.setData(
                Qt.ItemDataRole.UserRole,
                {
                    "display_path": display_file_path,
                    "processing_path": processing_file_path,
                },
            )
            # Use custom widget for display
            char_count = getattr(item, "total_char_count", 0)
            widget = QueueListItemWidget(display_file_path, char_count)
            self.listwidget.addItem(list_item)
            self.listwidget.setItemWidget(list_item, widget)
        self.update_button_states()

    def remove_item(self):
        items = self.listwidget.selectedItems()
        if not items:
            return
        from PyQt6.QtWidgets import QMessageBox

        # Remove by index to ensure correct mapping
        rows = sorted([self.listwidget.row(item) for item in items], reverse=True)
        # Warn user if removing multiple files
        if len(rows) > 1:
            reply = QMessageBox.question(
                self,
                "Confirm Remove",
                f"Are you sure you want to remove {len(rows)} selected items from the queue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        for row in rows:
            if 0 <= row < len(self.queue):
                del self.queue[row]
        self.process_queue()
        self.update_button_states()

    def clear_queue(self):
        from PyQt6.QtWidgets import QMessageBox

        if len(self.queue) > 1:
            reply = QMessageBox.question(
                self,
                "Confirm Clear Queue",
                f"Are you sure you want to clear {len(self.queue)} items from the queue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.queue.clear()
        self.listwidget.clear()
        self.empty_overlay.resize(
            self.listwidget.size()
        )  # Ensure overlay is sized correctly
        self.empty_overlay.show()  # Show the overlay when queue is empty
        self.update_button_states()

    def get_queue(self):
        return self.queue

    def get_current_attributes(self):
        # Fetch current attribute values from the parent abogen GUI
        attrs = {}
        parent = self.parent
        if parent is not None:
            # lang_code: use parent's get_voice_formula and get_selected_lang
            if hasattr(parent, "get_voice_formula") and hasattr(
                parent, "get_selected_lang"
            ):
                voice_formula = parent.get_voice_formula()
                attrs["lang_code"] = parent.get_selected_lang(voice_formula)
                attrs["voice"] = voice_formula
            else:
                attrs["lang_code"] = getattr(parent, "selected_lang", "")
                attrs["voice"] = getattr(parent, "selected_voice", "")
            # speed
            if hasattr(parent, "speed_slider"):
                attrs["speed"] = parent.speed_slider.value() / 100.0
            else:
                attrs["speed"] = getattr(parent, "speed", 1.0)
            # save_option
            attrs["save_option"] = getattr(parent, "save_option", "")
            # output_folder
            attrs["output_folder"] = getattr(parent, "selected_output_folder", "")
            # subtitle_mode
            if hasattr(parent, "get_actual_subtitle_mode"):
                attrs["subtitle_mode"] = parent.get_actual_subtitle_mode()
            else:
                attrs["subtitle_mode"] = getattr(parent, "subtitle_mode", "")
            # output_format
            attrs["output_format"] = getattr(parent, "selected_format", "")
            # total_char_count
            attrs["total_char_count"] = getattr(parent, "char_count", "")
            # replace_single_newlines
            attrs["replace_single_newlines"] = getattr(
                parent, "replace_single_newlines", True
            )
            # use_silent_gaps
            attrs["use_silent_gaps"] = getattr(parent, "use_silent_gaps", False)
            # subtitle_speed_method
            attrs["subtitle_speed_method"] = getattr(
                parent, "subtitle_speed_method", "tts"
            )
            # book handler options
            attrs["save_chapters_separately"] = getattr(
                parent, "save_chapters_separately", None
            )
            attrs["merge_chapters_at_end"] = getattr(
                parent, "merge_chapters_at_end", None
            )
        else:
            # fallback: empty values
            attrs = {
                k: ""
                for k in [
                    "lang_code",
                    "speed",
                    "voice",
                    "save_option",
                    "output_folder",
                    "subtitle_mode",
                    "output_format",
                    "total_char_count",
                    "replace_single_newlines",
                ]
            }
            attrs["save_chapters_separately"] = None
            attrs["merge_chapters_at_end"] = None
        return attrs

    def add_files_from_paths(self, file_paths):
        from abogen.subtitle_utils import calculate_text_length
        from PyQt6.QtWidgets import QMessageBox
        import os

        current_attrs = self.get_current_attributes()
        duplicates = []
        for file_path in file_paths:

            class QueueItem:
                pass

            item = QueueItem()
            item.file_name = file_path
            item.save_base_path = (
                file_path  # For .txt files, processing and save paths are the same
            )
            for attr, value in current_attrs.items():
                setattr(item, attr, value)
            # Override subtitle_mode to "Disabled" for subtitle files
            if file_path.lower().endswith((".srt", ".ass", ".vtt")):
                item.subtitle_mode = "Disabled"
            # Read file content and calculate total_char_count using calculate_text_length
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    file_content = f.read()
                item.total_char_count = calculate_text_length(file_content)
            except Exception:
                item.total_char_count = 0
            # Prevent adding duplicate items to the queue (check all attributes)
            is_duplicate = False
            for queued_item in self.queue:
                if (
                    getattr(queued_item, "file_name", None)
                    == getattr(item, "file_name", None)
                    and getattr(queued_item, "lang_code", None)
                    == getattr(item, "lang_code", None)
                    and getattr(queued_item, "speed", None)
                    == getattr(item, "speed", None)
                    and getattr(queued_item, "voice", None)
                    == getattr(item, "voice", None)
                    and getattr(queued_item, "save_option", None)
                    == getattr(item, "save_option", None)
                    and getattr(queued_item, "output_folder", None)
                    == getattr(item, "output_folder", None)
                    and getattr(queued_item, "subtitle_mode", None)
                    == getattr(item, "subtitle_mode", None)
                    and getattr(queued_item, "output_format", None)
                    == getattr(item, "output_format", None)
                    and getattr(queued_item, "total_char_count", None)
                    == getattr(item, "total_char_count", None)
                    and getattr(queued_item, "replace_single_newlines", True)
                    == getattr(item, "replace_single_newlines", True)
                    and getattr(queued_item, "use_silent_gaps", False)
                    == getattr(item, "use_silent_gaps", False)
                    and getattr(queued_item, "subtitle_speed_method", "tts")
                    == getattr(item, "subtitle_speed_method", "tts")
                    and getattr(queued_item, "save_base_path", None)
                    == getattr(item, "save_base_path", None)
                    and getattr(queued_item, "save_chapters_separately", None)
                    == getattr(item, "save_chapters_separately", None)
                    and getattr(queued_item, "merge_chapters_at_end", None)
                    == getattr(item, "merge_chapters_at_end", None)
                ):
                    is_duplicate = True
                    break
            if is_duplicate:
                duplicates.append(os.path.basename(file_path))
                continue
            self.queue.append(item)
        if duplicates:
            QMessageBox.warning(
                self,
                "Duplicate Item(s)",
                f"Skipping {len(duplicates)} file(s) with the same attributes, already in the queue.",
            )
        self.process_queue()
        self.update_button_states()

    def add_more_files(self):
        from PyQt6.QtWidgets import QFileDialog

        # Allow .txt, .srt, .ass, and .vtt files
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select text or subtitle files",
            "",
            "Supported Files (*.txt *.srt *.ass *.vtt)",
        )
        if not files:
            return
        self.add_files_from_paths(files)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "empty_overlay"):
            self.empty_overlay.resize(self.listwidget.size())

    def update_button_states(self):
        # Enable Remove if at least one item is selected, else disable
        if hasattr(self, "remove_button"):
            selected_count = len(self.listwidget.selectedItems())
            self.remove_button.setEnabled(selected_count > 0)
            if selected_count > 1:
                self.remove_button.setText(f"Remove selected ({selected_count})")
            else:
                self.remove_button.setText("Remove selected")
        # Disable Clear if queue is empty
        if hasattr(self, "clear_button"):
            self.clear_button.setEnabled(bool(self.queue))

    def show_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction, QDesktopServices
        from PyQt6.QtCore import QUrl
        import os

        global_pos = self.listwidget.viewport().mapToGlobal(pos)
        selected_items = self.listwidget.selectedItems()
        menu = QMenu(self)
        if len(selected_items) == 1:
            # Add Remove action
            remove_action = QAction("Remove this item", self)
            remove_action.triggered.connect(self.remove_item)
            menu.addAction(remove_action)

            # Get paths for determining if it's a document input
            item = selected_items[0]
            paths = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(paths, dict):
                display_path = paths.get("display_path", "")
                processing_path = paths.get("processing_path", "")
            else:
                display_path = paths
                processing_path = paths

            doc_exts = (".md", ".markdown", ".pdf", ".epub")
            is_document_input = (
                isinstance(display_path, str)
                and display_path.lower().endswith(doc_exts)
            ) or (
                isinstance(processing_path, str)
                and processing_path.lower().endswith(doc_exts)
            )

            # Add Open file action(s)
            def open_file_by_path(path_label: str):
                from PyQt6.QtWidgets import QMessageBox

                p = display_path if path_label == "display" else processing_path
                if not p:
                    QMessageBox.warning(
                        self, "File Not Found", "Path is not available."
                    )
                    return

                # Find the queue item and resolve the target path
                target_path = None
                for q in self.queue:
                    if (
                        getattr(q, "save_base_path", None) == display_path
                        or q.file_name == display_path
                    ):
                        if path_label == "display":
                            target_path = (
                                getattr(q, "save_base_path", None) or q.file_name
                            )
                        else:
                            target_path = q.file_name
                        break
                    if (
                        getattr(q, "save_base_path", None) == processing_path
                        or q.file_name == processing_path
                    ):
                        if path_label == "display":
                            target_path = (
                                getattr(q, "save_base_path", None) or q.file_name
                            )
                        else:
                            target_path = q.file_name
                        break

                # Fallback to the raw path if resolution failed
                if not target_path:
                    target_path = p

                if not os.path.exists(target_path):
                    QMessageBox.warning(
                        self, "File Not Found", f"The file does not exist."
                    )
                    return
                QDesktopServices.openUrl(QUrl.fromLocalFile(target_path))

            if is_document_input:
                # For documents, show two open options
                open_processed_action = QAction("Open processed file", self)
                open_processed_action.triggered.connect(
                    lambda: open_file_by_path("processing")
                )
                menu.addAction(open_processed_action)

                open_input_action = QAction("Open input file", self)
                open_input_action.triggered.connect(
                    lambda: open_file_by_path("display")
                )
                menu.addAction(open_input_action)
            else:
                # For plain text files, show single open option
                open_file_action = QAction("Open file", self)
                open_file_action.triggered.connect(lambda: open_file_by_path("display"))
                menu.addAction(open_file_action)

            # Add Go to folder action
            # If the queued item represents a converted document (markdown, pdf, epub)
            # show two actions: Go to processed file (the cached .txt) and Go to input file (original source)

            from PyQt6.QtWidgets import QMessageBox

            def open_folder_for(path_label: str):
                # path_label should be either 'display' or 'processing'
                p = display_path if path_label == "display" else processing_path
                if not p:
                    QMessageBox.warning(
                        self, "File Not Found", "Path is not available."
                    )
                    return
                # If the stored path is the display path (original) but the actual file may be
                # stored on the queue object differently, try to resolve via the queue entry.
                target_path = None
                for q in self.queue:
                    if (
                        getattr(q, "save_base_path", None) == display_path
                        or q.file_name == display_path
                    ):
                        if path_label == "display":
                            target_path = (
                                getattr(q, "save_base_path", None) or q.file_name
                            )
                        else:
                            target_path = q.file_name
                        break
                    if (
                        getattr(q, "save_base_path", None) == processing_path
                        or q.file_name == processing_path
                    ):
                        if path_label == "display":
                            target_path = (
                                getattr(q, "save_base_path", None) or q.file_name
                            )
                        else:
                            target_path = q.file_name
                        break
                # Fallback to the raw path if resolution failed
                if not target_path:
                    target_path = p

                if not os.path.exists(target_path):
                    QMessageBox.warning(
                        self,
                        "File Not Found",
                        f"The file does not exist: {target_path}",
                    )
                    return
                folder = os.path.dirname(target_path)
                if os.path.exists(folder):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

            if is_document_input:
                processed_action = QAction("Go to processed file", self)
                processed_action.triggered.connect(
                    lambda: open_folder_for("processing")
                )
                menu.addAction(processed_action)

                input_action = QAction("Go to input file", self)
                input_action.triggered.connect(lambda: open_folder_for("display"))
                menu.addAction(input_action)
            else:
                # Default behavior for non-document inputs: single "Go to folder" action
                go_to_folder_action = QAction("Go to folder", self)

                def go_to_folder():
                    item = selected_items[0]
                    paths = item.data(Qt.ItemDataRole.UserRole)
                    if isinstance(paths, dict):
                        file_path = paths.get(
                            "display_path", paths.get("processing_path", "")
                        )
                    else:
                        file_path = paths  # Fallback for old format
                    # Find the queue item
                    for q in self.queue:
                        if (
                            getattr(q, "save_base_path", None) == file_path
                            or q.file_name == file_path
                        ):
                            target_path = (
                                getattr(q, "save_base_path", None) or q.file_name
                            )
                            if not os.path.exists(target_path):
                                QMessageBox.warning(
                                    self, "File Not Found", f"The file does not exist."
                                )
                                return
                            folder = os.path.dirname(target_path)
                            if os.path.exists(folder):
                                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
                            break

                go_to_folder_action.triggered.connect(go_to_folder)
                menu.addAction(go_to_folder_action)

        elif len(selected_items) > 1:
            remove_action = QAction(f"Remove selected ({len(selected_items)})", self)
            remove_action.triggered.connect(self.remove_item)
            menu.addAction(remove_action)
        # Always add Clear Queue
        clear_action = QAction("Clear Queue", self)
        clear_action.triggered.connect(self.clear_queue)
        menu.addAction(clear_action)
        menu.exec(global_pos)

    def accept(self):
        # Save the override state to config so it persists globally
        self.config["queue_override_settings"] = self.override_chk.isChecked()
        save_config(self.config)
        
        super().accept()

    def reject(self):
        # Cancel: restore original queue
        from PyQt6.QtWidgets import QMessageBox

        # Warn if user changed a lot (e.g., more than 1 items difference)
        original_count = len(self._original_queue)
        current_count = len(self.queue)
        if abs(original_count - current_count) > 1:
            reply = QMessageBox.question(
                self,
                "Confirm Cancel",
                f"Are you sure you want to cancel and discard all changes?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.queue.clear()
        self.queue.extend(deepcopy(self._original_queue))
        super().reject()

    def keyPressEvent(self, event):
        from PyQt6.QtCore import Qt

        if event.key() == Qt.Key.Key_Delete:
            self.remove_item()
        else:
            super().keyPressEvent(event)
