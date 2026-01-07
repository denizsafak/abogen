import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import warnings
from threading import Thread
from typing import Dict, Optional

from functools import lru_cache

from dotenv import load_dotenv, find_dotenv

def _load_environment() -> None:
    explicit_path = os.environ.get("ABOGEN_ENV_FILE")
    if explicit_path:
        load_dotenv(explicit_path, override=False)
        return
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path, override=False)


_load_environment()

warnings.filterwarnings("ignore")


def detect_encoding(file_path):
    try:
        import chardet  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - optional dependency
        chardet = None  # type: ignore[assignment]

    try:
        import charset_normalizer  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - optional dependency
        charset_normalizer = None  # type: ignore[assignment]

    with open(file_path, "rb") as f:
        raw_data = f.read()
    detected_encoding = None
    for detectors in (charset_normalizer, chardet):
        if detectors is None:
            continue
        try:
            result = detectors.detect(raw_data)["encoding"]
        except Exception:
            continue
        if result is not None:
            detected_encoding = result
            break
    encoding = detected_encoding if detected_encoding else "utf-8"
    return encoding.lower()

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
        version_path = get_resource_path("/", "VERSION")
        if not version_path:
            raise FileNotFoundError("VERSION resource missing")
        with open(version_path, "r") as f:
            return f.read().strip()
    except Exception:
        return "Unknown"


# Define config path
def ensure_directory(path):
    resolved = os.path.abspath(os.path.expanduser(str(path)))
    os.makedirs(resolved, exist_ok=True)
    return resolved


@lru_cache(maxsize=1)
def get_user_settings_dir():
    override = os.environ.get("ABOGEN_SETTINGS_DIR")
    if override:
        return ensure_directory(override)

    data_root = os.environ.get("ABOGEN_DATA") or os.environ.get("ABOGEN_DATA_DIR")
    if data_root:
        try:
            return ensure_directory(os.path.join(data_root, "settings"))
        except OSError:
            pass

    data_mount = "/data"
    if os.path.isdir(data_mount):
        try:
            return ensure_directory(os.path.join(data_mount, "settings"))
        except OSError:
            pass

    from platformdirs import user_config_dir

    if platform.system() != "Windows":
        legacy_dir = os.path.join(os.path.expanduser("~"), ".config", "abogen")
        if os.path.exists(legacy_dir):
            return ensure_directory(legacy_dir)

    config_dir = user_config_dir("abogen", appauthor=False, roaming=True, ensure_exists=True)
    return ensure_directory(config_dir)


def get_user_config_path():
    return os.path.join(get_user_settings_dir(), "config.json")


# Define cache path
@lru_cache(maxsize=1)
def get_user_cache_root():
    logger = logging.getLogger(__name__)

    def _try_paths(*paths):
        last_error = None
        for candidate in paths:
            if not candidate:
                continue
            try:
                return ensure_directory(candidate)
            except OSError as exc:
                last_error = exc
                logger.debug("Unable to use cache directory %s: %s", candidate, exc)
        if last_error is not None:
            raise last_error

    def _configure_cache_env(root: Optional[str]) -> None:
        temp_root = None
        if root:
            try:
                temp_root = ensure_directory(root)
            except OSError:
                temp_root = None

        home_dir = os.environ.get("HOME")
        if not home_dir:
            home_dir = ensure_directory(os.path.join("/tmp", "abogen-home"))
            os.environ["HOME"] = home_dir
        else:
            home_dir = ensure_directory(home_dir)

        cache_base = os.environ.get("XDG_CACHE_HOME")
        if cache_base:
            cache_base = ensure_directory(cache_base)
        elif temp_root:
            cache_base = temp_root
            os.environ["XDG_CACHE_HOME"] = cache_base
        else:
            cache_base = ensure_directory(os.path.join(home_dir, ".cache"))
            os.environ["XDG_CACHE_HOME"] = cache_base

        hf_cache = os.environ.get("HF_HOME")
        if hf_cache:
            hf_cache = ensure_directory(hf_cache)
        elif temp_root:
            hf_cache = ensure_directory(os.path.join(temp_root, "huggingface"))
            os.environ["HF_HOME"] = hf_cache
        else:
            hf_cache = ensure_directory(os.path.join(cache_base, "huggingface"))
            os.environ["HF_HOME"] = hf_cache

        for env_var in ("HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE"):
            os.environ.setdefault(env_var, hf_cache)

        os.environ.setdefault("ABOGEN_INTERNAL_CACHE_ROOT", cache_base)

    cache_root: Optional[str] = None

    override = os.environ.get("ABOGEN_TEMP_DIR")
    if override:
        try:
            cache_root = ensure_directory(override)
        except OSError as exc:
            logger.warning("ABOGEN_TEMP_DIR=%s is not writable: %s", override, exc)

    if cache_root is None:
        from platformdirs import user_cache_dir

        default_cache = user_cache_dir("abogen", appauthor=False, opinion=True)

        data_root = os.environ.get("ABOGEN_DATA") or os.environ.get("ABOGEN_DATA_DIR")
        fallback_paths = [
            default_cache,
            os.path.join(data_root, "cache") if data_root else None,
            "/data/cache",
            "/tmp/abogen-cache",
        ]

        try:
            cache_root = _try_paths(*fallback_paths)
        except OSError:
            # Final safety net – attempt a tmp directory unique to this process.
            tmp_candidate = os.path.join("/tmp", f"abogen-cache-{os.getpid()}")
            logger.warning("Falling back to temp cache directory %s", tmp_candidate)
            cache_root = ensure_directory(tmp_candidate)

    if cache_root is None:
        raise RuntimeError("Unable to determine cache directory")

    _configure_cache_env(cache_root)
    return cache_root


