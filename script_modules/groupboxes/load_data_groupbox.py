"""
Load Data GroupBox

This module handles the load data group box.
The group box includes:
- Button to load an ASV project directory via folder dialog.
- Button to load a JSON file containing previously parsed ASV project metadata.
- Button to save the current metadata to a user-chosen location.
- Button to delete the temporary JSON metadata file from the project directory.

Each button opens the appropriate dialog and emits a signal with the
selected path. The parent tab handles the actual data operations
(parsing, loading, saving, deleting).

Button State Management
-----------------------
- Load ASV Project: Always enabled (disabled externally during parsing).
- Load Metadata File: Always enabled (disabled externally during parsing).
- Save Metadata File: Disabled until metadata is loaded.
- Delete Metadata File: Disabled until a temp file path is set and the
  file exists on disk.
"""
import logging
from pathlib import Path
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QFileDialog
)
from PySide6.QtCore import Signal, Slot
from script_modules.app_styles import AppStyles
from script_modules.widgets.button_widgets import (
    LoadASVDataButton, LoadJSONFileButton,
    SaveJSONFileButton, DeleteJSONFileButton
)


logger = logging.getLogger(__name__)


class LoadDataGroupBox(QGroupBox):

    # Emitted when a validated ASV project directory is selected.
    directory_selected = Signal(str)

    # Emitted when a JSON file is selected via the file dialog.
    json_file_selected = Signal(str)

    # Emitted when the user chooses a save destination.
    # Args: destination file path
    save_requested = Signal(str)

    # Emitted when the user clicks the delete button.
    delete_requested = Signal()

    # Emitted when directory validation fails.
    # Args: error message
    validation_failed = Signal(str)

    def __init__(self, validation_files: list[str] = None,
                 default_save_filename: str = "consolidated_asv_metadata.json",
                 parent=None):
        super().__init__(parent)
        self.validation_files: list[str] = validation_files or []
        self._default_save_filename: str = default_save_filename
        self._temp_file_path: Path | None = None
        self._last_browse_directory: str = ""
        # Create widgets
        self._create_widgets()
        # Setup layout
        self._setup_layout()
        # Connect button signals
        self._connect_signals()
        # Set initial button states
        self._set_initial_button_states()

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _create_widgets(self):
        self.load_project_dir_button = LoadASVDataButton(parent=self)
        self.load_json_file_button = LoadJSONFileButton(parent=self)
        self.save_json_file_button = SaveJSONFileButton(parent=self)
        self.delete_json_file_button = DeleteJSONFileButton(parent=self)

    def _setup_layout(self):
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.load_project_dir_button)
        main_layout.addWidget(self.load_json_file_button)
        main_layout.addWidget(self.save_json_file_button)
        main_layout.addWidget(self.delete_json_file_button)
        main_layout.setContentsMargins(
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN
        )
        main_layout.setSpacing(AppStyles.Dimensions.LAYOUT_VSPACING)
        self.setLayout(main_layout)
        self.setStyleSheet(AppStyles.GroupBox.default())

    def _connect_signals(self):
        self.load_project_dir_button.clicked.connect(
            self._on_load_project_clicked
        )
        self.load_json_file_button.clicked.connect(
            self._on_load_json_clicked
        )
        self.save_json_file_button.clicked.connect(
            self._on_save_json_clicked
        )
        self.delete_json_file_button.clicked.connect(
            self._on_delete_json_clicked
        )

    def _set_initial_button_states(self):
        """Disable Save and Delete buttons until data is available."""
        self.save_json_file_button.setEnabled(False)
        self.delete_json_file_button.setEnabled(False)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def set_temp_file_path(self, path: str | Path | None):
        """Set the path to the temporary metadata JSON file.

        Enables or disables the Delete button based on whether the
        file exists on disk. Called by the parent tab after parsing
        completes or when metadata is loaded.

        :param path: Path to the temp file, or None to clear.
        """
        if path is not None:
            self._temp_file_path = Path(path)
        else:
            self._temp_file_path = None
        self._update_delete_button_state()

    def set_save_enabled(self, enabled: bool):
        """Enable or disable the Save button.

        :param enabled: True when metadata is loaded and available
                        to save.
        """
        self.save_json_file_button.setEnabled(enabled)

    def refresh_delete_button_state(self):
        """Re-check whether the temp file exists and update the
        Delete button accordingly. Call after deletion or any
        operation that may affect the temp file.
        """
        self._update_delete_button_state()

    # -----------------------------------------------------------------
    # Dialog Handlers
    # -----------------------------------------------------------------

    @Slot()
    def _on_load_project_clicked(self):
        """Open a folder dialog for selecting an ASV project directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select ASV Project Directory",
            self._last_browse_directory,
            QFileDialog.Option.ShowDirsOnly
        )
        if not directory:
            return

        self._last_browse_directory = directory
        path = Path(directory)

        # Validate the selected directory
        is_valid, missing_files = self._validate_directory(path)
        if is_valid:
            logger.info(f"ASV project directory selected: {path}")
            self.directory_selected.emit(str(path.resolve()))
        else:
            missing_names = ", ".join(missing_files)
            message = (
                f"Invalid ASV project directory. "
                f"Missing required files: {missing_names}"
            )
            logger.warning(message)
            self.validation_failed.emit(message)

    @Slot()
    def _on_load_json_clicked(self):
        """Open a file dialog for selecting a JSON metadata file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Metadata JSON File",
            self._last_browse_directory,
            "JSON Files (*.json);;All Files (*)"
        )
        if not file_path:
            return

        self._last_browse_directory = str(Path(file_path).parent)
        logger.info(f"JSON metadata file selected: {file_path}")
        self.json_file_selected.emit(str(Path(file_path).resolve()))

    @Slot()
    def _on_save_json_clicked(self):
        """Open a save dialog for choosing a metadata file destination."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Metadata File",
            str(Path(self._last_browse_directory) / self._default_save_filename),
            "JSON Files (*.json);;All Files (*)"
        )
        if not file_path:
            return

        # Ensure .json extension
        path = Path(file_path)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")

        self._last_browse_directory = str(path.parent)
        logger.info(f"Save destination selected: {path}")
        self.save_requested.emit(str(path))

    @Slot()
    def _on_delete_json_clicked(self):
        """Emit the delete request signal for the temporary file."""
        if self._temp_file_path and self._temp_file_path.exists():
            logger.info(
                f"Delete requested for temp file: {self._temp_file_path}"
            )
            self.delete_requested.emit()

    # -----------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------

    def _validate_directory(
        self, directory_path: Path
    ) -> tuple[bool, list[str]]:
        """Validate that all required files are present in the directory.

        Uses the same validation file list as the drag-and-drop widget.

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

    # -----------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------

    def _update_delete_button_state(self):
        """Enable the Delete button only if the temp file exists."""
        exists = (
            self._temp_file_path is not None
            and self._temp_file_path.exists()
        )
        self.delete_json_file_button.setEnabled(exists)