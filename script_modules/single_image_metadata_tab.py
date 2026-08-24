"""
Single Image Metadata Tab

Displays raw metadata extracted from a single SEM/FIB image file.

The user drags and drops a .tif, .tiff, or .png image onto the
text area.  A background worker reads the file and populates the
display with numbered metadata lines.  A search field filters the
lines in real time while preserving original line numbers.

Layout (top to bottom)::

    ┌──────────────────────────────────────┐
    │  ┌────────────────────────────────┐  │
    │  │  Image Name:  <file_name>      │  │
    │  │  Image Path:  [scrollable path]│  │
    │  └────────────────────────────────┘  │
    │  search_line_edit                    │
    │  ┌──────────────────────────────────┐│
    │  │  MetadataReaderTextEdit          ││
    │  │  (drag-drop target + display)    ││
    │  │                                  ││
    │  └──────────────────────────────────┘│
    └──────────────────────────────────────┘
"""
import logging
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QLineEdit,
    QScrollArea, QSizePolicy, QGroupBox,
)
from PySide6.QtCore import QThread, Slot, Signal, Qt
from script_modules.app_styles import AppStyles
from script_modules.widgets.metadata_reader_widget import MetadataReaderTextEdit
from script_modules.metadata_reader_worker import MetadataReaderWorker
from script_modules.widgets.status_bar_widget import StatusBarWidget


logger = logging.getLogger(__name__)


# Placeholder text
_PLACEHOLDER_FILE_NAME = AppStyles.AppText.SINGLE_IMAGE_METADATA_FILE_NAME
_PLACEHOLDER_DROP = AppStyles.AppText.SINGLE_IMAGE_METADATA_DROP


