import os
import json
import warnings
import platform
import subprocess
import re
from threading import Thread

# suppress warnings and disable HF hub symlink warnings
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
warnings.filterwarnings("ignore")


def get_resource_path(package, resource):
    """
    Get the path to a resource file, with fallback to local file system.

    Args:
        package (str): Package name containing the resource (e.g., 'abogen.assets')
        resource (str): Resource filename (e.g., 'icon.ico')

    Returns:
        str: Path to the resource file, or None if not found
    """
    from importlib import resources

    # Try using importlib.resources first
    try:
        with resources.path(package, resource) as resource_path:
            if os.path.exists(resource_path):
                return str(resource_path)
    except (ImportError, FileNotFoundError):
        pass

    # Always try to resolve as a relative path from this file
    parts = package.split(".")
    rel_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), *parts[1:], resource
    )
    if os.path.exists(rel_path):
        return rel_path

    # Fallback to local file system
    try:
        # Extract the subdirectory from package name (e.g., 'assets' from 'abogen.assets')
        subdir = package.split(".")[-1] if "." in package else package
        local_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), subdir, resource
        )
        if os.path.exists(local_path):
            return local_path
    except Exception:
        pass

    return None


def get_version():
    """Return the current version of the application."""
    try:
        with open(get_resource_path("/", "VERSION"), "r") as f:
            return f.read().strip()
    except Exception:
        return "Unknown"


# Define config path
def get_user_config_path():
    from platformdirs import user_config_dir

    # TODO Config directory is changed for Linux and MacOS. But if old config exists, it will be used.
    # On non‑Windows, prefer ~/.config/abogen if it already exists
    if platform.system() != "Windows":
        custom_dir = os.path.join(os.path.expanduser("~"), ".config", "abogen")
        if os.path.exists(custom_dir):
            config_dir = custom_dir
        else:
            config_dir = user_config_dir("abogen", appauthor=False, roaming=True)
    else:
        # Windows and fallback case
        config_dir = user_config_dir("abogen", appauthor=False, roaming=True)

    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "config.json")


_sleep_procs = {"Darwin": None, "Linux": None}  # Store sleep prevention processes


def clean_text(text, *args, **kwargs):
    # Load replace_single_newlines from config
    cfg = load_config()
    replace_single_newlines = cfg.get("replace_single_newlines", False)
    # Collapse all whitespace (excluding newlines) into single spaces per line and trim edges
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    # Standardize paragraph breaks (multiple newlines become exactly two) and trim overall whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # Optionally replace single newlines with spaces, but preserve double newlines
    if replace_single_newlines:
        text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    return text


def load_config():
    try:
        with open(get_user_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(config):
    try:
        with open(get_user_config_path(), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass


def calculate_text_length(text):
    # Remove double newlines (replace them with single newlines)
    cleaned_text = text.replace("\n\n", "")
    # Calculate character count
    char_count = len(cleaned_text)
    return char_count


def get_gpu_acceleration(enabled):
    from torch.cuda import is_available

    if not enabled:
        return "CUDA GPU available but using CPU.", False

    if is_available():
        return "CUDA GPU available and enabled.", True
    return "CUDA GPU is not available. Using CPU.", False


def prevent_sleep_start():
    system = platform.system()
    if system == "Windows":
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(
            0x80000000 | 0x00000001 | 0x00000040
        )  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
    elif system == "Darwin":
        _sleep_procs["Darwin"] = subprocess.Popen(["caffeinate"])
    elif system == "Linux":
        try:
            _sleep_procs["Linux"] = subprocess.Popen(
                [
                    "systemd-inhibit",
                    "--what=sleep",
                    "--why=TextToAudiobook conversion",
                    "sleep",
                    "999999",
                ]
            )
        except Exception:
            try:
                subprocess.Popen(["xdg-screensaver", "reset"])
            except Exception:
                pass


def prevent_sleep_end():
    system = platform.system()
    if system == "Windows":
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS
    elif system in ("Darwin", "Linux") and _sleep_procs[system]:
        try:
            _sleep_procs[system].terminate()
            _sleep_procs[system] = None
        except Exception:
            pass


def load_numpy_kpipeline():
    import numpy as np
    from kokoro import KPipeline

    return np, KPipeline


class LoadPipelineThread(Thread):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def run(self):
        try:
            np_module, kpipeline_class = load_numpy_kpipeline()
            self.callback(np_module, kpipeline_class, None)
        except Exception as e:
            self.callback(None, None, str(e))
