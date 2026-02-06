"""
Pre-download dialog and worker for Abogen

This module consolidates pre-download logic for Kokoro voices and model
and spaCy language models. The code favors clarity, avoids duplication,
and handles optional dependencies gracefully.
"""

from typing import List, Optional, Tuple
import importlib
import importlib.util

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpacerItem,
    QSizePolicy,
)
from PyQt6.QtCore import QThread, pyqtSignal

from abogen.constants import COLORS, VOICES_INTERNAL
from abogen.spacy_utils import SPACY_MODELS
import abogen.hf_tracker


# Helpers
def _unique_sorted_models() -> List[str]:
    """Return a sorted list of unique spaCy model package names."""
    return sorted(set(SPACY_MODELS.values()))


def _is_package_installed(pkg_name: str) -> bool:
    """Return True if a package with the given name can be imported (site-packages)."""
    try:
        return importlib.util.find_spec(pkg_name) is not None
    except Exception:
        return False


# NOTE: explicit HF cache helper removed; we use try_to_load_from_cache in-scope where needed


class PreDownloadWorker(QThread):
    """Worker thread to download required models/voices.

    Emits human-readable messages via `progress`. Uses `category_done` to indicate
    a category (voices/model/spacy) finished successfully. Emits `error` on exception
    and `finished` after all work completes.
    """

    # Emit (category, status, message)
    progress = pyqtSignal(str, str, str)
    category_done = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = False
        # repo and filenames used for Kokoro model
        self._repo_id = "hexgrad/Kokoro-82M"
        self._model_files = ["kokoro-v1_0.pth", "config.json"]
        # Track download success per category
        self._voices_success = False
        self._model_success = False
        self._spacy_success = False
        # Suppress HF tracker warnings during downloads
        self._original_emitter = abogen.hf_tracker.show_warning_signal_emitter

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        # Suppress HF tracker warnings during downloads
        abogen.hf_tracker.show_warning_signal_emitter = None
        try:
            self._download_kokoro_voices()
            if self._cancelled:
                return
            if self._voices_success:
                self.category_done.emit("voices")

            self._download_kokoro_model()
            if self._cancelled:
                return
            if self._model_success:
                self.category_done.emit("model")

            self._download_spacy_models()
            if self._cancelled:
                return
            if self._spacy_success:
                self.category_done.emit("spacy")

            self.finished.emit()
        except Exception as exc:  # pragma: no cover - best-effort reporting
            self.error.emit(str(exc))
        finally:
            # Restore original emitter
            abogen.hf_tracker.show_warning_signal_emitter = self._original_emitter

    # Kokoro voices
    def _download_kokoro_voices(self) -> None:
        self._voices_success = True
        try:
            from huggingface_hub import hf_hub_download, try_to_load_from_cache
        except Exception:
            self.progress.emit(
                "voice", "warning", "huggingface_hub not installed, skipping voices..."
            )
            self._voices_success = False
            return

        voice_list = VOICES_INTERNAL
        for idx, voice in enumerate(voice_list, start=1):
            if self._cancelled:
                self._voices_success = False
                return
            filename = f"voices/{voice}.pt"
            if try_to_load_from_cache(repo_id=self._repo_id, filename=filename):
                self.progress.emit(
                    "voice",
                    "installed",
                    f"{idx}/{len(voice_list)}: {voice} already present",
                )
                continue
            self.progress.emit(
                "voice", "downloading", f"{idx}/{len(voice_list)}: {voice}..."
            )
            try:
                hf_hub_download(repo_id=self._repo_id, filename=filename)
                self.progress.emit("voice", "downloaded", f"{voice} downloaded")
            except Exception as exc:
                self.progress.emit(
                    "voice", "warning", f"could not download {voice}: {exc}"
                )
                self._voices_success = False

    # Kokoro model
    def _download_kokoro_model(self) -> None:
        self._model_success = True
        try:
            from huggingface_hub import hf_hub_download, try_to_load_from_cache
        except Exception:
            self.progress.emit(
                "model", "warning", "huggingface_hub not installed, skipping model..."
            )
            self._model_success = False
            return
        for fname in self._model_files:
            if self._cancelled:
                self._model_success = False
                return
            category = "config" if fname == "config.json" else "model"
            if try_to_load_from_cache(repo_id=self._repo_id, filename=fname):
                self.progress.emit(
                    category, "installed", f"file {fname} already present"
                )
                continue
            self.progress.emit(category, "downloading", f"file {fname}...")
            try:
                hf_hub_download(repo_id=self._repo_id, filename=fname)
                self.progress.emit(category, "downloaded", f"file {fname} downloaded")
            except Exception as exc:
                self.progress.emit(
                    category, "warning", f"could not download file {fname}: {exc}"
                )
                self._model_success = False

    # spaCy models
    def _download_spacy_models(self) -> None:
        """Download spaCy models. Prefer missing models provided by parent.

        Parent dialog will populate _spacy_models_missing during checking.
        """
        self._spacy_success = True
        # Determine which models to process: prefer parent-provided missing list to avoid
        # re-checking everything; otherwise use the full unique list.
        parent = self.parent()
        models_to_process: List[str] = _unique_sorted_models()
        try:
            if (
                parent is not None
                and hasattr(parent, "_spacy_models_missing")
                and parent._spacy_models_missing
            ):
                models_to_process = list(dict.fromkeys(parent._spacy_models_missing))
        except Exception:
            pass

        # If spaCy is not available to run the CLI, skip gracefully
        try:
            import spacy.cli as _spacy_cli
        except Exception:
            self.progress.emit(
                "spacy", "warning", "spaCy not available, skipping spaCy models..."
            )
            self._spacy_success = False
            return

        for idx, model_name in enumerate(models_to_process, start=1):
            if self._cancelled:
                self._spacy_success = False
                return
            if _is_package_installed(model_name):
                self.progress.emit(
                    "spacy",
                    "installed",
                    f"{idx}/{len(models_to_process)}: {model_name} already installed",
                )
                continue
            self.progress.emit(
                "spacy",
                "downloading",
                f"{idx}/{len(models_to_process)}: {model_name}...",
            )
            try:
                _spacy_cli.download(model_name)
                self.progress.emit("spacy", "downloaded", f"{model_name} downloaded")
            except Exception as exc:
                self.progress.emit(
                    "spacy", "warning", f"could not download {model_name}: {exc}"
                )
                self._spacy_success = False


