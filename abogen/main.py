import os
import sys
import platform
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import qInstallMessageHandler, QtMsgType

# Add the directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from abogen.gui import abogen
from abogen.utils import get_resource_path
from abogen.constants import PROGRAM_NAME, VERSION

# Set environment variables for AMD ROCm
os.environ["MIOPEN_FIND_MODE"] = "FAST"
os.environ["MIOPEN_CONV_PRECISE_ROCM_TUNING"] = "0"

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

# Set application ID for Windows taskbar icon
if platform.system() == "Windows":
    import ctypes

    app_id = f"{PROGRAM_NAME}.{VERSION}"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)

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
            app.setDesktopFileName("abogen.desktop")
        except AttributeError:
            pass

    ex = abogen()
    ex.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
