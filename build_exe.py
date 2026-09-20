# -*- coding: utf-8 -*-
"""
Build script to package the ARAM picker application into a Windows executable.
Uses PyInstaller to create a standalone .exe file.

Usage:
    python build_exe.py
    python build_exe.py --version 1.1.0
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

# Project configuration
PROJECT_NAME = "AramPicker"
MAIN_SCRIPT = "main.py"
ICON_PATH = os.path.join("aram_picker", "assets", "app.ico")
ASSETS_DIR = os.path.join("aram_picker", "assets")
VERSION_FILE = os.path.join("aram_picker", "_version.py")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def sanitize_version(version: str) -> str:
    """Keep version text safe for both display and Windows filenames."""
    version = version.strip()
    if not version:
        raise ValueError("Version cannot be empty.")

    if not re.fullmatch(r"[0-9A-Za-z._+-]+", version):
        raise ValueError(
            "Version can only contain letters, numbers, dots, "
            "underscores, plus signs, and hyphens."
        )

    return version


def read_current_version() -> str:
    """Read the version string from aram_picker/_version.py."""
    full_path = os.path.join(SCRIPT_DIR, VERSION_FILE)
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"Version file not found: {full_path}")

    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()

    match = re.search(r'__version__\s*=\s*"([^"]+)"', content)
    if not match:
        raise ValueError(f"No __version__ found in: {full_path}")

    return match.group(1)


def write_version(version: str):
    """Write version string into _version.py before building."""
    full_path = os.path.join(SCRIPT_DIR, VERSION_FILE)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write("# Single source of truth for app version.\n")
        f.write("# Updated by build_exe.py --version <ver> during packaging.\n")
        f.write(f'__version__ = "{version}"\n')
    print(f"  Version set to: {version}")


def check_environment():
    """Verify PyInstaller is available before building."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError
        print(f"  PyInstaller {result.stdout.strip()}")
    except (OSError, RuntimeError):
        print("ERROR: PyInstaller is not installed.")
        print(f"Install it with: {sys.executable} -m pip install pyinstaller")
        sys.exit(1)


def clean_previous_builds(project_name: str):
    """Remove stale dist/ and build/ artifacts."""
    targets = [
        os.path.join(SCRIPT_DIR, "dist"),
        os.path.join(SCRIPT_DIR, "build"),
    ]
    for target in targets:
        if os.path.exists(target):
            shutil.rmtree(target)
            print(f"  Removed previous build: {target}")


def build(project_name: str, version: str) -> bool:
    """Build the executable using PyInstaller."""
    print("[1/2] Building executable...")

    clean_previous_builds(project_name)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        f"--name={project_name}",
        "--windowed",
        "--onefile",
        f"--icon={ICON_PATH}",
        f"--add-data={ASSETS_DIR}{os.pathsep}{ASSETS_DIR}",
        "--hidden-import=PyQt6",
        "--hidden-import=PyQt6.QtCore",
        "--hidden-import=PyQt6.QtGui",
        "--hidden-import=PyQt6.QtWidgets",
        "--hidden-import=PyQt6.QtSvg",
        "--hidden-import=PyQt6.QtSvgWidgets",
        "--hidden-import=sip",
        "--collect-all=qfluentwidgets",
        "--noconfirm",
        "--clean",
        MAIN_SCRIPT,
    ]

    args_str = " ".join(cmd[2:])
    print(f"  Running: python -m {args_str}")
    print()

    result = subprocess.run(cmd, cwd=SCRIPT_DIR)

    if result.returncode != 0:
        print(f"ERROR: Build failed with exit code {result.returncode}")
        return False

    print("[2/2] Collecting output...")
    exe_path = os.path.join(SCRIPT_DIR, "dist", f"{project_name}.exe")
    if not os.path.exists(exe_path):
        print(f"ERROR: Executable not found at: {exe_path}")
        return False

    final_dir = os.path.join(SCRIPT_DIR, "dist", f"{project_name}_v{version}")
    os.makedirs(final_dir, exist_ok=True)
    final_exe_path = os.path.join(final_dir, f"{project_name}_v{version}.exe")
    shutil.move(exe_path, final_exe_path)

    size_mb = os.path.getsize(final_exe_path) / (1024 * 1024)
    print(f"  SUCCESS!")
    print(f"  Output: {final_exe_path}")
    print(f"  Size: {size_mb:.2f} MB")
    return True


def main():
    parser = argparse.ArgumentParser(description="Build ARAM picker executable")
    parser.add_argument(
        "--version", "-v",
        default=None,
        help="Version number to embed; defaults to aram_picker/_version.py",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("  AramPicker - Build Script")
    print("=" * 50)
    print()

    try:
        if args.version:
            version = sanitize_version(args.version)
            write_version(version)
        else:
            version = sanitize_version(read_current_version())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    print(f"App name: {PROJECT_NAME}")
    print(f"Version: {version}")
    print()
    check_environment()
    print()

    if not build(PROJECT_NAME, version):
        sys.exit(1)

    print()
    print("=" * 50)
    print("  Build Complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
