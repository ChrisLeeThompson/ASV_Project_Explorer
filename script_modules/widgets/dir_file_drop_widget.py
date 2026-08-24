"""
Directory / File Drop Widget

Module handles the directory / file drop widget. The widget is a QLabel.
The QLabel supports drag and drop of ASV project directories and
consolidated metadata JSON files.

Directory drops are validated against a list of required files.
JSON file drops are accepted by extension (.json) during drag, with
format validation handled by the receiving signal handler.

"""
from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QPixmap, QDragEnterEvent, QDropEvent, QDragLeaveEvent
from PySide6.QtCore import Qt, Signal
from pathlib import Path


class DirFileDropLabel(QLabel):

    # Signal emitted when a valid directory is dropped.
    directory_path_signal: Signal = Signal(str)

    # Signal emitted when a JSON file is dropped.
    json_file_path_signal: Signal = Signal(str)

    # Signal emitted when validation fails.
    validation_failed_signal: Signal = Signal(str)

    def __init__(self, color_path, grayscale_path, scale_factor=1.8,
                 validation_files: list[str] = None, parent=None):
        super().__init__(parent)
        self.scale_factor: float = scale_factor
        self.validation_files: list[str] = validation_files or []
        self.setAcceptDrops(True)
        self.color_path = Path(color_path)
        self.grayscale_path = Path(grayscale_path)

        # Set default pixmap (grayscale)
        self.pix = QPixmap(str(self.grayscale_path))
        self.setPixmap(self.pix)

        # Set default label size based on pixmap size
        self.setScaledContents(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        widget_width = int(self.pix.width() / self.scale_factor)
        widget_height = int(self.pix.height() / self.scale_factor)
        self.setFixedSize(widget_width, widget_height)
        self.setMargin(2)

    def _validate_directory(self, directory_path: Path) -> tuple[bool, list[str]]:
        """
        Validate that all required files are present in the directory.

        :param directory_path: Path to the directory to validate.
        :return: Tuple of (is_valid, list of missing file names).
        """
        if not self.validation_files:
            return True, []
        missing_files = [
            file_name for file_name in self.validation_files
            if not (directory_path / file_name).exists()
        ]
        return len(missing_files) == 0, missing_files

    def set_image_grayscale(self):
        """Set the image drop zone to grayscale (default/inactive state)."""
        self.pix = QPixmap(str(self.grayscale_path))
        self.setPixmap(self.pix)

    def set_image_color(self):
        """Set the image drop zone to color (active/hover state)."""
        self.pix = QPixmap(str(self.color_path))
        self.setPixmap(self.pix)

    def set_accepts_drops(self, state: bool):
        """
        Method sets accepts drops.
        :param state: True or False
        """
        self.setAcceptDrops(state)

    def dragEnterEvent(self, event: QDragEnterEvent):
        """
        Handle drag enter events. Accept the drag if it contains:
        - A valid ASV project directory (with required validation files), or
        - A .json file (format validation occurs on drop).
        """
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            for url in urls:
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    # Check for valid directory
                    if path.is_dir():
                        is_valid, missing_files = self._validate_directory(path)
                        if is_valid:
                            event.acceptProposedAction()
                            self.set_image_color()
                            return
                        else:
                            missing_names = ", ".join(missing_files)
                            self.validation_failed_signal.emit(
                                f"Invalid ASV project directory. "
                                f"Missing required files: {missing_names}"
                            )
                    # Check for JSON file
                    elif path.is_file() and path.suffix.lower() == ".json":
                        event.acceptProposedAction()
                        self.set_image_color()
                        return
            event.ignore()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        """Handle drag leave events. Change back to grayscale image."""
        self.set_image_grayscale()
        event.accept()

    def dropEvent(self, event: QDropEvent):
        """
        Handle drop events. Process the first valid item found:
        - Directories: validate and emit directory_path_signal.
        - JSON files: emit json_file_path_signal (format validation
          is handled by the receiving signal handler).
        """
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            for url in urls:
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    # Handle directory drop
                    if path.is_dir():
                        is_valid, missing_files = self._validate_directory(path)
                        if is_valid:
                            self.directory_path_signal.emit(str(path.resolve()))
                            event.acceptProposedAction()
                            return
                        else:
                            missing_names = ", ".join(missing_files)
                            self.validation_failed_signal.emit(
                                f"Invalid ASV project directory. "
                                f"Missing required files: {missing_names}"
                            )
                    # Handle JSON file drop
                    elif path.is_file() and path.suffix.lower() == ".json":
                        self.json_file_path_signal.emit(str(path.resolve()))
                        event.acceptProposedAction()
                        return
            event.ignore()
            self.set_image_grayscale()
        else:
            event.ignore()
            self.set_image_grayscale()