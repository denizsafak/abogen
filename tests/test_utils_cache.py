import os
import sys
from pathlib import Path
from typing import Iterable

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def clear_utils_cache():
    import abogen.utils as utils

    getattr(utils.get_user_cache_root, "cache_clear")()
    yield
    getattr(utils.get_user_cache_root, "cache_clear")()


def _clear_env(monkeypatch: pytest.MonkeyPatch, keys: Iterable[str]) -> None:
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def test_abogen_temp_dir_configures_hf_cache(monkeypatch, tmp_path):
    import abogen.utils as utils

    cache_root = tmp_path / "cache-root"
    home_dir = tmp_path / "home"

    monkeypatch.setenv("ABOGEN_TEMP_DIR", str(cache_root))
    monkeypatch.setenv("HOME", str(home_dir))
    _clear_env(
        monkeypatch,
        (
            "XDG_CACHE_HOME",
            "HF_HOME",
            "HUGGINGFACE_HUB_CACHE",
            "TRANSFORMERS_CACHE",
            "ABOGEN_INTERNAL_CACHE_ROOT",
        ),
    )

    root = utils.get_user_cache_root()

    expected_root = os.path.abspath(str(cache_root))
    expected_hf = os.path.join(expected_root, "huggingface")

    assert root == expected_root
    assert os.environ["XDG_CACHE_HOME"] == expected_root
    assert os.environ["HF_HOME"] == expected_hf
    assert os.environ["HUGGINGFACE_HUB_CACHE"] == expected_hf
    assert os.environ["TRANSFORMERS_CACHE"] == expected_hf