class SingleImageMetadataTab(QWidget):
    """
    Tab widget for quick raw metadata inspection of single images.

    Signals
    -------
    processing_active : bool
        Emitted ``True`` when the worker starts and ``False`` when
        it finishes.  Used by MainWindow to disable other tabs.
    """

    processing_active = Signal(bool)

    def __init__(self, status_bar: StatusBarWidget, parent=None):
        super().__init__(parent)
        self.status_bar = status_bar
        # Data storage
        self._metadata_lines: list[str] = []
        # Worker references
        self._worker: MetadataReaderWorker | None = None
        self._worker_thread: QThread | None = None
        # Build UI
        self._create_widgets()
        self._setup_layout()
        self._connect_signals()

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _create_widgets(self):
        """Create file info group box, search field, and metadata text area."""
        # --- File info group box (image name + scrollable path) ---
        self.file_info_groupbox = QGroupBox()
        self.file_info_groupbox.setStyleSheet(AppStyles.GroupBox.default() +
                                              f"QGroupBox {{ background-color: {AppStyles.Colors.MAIN_BG}; }}")
        self.file_info_groupbox.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        info_layout = QGridLayout(self.file_info_groupbox)
        info_layout.setContentsMargins(
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
        )
        info_layout.setSpacing(AppStyles.Dimensions.LAYOUT_VSPACING)

        # Row 0: Image Name
        image_name_label = QLabel("Image Name:")
        image_name_label.setStyleSheet(AppStyles.Label.large_label())
        self.image_name_field = QLabel(_PLACEHOLDER_FILE_NAME)
        self.image_name_field.setStyleSheet(AppStyles.Label.large_label())
        self.image_name_field.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        info_layout.addWidget(
            image_name_label, 0, 0,
            alignment=Qt.AlignmentFlag.AlignLeft,
        )
        info_layout.addWidget(self.image_name_field, 0, 1)

        # Row 1: Image Path (horizontally scrollable for long paths)
        image_path_label = QLabel("Image Path:")
        image_path_label.setStyleSheet(AppStyles.Label.large_label())
        self.image_path_field = QLabel("")
        self.image_path_field.setStyleSheet(AppStyles.Label.large_label())
        self.image_path_field.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._path_scroll_area = QScrollArea()
        self._path_scroll_area.setWidget(self.image_path_field)
        self._path_scroll_area.setWidgetResizable(True)
        self._path_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._path_scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._path_scroll_area.setFixedHeight(42)
        self._path_scroll_area.setStyleSheet(
            AppStyles.ScrollArea.horizontal_only()
        )
        self._path_scroll_area.setVisible(False)

        info_layout.addWidget(
            image_path_label, 1, 0,
            alignment=Qt.AlignmentFlag.AlignLeft,
        )
        info_layout.addWidget(self._path_scroll_area, 1, 1)

        # Let column 1 stretch to fill available width
        info_layout.setColumnStretch(1, 1)

        # --- Search / filter field (hidden until metadata is loaded) ---
        self.search_line_edit = QLineEdit()
        self.search_line_edit.setPlaceholderText("Search metadata")
        self.search_line_edit.setStyleSheet(AppStyles.LineEdit.search() + f"QLineEdit {{ font-size: {AppStyles.Dimensions.FONT_SIZE_LARGE}; }}")
        self.search_line_edit.setVisible(False)

        # --- Metadata text area (always visible — serves as drop target) ---
        self.metadata_text_edit = MetadataReaderTextEdit(
            placeholder=_PLACEHOLDER_DROP, parent=self
        )
        self.metadata_text_edit.setStyleSheet(AppStyles.TextEdit.metadata())

    def _setup_layout(self):
        """Stack widgets vertically."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
        )
        layout.setSpacing(AppStyles.Dimensions.LAYOUT_VSPACING)
        layout.addWidget(self.file_info_groupbox)
        layout.addWidget(self.search_line_edit)
        layout.addWidget(self.metadata_text_edit, 1)

    def _connect_signals(self):
        """Wire up drop and search signals."""
        self.metadata_text_edit.file_dropped.connect(
            self._on_files_dropped
        )
        self.search_line_edit.textChanged.connect(
            self._apply_filter
        )

    # -----------------------------------------------------------------
    # Drop / Worker
    # -----------------------------------------------------------------

    @Slot(list)
    def _on_files_dropped(self, file_paths: list[str]):
        """
        Handle a file drop.  Spin up a worker thread to parse the
        metadata without blocking the UI.
        """
        logger.info(f"File dropped: {file_paths}")
        # Ignore drops while a previous parse is still running —
        # rebinding the references would destroy a running QThread.
        if self._worker_thread is not None:
            self.status_bar.set_status_bar_message_timed(
                "Still parsing previous image; please wait.", 3000
            )
            return
        self.processing_active.emit(True)
        self.status_bar.set_status_bar_message("Parsing image metadata...")

        # Create worker and thread
        self._worker = MetadataReaderWorker(file_paths)
        self._worker_thread = QThread()
        self._worker.moveToThread(self._worker_thread)

        # Connect worker signals
        self._worker.file_path.connect(self._on_file_path)
        self._worker.metadata.connect(self._on_metadata)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)

        # Start
        self._worker_thread.started.connect(self._worker.run)
        self._worker_thread.start()

    @Slot(str)
    def _on_file_path(self, file_path: str):
        """Update file info fields from the worker."""
        path = Path(file_path)
        self.image_name_field.setText(path.name)
        self.image_path_field.setText(str(path))
        self._path_scroll_area.setVisible(True)

    @Slot(list)
    def _on_metadata(self, lines: list[str]):
        """Store and display the parsed metadata lines."""
        self._metadata_lines = lines
        self.search_line_edit.setVisible(True)
        self._display_lines(lines)

    @Slot(str)
    def _on_error(self, message: str):
        """Show error in the status bar."""
        logger.error(f"Metadata reader error: {message}")
        self.status_bar.set_status_bar_message_timed(message, 8000)

    @Slot()
    def _on_finished(self):
        """Clean up worker and re-enable tabs."""
        self._cleanup_worker()
        self.status_bar.set_status_bar_message("")
        self.processing_active.emit(False)

    def _cleanup_worker(self):
        """Shut down the worker thread (bounded wait)."""
        if self._worker_thread and self._worker_thread.isRunning():
            self._worker_thread.quit()
            if not self._worker_thread.wait(10000):
                # Keep the references — destroying a still-running
                # QThread would hard-abort the process.
                logger.warning("Metadata reader thread did not stop in time.")
                return
        self._worker = None
        self._worker_thread = None

    # -----------------------------------------------------------------
    # Display / Filter
    # -----------------------------------------------------------------

    def _display_lines(self, lines: list[str]):
        """
        Render metadata lines in the text edit with line numbers.

        :param lines: The metadata lines to display.
        """
        self.metadata_text_edit.clear()
        numbered = [
            f"{i}. {line}" for i, line in enumerate(lines, 1)
        ]
        self.metadata_text_edit.setPlainText("\n".join(numbered))
        # Scroll to top
        self.metadata_text_edit.verticalScrollBar().setValue(0)

    @Slot(str)
    def _apply_filter(self, text: str):
        """
        Filter displayed metadata based on the search field.

        Matching is a case-insensitive literal substring test.
        Original line numbers are preserved so the user can
        reference them in the full list.
        """
        self.metadata_text_edit.clear()
        search = text.strip()

        if not search:
            self._display_lines(self._metadata_lines)
            return

        filtered = [
            f"{i}. {line}"
            for i, line in enumerate(self._metadata_lines, 1)
            if search.lower() in line.lower()
        ]
        self.metadata_text_edit.setPlainText("\n".join(filtered))
        self.metadata_text_edit.verticalScrollBar().setValue(0)

    # -----------------------------------------------------------------
    # Cleanup (called from MainWindow.closeEvent)
    # -----------------------------------------------------------------

    def cleanup(self):
        """Stop any running worker thread."""
        self._cleanup_worker()
        logger.info("Single image metadata tab cleaned up.")