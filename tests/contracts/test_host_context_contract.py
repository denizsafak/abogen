"""Contract tests for HostContext.

These tests verify that HostContext satisfies the architectural requirements:
- Minimal (3 fields maximum)
- Frozen dataclass
- config_dir: Path
- logger: Logger
- http_client: HttpClient protocol
"""

import logging
from pathlib import Path

import pytest

from abogen.tts_plugin.host_context import HttpClient, HostContext


class TestHostContextContract:
    """Contract tests for HostContext dataclass."""

    def test_is_frozen_dataclass(self) -> None:
        assert hasattr(HostContext, "__dataclass_params__")
        assert HostContext.__dataclass_params__.frozen is True

    def test_required_fields(self, tmp_path: Path) -> None:
        logger = logging.getLogger("test")

        class FakeClient:
            def get(self, url: str, **kwargs: object) -> object:
                return None

            def post(self, url: str, **kwargs: object) -> object:
                return None

        ctx = HostContext(
            config_dir=tmp_path,
            logger=logger,
            http_client=FakeClient(),
        )
        assert ctx.config_dir == tmp_path
        assert ctx.logger is logger

    def test_immutability(self, tmp_path: Path) -> None:
        class FakeClient:
            def get(self, url: str, **kwargs: object) -> object:
                return None

            def post(self, url: str, **kwargs: object) -> object:
                return None

        ctx = HostContext(
            config_dir=tmp_path,
            logger=logging.getLogger("test"),
            http_client=FakeClient(),
        )
        with pytest.raises(AttributeError):
            ctx.config_dir = Path("/other")  # type: ignore[misc]

    def test_max_three_fields(self) -> None:
        """Architecture spec: HostContext is minimal (3 fields max)."""
        import dataclasses

        fields = dataclasses.fields(HostContext)
        assert len(fields) <= 3


class TestHttpClientProtocolContract:
    """Contract tests for HttpClient protocol."""

    def test_http_client_is_protocol(self) -> None:
        assert hasattr(HttpClient, "__protocol_attrs__")

    def test_http_client_has_get(self) -> None:
        assert hasattr(HttpClient, "get")

    def test_http_client_has_post(self) -> None:
        assert hasattr(HttpClient, "post")

    def test_http_client_satisfied(self) -> None:
        class FakeClient:
            def get(self, url: str, **kwargs: object) -> object:
                return None

            def post(self, url: str, **kwargs: object) -> object:
                return None

        client = FakeClient()
        assert isinstance(client, HttpClient)
