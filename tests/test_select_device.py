import sys
from unittest.mock import patch, MagicMock


class TestSelectDevice:
    """Tests for domain.device.select_device."""

    def test_returns_mps_on_apple_silicon_when_available(self) -> None:
        from abogen.domain.device import select_device

        mock_platform = MagicMock()
        mock_platform.system.return_value = "Darwin"
        mock_platform.processor.return_value = "arm"

        mock_torch = MagicMock()
        mock_torch.backends.mps.is_available.return_value = True
        mock_torch.cuda.is_available.return_value = False

        with patch("abogen.domain.device._platform", mock_platform), \
             patch.dict(sys.modules, {"torch": mock_torch}):
            result = select_device()
        assert result == "mps"

    def test_returns_cpu_on_apple_silicon_when_mps_unavailable(self) -> None:
        from abogen.domain.device import select_device

        mock_platform = MagicMock()
        mock_platform.system.return_value = "Darwin"
        mock_platform.processor.return_value = "arm"

        mock_torch = MagicMock()
        mock_torch.backends.mps.is_available.return_value = False
        mock_torch.cuda.is_available.return_value = False

        with patch("abogen.domain.device._platform", mock_platform), \
             patch.dict(sys.modules, {"torch": mock_torch}):
            result = select_device()
        assert result == "cpu"

    def test_returns_cuda_when_available(self) -> None:
        from abogen.domain.device import select_device

        mock_platform = MagicMock()
        mock_platform.system.return_value = "Linux"
        mock_platform.processor.return_value = "x86_64"

        mock_torch = MagicMock()
        mock_torch.backends.mps.is_available.return_value = False
        mock_torch.cuda.is_available.return_value = True

        with patch("abogen.domain.device._platform", mock_platform), \
             patch.dict(sys.modules, {"torch": mock_torch}):
            result = select_device()
        assert result == "cuda"

    def test_returns_cpu_when_cuda_unavailable(self) -> None:
        from abogen.domain.device import select_device

        mock_platform = MagicMock()
        mock_platform.system.return_value = "Linux"
        mock_platform.processor.return_value = "x86_64"

        mock_torch = MagicMock()
        mock_torch.backends.mps.is_available.return_value = False
        mock_torch.cuda.is_available.return_value = False

        with patch("abogen.domain.device._platform", mock_platform), \
             patch.dict(sys.modules, {"torch": mock_torch}):
            result = select_device()
        assert result == "cpu"

    def test_returns_cpu_when_torch_not_installed(self) -> None:
        from abogen.domain.device import select_device

        mock_platform = MagicMock()
        mock_platform.system.return_value = "Linux"
        mock_platform.processor.return_value = "x86_64"

        with patch("abogen.domain.device._platform", mock_platform), \
             patch.dict(sys.modules, {"torch": None}):
            result = select_device()
        assert result == "cpu"

    def test_handles_torch_import_error(self) -> None:
        from abogen.domain.device import select_device

        mock_platform = MagicMock()
        mock_platform.system.return_value = "Windows"
        mock_platform.processor.return_value = "AMD64"

        with patch("abogen.domain.device._platform", mock_platform), \
             patch.dict(sys.modules, {"torch": None}):
            result = select_device()
        assert result == "cpu"
