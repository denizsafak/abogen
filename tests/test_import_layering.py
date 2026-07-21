"""Import/layering tests for the conversion flow unification.

Verifies that:
- Application layer does not import from PyQt or WebUI
- Adapters import from application/domain (not the other way around)
- All application models are importable without GUI/Flask side effects
"""

import importlib
import sys
from pathlib import Path

import pytest


# ─── Application layer imports ─────────────────────────────────────


class TestApplicationLayerImports:
    """Verify application layer has no PyQt/WebUI imports."""

    APPLICATION_DIR = Path(__file__).parent.parent / "abogen" / "application"

    def _get_python_files(self):
        """Get all Python files in the application directory."""
        return list(self.APPLICATION_DIR.glob("*.py"))

    def test_no_pyqt_imports(self):
        """Application layer must not import from abogen.pyqt."""
        import re

        forbidden = re.compile(r"from\s+abogen\.pyqt|import\s+abogen\.pyqt")
        violations = []

        for py_file in self._get_python_files():
            content = py_file.read_text(encoding="utf-8")
            if forbidden.search(content):
                violations.append(py_file.name)

        assert not violations, f"Application files import from PyQt: {violations}"

    def test_no_webui_imports(self):
        """Application layer must not import from abogen.webui."""
        import re

        forbidden = re.compile(r"from\s+abogen\.webui|import\s+abogen\.webui")
        violations = []

        for py_file in self._get_python_files():
            content = py_file.read_text(encoding="utf-8")
            if forbidden.search(content):
                violations.append(py_file.name)

        assert not violations, f"Application files import from WebUI: {violations}"

    def test_no_flask_imports(self):
        """Application layer must not import Flask."""
        import re

        forbidden = re.compile(r"from\s+flask|import\s+flask")
        violations = []

        for py_file in self._get_python_files():
            content = py_file.read_text(encoding="utf-8")
            if forbidden.search(content):
                violations.append(py_file.name)

        assert not violations, f"Application files import Flask: {violations}"

    def test_no_qthread_imports(self):
        """Application layer must not import QThread."""
        import re

        forbidden = re.compile(r"from\s+PyQt6|import\s+PyQt6")
        violations = []

        for py_file in self._get_python_files():
            content = py_file.read_text(encoding="utf-8")
            if forbidden.search(content):
                violations.append(py_file.name)

        assert not violations, f"Application files import PyQt6: {violations}"


class TestApplicationModelsImportable:
    """Verify application models are importable without side effects."""

    def test_conversion_request_importable(self):
        from abogen.application.conversion_request import ConversionRequest

        assert ConversionRequest is not None

    def test_conversion_models_importable(self):
        from abogen.application.conversion_models import (
            ChapterPlan,
            ConversionPlan,
            IntroOutroSpec,
            OutputLayout,
            SegmentPlan,
        )

        assert all(
            cls is not None
            for cls in [ChapterPlan, ConversionPlan, IntroOutroSpec, OutputLayout, SegmentPlan]
        )

    def test_conversion_result_importable(self):
        from abogen.application.conversion_result import ConversionError, ConversionResult

        assert ConversionResult is not None
        assert ConversionError is not None

    def test_conversion_ports_importable(self):
        from abogen.application.conversion_ports import (
            AudioSink,
            ConversionEvents,
            PipelineProvider,
            ResolvedVoice,
            SubtitleWriter,
            VoiceResolver,
        )

        assert all(
            cls is not None
            for cls in [
                AudioSink,
                ConversionEvents,
                PipelineProvider,
                ResolvedVoice,
                SubtitleWriter,
                VoiceResolver,
            ]
        )

    def test_output_layout_service_importable(self):
        from abogen.application.output_layout_service import (
            resolve_chapter_path,
            resolve_merged_path,
            resolve_output_layout,
            should_merge_output,
        )

        assert all(
            fn is not None
            for fn in [resolve_chapter_path, resolve_merged_path, resolve_output_layout, should_merge_output]
        )

    def test_conversion_planner_importable(self):
        from abogen.application.conversion_planner import build_conversion_plan

        assert build_conversion_plan is not None

    def test_conversion_executor_importable(self):
        from abogen.application.conversion_executor import execute_conversion

        assert execute_conversion is not None

    def test_conversion_service_importable(self):
        from abogen.application.conversion_service import run_conversion

        assert run_conversion is not None


class TestAdapterImports:
    """Verify adapters import from application/domain correctly."""

    def test_webui_adapter_imports_application(self):
        from abogen.webui.conversion_adapter import (
            WebJobEvents,
            WebPipelineProvider,
            WebVoiceResolver,
            build_conversion_request_from_job,
        )

        assert all(
            cls is not None
            for cls in [
                WebJobEvents,
                WebPipelineProvider,
                WebVoiceResolver,
                build_conversion_request_from_job,
            ]
        )

    def test_pyqt_adapter_imports_application(self):
        from abogen.pyqt.conversion_adapter import (
            PyQtEvents,
            PyQtPipelineProvider,
            PyQtVoiceResolver,
            build_conversion_request_from_thread,
        )

        assert all(
            cls is not None
            for cls in [
                PyQtEvents,
                PyQtPipelineProvider,
                PyQtVoiceResolver,
                build_conversion_request_from_thread,
            ]
        )

    def test_webui_adapter_does_not_import_pyqt(self):
        """WebUI adapter must not import from PyQt."""
        import re

        adapter_path = Path(__file__).parent.parent / "abogen" / "webui" / "conversion_adapter.py"
        content = adapter_path.read_text(encoding="utf-8")

        forbidden = re.compile(r"from\s+abogen\.pyqt|import\s+abogen\.pyqt")
        assert not forbidden.search(content), "WebUI adapter imports from PyQt"

    def test_pyqt_adapter_does_not_import_webui(self):
        """PyQt adapter must not import from WebUI."""
        import re

        adapter_path = Path(__file__).parent.parent / "abogen" / "pyqt" / "conversion_adapter.py"
        content = adapter_path.read_text(encoding="utf-8")

        forbidden = re.compile(r"from\s+abogen\.webui|import\s+abogen\.webui")
        assert not forbidden.search(content), "PyQt adapter imports from WebUI"
