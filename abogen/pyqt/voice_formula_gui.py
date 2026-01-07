import json
import os
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QCheckBox,
    QLabel,
    QHBoxLayout,
    QDoubleSpinBox,
    QSlider,
    QScrollArea,
    QWidget,
    QPushButton,
    QSizePolicy,
    QMessageBox,
    QFrame,
    QLayout,
    QStyle,
    QListWidget,
    QListWidgetItem,
    QInputDialog,
    QFileDialog,
    QSplitter,
    QMenu,
    QApplication,
    QComboBox,
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QRect, QSize
from PyQt6.QtGui import QPixmap, QIcon, QAction
from abogen.constants import (
    VOICES_INTERNAL,
    SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION,
    LANGUAGE_DESCRIPTIONS,
    COLORS,
)
import re
import platform
from abogen.utils import get_resource_path
from abogen.voice_profiles import (
    load_profiles,
    save_profiles,
    delete_profile,
    duplicate_profile,
    export_profiles,
)


# Constants
VOICE_MIXER_WIDTH = 100
SLIDER_WIDTH = 32
MIN_WINDOW_WIDTH = 600
MIN_WINDOW_HEIGHT = 400
INITIAL_WINDOW_WIDTH = 1200
INITIAL_WINDOW_HEIGHT = 500

# Language options for the language selector loaded from constants
LANGUAGE_OPTIONS = list(LANGUAGE_DESCRIPTIONS.items())


class SaveButtonWidget(QWidget):
    def __init__(self, parent, profile_name, save_callback):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.save_btn = QPushButton("Save", self)
        self.save_btn.setFixedWidth(48)
        self.save_btn.clicked.connect(lambda: save_callback(profile_name))
        layout.addStretch()
        layout.addWidget(self.save_btn)
        self.setLayout(layout)


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        if parent:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._item_list = []

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self._item_list.append(item)

    def count(self):
        return len(self._item_list)

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def sizeHint(self):
        return self.minimumSize()

    def itemAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list.pop(index)
        return None

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def minimumSize(self):
        size = QSize()
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
        margin, _, _, _ = self.getContentsMargins()
        size += QSize(2 * margin, 2 * margin)
        return size

    def _do_layout(self, rect, test_only):
        x, y = rect.x(), rect.y()
        line_height = 0
        spacing = self.spacing()

        for item in self._item_list:
            style = self.parentWidget().style() if self.parentWidget() else QStyle()
            layout_spacing_x = style.layoutSpacing(
                QSizePolicy.ControlType.PushButton,
                QSizePolicy.ControlType.PushButton,
                Qt.Orientation.Horizontal,
            )
            layout_spacing_y = style.layoutSpacing(
                QSizePolicy.ControlType.PushButton,
                QSizePolicy.ControlType.PushButton,
                Qt.Orientation.Vertical,
            )
            space_x = spacing if spacing >= 0 else layout_spacing_x
            space_y = spacing if spacing >= 0 else layout_spacing_y

            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y()


