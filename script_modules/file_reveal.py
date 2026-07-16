"""
Reveal a file in the OS file manager.

Thin Qt/OS boundary helper: on Windows it opens Explorer with the file
selected (highlighted); on other platforms it falls back to opening the
file's containing folder. Kept in its own module so both the metadata tab
and the full-resolution dialog can share one implementation, and so the
platform branch can be unit-tested by monkeypatching ``sys.platform`` and
``subprocess.run``.
"""
import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


logger = logging.getLogger(__name__)


def reveal_in_file_manager(path) -> bool:
    """Open the OS file manager with ``path`` selected.

    On Windows the file is highlighted inside its directory via
    ``explorer /select,<path>``. On other platforms (and if the Windows
    call fails) the containing folder is opened instead.

    :param path: Absolute path to the file to reveal (str or Path).
    :return: True on best-effort success, False if the path is missing or
        could not be opened.
    """
    if not path:
        logger.warning("Cannot reveal image: no path provided.")
        return False

    target = Path(path)
    if not target.exists():
        logger.warning("Cannot reveal image: path not found: %s", target)
        return False

    if sys.platform.startswith("win"):
        try:
            # explorer.exe wants "/select,<path>" as a single token and,
            # quirk of the tool, returns exit code 1 even on success — so
            # do not gate on the return code.
            subprocess.run(
                f'explorer /select,"{os.path.normpath(target)}"'
            )
            return True
        except OSError as exc:
            logger.warning(
                "explorer /select failed for %s: %s — opening folder instead.",
                target, exc,
            )
            # Fall through to the folder-open fallback below.

    # Cross-platform fallback: open the containing folder.
    opened = QDesktopServices.openUrl(
        QUrl.fromLocalFile(str(target.parent))
    )
    if not opened:
        logger.warning("Could not open containing folder for: %s", target)
    return opened
