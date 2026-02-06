#!/usr/bin/env python3
"""Build PyPI package (wheel and sdist) to `dist` folder for abogen."""

import subprocess
import os
import shutil
import tempfile


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "dist")

    print("🔧 abogen PyPI Package Builder")
    print("=" * 40)
    print(f"📁 Script directory: {script_dir}")
    print(f"📦 Output directory: {output_dir}")

    # Try to print package version if present
    version = None
    version_file = os.path.join(script_dir, "abogen", "VERSION")
    if os.path.isfile(version_file):
        try:
            with open(version_file, "r", encoding="utf-8") as vf:
                version = vf.read().strip()
        except Exception:
            version = None
    if version:
        print(f"🔖 Package version: {version}")

    # Check if build module is installed, install if not
    # Temporarily remove script_dir from sys.path to avoid importing local build.py
    import sys

    original_path = sys.path[:]
    try:
        sys.path = [p for p in sys.path if os.path.abspath(p) != script_dir]
        import build
    except ImportError:
        print("📦 Installing build module...")
        subprocess.run([sys.executable, "-m", "pip", "install", "build"], check=True)
    finally:
        sys.path = original_path

    # Create output directory
    print(f"📂 Preparing output directory: {output_dir}")
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    print("🏗️  Building PyPI package...")
    print("   Using temporary directory to avoid module conflicts...")

    # Run from temp directory to avoid local build.py shadowing the build module
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"   Temp directory: {tmpdir}")
        print("   Running: python -m build -o <output_dir> <source_dir>")

        result = subprocess.run(
            [sys.executable, "-m", "build", "-o", output_dir, script_dir],
            check=False,
            cwd=tmpdir,
        )

    print("\n" + "=" * 40)
    if result.returncode == 0:
        print("✅ Build successful!")
        print(f"📦 Files created in {output_dir}:")

        files = os.listdir(output_dir)
        if files:
            for f in files:
                file_path = os.path.join(output_dir, f)
                size = os.path.getsize(file_path)
                print(f"   📄 {f} ({size:,} bytes)")
        else:
            print("   (No files found)")

        print("\n🚀 Ready for upload with:\n")
        print("   - To test on Test PyPI:")
        print(f"       python -m twine upload --repository testpypi {output_dir}/*")
        print("\n   - To upload to PyPI (when ready):")
        print(f"       python -m twine upload {output_dir}/*")
    else:
        print("❌ Build failed!")
        print(f"   Exit code: {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
