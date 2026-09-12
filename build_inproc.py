# -*- coding: utf-8 -*-
"""
In-process PyInstaller launcher for LogParser.

Problem: PyInstaller 6.22.2 spawns isolated helper subprocesses
(PyInstaller.isolated.Python) to discover hook dirs / library search paths.
In a supervised execution context those subprocesses are killed or their
stdio pipes are severed, so the parent blocks forever (zero output, no error).

Fix: replace PyInstaller.isolated.Python with an in-process shim that executes
the helper function directly in the current interpreter. No subprocess -> no
deadlock. The helper functions (setup / import_library / process_search_paths)
only need to import libraries to discover DLLs, which works fine in-process.
"""
import sys
import PyInstaller.isolated as _iso
import PyInstaller.isolated._parent as _parent
import PyInstaller.building.build_main as _bm


class _InProcPython:
    """Drop-in replacement for PyInstaller.isolated.Python that runs in-process."""

    def __init__(self, strict_mode=None):
        # Pretend we are NOT already isolated so call() executes directly.
        self._already_isolated = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return None

    def call(self, function, *args, **kwargs):
        # Run the helper directly in this process and return its real value.
        return function(*args, **kwargs)


# Patch the class everywhere it can be referenced:
#  - PyInstaller.isolated.Python  (used by build_main via `isolated.Python()`)
#  - PyInstaller.isolated._parent.Python (the real class, used by `call`/`decorate`)
# Both must point at the same stub or the subprocess still spawns.
_iso.Python = _InProcPython
_parent.Python = _InProcPython
_bm.isolated.Python = _InProcPython

# Build with the exact same arguments as 打包.bat.
argv = [
    "--onefile",
    "--windowed",
    "--icon=app.ico",
    "--add-data=app.ico;.",
    "--version-file=version.txt",
    "--name=LogParser",
    "--noconfirm",
    "--hidden-import=urllib.request",
    "--hidden-import=PIL",
    "--hidden-import=PIL.ImageTk",
    "LogParser.py",
]

from PyInstaller.__main__ import run

if __name__ == "__main__":
    sys.exit(run(argv))
