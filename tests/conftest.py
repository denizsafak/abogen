import importlib
import sys

import os

import pytest

# Ensure real optional dependencies are imported before tests that install stubs
# so that available packages (like ebooklib, bs4, numpy) aren't replaced with dummy modules.
for module_name in ("ebooklib", "bs4", "numpy"):
    if module_name not in sys.modules:
        try:
            importlib.import_module(module_name)
        except Exception:
            # On environments without the optional dependency, downstream tests
            # will install lightweight stubs as needed.
            pass


@pytest.fixture(autouse=True, scope="session")
def _isolate_settings_dir(tmp_path_factory: pytest.TempPathFactory):
    settings_dir = tmp_path_factory.mktemp("abogen-settings")
    os.environ["ABOGEN_SETTINGS_DIR"] = str(settings_dir)

    try:
        from abogen.utils import get_user_settings_dir

        get_user_settings_dir.cache_clear()
    except Exception:
        pass

    try:
        from abogen.normalization_settings import clear_cached_settings

        clear_cached_settings()
    except Exception:
        pass

    yield
