import sys
import os
import platform
import ctypes
import importlib.util

def check_cuda_with_fix():
    """
    Check if CUDA is available, with a fix for PyTorch DLL loading issue 
    ([WinError 1114]) on Windows.
    """
    # Fix PyTorch DLL loading issue ([WinError 1114]) on Windows
    try:
        if platform.system() == "Windows":
            spec = importlib.util.find_spec("torch")
            if spec and spec.origin:
                dll_path = os.path.join(os.path.dirname(spec.origin), "lib", "c10.dll")
                if os.path.exists(dll_path):
                    ctypes.CDLL(os.path.normpath(dll_path))
    except Exception:
        pass

    try:
        from torch.cuda import is_available
        print(is_available())
    except ImportError:
        print("False")

if __name__ == "__main__":
    check_cuda_with_fix()
