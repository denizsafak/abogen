# a simple window with a list of items in the queue, no checkboxes
# button to remove an item from the queue
# button to clear the queue

from PyQt5.QtWidgets import (
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
)
from PyQt5.QtCore import QFileInfo, Qt
from abogen.constants import COLORS
from copy import deepcopy
from PyQt5.QtGui import QFontMetrics


class ElidedLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def setText(self, text):
        self._full_text = text
        super().setText(text)
        self.update()

    def resizeEvent(self, event):
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._full_text, Qt.ElideRight, self.width())
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
        char_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        char_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
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
        self.drag_overlay.setAlignment(Qt.AlignCenter)
        self.drag_overlay.setStyleSheet(
            f"border:2px dashed {COLORS['BLUE_BORDER_HOVER']}; border-radius:5px; padding:20px; background:{COLORS['BLUE_BG_HOVER']};"
        )
        self.drag_overlay.setVisible(False)
        self.drag_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".txt"):
                    self.drag_overlay.resize(self.size())
                    self.drag_overlay.setVisible(True)
                    event.acceptProposedAction()
                    return
        self.drag_overlay.setVisible(False)
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".txt"):
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
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".txt")
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
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)  # set main layout margins
        layout.setSpacing(12)  # set spacing between widgets in main layout
        # list of queued items
        self.listwidget = DroppableQueueListWidget(self)
        self.listwidget.setSelectionMode(QListWidget.ExtendedSelection)
        self.listwidget.setAlternatingRowColors(True)
        self.listwidget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.listwidget.customContextMenuRequested.connect(self.show_context_menu)
        # Add informative instructions at the top
        instructions = QLabel(
            "<h2>How Queue Works?</h2>"
            "You can add text files (.txt) directly using the '<b>Add files</b>' button below. "
            "To add PDF or EPUB files, use the input box in the main window and click the <b>'Add to Queue'</b> button. "
            "Each file in the queue keeps the configuration settings active when it was added. "
            "Changing the main window configuration afterward <b>does not</b> affect files already in the queue. "
            "You can view each file's configuration by hovering over them."
        )
        instructions.setAlignment(Qt.AlignLeft)
        instructions.setWordWrap(True)
        instructions.setStyleSheet("margin-bottom: 8px;")
        layout.addWidget(instructions)
        # Overlay label for empty queue
        self.empty_overlay = QLabel(
            "Drag and drop your text files here or use the 'Add files' button.",
            self.listwidget,
        )
        self.empty_overlay.setAlignment(Qt.AlignCenter)
        self.empty_overlay.setStyleSheet(
            f"color: {COLORS['LIGHT_DISABLED']}; background: transparent; padding: 20px;"
        )
        self.empty_overlay.setWordWrap(True)
        self.empty_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
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

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(buttons)

        self.setLayout(layout)

        self.setWindowTitle(title)
        self.resize(*size)

        self.update_button_states()

    def process_queue(self):
        """Process the queue items."""
        self.listwidget.clear()
        if not self.queue:
            self.empty_overlay.resize(self.listwidget.size())
            self.empty_overlay.show()
            self.update_button_states()
            return
        else:
            self.empty_overlay.hide()
        icon_provider = QFileIconProvider()
        for item in self.queue:
            # Only show the file name, not the full path
            file_name = item.file_name
            display_name = file_name
            import os

            if os.path.sep in file_name:
                display_name = os.path.basename(file_name)
            # Get icon for the file
            icon = icon_provider.icon(QFileInfo(file_name))
            list_item = QListWidgetItem()
            # Set tooltip with detailed info
            output_folder = getattr(item, "output_folder", "")
            tooltip = (
                f"<b>Path:</b> {file_name}<br>"
                f"<b>Language:</b> {getattr(item, 'lang_code', '')}<br>"
                f"<b>Speed:</b> {getattr(item, 'speed', '')}<br>"
                f"<b>Voice:</b> {getattr(item, 'voice', '')}<br>"
                f"<b>Save Option:</b> {getattr(item, 'save_option', '')}<br>"
            )
            if output_folder not in (None, "", "None"):
                tooltip += f"<b>Output Folder:</b> {output_folder}<br>"
            tooltip += (
                f"<b>Subtitle Mode:</b> {getattr(item, 'subtitle_mode', '')}<br>"
                f"<b>Output Format:</b> {getattr(item, 'output_format', '')}<br>"
                f"<b>Characters:</b> {getattr(item, 'total_char_count', '')}<br>"
                f"<b>Replace Single Newlines:</b> {getattr(item, 'replace_single_newlines', False)}"
            )
            list_item.setToolTip(tooltip)
            list_item.setIcon(icon)
            # Use custom widget for display
            char_count = getattr(item, "total_char_count", 0)
            widget = QueueListItemWidget(file_name, char_count)
            self.listwidget.addItem(list_item)
            self.listwidget.setItemWidget(list_item, widget)
        self.update_button_states()

    def remove_item(self):
        items = self.listwidget.selectedItems()
        if not items:
            return
        from PyQt5.QtWidgets import QMessageBox

        # Remove by index to ensure correct mapping
        rows = sorted([self.listwidget.row(item) for item in items], reverse=True)
        # Warn user if removing multiple files
        if len(rows) > 1:
            reply = QMessageBox.question(
                self,
                "Confirm Remove",
                f"Are you sure you want to remove {len(rows)} selected items from the queue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        for row in rows:
            if 0 <= row < len(self.queue):
                del self.queue[row]
        self.process_queue()
        self.update_button_states()

    def clear_queue(self):
        from PyQt5.QtWidgets import QMessageBox

        if len(self.queue) > 1:
            reply = QMessageBox.question(
                self,
                "Confirm Clear Queue",
                f"Are you sure you want to clear {len(self.queue)} items from the queue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
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
                parent, "replace_single_newlines", False
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
        return attrs

    def add_files_from_paths(self, file_paths):
        from abogen.utils import calculate_text_length
        from PyQt5.QtWidgets import QMessageBox
        import os

        current_attrs = self.get_current_attributes()
        duplicates = []
        for file_path in file_paths:

            class QueueItem:
                pass

            item = QueueItem()
            item.file_name = file_path
            for attr, value in current_attrs.items():
                setattr(item, attr, value)
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
                    and getattr(queued_item, "replace_single_newlines", False)
                    == getattr(item, "replace_single_newlines", False)
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
        from PyQt5.QtWidgets import QFileDialog
        from abogen.utils import calculate_text_length  # import the function

        # Only allow .txt files
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select .txt files", "", "Text Files (*.txt)"
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
        from PyQt5.QtWidgets import QMenu, QAction
        from PyQt5.QtGui import QDesktopServices
        from PyQt5.QtCore import QUrl
        import os

        global_pos = self.listwidget.viewport().mapToGlobal(pos)
        selected_items = self.listwidget.selectedItems()
        menu = QMenu(self)
        if len(selected_items) == 1:
            # Add Remove action
            remove_action = QAction("Remove this item", self)
            remove_action.triggered.connect(self.remove_item)
            menu.addAction(remove_action)

            # Add Open file action
            open_file_action = QAction("Open file", self)

            def open_file():
                from PyQt5.QtWidgets import QMessageBox

                item = selected_items[0]
                display_name = item.text()
                for q in self.queue:
                    if os.path.basename(q.file_name) == display_name:
                        if not os.path.exists(q.file_name):
                            QMessageBox.warning(
                                self, "File Not Found", f"The file does not exist."
                            )
                            return
                        QDesktopServices.openUrl(QUrl.fromLocalFile(q.file_name))
                        break

            open_file_action.triggered.connect(open_file)
            menu.addAction(open_file_action)

            # Add Go to folder action
            go_to_folder_action = QAction("Go to folder", self)

            def go_to_folder():
                from PyQt5.QtWidgets import QMessageBox

                item = selected_items[0]
                display_name = item.text()
                for q in self.queue:
                    if os.path.basename(q.file_name) == display_name:
                        if not os.path.exists(q.file_name):
                            QMessageBox.warning(
                                self, "File Not Found", f"The file does not exist."
                            )
                            return
                        folder = os.path.dirname(q.file_name)
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
        menu.exec_(global_pos)

    def accept(self):
        # Accept: keep changes
        super().accept()

    def reject(self):
        # Cancel: restore original queue
        from PyQt5.QtWidgets import QMessageBox

        # Warn if user changed a lot (e.g., more than 1 items difference)
        original_count = len(self._original_queue)
        current_count = len(self.queue)
        if abs(original_count - current_count) > 1:
            reply = QMessageBox.question(
                self,
                "Confirm Cancel",
                f"Are you sure you want to cancel and discard all changes?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self.queue.clear()
        self.queue.extend(deepcopy(self._original_queue))
        super().reject()

    def keyPressEvent(self, event):
        from PyQt5.QtCore import Qt

        if event.key() == Qt.Key_Delete:
            self.remove_item()
        else:
            super().keyPressEvent(event)
