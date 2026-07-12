"""Contract tests for error hierarchy.

These tests verify that the error hierarchy satisfies the architectural requirements:
- All errors inherit from EngineError
- EngineError inherits from Exception
- Each error type is properly classified
"""

import pytest

from abogen.tts_plugin.errors import (
    CancelledError,
    ConfigurationError,
    EngineError,
    InternalError,
    InvalidInputError,
    ModelLoadError,
    ModelNotFoundError,
    NetworkError,
)


class TestErrorHierarchyContract:
    """Contract tests for the error hierarchy."""

    def test_engine_error_is_exception(self) -> None:
        assert issubclass(EngineError, Exception)

    def test_all_errors_inherit_from_engine_error(self) -> None:
        error_classes = [
            ModelNotFoundError,
            ModelLoadError,
            NetworkError,
            InvalidInputError,
            ConfigurationError,
            CancelledError,
            InternalError,
        ]
        for error_class in error_classes:
            assert issubclass(error_class, EngineError), (
                f"{error_class.__name__} must inherit from EngineError"
            )

    def test_all_errors_are_catchable(self) -> None:
        error_classes = [
            EngineError,
            ModelNotFoundError,
            ModelLoadError,
            NetworkError,
            InvalidInputError,
            ConfigurationError,
            CancelledError,
            InternalError,
        ]
        for error_class in error_classes:
            with pytest.raises(EngineError):
                raise error_class("test message")

    def test_error_message_preserved(self) -> None:
        msg = "Model not found: bert-base"
        with pytest.raises(ModelNotFoundError, match=msg):
            raise ModelNotFoundError(msg)

    def test_error_can_be_caught_as_engine_error(self) -> None:
        with pytest.raises(EngineError):
            raise ModelNotFoundError("test")

    def test_cancelled_error_is_engine_error(self) -> None:
        """CancelledError is a subtype of EngineError per architecture spec."""
        assert issubclass(CancelledError, EngineError)

    def test_error_hierarchy_no_cycles(self) -> None:
        """Verify no circular inheritance."""
        error_classes = [
            EngineError,
            ModelNotFoundError,
            ModelLoadError,
            NetworkError,
            InvalidInputError,
            ConfigurationError,
            CancelledError,
            InternalError,
        ]
        for cls in error_classes:
            assert cls not in cls.__bases__
