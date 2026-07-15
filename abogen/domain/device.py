from __future__ import annotations

import platform as _platform


def select_device() -> str:
    """Return the best available compute device (``"mps"``, ``"cuda"``, or ``"cpu"``).

    Checks ``torch`` availability at runtime so this can be called from
    any context without requiring torch at import time.
    """
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return "cpu"

    system = _platform.system()
    if system == "Darwin" and _platform.processor() == "arm":
        try:
            if torch.backends.mps.is_available():  # type: ignore[union-attr]
                return "mps"
        except Exception:
            pass
        return "cpu"

    try:
        if torch.cuda.is_available():  # type: ignore[union-attr]
            return "cuda"
    except Exception:
        pass
    return "cpu"
