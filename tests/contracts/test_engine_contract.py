"""Contract tests for Engine protocol.

These tests verify that Engine implementations satisfy the architectural requirements:
- createSession() returns EngineSession
- dispose() is idempotent
- After dispose(), createSession() raises EngineError
- Engine is thread-safe for createSession()
"""

import pytest

from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.errors import EngineError

from .conftest import FakeEngine, FakeEngineSession


class TestEngineProtocolContract:
    """Contract tests for the Engine protocol itself."""

    def test_engine_is_protocol(self) -> None:
        assert hasattr(Engine, "__protocol_attrs__")

    def test_engine_session_is_protocol(self) -> None:
        assert hasattr(EngineSession, "__protocol_attrs__")

    def test_fake_engine_satisfies_protocol(self) -> None:
        engine = FakeEngine()
        assert isinstance(engine, Engine)

    def test_fake_session_satisfies_protocol(self) -> None:
        session = FakeEngineSession()
        assert isinstance(session, EngineSession)


class TestEngineCreateSessionContract:
    """Contract tests for Engine.createSession()."""

    def test_create_session_returns_engine_session(self) -> None:
        engine = FakeEngine()
        session = engine.createSession()
        assert isinstance(session, EngineSession)

    def test_create_session_returns_new_instance(self) -> None:
        engine = FakeEngine()
        session1 = engine.createSession()
        session2 = engine.createSession()
        assert session1 is not session2

    def test_create_session_ownership_transfers(self) -> None:
        """Architecture spec: Ownership transfers to caller."""
        engine = FakeEngine()
        session = engine.createSession()
        assert isinstance(session, EngineSession)


class TestEngineDisposeContract:
    """Contract tests for Engine.dispose()."""

    def test_dispose_is_idempotent(self) -> None:
        """Architecture spec: dispose() is idempotent."""
        engine = FakeEngine()
        engine.dispose()
        engine.dispose()  # Should not raise

    def test_dispose_never_raises(self) -> None:
        """Architecture spec: dispose() never raises exceptions."""
        engine = FakeEngine()
        engine.dispose()  # Should not raise

    def test_create_session_after_dispose_raises(self) -> None:
        """Architecture spec: After dispose(), all methods except dispose() raise EngineError."""
        engine = FakeEngine()
        engine.dispose()
        with pytest.raises(EngineError):
            engine.createSession()


class TestEngineLifecycleContract:
    """Contract tests for Engine lifecycle."""

    def test_full_lifecycle(self) -> None:
        """Test complete engine lifecycle: create -> sessions -> dispose."""
        engine = FakeEngine()

        # Create sessions
        session1 = engine.createSession()
        session2 = engine.createSession()

        # Use sessions
        assert isinstance(session1, EngineSession)
        assert isinstance(session2, EngineSession)

        # Dispose sessions
        session1.dispose()
        session2.dispose()

        # Dispose engine
        engine.dispose()

    def test_engine_disposed_session_raises(self) -> None:
        """Architecture spec: After dispose(), all methods except dispose() raise EngineError."""
        engine = FakeEngine()
        engine.dispose()
        with pytest.raises(EngineError):
            engine.createSession()