class PreDownloadDialog(QDialog):
    """Dialog to show and control pre-download process."""

    VOICE_PREFIX = "Kokoro voices: "
    MODEL_PREFIX = "Kokoro model: "
    CONFIG_PREFIX = "Kokoro config: "
    SPACY_PREFIX = "spaCy models: "

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pre-download Models and Voices")
        self.setMinimumWidth(500)
        self.worker: Optional[PreDownloadWorker] = None
        self.has_missing = False
        self._spacy_models_checked: List[tuple] = []
        self._spacy_models_missing: List[str] = []
        self._status_worker = None

        # Map keywords to (label, prefix) - labels filled after UI creation
        self.status_map = {
            "voice": (None, self.VOICE_PREFIX),
            "spacy": (None, self.SPACY_PREFIX),
            "model": (None, self.MODEL_PREFIX),
            "config": (None, self.CONFIG_PREFIX),
        }

        self.category_map = {
            "voices": ["voice"],
            "model": ["model", "config"],
            "spacy": ["spacy"],
        }

        self._setup_ui()
        self._start_status_check()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(15, 0, 15, 15)

        desc = QLabel(
            "You can pre-download all required models and voices for offline use.\n"
            "This includes Kokoro voices, Kokoro model (and config), and spaCy models."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Status rows
        status_layout = QVBoxLayout()
        status_title = QLabel("<b>Current Status:</b>")
        status_layout.addWidget(status_title)

        self.voices_status = QLabel(self.VOICE_PREFIX + "⏳ Checking...")
        row = QHBoxLayout()
        row.addWidget(self.voices_status)
        row.addStretch()
        status_layout.addLayout(row)

        self.model_status = QLabel(self.MODEL_PREFIX + "⏳ Checking...")
        row = QHBoxLayout()
        row.addWidget(self.model_status)
        row.addStretch()
        status_layout.addLayout(row)

        self.config_status = QLabel(self.CONFIG_PREFIX + "⏳ Checking...")
        row = QHBoxLayout()
        row.addWidget(self.config_status)
        row.addStretch()
        status_layout.addLayout(row)

        self.spacy_status = QLabel(self.SPACY_PREFIX + "⏳ Checking...")
        row = QHBoxLayout()
        row.addWidget(self.spacy_status)
        row.addStretch()
        status_layout.addLayout(row)

        # register labels
        self.status_map["voice"] = (self.voices_status, self.VOICE_PREFIX)
        self.status_map["model"] = (self.model_status, self.MODEL_PREFIX)
        self.status_map["config"] = (self.config_status, self.CONFIG_PREFIX)
        self.status_map["spacy"] = (self.spacy_status, self.SPACY_PREFIX)

        layout.addLayout(status_layout)

        layout.addItem(
            QSpacerItem(0, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        )

        # Buttons
        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        self.download_btn = QPushButton("Download all")
        self.download_btn.setMinimumWidth(100)
        self.download_btn.setMinimumHeight(35)
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._start_download)
        button_row.addWidget(self.download_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.setMinimumWidth(100)
        self.close_btn.setMinimumHeight(35)
        self.close_btn.clicked.connect(self._handle_close)
        button_row.addWidget(self.close_btn)

        layout.addLayout(button_row)
        self.adjustSize()

    # Status checking worker
    class StatusCheckWorker(QThread):
        voices_checked = pyqtSignal(bool, list)
        model_checked = pyqtSignal(bool)
        config_checked = pyqtSignal(bool)
        spacy_model_checking = pyqtSignal(str)
        spacy_model_result = pyqtSignal(str, bool)
        spacy_checked = pyqtSignal(bool, list)

        def run(self):
            parent = self.parent()
            if parent is None:
                return

            voices_ok, missing_voices = parent._check_kokoro_voices()
            self.voices_checked.emit(voices_ok, missing_voices)

            model_ok = parent._check_kokoro_model()
            self.model_checked.emit(model_ok)

            config_ok = parent._check_kokoro_config()
            self.config_checked.emit(config_ok)

            # Check spaCy models by package name to detect site-package installs
            unique = _unique_sorted_models()
            missing: List[str] = []
            for name in unique:
                self.spacy_model_checking.emit(name)
                ok = _is_package_installed(name)
                self.spacy_model_result.emit(name, ok)
                if not ok:
                    missing.append(name)
            parent._spacy_models_missing = missing
            self.spacy_checked.emit(len(missing) == 0, missing)

    def _start_status_check(self) -> None:
        self._status_worker = self.StatusCheckWorker(self)
        self._status_worker.voices_checked.connect(self._update_voices_status)
        self._status_worker.model_checked.connect(self._update_model_status)
        self._status_worker.config_checked.connect(self._update_config_status)
        self._status_worker.spacy_model_checking.connect(self._spacy_model_checking)
        self._status_worker.spacy_model_result.connect(self._spacy_model_result)
        self._status_worker.spacy_checked.connect(self._update_spacy_status)

        # These are initialized in __init__ to keep consistent object state

        # Set checking visual state
        for lbl in (
            self.voices_status,
            self.model_status,
            self.config_status,
            self.spacy_status,
        ):
            lbl.setStyleSheet(f"color: {COLORS['ORANGE']};")

        self.spacy_status.setText(self.SPACY_PREFIX + "⏳ Checking...")
        self._status_worker.start()

    # UI update callbacks
    def _spacy_model_checking(self, name: str) -> None:
        self.spacy_status.setText(f"{self.SPACY_PREFIX}Checking {name}...")

    def _spacy_model_result(self, name: str, ok: bool) -> None:
        self._spacy_models_checked.append((name, ok))
        if not ok and name not in self._spacy_models_missing:
            self._spacy_models_missing.append(name)
        checked = len(self._spacy_models_checked)
        missing_count = len(self._spacy_models_missing)
        if missing_count:
            self.spacy_status.setText(
                f"{self.SPACY_PREFIX}{checked} checked, {missing_count} missing..."
            )
        else:
            self.spacy_status.setText(f"{self.SPACY_PREFIX}{checked} checked...")

    def _update_voices_status(self, ok: bool, missing: List[str]) -> None:
        if ok:
            self._set_status("voice", "✓ Downloaded", COLORS["GREEN"])
        else:
            self.has_missing = True
            if missing:
                self._set_status(
                    "voice", f"✗ Missing {len(missing)} voices", COLORS["RED"]
                )
            else:
                self._set_status("voice", "✗ Not downloaded", COLORS["RED"])

    def _update_model_status(self, ok: bool) -> None:
        if ok:
            self._set_status("model", "✓ Downloaded", COLORS["GREEN"])
        else:
            self.has_missing = True
            self._set_status("model", "✗ Not downloaded", COLORS["RED"])

    def _update_config_status(self, ok: bool) -> None:
        if ok:
            self._set_status("config", "✓ Downloaded", COLORS["GREEN"])
        else:
            self.has_missing = True
            self._set_status("config", "✗ Not downloaded", COLORS["RED"])

    def _update_spacy_status(self, ok: bool, missing: List[str]) -> None:
        if ok:
            self._set_status("spacy", "✓ Downloaded", COLORS["GREEN"])
        else:
            self.has_missing = True
            if missing:
                self._set_status(
                    "spacy", f"✗ Missing {len(missing)} model(s)", COLORS["RED"]
                )
            else:
                self._set_status("spacy", "✗ Not downloaded", COLORS["RED"])
        self.download_btn.setEnabled(self.has_missing)

    def _set_status(self, key: str, text: str, color: str) -> None:
        lbl, prefix = self.status_map.get(key, (None, ""))
        if not lbl:
            return
        lbl.setText(prefix + text)
        lbl.setStyleSheet(f"color: {color};")

    # Helper checks
    def _check_kokoro_voices(self) -> Tuple[bool, List[str]]:
        """Return (ok, missing_list) for Kokoro voices check."""
        missing = []
        try:
            from huggingface_hub import try_to_load_from_cache

            for voice in VOICES_INTERNAL:
                if not try_to_load_from_cache(
                    repo_id="hexgrad/Kokoro-82M", filename=f"voices/{voice}.pt"
                ):
                    missing.append(voice)
        except Exception:
            # If HF missing, report all as missing
            return False, list(VOICES_INTERNAL)
        return (len(missing) == 0), missing

    def _check_kokoro_model(self) -> bool:
        try:
            from huggingface_hub import try_to_load_from_cache

            return (
                try_to_load_from_cache(
                    repo_id="hexgrad/Kokoro-82M", filename="kokoro-v1_0.pth"
                )
                is not None
            )
        except Exception:
            return False

    def _check_kokoro_config(self) -> bool:
        try:
            from huggingface_hub import try_to_load_from_cache

            return (
                try_to_load_from_cache(
                    repo_id="hexgrad/Kokoro-82M", filename="config.json"
                )
                is not None
            )
        except Exception:
            return False

    def _check_spacy_models(self) -> bool:
        unique = _unique_sorted_models()
        missing = [m for m in unique if not _is_package_installed(m)]
        self._spacy_models_missing = missing
        return len(missing) == 0

    # Download control
    def _start_download(self) -> None:
        self.download_btn.setEnabled(False)
        self.download_btn.setText("Downloading...")
        # mark the start of downloads; this triggers the labels
        self._on_progress("system", "starting", "Processing, please wait...")
        self.worker = PreDownloadWorker(self)
        self.worker.progress.connect(self._on_progress)
        self.worker.category_done.connect(self._on_category_done)
        self.worker.finished.connect(self._on_download_finished)
        self.worker.error.connect(self._on_download_error)
        self.worker.start()

    def _on_progress(self, category: str, status: str, message: str) -> None:
        """Map worker (category, status, message) to UI label updates.

        Status is one of: 'downloading', 'installed', 'downloaded', 'warning', 'starting'.
        Category is one of: 'voice', 'model', 'spacy', 'config', or 'system'.
        """
        try:
            # If the category targets a specific label, update directly
            if category in self.status_map:
                lbl, prefix = self.status_map[category]
                if not lbl:
                    return
                # Compose message and set color based on status token
                full_text = prefix + message
                if len(full_text) > 60:
                    display_text = full_text[:57] + "..."
                    lbl.setText(display_text)
                    lbl.setToolTip(full_text)
                else:
                    lbl.setText(full_text)
                    lbl.setToolTip("")  # Clear tooltip if not needed
                if status == "downloading":
                    lbl.setStyleSheet(f"color: {COLORS['ORANGE']};")
                elif status in ("installed", "downloaded"):
                    lbl.setStyleSheet(f"color: {COLORS['GREEN']};")
                elif status == "warning":
                    lbl.setStyleSheet(f"color: {COLORS['RED']};")
                elif status == "error":
                    lbl.setStyleSheet(f"color: {COLORS['RED']};")
                return

            # System-level messages
            if category == "system":
                if status == "starting":
                    for k in self.status_map:
                        lbl, prefix = self.status_map[k]
                        if lbl:
                            lbl.setText(prefix + "Processing, please wait...")
                            lbl.setStyleSheet(f"color: {COLORS['ORANGE']};")
                # other system statuses don't require action
                return
        except Exception:
            # Do not let UI thread crash on unexpected worker message
            pass

    def _on_category_done(self, category: str) -> None:
        for key in self.category_map.get(category, []):
            self._set_status(key, "✓ Downloaded", COLORS["GREEN"])

    def _on_download_finished(self) -> None:
        self.has_missing = False
        self.download_btn.setText("Download all")
        self.download_btn.setEnabled(False)

    def _on_download_error(self, error_msg: str) -> None:
        self.download_btn.setText("Download all")
        self.download_btn.setEnabled(True)
        for key in self.status_map:
            self._set_status(key, f"✗ Error - {error_msg}", COLORS["RED"])

    def _handle_close(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        self.accept()

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        super().closeEvent(event)
