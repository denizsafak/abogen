import os
import sys
import platform
import atexit
import signal
from abogen.utils import get_resource_path, load_config, prevent_sleep_end


# Fix PyTorch DLL loading issue ([WinError 1114]) on Windows before importing PyQt6
if platform.system() == "Windows":
    import ctypes
    from importlib.util import find_spec

    try:
        if (
            (spec := find_spec("torch"))
            and spec.origin
            and os.path.exists(
                dll_path := os.path.join(os.path.dirname(spec.origin), "lib", "c10.dll")
            )
        ):
            ctypes.CDLL(os.path.normpath(dll_path))
    except Exception:
        pass


# Qt platform plugin detection (fixes #59)
try:
    from PyQt6.QtCore import QLibraryInfo

    # Get the path to the plugins directory
    plugins = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)

    # Normalize path to use the OS-native separators and absolute path
    platform_dir = os.path.normpath(os.path.join(plugins, "platforms"))

    # Ensure we work with an absolute path for clarity
    platform_dir = os.path.abspath(platform_dir)

    if os.path.isdir(platform_dir):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = platform_dir
        print("QT_QPA_PLATFORM_PLUGIN_PATH set to:", platform_dir)
    else:
        print("PyQt6 platform plugins not found at", platform_dir)
except ImportError:
    print("PyQt6 not installed.")


# Pre-load "libxcb-cursor" on Linux (fixes #101)
if platform.system() == "Linux":
    arch = platform.machine().lower()
    lib_filename = {"x86_64": "libxcb-cursor-amd64.so.0", "amd64": "libxcb-cursor-amd64.so.0", "aarch64": "libxcb-cursor-arm64.so.0", "arm64": "libxcb-cursor-arm64.so.0"}.get(arch)
    if lib_filename:
        import ctypes
        try:
            # Try to load the system libxcb-cursor.so.0 first
            ctypes.CDLL('libxcb-cursor.so.0', mode=ctypes.RTLD_GLOBAL)
        except OSError:
            # System lib not available, load the bundled version
            lib_path = get_resource_path('abogen.libs', lib_filename)
            if lib_path:
                try:
                    ctypes.CDLL(lib_path, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    # If it fails (e.g. wrong glibc version on very old systems),
                    # we simply ignore it and hope the system has the library.
                    pass


# Set application ID for Windows taskbar icon
if platform.system() == "Windows":
    try:
        from abogen.constants import PROGRAM_NAME, VERSION
        import ctypes

        app_id = f"{PROGRAM_NAME}.{VERSION}"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception as e:
        print("Warning: failed to set AppUserModelID:", e)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import (
    QLibraryInfo,
    qInstallMessageHandler,
    QtMsgType,
)

# Add the directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# Set Hugging Face Hub environment variables
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"  # Disable Hugging Face telemetry
os.environ["HF_HUB_ETAG_TIMEOUT"] = "10"  # Metadata request timeout (seconds)
os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "10"  # File download timeout (seconds)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"  # Disable symlinks warning
if load_config().get("disable_kokoro_internet", False):
    print("INFO: Kokoro's internet access is disabled.")
    os.environ["HF_HUB_OFFLINE"] = "1"  # Disable Hugging Face Hub internet access

from abogen.pyqt.gui import abogen
from abogen.constants import PROGRAM_NAME, VERSION

# Set environment variables for AMD ROCm
os.environ["MIOPEN_FIND_MODE"] = "FAST"
os.environ["MIOPEN_CONV_PRECISE_ROCM_TUNING"] = "0"

# Reset sleep states
atexit.register(prevent_sleep_end)


# Also handle signals (Ctrl+C, kill, etc.)
def _cleanup_sleep(signum, frame):
    prevent_sleep_end()
    sys.exit(0)


signal.signal(signal.SIGINT, _cleanup_sleep)
signal.signal(signal.SIGTERM, _cleanup_sleep)

# Ensure sys.stdout and sys.stderr are valid in GUI mode
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# Enable MPS GPU acceleration on Mac Apple Silicon
if platform.system() == "Darwin" and platform.processor() == "arm":
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"


# Custom message handler to filter out specific Qt warnings
def qt_message_handler(mode, context, message):
    # In PyQt6, the mode is an enum, so we compare with the enum members
    if "Wayland does not support QWindow::requestActivate()" in message:
        return  # Suppress this specific message
    if "setGrabPopup called with a parent, QtWaylandClient" in message:
        return

    if mode == QtMsgType.QtWarningMsg:
        print(f"Qt Warning: {message}")
    elif mode == QtMsgType.QtCriticalMsg:
        print(f"Qt Critical: {message}")
    elif mode == QtMsgType.QtFatalMsg:
        print(f"Qt Fatal: {message}")
    elif mode == QtMsgType.QtInfoMsg:
        print(f"Qt Info: {message}")


# Install the custom message handler
qInstallMessageHandler(qt_message_handler)

# Handle Wayland on Linux GNOME
if platform.system() == "Linux":
    xdg_session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if (
        "gnome" in desktop
        and xdg_session == "wayland"
        and "QT_QPA_PLATFORM" not in os.environ
    ):
        os.environ["QT_QPA_PLATFORM"] = "wayland"


def main():
    """Main entry point for console usage."""
    app = QApplication(sys.argv)

    # Set application icon using get_resource_path from utils
    icon_path = get_resource_path("abogen.assets", "icon.ico")
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    # Set the .desktop name on Linux
    if platform.system() == "Linux":
        try:
            app.setDesktopFileName("abogen")
        except AttributeError:
            pass

    ex = abogen()
    ex.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
