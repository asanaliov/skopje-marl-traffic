"""Check whether the local Python and SUMO setup is ready for the project."""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import sys
from pathlib import Path


REQUIRED_PYTHON = (3, 11)
SUMO_EXECUTABLES = ("sumo", "sumo-gui", "netedit")
REQUIRED_IMPORTS = (
    "traci",
    "sumo_rl",
    "pettingzoo",
    "gymnasium",
    "numpy",
    "pandas",
    "matplotlib",
)


def check_python() -> bool:
    """Report whether the active interpreter is Python 3.11."""
    print(f"Python version: {platform.python_version()}")
    print(f"Python executable: {Path(sys.executable)}")

    is_supported = sys.version_info[:2] == REQUIRED_PYTHON
    if is_supported:
        print("[OK] Python 3.11 is active.")
    else:
        print("[FAIL] This project requires Python 3.11.")
    return is_supported


def check_sumo_home() -> bool:
    """Report whether SUMO_HOME points to an existing directory."""
    sumo_home = os.environ.get("SUMO_HOME")
    print(f"SUMO_HOME: {sumo_home or '<not set>'}")

    if not sumo_home:
        print("[FAIL] Set SUMO_HOME to the SUMO installation directory.")
        return False

    if not Path(sumo_home).is_dir():
        print(f"[FAIL] SUMO_HOME is not a directory: {sumo_home}")
        return False

    print("[OK] SUMO_HOME points to an existing directory.")
    return True


def check_sumo_executables() -> bool:
    """Report whether the required SUMO programs are available on PATH."""
    all_available = True
    for executable in SUMO_EXECUTABLES:
        executable_path = shutil.which(executable)
        if executable_path:
            print(f"[OK] {executable}: {executable_path}")
        else:
            print(f"[FAIL] {executable} is not available on PATH.")
            all_available = False
    return all_available


def check_imports() -> bool:
    """Try each required import and report readable failures."""
    all_available = True
    for module_name in REQUIRED_IMPORTS:
        try:
            importlib.import_module(module_name)
        except Exception as error:  # Import failures can wrap dependency errors.
            print(
                f"[FAIL] import {module_name}: "
                f"{type(error).__name__}: {error}"
            )
            all_available = False
        else:
            print(f"[OK] import {module_name}")
    return all_available


def main() -> int:
    """Run all setup checks and return a shell-friendly exit code."""
    python_ok = check_python()
    print()
    sumo_home_ok = check_sumo_home()
    executables_ok = check_sumo_executables()
    print()
    imports_ok = check_imports()

    if not executables_ok:
        print(
            "\nSUMO must be installed separately on Windows. "
            "After installation, add its bin directory to PATH."
        )

    if python_ok and sumo_home_ok and executables_ok and imports_ok:
        print("\n[OK] The required project setup is available.")
        return 0

    print("\n[FAIL] Setup is incomplete. Fix the items above and run this check again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