def get_internal_cache_root():
    root = os.environ.get("ABOGEN_INTERNAL_CACHE_ROOT") or os.environ.get("XDG_CACHE_HOME")
    if root:
        return ensure_directory(root)
    home_dir = os.environ.get("HOME") or os.path.join("/tmp", "abogen-home")
    home_dir = ensure_directory(home_dir)
    return ensure_directory(os.path.join(home_dir, ".cache"))


def get_internal_cache_path(folder=None):
    base = get_internal_cache_root()
    if folder:
        return ensure_directory(os.path.join(base, folder))
    return base


def get_user_cache_path(folder=None):
    base = get_user_cache_root()
    if folder:
        return ensure_directory(os.path.join(base, folder))
    return base


@lru_cache(maxsize=1)
def get_user_output_root():
    override = (
        os.environ.get("ABOGEN_OUTPUT_DIR")
        or os.environ.get("ABOGEN_OUTPUT_ROOT")
    )
    if override:
        return ensure_directory(override)
    return ensure_directory(os.path.join(get_user_cache_root(), "outputs"))


def get_user_output_path(folder=None):
    base = get_user_output_root()
    if folder:
        return ensure_directory(os.path.join(base, folder))
    return base


_sleep_procs: Dict[str, Optional[subprocess.Popen[str]]] = {"Darwin": None, "Linux": None}  # Store sleep prevention processes


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
    if use_shell:
        logger.warning("Security Warning: create_process called with string command. Prefer using a list of arguments to avoid shell injection risks.")

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
        startupinfo = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
        startupinfo.wShowWindow = subprocess.SW_HIDE  # type: ignore[attr-defined]
        kwargs.update(
            {
                "startupinfo": startupinfo,
                "creationflags": subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
            }
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
        import torch  # type: ignore[import-not-found]
        from torch.cuda import is_available as cuda_available  # type: ignore[import-not-found]

        if not enabled:
            return "GPU available but using CPU.", False
        
        # Check for Apple Silicon MPS
        if platform.system() == "Darwin" and platform.processor() == "arm":
            if torch.backends.mps.is_available():
                return "MPS GPU available and enabled.", True
            else:
                return "MPS GPU not available on Apple Silicon. Using CPU.", False
        
        # Check for CUDA
        if cuda_available():
            return "CUDA GPU available and enabled.", True
        
        # Gather CUDA diagnostic info if not available
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
        return f"Error checking GPU: {e}", False


def prevent_sleep_start():
    from abogen.constants import PROGRAM_NAME

    system = platform.system()
    if system == "Windows":
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(  # type: ignore[attr-defined]
            0x80000000 | 0x00000001 | 0x00000040
        )
    elif system == "Darwin":
        _sleep_procs["Darwin"] = create_process(["caffeinate"])
    elif system == "Linux":
        # Add program name and reason for inhibition
        program_name = PROGRAM_NAME
        reason = "Prevent sleep during abogen process"
        # Only attempt to use systemd-inhibit if it's available on the system.
        if shutil.which("systemd-inhibit"):
            _sleep_procs["Linux"] = create_process(
                [
                    "systemd-inhibit",
                    f"--who={program_name}",
                    f"--why={reason}",
                    "--what=sleep",
                    "--mode=block",
                    "sleep",
                    "infinity",
                ]
            )
        else:
            # Non-systemd distro or systemd tools not installed: skip inhibition rather than crash
            print(
                "systemd-inhibit not found: skipping sleep inhibition on this Linux system."
            )


def prevent_sleep_end():
    system = platform.system()
    if system == "Windows":
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # type: ignore[attr-defined]
    elif system in ("Darwin", "Linux"):
        proc = _sleep_procs.get(system)
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass
            finally:
                _sleep_procs[system] = None


def load_numpy_kpipeline():
    import numpy as np
    from kokoro import KPipeline  # type: ignore[import-not-found]

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
