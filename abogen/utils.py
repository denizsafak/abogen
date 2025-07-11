import os
import sys
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


default_encoding = sys.getfilesystemencoding()


def create_process(cmd, stdin=None, text=True, capture_output=False):
    import logging

    logger = logging.getLogger(__name__)

    # Configure root logger to output to console if not already configured
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    # Determine shell usage: use shell only for string commands
    use_shell = isinstance(cmd, str)
    kwargs = {
        "shell": use_shell,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "bufsize": 1,  # Line buffered
    }

    if text:
        # Configure for text I/O
        kwargs["text"] = True
        kwargs["encoding"] = default_encoding
        kwargs["errors"] = "replace"
    else:
        # Configure for binary I/O
        kwargs["text"] = False
        # For binary mode, 'encoding' and 'errors' arguments must not be passed to Popen
        kwargs["bufsize"] = 0  # Use unbuffered mode for binary data

    if stdin is not None:
        kwargs["stdin"] = stdin

    if platform.system() == "Windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs.update(
            {"startupinfo": startupinfo, "creationflags": subprocess.CREATE_NO_WINDOW}
        )

    # Print the command being executed
    print(f"Executing: {cmd if isinstance(cmd, str) else ' '.join(cmd)}")

    proc = subprocess.Popen(cmd, **kwargs)

    # Stream output to console in real-time if not capturing
    if proc.stdout and not capture_output:

        def _stream_output(stream):
            if text:
                # For text mode, read character by character for real-time output
                while True:
                    char = stream.read(1)
                    if not char:
                        break
                    # Direct write to stdout for immediate feedback
                    sys.stdout.write(char)
                    sys.stdout.flush()
            else:
                # For binary mode, read small chunks
                while True:
                    chunk = stream.read(1)  # Read byte by byte for real-time output
                    if not chunk:
                        break
                    try:
                        # Try to decode binary data for display
                        sys.stdout.write(
                            chunk.decode(default_encoding, errors="replace")
                        )
                        sys.stdout.flush()
                    except Exception:
                        pass
            stream.close()

        # Start a daemon thread to handle output streaming
        Thread(target=_stream_output, args=(proc.stdout,), daemon=True).start()

    return proc


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
    # Ignore chapter markers
    text = re.sub(r"<<CHAPTER_MARKER:.*?>>", "", text)
    # Ignore metadata patterns
    text = re.sub(r"<<METADATA_[^:]+:[^>]*>>", "", text)
    # Ignore newlines
    text = text.replace("\n", "")
    # Ignore leading/trailing spaces
    text = text.strip()
    # Calculate character count
    char_count = len(text)
    return char_count


def get_gpu_acceleration(enabled):
    try:
        import torch
        from torch.cuda import is_available

        if not enabled:
            return "CUDA GPU available but using CPU.", False
        if is_available():
            return "CUDA GPU available and enabled.", True
        # Gather more diagnostic info if CUDA is not available
        try:
            cuda_devices = torch.cuda.device_count()
            cuda_error = (
                torch.cuda.get_device_name(0)
                if cuda_devices > 0
                else "No devices found"
            )
        except Exception as e:
            cuda_error = str(e)
        return f"CUDA GPU is not available. Using CPU. ({cuda_error})", False
    except Exception as e:
        return f"Error checking CUDA GPU: {e}", False


def prevent_sleep_start():
    system = platform.system()
    if system == "Windows":
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(
            0x80000000 | 0x00000001 | 0x00000040
        )
    elif system == "Darwin":
        _sleep_procs["Darwin"] = create_process(["caffeinate"])
    elif system == "Linux":
        # use a sleep that never exits so inhibition stays active
        _sleep_procs["Linux"] = create_process(
            [
                "systemd-inhibit",
                "--what=handle-lid-switch:sleep",
                "--mode=block",
                "sleep",
                "infinity",
            ]
        )


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