class VoiceMixer(QWidget):
    def __init__(
        self, voice_name, language_code, initial_status=False, initial_weight=0.0
    ):
        super().__init__()
        self.voice_name = voice_name
        self.setFixedWidth(VOICE_MIXER_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # TODO Set CSS for rounded corners
        # self.setObjectName("VoiceMixer")
        # self.setStyleSheet(self.ROUNDED_CSS)

        layout = QVBoxLayout()

        # Name label at the top
        name = voice_name
        layout.addWidget(QLabel(name), alignment=Qt.AlignmentFlag.AlignCenter)

        # Voice name label with gender icon
        is_female = self.voice_name in VOICES_INTERNAL and self.voice_name[1] == "f"

        # Icons layout (flag and gender)
        icons_layout = QHBoxLayout()
        icons_layout.setSpacing(3)
        icons_layout.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )  # Center the icons horizontally

        # Flag icon
        flag_icon_path = get_resource_path(
            "abogen.assets.flags", f"{language_code}.png"
        )
        gender_icon_path = get_resource_path(
            "abogen.assets", "female.png" if is_female else "male.png"
        )
        flag_label = QLabel()
        gender_label = QLabel()
        flag_pixmap = QPixmap(flag_icon_path)
        flag_label.setPixmap(
            flag_pixmap.scaled(
                16,
                16,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        gender_pixmap = QPixmap(gender_icon_path)
        gender_label.setPixmap(
            gender_pixmap.scaled(
                16,
                16,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        icons_layout.addWidget(flag_label)
        icons_layout.addWidget(gender_label)

        # Add icons layout
        layout.addLayout(icons_layout)

        # Checkbox (now below icons)
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(initial_status)
        self.checkbox.stateChanged.connect(self.toggle_inputs)
        layout.addWidget(self.checkbox, alignment=Qt.AlignmentFlag.AlignCenter)

        # Spinbox and slider
        self.spin_box = QDoubleSpinBox()
        self.spin_box.setRange(0, 1)
        self.spin_box.setSingleStep(0.01)
        self.spin_box.setDecimals(2)
        self.spin_box.setValue(initial_weight)

        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(initial_weight * 100))
        self.slider.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self.slider.setFixedWidth(SLIDER_WIDTH)

        # Apply slider styling after widget is added to window (see showEvent)
        self._slider_style_applied = False

        # Connect controls
        self.slider.valueChanged.connect(lambda val: self.spin_box.setValue(val / 100))
        self.spin_box.valueChanged.connect(
            lambda val: self.slider.setValue(int(val * 100))
        )

        # Layout for slider and labels
        slider_layout = QVBoxLayout()
        slider_layout.addWidget(self.spin_box)
        slider_layout.addWidget(QLabel("1", alignment=Qt.AlignmentFlag.AlignCenter))

        slider_center_layout = QHBoxLayout()
        slider_center_layout.addWidget(
            self.slider, alignment=Qt.AlignmentFlag.AlignHCenter
        )
        slider_center_layout.setContentsMargins(0, 0, 0, 0)

        slider_center_widget = QWidget()
        slider_center_widget.setLayout(slider_center_layout)

        slider_layout.addWidget(slider_center_widget, stretch=1)
        slider_layout.addWidget(QLabel("0", alignment=Qt.AlignmentFlag.AlignCenter))
        slider_layout.setStretch(2, 1)

        layout.addLayout(slider_layout, stretch=1)
        self.setLayout(layout)
        self.toggle_inputs()

    def showEvent(self, event):
        super().showEvent(event)
        # Apply slider styling once when widget is shown and has access to parent
        if not self._slider_style_applied:
            self._slider_style_applied = True

            # Fix slider in Windows
            if platform.system() == "Windows":
                appstyle = QApplication.instance().style().objectName().lower()
                if appstyle != "windowsvista":
                    # Set custom groove color for disabled state using COLORS["GREY_BACKGROUND"]
                    self.slider.setStyleSheet(
                        f"""
                        QSlider::groove:vertical:disabled {{
                            background: {COLORS.get("GREY_BACKGROUND")};
                            width: 4px;
                            border-radius: 4px;
                        }}
                    """
                    )
            else:
                # Apply same fix for Light theme on non-Windows systems
                # Get theme from parent window's config
                parent_window = self.window()
                theme = "system"
                while parent_window:
                    if hasattr(parent_window, "config"):
                        theme = parent_window.config.get("theme", "system")
                        break
                    parent_window = parent_window.parent()

                if theme == "light":
                    self.slider.setStyleSheet(
                        f"""
                        QSlider::groove:vertical:disabled {{
                            background: {COLORS.get("GREY_BACKGROUND")};
                            width: 4px;
                            border-radius: 4px;
                        }}
                    """
                    )

    def toggle_inputs(self):
        is_enabled = self.checkbox.isChecked()
        self.spin_box.setEnabled(is_enabled)
        self.slider.setEnabled(is_enabled)

    def get_voice_weight(self):
        if self.checkbox.isChecked():
            return self.voice_name, self.spin_box.value()
        return None


class HoverLabel(QLabel):
    def __init__(self, text, voice_name, parent=None):
        super().__init__(text, parent)
        self.voice_name = voice_name
        self.setMouseTracking(True)
        self.setStyleSheet(
            "background-color: rgba(140, 140, 140, 0.15); border-radius: 4px; padding: 3px 6px 3px 6px; margin: 2px;"
        )

        # Create delete button
        self.delete_button = QPushButton("×", self)
        self.delete_button.setFixedSize(16, 16)
        self.delete_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.get("RED")};
                color: white;
                border-radius: 7px;
                font-weight: bold;
                font-size: 12px;
                border: none;
                padding: 0px;
                margin: 0px;
            }}
            QPushButton:hover {{
                background-color: red;
            }}
            """
        )
        # Make sure the entire button is clickable, not just the text
        self.delete_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.delete_button.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, False
        )
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Position the button in the top-right corner with a small margin
        self.delete_button.move(self.width() - 16, +0)

    def enterEvent(self, event):
        self.delete_button.show()

    def leaveEvent(self, event):
        self.delete_button.hide()


class VoiceFormulaDialog(QDialog):
    def __init__(self, parent=None, initial_state=None, selected_profile=None):
        super().__init__(parent)
        # Store original profile/mix state for restoration on cancel
        self._original_profile_name = None
        self._original_mixed_voice_state = None
        if parent is not None:
            self._original_profile_name = getattr(parent, "selected_profile_name", None)
            self._original_mixed_voice_state = getattr(
                parent, "mixed_voice_state", None
            )
        profiles = load_profiles()
        self._virtual_new_profile = False
        if not profiles:
            # No profiles: show 'New profile' in the list, unsaved, not in JSON
            self.current_profile = "New profile"
            self._profile_dirty = {"New profile": True}
            self._virtual_new_profile = True
            profiles = {}  # Do not add to JSON yet
        else:
            self.current_profile = (
                selected_profile
                if selected_profile in profiles
                else list(profiles.keys())[0]
            )
            self._profile_dirty = {name: False for name in profiles}
        # Track unsaved states per profile
        self._profile_states = {}
        # Add subtitle_combo reference if parent has it
        self.subtitle_combo = None
        if parent is not None and hasattr(parent, "subtitle_combo"):
            self.subtitle_combo = parent.subtitle_combo
        # Create main container layout with profile section and mixer section
        splitter = QSplitter(Qt.Orientation.Horizontal)
        # Profile section
        profile_widget = QWidget()
        profile_layout = QVBoxLayout(profile_widget)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        # Profile header and save/new buttons
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Profiles:"))
        header_layout.addStretch()
        self.btn_new_profile = QPushButton("New profile")
        header_layout.addWidget(self.btn_new_profile)
        profile_layout.addLayout(header_layout)
        # Profile list
        self.profile_list = QListWidget()
        self.profile_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.profile_list.setSelectionBehavior(QListWidget.SelectionBehavior.SelectRows)
        self.profile_list.setStyleSheet(
            "QListWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }"
        )
        icon = QIcon(get_resource_path("abogen.assets", "profile.png"))
        if self._virtual_new_profile:
            item = QListWidgetItem(icon, "New profile")
            self.profile_list.addItem(item)
            self.profile_list.setCurrentRow(0)
        else:
            for name in profiles:
                item = QListWidgetItem(icon, name)
                self.profile_list.addItem(item)
            idx = list(profiles.keys()).index(self.current_profile)
            self.profile_list.setCurrentRow(idx)
        profile_layout.addWidget(self.profile_list)
        self.profile_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.profile_list.customContextMenuRequested.connect(
            self.show_profile_context_menu
        )
        self.profile_list.setItemWidget = (
            self.profile_list.setItemWidget
        )  # for type hints
        # Save and management buttons
        mgmt_layout = QVBoxLayout()
        self.btn_import_profiles = QPushButton("Import profile(s)")
        mgmt_layout.addWidget(self.btn_import_profiles)
        self.btn_export_profiles = QPushButton("Export profiles")
        mgmt_layout.addWidget(self.btn_export_profiles)
        profile_layout.addLayout(mgmt_layout)
        # prepare mixer widget
        mixer_widget = QWidget()
        mixer_layout = QVBoxLayout(mixer_widget)
        mixer_layout.setContentsMargins(5, 0, 0, 0)

        self.setWindowTitle("Voice Mixer")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.resize(INITIAL_WINDOW_WIDTH, INITIAL_WINDOW_HEIGHT)
        self.voice_mixers = []
        self.last_enabled_voice = None

        # Header label and language selector
        self.header_label = QLabel(
            "Adjust voice weights to create your preferred voice mix."
        )
        self.header_label.setStyleSheet("font-size: 13px;")
        self.header_label.setWordWrap(True)
        header_row = QHBoxLayout()
        header_row.addWidget(self.header_label, 1)
        header_row.addStretch()
        header_row.addWidget(QLabel("Language:"))
        self.language_combo = QComboBox()
        for code, desc in LANGUAGE_OPTIONS:
            flag = get_resource_path("abogen.assets.flags", f"{code}.png")
            if flag and os.path.exists(flag):
                self.language_combo.addItem(QIcon(flag), desc, code)
            else:
                self.language_combo.addItem(desc, code)
        # set current language for profile
        prof = profiles.get(self.current_profile, {})
        lang = prof.get("language") if isinstance(prof, dict) else None
        if not lang:
            lang = list(LANGUAGE_DESCRIPTIONS.keys())[0]
        idx = self.language_combo.findData(lang)
        if idx >= 0:
            self.language_combo.setCurrentIndex(idx)
        self.language_combo.currentIndexChanged.connect(self.mark_profile_modified)
        header_row.addWidget(self.language_combo)
        # Preview current voice mix using main window's preview
        self.btn_preview_mix = QPushButton("Preview", self)
        self.btn_preview_mix.setToolTip("Preview current voice mix")
        self.btn_preview_mix.clicked.connect(self.preview_current_mix)
        header_row.addWidget(self.btn_preview_mix)
        mixer_layout.addLayout(header_row)

        # Error message
        self.error_label = QLabel(
            "Please select at least one voice and set its weight above 0."
        )
        self.error_label.setStyleSheet("color: red; font-weight: bold;")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        mixer_layout.addWidget(self.error_label)

        # Voice weights display
        self.weighted_sums_container = QWidget()
        self.weighted_sums_layout = FlowLayout(self.weighted_sums_container)
        self.weighted_sums_layout.setSpacing(5)
        self.weighted_sums_layout.setContentsMargins(5, 5, 5, 5)
        mixer_layout.addWidget(self.weighted_sums_container)

        # Separator
        separator = QFrame()
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        mixer_layout.addWidget(separator)

        # Voice list scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll_area.viewport().installEventFilter(self)

        self.voice_list_widget = QWidget()
        self.voice_list_layout = QHBoxLayout()
        self.voice_list_widget.setLayout(self.voice_list_layout)
        self.voice_list_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.scroll_area.setWidget(self.voice_list_widget)
        mixer_layout.addWidget(self.scroll_area, stretch=1)

        # Buttons
        button_layout = QHBoxLayout()
        clear_all_button = QPushButton("Clear all")
        ok_button = QPushButton("OK")
        cancel_button = QPushButton("Cancel")

        # Set OK button as default
        ok_button.setDefault(True)
        ok_button.setFocus()

        # Connect buttons
        clear_all_button.clicked.connect(self.clear_all_voices)
        ok_button.clicked.connect(self.accept)
        # Connect buttons
        clear_all_button.clicked.connect(self.clear_all_voices)
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)

        button_layout.addStretch()
        button_layout.addWidget(clear_all_button)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        mixer_layout.addLayout(button_layout)

        self.add_voices(initial_state or [])
        self.update_weighted_sums()

        # assemble splitter
        splitter.addWidget(profile_widget)
        splitter.addWidget(mixer_widget)
        splitter.setStretchFactor(1, 1)
        # set as main layout
        self.setLayout(QHBoxLayout())
        self.layout().addWidget(splitter)

        # Connect profile actions
        self.profile_list.currentRowChanged.connect(self.on_profile_selection_changed)
        # Track initial profile for proper dirty-state saving
        self.last_profile_row = self.profile_list.currentRow()
        self.btn_new_profile.clicked.connect(self.new_profile)
        self.btn_export_profiles.clicked.connect(self.export_all_profiles)
        self.btn_import_profiles.clicked.connect(self.import_profiles_dialog)
        # Detect modifications in voice mixers
        for vm in self.voice_mixers:
            vm.spin_box.valueChanged.connect(self.mark_profile_modified)
            vm.checkbox.stateChanged.connect(lambda *_: self.mark_profile_modified())

    def keyPressEvent(self, event):
        # Bind Delete key to delete_profile when a profile is selected
        if event.key() == Qt.Key.Key_Delete and self.profile_list.hasFocus():
            item = self.profile_list.currentItem()
            if item:
                self.delete_profile(item)
                return
        super().keyPressEvent(event)

    def _has_unsaved_changes(self):
        # Only return True if there are actually modified (yellow background) profiles
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            # Only consider as unsaved if profile is marked dirty (yellow background)
            if item.text().startswith("*"):
                return True
        return False

    def _prompt_save_changes(self):
        dirty_indices = [
            i
            for i in range(self.profile_list.count())
            if self.profile_list.item(i).text().startswith("*")
        ]
        parent = self.parent()
        if len(dirty_indices) > 1:
            msg = f"You have unsaved changes in {len(dirty_indices)} profiles. Do you want to save all?"
            ret = QMessageBox.question(
                self,
                "Unsaved Changes",
                msg,
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if ret == QMessageBox.StandardButton.Save:
                # Save all using stored states
                profiles = load_profiles()
                for i in dirty_indices:
                    name = self.profile_list.item(i).text().lstrip("*")
                    state = self._profile_states.get(name)
                    if state is not None:
                        profiles[name] = state
                        self._profile_dirty[name] = False
                save_profiles(profiles)
                # clear states
                for name in list(self._profile_states.keys()):
                    if name not in profiles:
                        continue
                    del self._profile_states[name]
                if hasattr(parent, "populate_profiles_in_voice_combo"):
                    parent.populate_profiles_in_voice_combo()
                # clear markers
                for i in dirty_indices:
                    item = self.profile_list.item(i)
                    n = item.text().lstrip("*")
                    item.setText(n)
                self.update_profile_save_buttons()
                self.update_profile_list_colors()
                return True
            elif ret == QMessageBox.StandardButton.Discard:
                # Discard all modifications
                self._profile_states.clear()
                for i in dirty_indices:
                    item = self.profile_list.item(i)
                    n = item.text().lstrip("*")
                    item.setText(n)
                    self._profile_dirty[n] = False
                self.update_profile_save_buttons()
                self.update_profile_list_colors()
                # reload current profile
                profiles = load_profiles()
                if self.current_profile in profiles:
                    self.load_profile_state(self.current_profile)
                if hasattr(parent, "populate_profiles_in_voice_combo"):
                    parent.populate_profiles_in_voice_combo()
                return True
            else:
                return False
        else:
            # Fallback to original logic for 0 or 1 dirty profile
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Unsaved Changes")
            box.setText(
                "You have unsaved changes in your profile. Do you want to save the changes?"
            )
            box.setStandardButtons(
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QMessageBox.StandardButton.Save)
            ret = box.exec()
            if ret == QMessageBox.StandardButton.Save:
                for i in range(self.profile_list.count()):
                    item = self.profile_list.item(i)
                    name = item.text().lstrip("*")
                    if (
                        self._profile_dirty.get(name, False)
                        or item.text().startswith("*")
                        or (name == self.current_profile)
                    ):
                        self.profile_list.setCurrentRow(i)
                        self.save_profile_by_name(name)
                if hasattr(parent, "populate_profiles_in_voice_combo"):
                    parent.populate_profiles_in_voice_combo()
                return True
            elif ret == QMessageBox.StandardButton.Discard:
                profiles = load_profiles()
                for i in range(self.profile_list.count()):
                    item = self.profile_list.item(i)
                    name = item.text().lstrip("*")
                    self._profile_dirty[name] = False
                    if item.text().startswith("*"):
                        item.setText(name)
                self.update_profile_save_buttons()
                self.update_profile_list_colors()
                if self.current_profile in profiles:
                    self.load_profile_state(self.current_profile)
                if hasattr(parent, "populate_profiles_in_voice_combo"):
                    parent.populate_profiles_in_voice_combo()
                return True
            else:
                return False

    def on_profile_selection_changed(self, row):
        # Save dirty state for previous profile
        if hasattr(self, "last_profile_row") and self.last_profile_row is not None:
            prev_item = self.profile_list.item(self.last_profile_row)
            if prev_item:
                prev_name = prev_item.text().lstrip("*")
                self._profile_dirty[prev_name] = prev_item.text().startswith("*")
        # Do NOT auto-save if modifications pending
        # load new profile
        item = self.profile_list.item(row)
        if item:
            name = item.text().lstrip("*")
            self.load_profile_state(name)
            # Restore dirty state for this profile
            dirty = self._profile_dirty.get(name, False)
            if dirty and not item.text().startswith("*"):
                item.setText("*" + item.text())
            elif not dirty and item.text().startswith("*"):
                item.setText(item.text().lstrip("*"))
        self.last_profile_row = row
        self.update_profile_save_buttons()
        self.update_profile_list_colors()

    def add_voices(self, initial_state):
        first_enabled_voice = None
        for voice in VOICES_INTERNAL:
            language_code = voice[0]  # First character is the language code
            matching_voice = next(
                (item for item in initial_state if item[0] == voice), None
            )
            initial_status = matching_voice is not None
            initial_weight = matching_voice[1] if matching_voice else 1.0
            voice_mixer = self.add_voice(
                voice, language_code, initial_status, initial_weight
            )
            if initial_status and first_enabled_voice is None:
                first_enabled_voice = voice_mixer

        if first_enabled_voice:
            QTimer.singleShot(
                0, lambda: self.scroll_area.ensureWidgetVisible(first_enabled_voice)
            )

    def add_voice(
        self, voice_name, language_code, initial_status=False, initial_weight=1.0
    ):
        voice_mixer = VoiceMixer(
            voice_name, language_code, initial_status, initial_weight
        )
        self.voice_mixers.append(voice_mixer)
        self.voice_list_layout.addWidget(voice_mixer)
        voice_mixer.checkbox.stateChanged.connect(
            lambda state, vm=voice_mixer: self.handle_voice_checkbox(vm, state)
        )
        voice_mixer.spin_box.valueChanged.connect(self.update_weighted_sums)
        voice_mixer.checkbox.stateChanged.connect(self.update_weighted_sums)
        voice_mixer.spin_box.valueChanged.connect(self.mark_profile_modified)
        voice_mixer.checkbox.stateChanged.connect(
            lambda *_: self.mark_profile_modified()
        )
        return voice_mixer

    def handle_voice_checkbox(self, voice_mixer, state):
        if state == Qt.CheckState.Checked.value:
            self.last_enabled_voice = voice_mixer.voice_name
        self.update_weighted_sums()

    def get_selected_voices(self):
        return [
            v
            for v in (m.get_voice_weight() for m in self.voice_mixers)
            if v and v[1] > 0
        ]

    def update_weighted_sums(self):
        # Clear previous labels
        while self.weighted_sums_layout.count():
            item = self.weighted_sums_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        # Get selected voices
        selected = [
            (m.voice_name, m.spin_box.value())
            for m in self.voice_mixers
            if m.checkbox.isChecked() and m.spin_box.value() > 0
        ]

        total = sum(w for _, w in selected)
        # disable Preview if no voices selected, but don't enable while loading
        if not getattr(self, "_loading", False):
            self.btn_preview_mix.setEnabled(total > 0)

        if total > 0:
            self.error_label.hide()
            self.weighted_sums_container.show()

            # Reorder so last enabled voice is at the end
            if self.last_enabled_voice and any(
                name == self.last_enabled_voice for name, _ in selected
            ):
                others = [(n, w) for n, w in selected if n != self.last_enabled_voice]
                last = [(n, w) for n, w in selected if n == self.last_enabled_voice]
                selected = others + last

            # Add voice labels
            for name, weight in selected:
                percentage = weight / total * 100
                # Make the voice name bold and include percentage
                voice_label = HoverLabel(
                    f'<b><span style="color:{COLORS.get("BLUE")}">{name}: {percentage:.1f}%</span></b>',
                    name,
                )
                voice_label.setSizePolicy(
                    QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
                )
                voice_label.delete_button.clicked.connect(
                    lambda _, vn=name: self.disable_voice_by_name(vn)
                )
                self.weighted_sums_layout.addWidget(voice_label)
        else:
            self.error_label.show()
            self.weighted_sums_container.hide()

    def disable_voice_by_name(self, voice_name):
        for mixer in self.voice_mixers:
            if mixer.voice_name == voice_name:
                mixer.checkbox.setChecked(False)
                break

    def clear_all_voices(self):
        for mixer in self.voice_mixers:
            mixer.checkbox.setChecked(False)

    def eventFilter(self, source, event):
        if source is self.scroll_area.viewport() and event.type() == event.Type.Wheel:
            # Skip if over an enabled slider
            if any(
                mixer.slider.underMouse() and mixer.slider.isEnabled()
                for mixer in self.voice_mixers
            ):
                return False

            # Horizontal scrolling
            horiz_bar = self.scroll_area.horizontalScrollBar()
            delta = -120 if event.angleDelta().y() > 0 else 120
            horiz_bar.setValue(horiz_bar.value() + delta)
            return True
        return super().eventFilter(source, event)

    def load_profile_state(self, profile_name):
        name = profile_name.lstrip("*")
        profiles = load_profiles()
        # load voices and language from state or JSON
        if name in self._profile_states:
            state = self._profile_states[name]
        else:
            state = profiles.get(name, {})
        voices = state.get("voices") if isinstance(state, dict) else state
        lang = state.get("language") if isinstance(state, dict) else None
        # apply language selection
        if lang:
            i = self.language_combo.findData(lang)
            if i >= 0:
                self.language_combo.blockSignals(True)
                self.language_combo.setCurrentIndex(i)
                self.language_combo.blockSignals(False)
        self.current_profile = name
        weights = {n: w for n, w in voices}
        for vm in self.voice_mixers:
            weight = weights.get(vm.voice_name, 0.0)
            # block signals to avoid triggering updates
            vm.checkbox.blockSignals(True)
            vm.spin_box.blockSignals(True)
            vm.slider.blockSignals(True)
            vm.checkbox.setChecked(weight > 0)
            val = weight if weight > 0 else 1.0
            vm.spin_box.setValue(val)
            vm.slider.setValue(int(val * 100))
            # restore signals
            vm.checkbox.blockSignals(False)
            vm.spin_box.blockSignals(False)
            vm.slider.blockSignals(False)
            # sync enabled state
            vm.toggle_inputs()
        self.update_weighted_sums()

    def save_profile_by_name(self, name):
        profiles = load_profiles()
        state = self._profile_states.get(name, None)
        if state is not None:
            # ensure dict format
            if isinstance(state, dict):
                entry = state
            else:
                entry = {"voices": state, "language": self.language_combo.currentData()}
            profiles[name] = entry
            save_profiles(profiles)
            self._profile_dirty[name] = False
            del self._profile_states[name]
            self._virtual_new_profile = False
            # Remove * marker
            for i in range(self.profile_list.count()):
                item = self.profile_list.item(i)
                if item.text().lstrip("*") == name:
                    item.setText(name)
                    break
            self.update_profile_list_colors()
            self.update_profile_save_buttons()
            self.update_weighted_sums()

    def _handle_zero_weight_profiles(self):
        profiles = load_profiles()
        if len(profiles) < 1:
            return False
        zero = []
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            name = item.text().lstrip("*")
            weights = profiles.get(name, {}).get("voices", [])
            total = 0
            if isinstance(weights, list):
                for entry in weights:
                    if (
                        isinstance(entry, (list, tuple))
                        and len(entry) == 2
                        and isinstance(entry[1], (int, float))
                    ):
                        total += entry[1]
            if total == 0:
                zero.append((i, name))
        if not zero:
            return False
        msg = f"{len(zero)} invalid profile(s) with no voices selected or their total weights are 0. They will be ignored and deleted. Do you want to delete?"
        reply = QMessageBox.question(
            self,
            "Invalid Profiles",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for i, name in reversed(zero):
                self.profile_list.takeItem(i)
                delete_profile(name)
            parent = self.parent()
            if hasattr(parent, "populate_profiles_in_voice_combo"):
                parent.populate_profiles_in_voice_combo()
            self.update_profile_list_colors()
            self.update_profile_save_buttons()
            return False
        else:
            idx, _ = zero[0]
            self.profile_list.setCurrentRow(idx)
            return True

    def accept(self):
        # If no profiles, treat as cancel
        if self.profile_list.count() == 0:
            # Update subtitle_mode to match combo before closing
            if self.subtitle_combo:
                parent = self.parent()
                if parent is not None:
                    parent.subtitle_mode = self.subtitle_combo.currentText()
            self.reject()
            return
        # Prompt to save if unsaved changes, then check for zero-weight error after save
        if self._has_unsaved_changes():
            if not self._prompt_save_changes():
                return
        if self._handle_zero_weight_profiles():
            return
        selected_voices = self.get_selected_voices()
        total_weight = sum(weight for _, weight in selected_voices)
        if total_weight == 0:
            QMessageBox.warning(
                self,
                "Invalid Weights",
                "The total weight of selected voices cannot be zero. Please select at least one voice or adjust the weights.",
            )
            self.update_weighted_sums()
            return
        # Save weights to current profile
        profiles = load_profiles()
        profiles[self.current_profile] = {
            "voices": selected_voices,
            "language": self.language_combo.currentData(),
        }
        save_profiles(profiles)
        # Mark this profile as not dirty
        self._profile_dirty[self.current_profile] = False
        super().accept()

    def reject(self):
        # Restore parent's profile/mix state on cancel
        parent = self.parent()
        if parent is not None:
            if hasattr(self, "_original_profile_name"):
                parent.selected_profile_name = self._original_profile_name
            if hasattr(self, "_original_mixed_voice_state"):
                parent.mixed_voice_state = self._original_mixed_voice_state
        # Prompt to save if unsaved changes, then check for zero-weight error after save
        if self._has_unsaved_changes():
            if not self._prompt_save_changes():
                return
        if self._handle_zero_weight_profiles():
            return
        super().reject()

    def closeEvent(self, event):
        # Restore parent's profile/mix state on close
        parent = self.parent()
        if parent is not None:
            if hasattr(self, "_original_profile_name"):
                parent.selected_profile_name = self._original_profile_name
            if hasattr(self, "_original_mixed_voice_state"):
                parent.mixed_voice_state = self._original_mixed_voice_state
        # Prompt to save if unsaved changes, then check for zero-weight error after save
        if self._has_unsaved_changes():
            if not self._prompt_save_changes():
                event.ignore()
                return
        if self._handle_zero_weight_profiles():
            event.ignore()
            return
        super().closeEvent(event)

    def _parse_rgba_to_qcolor(self, rgba_str):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QColor

        """Helper to convert 'rgba(R,G,B,A_float)' string to QColor."""
        match = re.match(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", rgba_str)
        if match:
            r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
            a_float = float(match.group(4))
            a_int = int(a_float * 255)
            return QColor(r, g, b, a_int)
        return Qt.GlobalColor.transparent

    def mark_profile_modified(self):
        item = self.profile_list.currentItem()
        if item and not item.text().startswith("*"):
            item.setText("*" + item.text())
        # Flag profile as dirty and store unsaved state
        name = self.current_profile
        self._profile_dirty[name] = True
        self._profile_states[name] = {
            "voices": self.get_selected_voices(),
            "language": self.language_combo.currentData(),
        }
        self.update_profile_save_buttons()
        self.update_profile_list_colors()

    def new_profile(self):
        import re

        while True:
            name, ok = QInputDialog.getText(self, "New Profile", "Enter profile name:")
            if not ok or not name:
                break
            name = name.strip()  # Remove leading/trailing spaces
            if not name:
                continue
            if not re.match(r"^[\w\- ]+$", name):
                QMessageBox.warning(
                    self,
                    "Invalid Name",
                    "Profile name can only contain letters, numbers, spaces, underscores, and hyphens.",
                )
                continue
            profiles = load_profiles()
            # Remove 'New profile' placeholder if not persisted in JSON
            if (
                self.profile_list.count() == 1
                and self.profile_list.item(0).text() == "New profile"
                and "New profile" not in profiles
            ):
                self.profile_list.takeItem(0)
                self._virtual_new_profile = False
                self._profile_dirty.pop("New profile", None)
            if name in profiles:
                QMessageBox.warning(self, "Duplicate Name", "Profile already exists.")
                continue
            profiles[name] = {
                "voices": [],
                "language": self.language_combo.currentData(),
            }
            save_profiles(profiles)
            self.profile_list.addItem(
                QListWidgetItem(
                    QIcon(get_resource_path("abogen.assets", "profile.png")), name
                )
            )
            self.profile_list.setCurrentRow(self.profile_list.count() - 1)
            # reset UI mixers
            for vm in self.voice_mixers:
                vm.checkbox.setChecked(False)
                vm.spin_box.setValue(1.0)
            parent = self.parent()
            if hasattr(parent, "populate_profiles_in_voice_combo"):
                parent.populate_profiles_in_voice_combo()
            break
        self.update_profile_save_buttons()
        self.update_profile_list_colors()
        self.update_weighted_sums()

    def export_all_profiles(self):
        # Prevent export if any profile has total weight 0
        profiles = load_profiles()
        for name, weights in profiles.items():
            total = 0
            voices = weights.get("voices", [])
            if isinstance(voices, list):
                for entry in voices:
                    if (
                        isinstance(entry, (list, tuple))
                        and len(entry) == 2
                        and isinstance(entry[1], (int, float))
                    ):
                        total += entry[1]
            if total == 0:
                QMessageBox.warning(
                    self,
                    "Export Blocked",
                    f"Profile '{name}' has no voices selected (total weight is 0). Please fix before exporting.",
                )
                return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Profiles", "voice_profiles", "JSON Files (*.json)"
        )
        if path:
            export_profiles(path)

    def import_profiles_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Profiles", "", "JSON Files (*.json)"
        )
        if path:
            from abogen.voice_profiles import load_profiles, save_profiles

            # Try to read the file and count profiles
            try:
                import json

                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # always expect abogen_voice_profiles wrapper
                if not (isinstance(data, dict) and "abogen_voice_profiles" in data):
                    QMessageBox.warning(
                        self,
                        "Invalid File",
                        "This file is not a valid abogen voice profiles file.",
                    )
                    return
                imported_profiles = data["abogen_voice_profiles"]
                if not isinstance(imported_profiles, dict):
                    QMessageBox.warning(
                        self,
                        "Invalid File",
                        "This file is not a valid abogen voice profiles file.",
                    )
                    return
                count = len(imported_profiles)
            except Exception:
                QMessageBox.warning(
                    self, "Import Error", "Could not read the selected file."
                )
                return
            if count == 0:
                QMessageBox.information(
                    self, "No Profiles", "No profiles found in the selected file."
                )
                return
            profiles = load_profiles()
            collisions = [name for name in imported_profiles if name in profiles]
            # Combine prompts: show both import count and overwrite count if any
            if count == 1:
                orig_name = next(iter(imported_profiles.keys()))
                msg = f"Profile '{orig_name}' will be imported."
                if collisions:
                    msg += f"\nThis will overwrite an existing profile."
                msg += "\nContinue?"
                reply = QMessageBox.question(
                    self,
                    "Import Profile",
                    msg,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                profiles.update(imported_profiles)
                save_profiles(profiles)
                QMessageBox.information(
                    self,
                    "Profile Imported",
                    f"Profile '{orig_name}' imported successfully.",
                )
            else:
                msg = f"{count} profiles will be imported."
                if collisions:
                    msg += f"\n{len(collisions)} profile(s) will be overwritten."
                msg += "\nContinue?"
                reply = QMessageBox.question(
                    self,
                    "Import Profiles",
                    msg,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                profiles.update(imported_profiles)
                save_profiles(profiles)
                QMessageBox.information(
                    self,
                    "Profiles Imported",
                    f"{count} profiles imported successfully.",
                )
            # Refresh list
            self.profile_list.clear()
            profiles = load_profiles()
            for nm in profiles:
                self.profile_list.addItem(
                    QListWidgetItem(
                        QIcon(get_resource_path("abogen.assets", "profile.png")), nm
                    )
                )
            if self.profile_list.count() > 0:
                self.profile_list.setCurrentRow(0)
            parent = self.parent()
            if hasattr(parent, "populate_profiles_in_voice_combo"):
                parent.populate_profiles_in_voice_combo()
            self._virtual_new_profile = False
        self.update_profile_save_buttons()
        self.update_profile_list_colors()

    def show_profile_context_menu(self, pos):
        item = self.profile_list.itemAt(pos)
        if not item:
            return
        name = item.text().lstrip("*")
        menu = QMenu(self)
        rename_act = QAction("Rename", self)
        delete_act = QAction("Delete", self)
        dup_act = QAction("Duplicate", self)
        export_act = QAction("Export this profile", self)
        menu.addAction(rename_act)
        menu.addAction(dup_act)
        menu.addAction(export_act)
        menu.addAction(delete_act)
        act = menu.exec(self.profile_list.viewport().mapToGlobal(pos))
        if act == rename_act:
            self.rename_profile(item)
        elif act == delete_act:
            self.delete_profile(item)
        elif act == dup_act:
            self.duplicate_profile(item)
        elif act == export_act:
            self.export_selected_profile_item(item)

    def export_selected_profile_item(self, item):
        if not item:
            return
        name = item.text().lstrip("*")
        profiles = load_profiles()
        weights = profiles.get(name, {}).get("voices", [])
        total = 0
        if isinstance(weights, list):
            for entry in weights:
                if (
                    isinstance(entry, (list, tuple))
                    and len(entry) == 2
                    and isinstance(entry[1], (int, float))
                ):
                    total += entry[1]
        if total == 0:
            QMessageBox.warning(
                self,
                "Export Blocked",
                f"Profile '{name}' has no voices selected (total weight is 0). Please fix before exporting.",
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Profile", f"{name}.json", "JSON Files (*.json)"
        )
        if path:
            # Use abogen_voice_profiles wrapper for single profile export
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {"abogen_voice_profiles": {name: profiles.get(name, {})}},
                    f,
                    indent=2,
                )

    def rename_profile(self, item):
        name = item.text().lstrip("*")
        # block if profile has unsaved changes and it's not a virtual New profile
        if self._profile_dirty.get(name, False) and not (
            self._virtual_new_profile and name == "New profile"
        ):
            QMessageBox.warning(
                self, "Unsaved Changes", "Please save the profile before renaming."
            )
            return
        old = item.text().lstrip("*")
        import re

        while True:
            new, ok = QInputDialog.getText(
                self, "Rename Profile", f"Profile name:", text=old
            )
            if not ok or not new or new == old:
                break
            new = new.strip()  # Remove leading/trailing spaces
            if not new:
                continue
            if not re.match(r"^[\w\- ]+$", new):
                QMessageBox.warning(
                    self,
                    "Invalid Name",
                    "Profile name can only contain letters, numbers, spaces, underscores, and hyphens.",
                )
                continue

            profiles = load_profiles()
            if new in profiles:
                QMessageBox.warning(self, "Duplicate Name", "Profile already exists.")
                continue

            # Special case for renaming the virtual "New profile"
            if self._virtual_new_profile and name == "New profile":
                # Create the profile with the new name
                profiles[new] = {
                    "voices": self.get_selected_voices(),
                    "language": self.language_combo.currentData(),
                }
                save_profiles(profiles)

                # Update tracking properties
                self._virtual_new_profile = False
                self._profile_dirty.pop("New profile", None)
                self._profile_dirty[new] = False

                # Update the current profile name
                self.current_profile = new
                item.setText(new)
            else:
                # Standard renaming for regular profiles
                profiles[new] = profiles.pop(old)
                save_profiles(profiles)
                item.setText(new)

                # Update the current profile name if it was renamed
                if self.current_profile == old:
                    self.current_profile = new

            parent = self.parent()
            if hasattr(parent, "populate_profiles_in_voice_combo"):
                parent.populate_profiles_in_voice_combo()
            break
        self.update_profile_save_buttons()
        self.update_profile_list_colors()

    def delete_profile(self, item):
        name = item.text().lstrip("*")
        if self._virtual_new_profile and name == "New profile":
            row = self.profile_list.row(item)
            self.profile_list.takeItem(row)
            self._virtual_new_profile = False
            self._profile_dirty.pop("New profile", None)
            self.update_profile_save_buttons()
            self.update_profile_list_colors()
            return
        reply = QMessageBox.question(
            self,
            "Delete Profile",
            f"Delete profile '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_profile(name)
            row = self.profile_list.row(item)
            self.profile_list.takeItem(row)
            parent = self.parent()
            if hasattr(parent, "populate_profiles_in_voice_combo"):
                parent.populate_profiles_in_voice_combo()
        self.update_profile_save_buttons()
        self.update_profile_list_colors()

    def duplicate_profile(self, item):
        name = item.text().lstrip("*")
        # block duplicating if profile has unsaved changes
        if self._profile_dirty.get(name, False):
            QMessageBox.warning(
                self, "Unsaved Changes", "Please save the profile before duplicating."
            )
            return
        src = item.text().lstrip("*")
        profiles = load_profiles()
        base = f"{src}_duplicate"
        new = base
        i = 1
        while new in profiles:
            new = f"{base}{i}"
            i += 1
        duplicate_profile(src, new)
        self.profile_list.addItem(
            QListWidgetItem(
                QIcon(get_resource_path("abogen.assets", "profile.png")), new
            )
        )
        parent = self.parent()
        if hasattr(parent, "populate_profiles_in_voice_combo"):
            parent.populate_profiles_in_voice_combo()
        self.update_profile_save_buttons()
        self.update_profile_list_colors()

    def update_profile_save_buttons(self):
        # Remove all save buttons first
        for i in range(self.profile_list.count()):
            self.profile_list.setItemWidget(self.profile_list.item(i), None)
        # Add save button to dirty profiles
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            name = item.text().lstrip("*")
            if item.text().startswith("*"):
                widget = SaveButtonWidget(
                    self.profile_list, name, self.save_profile_by_name
                )
                self.profile_list.setItemWidget(item, widget)

    def update_profile_list_colors(self):
        from PyQt6.QtCore import Qt

        profiles = load_profiles()
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            name = item.text().lstrip("*")
            if self._virtual_new_profile and name == "New profile":
                color = self._parse_rgba_to_qcolor(COLORS.get("YELLOW_BACKGROUND"))
                item.setData(Qt.ItemDataRole.BackgroundRole, color)
            elif item.text().startswith("*"):
                color = self._parse_rgba_to_qcolor(COLORS.get("YELLOW_BACKGROUND"))
                item.setData(Qt.ItemDataRole.BackgroundRole, color)
            else:
                item.setData(
                    Qt.ItemDataRole.BackgroundRole,
                    self.profile_list.palette().base().color(),
                )
                weights = profiles.get(name, {}).get("voices", [])
                total = 0
                if isinstance(weights, list):
                    for entry in weights:
                        if (
                            isinstance(entry, (list, tuple))
                            and len(entry) == 2
                            and isinstance(entry[1], (int, float))
                        ):
                            total += entry[1]
                if total == 0:
                    color = self._parse_rgba_to_qcolor(COLORS.get("RED_BACKGROUND"))
                    item.setData(Qt.ItemDataRole.BackgroundRole, color)
        self.update_profile_save_buttons()

    def preview_current_mix(self):
        # Disable preview until playback completes
        self.btn_preview_mix.setEnabled(False)
        self.btn_preview_mix.setText("Loading...")
        self._loading = True
        parent = self.parent()
        if parent and hasattr(parent, "preview_voice"):
            # Apply mixed voices and selected language
            parent.mixed_voice_state = self.get_selected_voices()
            parent.selected_profile_name = None
            lang = self.language_combo.currentData()
            parent.selected_lang = lang
            parent.subtitle_combo.setEnabled(
                lang in SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION
            )
            # Reset start flag and trigger preview
            self._started = False
            parent.preview_voice()
            # Poll preview_playing: wait for start then end
            self._preview_poll_timer = QTimer(self)
            self._preview_poll_timer.timeout.connect(self._check_preview_done)
            self._preview_poll_timer.start(200)

    def _check_preview_done(self):
        parent = self.parent()
        if parent and hasattr(parent, "preview_playing"):
            # Mark when playback starts
            if parent.preview_playing:
                self._started = True
                # Update button text to "Playing..." when playback starts
                self.btn_preview_mix.setText("Playing...")
            # Once started and then stopped, re-enable
            elif getattr(self, "_started", False):
                self.btn_preview_mix.setEnabled(True)
                self.btn_preview_mix.setText("Preview")
                self._loading = False
                self._preview_poll_timer.stop()
