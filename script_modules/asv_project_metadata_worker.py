"""
ASV Project Metadata Worker

This module handles the ASV Project Metadata tab background operations
to keep the UI responsive.
The worker performs the following tasks:
- Discover .tif files to determine total image count for progress tracking.
- Parse metadata from an ASV project directory with progress reporting.
- Parse execution history and merge into image data.
- Handle cancellation requests from the UI.
- Write the consolidated metadata JSON file.
- Emit signals for status bar, progress bar, and dir_image QLabel image updates.

Architecture:
    The worker uses the QObject + QThread pattern. The ASVProjectMetadataTab
    creates a ProjectParsingWorker instance, moves it to a QThread, connects
    signals, and starts the thread. The worker emits signals to update UI
    elements (status bar, progress bar, dir_image QLabel) from the main thread.

    Cancellation is handled via a threading.Event flag that is checked
    between image parses by the directory parser's progress callback.

"""
import logging
import time
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from script_modules.asv_project_directory_parser import (
    discover_tif_files, parse_project_directory
)
from script_modules.consolidated_metadata_writer import write_consolidated_metadata
from script_modules.execution_history_parser import parse_execution_history
from script_modules.project_file_parser import parse_project_file


logger = logging.getLogger(__name__)


class ProjectParsingWorker(QObject):
    """
    Worker that parses an ASV project directory in a background thread.

    Performs four phases:
        1. Discovery — count .tif files for progress tracking.
        2. Parsing — extract metadata from each image with progress.
        3. Execution History — parse and merge execution history into images.
        4. Writing — save the consolidated metadata JSON file.

    Signals are emitted at each phase boundary and after each image
    so the UI can update the status bar, progress bar, and dir_image QLabel.
    """

    # --- Signals ---
    started = Signal(int)               # Total image count
    progress_updated = Signal(int, int)  # (current, total)
    status_message = Signal(str)         # Status bar message
    status_message_timed = Signal(str, int)   # Status bar message that clears after a delay
    completed = Signal(str)              # Output file path
    failed = Signal(str)                 # Error message
    cancelled = Signal()                 # Cancellation confirmed

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_event = threading.Event()
        self._execution_history_config: dict = {}
        self._project_file_config: dict = {}
        self._minify_json: bool = True

    def set_execution_history_config(self, config: dict):
        """Set the execution history configuration for parsing.

        Called once during setup before the worker thread starts.

        :param config: The ExecutionHistoryConfig section from the
            application configuration file.
        """
        self._execution_history_config = config
    
    def set_project_file_config(self, config: dict):
        """Set the project file configuration for parsing."""
        self._project_file_config = config

    def set_minify_json(self, value: bool):
        """Set whether the consolidated JSON file should be minified.

        Called once during setup before the worker thread starts.

        :param value: If True, write compact JSON. If False, write indented JSON.
        """
        self._minify_json = value

    def request_cancel(self):
        """Request cancellation of the current operation."""
        self._cancel_event.set()

    def _is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancel_event.is_set()

    def _on_progress(self, current: int, total: int):
        """Callback passed to the parser for per-image progress updates."""
        self.progress_updated.emit(current, total)

    @Slot(str, list, list, list, str, str)
    def run(
        self,
        project_path: str,
        root_dirs_to_exclude: list[str],
        sub_dirs_to_include: list[str],
        sub_dirs_to_exclude: list[str],
        output_dir_name: str,
        output_filename: str
    ):
        """
        Execute the full parsing workflow.

        :param project_path: Path to the ASV project root directory.
        :param root_dirs_to_exclude: Directory names to skip at the site level.
        :param sub_dirs_to_include: Subdirectory names to include within steps.
        :param sub_dirs_to_exclude: Subdirectory names to skip within steps.
        :param output_dir_name: Name of the output subdirectory for the JSON file.
        :param output_filename: Name of the consolidated metadata JSON file.
        """
        self._cancel_event.clear()
        project = Path(project_path)
        start_time = time.perf_counter()

        # --- Phase 1: Discovery ---
        self.status_message.emit(f"Discovering images in {project.name}...")
        logger.info(f"Discovering .tif files in: {project}")

        try:
            tif_files = discover_tif_files(
                project_path=project,
                root_dirs_to_exclude=root_dirs_to_exclude,
                sub_dirs_to_include=sub_dirs_to_include,
                sub_dirs_to_exclude=sub_dirs_to_exclude
            )
        except Exception:
            logger.error("Discovery failed", exc_info=True)
            self.failed.emit("Failed to discover images.")
            return

        total_images = len(tif_files)
        if total_images == 0:
            self.failed.emit("No .tif images found in the project directory.")
            return

        self.started.emit(total_images)
        logger.info(f"Discovered {total_images} .tif files.")

        if self._is_cancelled():
            self._handle_cancellation()
            return

        # --- Phase 2: Parsing ---
        self.status_message.emit(
            f"Parsing {total_images} images in {project.name}..."
        )
        logger.info(f"Parsing project directory: {project}")

        try:
            sites = parse_project_directory(
                project_path=project,
                root_dirs_to_exclude=root_dirs_to_exclude,
                sub_dirs_to_include=sub_dirs_to_include,
                sub_dirs_to_exclude=sub_dirs_to_exclude,
                progress_callback=self._on_progress,
                cancel_check=self._is_cancelled,
                total_images=total_images
            )
        except Exception:
            logger.error("Parsing failed", exc_info=True)
            self.failed.emit("Parsing failed.")
            return

        if self._is_cancelled():
            self._handle_cancellation()
            return

        if not sites:
            self.failed.emit("No valid sites found in the project directory.")
            return

        # Tally per-image extraction failures (extract_tif_metadata sets
        # an "Error" key on images it could not read)
        error_count = sum(
            1
            for site in sites
            for step in site.get("Steps", [])
            for image in step.get("Images", [])
            if "Error" in image
        )
        if error_count > 0:
            logger.warning(
                f"{error_count} image(s) could not be read during parsing."
            )
            self.status_message_timed.emit(
                f"Warning: {error_count} image(s) could not be read "
                "(metadata is empty in the output).",
                5000
            )

        # --- Phase 3: Execution History ---
        exec_history_path = project / "ExecutionHistory.json"
        if exec_history_path.exists() and self._execution_history_config:
            self.status_message.emit("Parsing execution history...")
            logger.info(f"Parsing execution history: {exec_history_path}")

            try:
                exec_history = parse_execution_history(
                    file_path=exec_history_path,
                    config=self._execution_history_config,
                )
                if exec_history:
                    merged_count = _merge_execution_history(
                        sites, exec_history
                    )
                    logger.info(
                        f"Merged execution history into "
                        f"{merged_count} image(s)."
                    )
            except Exception:
                # Execution history is supplemental — log but don't fail
                logger.error(
                    "Execution history parsing failed", exc_info=True
                )
                self.status_message_timed.emit(
                    "Warning: Execution history could not be parsed.", 5000
                )
        else:
            if not exec_history_path.exists():
                logger.info(
                    "No ExecutionHistory.json found — skipping."
                )

        if self._is_cancelled():
            self._handle_cancellation()
            return
        
        # --- Phase 3.5: Project Parameters ---
        project_file_path = project / "Project.AsvProject"
        project_parameters = {}
        if project_file_path.exists() and self._project_file_config:
            self.status_message.emit("Parsing project parameters...")
            logger.info(f"Parsing project file: {project_file_path}")

            try:
                project_parameters = parse_project_file(
                    file_path=project_file_path,
                    config=self._project_file_config,
                )
            except Exception:
                logger.error(
                    "Project file parsing failed", exc_info=True
                )
                self.status_message_timed.emit(
                    "Warning: Project parameters could not be parsed.", 5000
                )
        else:
            if not project_file_path.exists():
                logger.info("No Project.AsvProject found — skipping.")

        # --- Phase 4: Writing ---
        self.status_message.emit("Writing consolidated metadata file...")
        logger.info("Writing consolidated metadata JSON file.")

        try:
            output_dir = project / output_dir_name
            output_path = write_consolidated_metadata(
                output_directory=output_dir,
                output_filename=output_filename,
                project_name=project.name,
                project_root=str(project),
                sites=sites,
                project_parameters=project_parameters,
                minify=self._minify_json
            )
        except Exception:
            logger.error("Write failed", exc_info=True)
            self.failed.emit("Failed to write metadata.")
            return

        if output_path is None:
            self.failed.emit("Failed to write consolidated metadata file")
            return

        # --- Complete ---
        elapsed = time.perf_counter() - start_time
        minutes, seconds = divmod(elapsed, 60)
        message = f"Parsing complete in {int(minutes)}m {seconds:.2f}s."
        logger.info(message)
        logger.info(f"Consolidated metadata written to: {output_path}")
        self.status_message_timed.emit(message, 10000)
        self.completed.emit(str(output_path))

    def _handle_cancellation(self):
        """Log and emit the cancellation signal."""
        logger.info("Parsing cancelled by user.")
        self.status_message_timed.emit("Parsing cancelled.", 5000)
        self.cancelled.emit()


def _merge_execution_history(
    sites: list[dict],
    exec_history: dict,
) -> int:
    """
    Merge parsed execution history into the image data structures.

    For each image, looks up the execution history by site name and
    slice index, then stores the matching data in the image's
    ``ExecutionHistory`` field.

    :param sites: List of site dicts from the directory parser.
        Modified in place.
    :param exec_history: Parsed execution history keyed by
        site name -> slice index -> recipe -> activity.
    :return: Number of images that received execution history.
    """
    merged_count = 0

    for site in sites:
        site_name = site.get("SiteName", "")
        site_history = exec_history.get(site_name, {})

        if not site_history:
            continue

        for step in site.get("Steps", []):
            for image in step.get("Images", []):
                slice_index = image.get("FileNameSliceIndex")
                if slice_index is None:
                    continue

                # Execution history keys are integers
                slice_history = site_history.get(slice_index)
                if slice_history is None:
                    # Try string-to-int conversion
                    try:
                        slice_history = site_history.get(int(slice_index))
                    except (ValueError, TypeError):
                        continue

                if slice_history:
                    image["ExecutionHistory"] = slice_history
                    merged_count += 1

    return merged_count