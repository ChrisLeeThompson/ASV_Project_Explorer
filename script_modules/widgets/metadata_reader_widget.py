"""
Metadata Reader Widget

A read-only QTextEdit that accepts drag-and-drop of single SEM/FIB
image files (.tif, .tiff, .png).  When a valid file is dropped the
``file_dropped`` signal is emitted with the list of file paths.

The widget shows placeholder text when empty and displays parsed
metadata as numbered lines once populated.
"""
from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtCore import Signal


_ALLOWED_EXTENSIONS = (".tif", ".tiff", ".png")


class MetadataReaderTextEdit(QTextEdit):
    """
    Read-only text area with drag-and-drop support for single image files.

    Signals
    -------
    file_dropped : list[str]
        Emitted when one or more valid image files are dropped.
    """

    file_dropped = Signal(list)

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setReadOnly(True)
        self.setPlaceholderText(placeholder)

    # -----------------------------------------------------------------
    # Drag-and-drop
    # -----------------------------------------------------------------

    def _all_valid(self, mime_data) -> bool:
        """Return True if every dropped URL is a supported image."""
        if not mime_data.hasUrls():
            return False
        return all(
            any(
                url.toLocalFile().lower().endswith(ext)
                for ext in _ALLOWED_EXTENSIONS
            )
            for url in mime_data.urls()
        )

    def dragEnterEvent(self, event: QDragEnterEvent):
        if self._all_valid(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if self._all_valid(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        if self._all_valid(event.mimeData()):
            paths = [
                url.toLocalFile() for url in event.mimeData().urls()
            ]
            self.file_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()