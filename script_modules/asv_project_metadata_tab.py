"""
Module handles the ASV project metadata tab.

The tab includes:
- Two tabs: "Plots" and "Project Parameters"
- The "Plots" tab is populated with the plots_tab module.
- The "Project Parameters" tab is populated with the project_parameters_tab module.
- A right column with controls that is visible only when the "Plots" tab is active.
- A background worker (ProjectParsingWorker) for parsing ASV project directories.
- Cascading combo box population from loaded metadata.
- Display / Clear / Update plot wiring: extract data from metadata and create
  ASVPlotWidget instances in the PlotDisplayArea.
- Plots accumulate across Display clicks, allowing comparison of the same
  field across different site/step/detector combinations. Each plot is keyed
  by a composite key (site|step|detector|field_path) to prevent duplicates.
- Per-plot slice range spinboxes with auto-replot when the user adjusts them.
- Global Slice Index Range that applies a new start/end to all displayed plots.
"""
import logging
import shutil
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QPushButton, QApplication,
    QScrollArea
)
from PySide6.QtCore import QThread, QTimer, Slot, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from script_modules import config_manager
from script_modules.app_styles import AppStyles
from script_modules.plots_tab import PlotsTab
from script_modules.project_parameters_tab import ProjectParametersTab
from script_modules.config_manager import ConfigManager
from script_modules.groupboxes.dir_file_drop_groupbox import DirFileDropGroupBox
from script_modules.groupboxes.plot_selection_groupbox import PlotSelectionGroupBox
from script_modules.groupboxes.slice_index_range_groupbox import SliceIndexRangeGroupBox
from script_modules.groupboxes.global_slice_selection_groupbox import GlobalSliceSelectionGroupBox
from script_modules.groupboxes.load_data_groupbox import LoadDataGroupBox
from script_modules.groupboxes.auto_update_groupbox import AutoUpdateGroupBox
from script_modules.asv_project_metadata_worker import ProjectParsingWorker
from script_modules.auto_update_worker import FolderScanWorker
from script_modules.consolidated_metadata_writer import (
    load_consolidated_metadata, FORMAT_ID
)
from script_modules.widgets.status_bar_widget import StatusBarWidget
from script_modules.widgets.asv_plot_widget import ASVPlotWidget
from script_modules.metadata_query import (
    get_unique_detectors,
    filter_images_by_detector,
    get_available_plot_fields,
    get_slice_indices,
    extract_plot_data,
    detect_unit_suffix,
    parse_decimal_places,
    parse_plot_as_text,
    parse_convert_to_unit,
    resolve_plot_unit_and_conversion,
)
from script_modules.plot_exporter import export_all_plots
from script_modules.file_reveal import reveal_in_file_manager


logger = logging.getLogger(__name__)


class ASVProjectMetadataTab(QWidget):

    # Signal emitted when parsing state changes
    parsing_active = Signal(bool)
    _start_parsing = Signal(str, list, list, list, str, str)  # Internal signal
    _request_scan = Signal(str, list, list, list)  # Internal signal

    def __init__(self, config: ConfigManager, status_bar: StatusBarWidget,
                 parent=None):
        super().__init__(parent)
        self.config = config
        self.status_bar = status_bar
        self._metadata = None
        self._available_plot_fields = []
        # Default spinbox range from combo box context (for new plot creation)
        self._default_slice_min: int = 0
        self._default_slice_max: int = 0
        # Flag for cancelling plot rendering
        self._render_cancelled: bool = False
        # Path to the currently loaded metadata file (for save operations)
        self._metadata_file_path: Path | None = None
        # Composite key of the last plot that emitted slice_selected
        # (used to sync highlight during Prev/Next navigation)
        self._last_plot_key: str | None = None
        # Guard flag to prevent re-entry when navigation triggers
        # _on_slice_selected internally
        self._navigating: bool = False
        # When True, a slice selected in one plot is propagated to all
        # other displayed plots (driven by the "Link Slice Selection"
        # checkbox in the Global Slice Selection group box).
        self._slice_link_enabled: bool = False
        # Auto-update state: whether the folder watch is enabled, the
        # last {relative_path: mtime} snapshot of the project folder,
        # and guards so ticks are skipped (never queued) while a scan
        # or parse is in flight or the app is closing.
        self._auto_update_enabled: bool = False
        self._last_snapshot: dict | None = None
        self._scan_in_flight: bool = False
        self._parse_in_flight: bool = False
        self._auto_refresh_active: bool = False
        self._closing: bool = False
        # Snapshot that triggered the in-flight quiet rebuild; committed
        # to _last_snapshot only after the refresh succeeds so a failed
        # rebuild is retried on the next tick.
        self._pending_snapshot: dict | None = None
        # Project root the in-flight scan was requested for; results
        # from a previously loaded project are discarded.
        self._scan_requested_root: str = ""
        # Generation token: bumped whenever the loaded metadata is
        # replaced or deleted, so a quiet rebuild that was started for
        # older metadata discards its result instead of applying it.
        self._parse_generation: int = 0
        self._quiet_parse_generation: int = -1
        # True while a Display/Export loop is pumping events; a quiet
        # refresh completing in that window is deferred so it cannot
        # re-enter the loop and mix old and new metadata.
        self._ui_busy: bool = False
        self._pending_refresh_path: str | None = None
        # Manual parse completions are deferred the same way (F5): a
        # _load_metadata mid-render would clear plots under the loop.
        self._pending_manual_load_path: str | None = None
        # Create widgets
        self._create_widgets()
        # Setup layout
        self._setup_layout()
        # Setup worker
        self._setup_worker()
        # Setup auto-update scan worker and polling timer
        self._setup_auto_update()
        # Connect signals
        self._connect_signals()
        # Set initial button states (all disabled until data/selections exist)
        self._set_initial_button_states()

    def _create_widgets(self):
        """Create sub-tabs and right column controls."""
        # Sub-tabs
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(AppStyles.Window.tabs())
        self.plots_tab = PlotsTab(parent=self)
        self.project_parameters_tab = ProjectParametersTab(parent=self)
        self.tab_widget.addTab(self.plots_tab, "Plots")
        self.tab_widget.addTab(self.project_parameters_tab, "Project Parameters")

        # Project name button — displayed in the tab bar's right corner
        # so it sits in line with the tab labels and to the left of the
        # right-column controls.  Styled as a link-like title (label
        # appearance, tab-style hover); clicking it opens the project
        # directory in the OS file manager.
        self.project_name_button = QPushButton("")
        self.project_name_button.setVisible(False)
        self.project_name_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.project_name_button.setToolTip(
            AppStyles.AppToolTips.PROJECT_NAME_BUTTON
        )
        self.project_name_button.setStyleSheet(
            AppStyles.Button.link_title()
        )
        self.tab_widget.setCornerWidget(
            self.project_name_button, Qt.Corner.TopRightCorner
        )
        # Right column controls
        self.dir_file_drop_groupbox = DirFileDropGroupBox(
            validation_files=self.config.validation_files,
            parent=self    
        )
        self.plot_selection_groupbox = PlotSelectionGroupBox(parent=self)
        self.global_slice_selection_groupbox = GlobalSliceSelectionGroupBox(parent=self)
        self.slice_index_range_groupbox = SliceIndexRangeGroupBox(parent=self)
        self.auto_update_groupbox = AutoUpdateGroupBox(parent=self)
        self.load_data_groupbox = LoadDataGroupBox(
            validation_files=self.config.validation_files,
            default_save_filename=self.config.default_saved_json_filename,
            parent=self
        )

    def _setup_layout(self):
        """Setup the main layout with tabs on the left and controls on the right."""
        main_layout = QHBoxLayout(self)
        # Right column container
        self.right_column_container = QWidget()
        right_column_layout = QVBoxLayout(self.right_column_container)
        right_column_layout.setContentsMargins(0, 0, 0, 0)
        right_column_layout.setSpacing(0)
        right_column_layout.addWidget(self.dir_file_drop_groupbox)
        right_column_layout.addWidget(self.plot_selection_groupbox)
        right_column_layout.addWidget(self.global_slice_selection_groupbox)
        right_column_layout.addWidget(self.slice_index_range_groupbox)
        right_column_layout.addWidget(self.auto_update_groupbox)
        right_column_layout.addWidget(self.load_data_groupbox)
        right_column_layout.addStretch()

        # Scroll area wrapper: collapses the column's contribution to the
        # window minimum height so small screens can honor the requested
        # geometry (the column scrolls internally instead).
        self.right_column_scroll_area = QScrollArea()
        self.right_column_scroll_area.setWidget(self.right_column_container)
        self.right_column_scroll_area.setWidgetResizable(True)
        self.right_column_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.right_column_scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.right_column_scroll_area.setStyleSheet(
            AppStyles.ScrollArea.default()
        )
        # Reserve room for the vertical scrollbar so the groupboxes are
        # never squeezed or clipped when it appears (horizontal scrolling
        # is off).
        scrollbar_width = (
            self.right_column_scroll_area.verticalScrollBar()
            .sizeHint().width()
        )
        self.right_column_scroll_area.setMinimumWidth(
            self.right_column_container.sizeHint().width() + scrollbar_width
        )

        # Main layout
        main_layout.addWidget(self.tab_widget, 4)
        main_layout.addWidget(self.right_column_scroll_area, 1)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

    def _setup_worker(self):
        """Create the parsing worker and move it to a background thread."""
        self._worker_thread = QThread()
        self._worker = ProjectParsingWorker()
        # Pass execution history config to worker before moving to thread
        self._worker.set_execution_history_config(
            self.config.execution_history_config
        )
        # Pass project file config to worker before moving to thread
        self._worker.set_project_file_config(
            self.config.project_file_config
        )
        # Pass minify flag to worker before moving to thread
        self._worker.set_minify_json(self.config.minify_exported_json)
        self._worker.moveToThread(self._worker_thread)
        # Connect worker signals
        self._worker.started.connect(self._on_parsing_started)
        self._worker.progress_updated.connect(self._on_parsing_progress)
        self._worker.status_message.connect(self._on_status_message)
        self._worker.status_message_timed.connect(self._on_status_message_timed)
        self._worker.completed.connect(self._on_parsing_completed)
        self._worker.failed.connect(self._on_parsing_failed)
        self._worker.cancelled.connect(self._on_parsing_cancelled)
        self.status_bar.cancel_button_clicked_signal.connect(
            self._worker.request_cancel, Qt.ConnectionType.DirectConnection
        )
        self._start_parsing.connect(self._worker.run)
        # Start thread
        self._worker_thread.start()

    def _setup_auto_update(self):
        """Create the folder scan worker on a background thread and the
        polling timer that triggers scans.

        The main-thread timer only *requests* scans; the directory walk
        itself runs on the scan thread so large or slow (network) project
        folders never stall the UI.
        """
        self._scan_thread = QThread()
        self._scan_worker = FolderScanWorker()
        self._scan_worker.moveToThread(self._scan_thread)
        # Connect scan worker signals
        self._scan_worker.snapshot_ready.connect(self._on_scan_snapshot_ready)
        self._scan_worker.scan_failed.connect(self._on_scan_failed)
        self._request_scan.connect(self._scan_worker.scan)
        # Start thread
        self._scan_thread.start()
        # Polling timer (started/stopped by the auto-update checkbox)
        self._auto_update_timer = QTimer(self)
        self._auto_update_timer.timeout.connect(self._on_auto_update_tick)

    def _connect_signals(self):
        """Connect widget signals to handlers."""
        # Tab change: show/hide right column based on active tab
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        # Project name button: open the project directory
        self.project_name_button.clicked.connect(
            self._on_project_name_clicked
        )
        # Slice-data file name link: reveal the image in the file manager
        self.plots_tab.slice_data_groupbox.image_link_activated.connect(
            self._on_image_name_clicked
        )
        # Drop widget: directory dropped
        drop_widget = self.dir_file_drop_groupbox.dir_file_drop_widget
        drop_widget.directory_path_signal.connect(self._on_project_directory_dropped)
        drop_widget.validation_failed_signal.connect(self._on_validation_failed)
        # Drop widget: JSON dropped
        drop_widget.json_file_path_signal.connect(self._on_json_file_dropped)
        # Combo box cascade (activated = user interaction only)
        ps = self.plot_selection_groupbox
        ps.site_combobox.activated.connect(self._on_site_selected)
        ps.step_name_combobox.activated.connect(self._on_step_selected)
        ps.detector_combobox.activated.connect(self._on_detector_selected)
        # Display, Clear, and Export buttons
        ps.display_plots_button.clicked.connect(self._on_display_plots)
        ps.clear_plots_button.clicked.connect(self._on_clear_plots)
        ps.export_plots_button.clicked.connect(self._on_export_plots)
        # Plot selection combobox: enable/disable Display button
        ps.select_plots_combobox.selection_changed.connect(
            self._on_plot_selection_changed
        )
        # Global slice range update button
        sr = self.slice_index_range_groupbox
        sr.update_button.clicked.connect(self._on_update_slice_range)
        # Global slice selection: link slice selection across plots
        gss = self.global_slice_selection_groupbox
        gss.link_checkbox.toggled.connect(self._on_slice_link_toggled)
        # Cancel button: also handle plot rendering cancellation
        # (The worker connection in _setup_worker handles parsing cancellation;
        #  this additional connection handles the main-thread render loop.)
        self.status_bar.cancel_button_clicked_signal.connect(
            self._on_cancel_rendering
        )
        # Load data groupbox: dialog-based load, save, and delete
        ldg = self.load_data_groupbox
        ldg.directory_selected.connect(self._on_project_directory_dropped)
        ldg.json_file_selected.connect(self._on_json_file_dropped)
        ldg.save_requested.connect(self._on_save_metadata)
        ldg.delete_requested.connect(self._on_delete_temp_file)
        ldg.validation_failed.connect(self._on_validation_failed)
        # Auto-update groupbox: watch toggle and polling interval
        aug = self.auto_update_groupbox
        aug.auto_update_toggled.connect(self._on_auto_update_toggled)
        aug.interval_changed.connect(self._on_auto_update_interval_changed)
        # Image viewer: Prev / Next navigation
        sdg = self.plots_tab.slice_data_groupbox
        sdg.image_viewer_groupbox.slice_navigation_requested.connect(
            self._on_image_navigation
        )
        # Full-resolution dialogs: keyed Prev / Next navigation, routed
        # to the plot each dialog is tied to
        sdg.image_viewer_groupbox.dialog_navigation_requested.connect(
            self._on_dialog_navigation
        )
        # Metadata lookup for the full-resolution dialog panel
        sdg.image_viewer_groupbox.set_metadata_lookup(
            self._lookup_image_data
        )

    # =========================================================================
    # Tab Handlers
    # =========================================================================

    @Slot(int)
    def _on_tab_changed(self, index):
        """Show/hide the right column based on active tab."""
        self.right_column_scroll_area.setVisible(index == 0)  # 0 = Plots tab

    # =========================================================================
    # Drop Handlers
    # =========================================================================

    @Slot(str)
    def _on_project_directory_dropped(self, directory_path: str):
        """Handle a valid ASV project directory drop. Start the background
        parsing worker.
        """
        logger.info(f"Project directory dropped: {directory_path}")
        # Disable drops during parsing
        self.dir_file_drop_groupbox.dir_file_drop_widget.set_accepts_drops(False)
        # Start parsing via the worker (queued connection across threads)
        self._start_parsing.emit(
            directory_path,
            self.config.root_directories_to_exclude,
            self.config.sub_directories_to_include,
            self.config.sub_directories_to_exclude,
            self.config.temp_json_directory_name,
            self.config.temp_consolidated_json_filename
        )
    
    @Slot(str)
    def _on_json_file_dropped(self, file_path: str):
        """Handle a JSON file drop. Validate format and load metadata.

        The file is parsed once: the same dict is used for format
        validation and for loading (consolidated files can exceed
        100 MB, so a separate validation parse would double the hang).
        """
        if self._ui_busy:
            # A Display/Export loop is pumping events; loading now would
            # clear plots and swap metadata under the loop.
            self.status_bar.set_status_bar_message_timed(
                "Busy rendering; try loading again in a moment.", 3000
            )
            return

        path = Path(file_path)
        logger.info(f"JSON file dropped: {path}")

        metadata = load_consolidated_metadata(path)
        if metadata is None or metadata.get("_format") != FORMAT_ID:
            logger.warning(f"Invalid metadata file: {path.name}")
            self.status_bar.set_status_bar_message_timed(
                f"Invalid metadata file: {path.name}", 5000
            )
            self._update_catbug_state()
            return

        self._update_catbug_state()
        self._load_metadata(file_path, metadata=metadata)
        self.status_bar.set_status_bar_message_timed(
            f"Loaded: {path.name}", 5000
        )

    @Slot(str)
    def _on_validation_failed(self, message: str):
        """Handle validation failure from the drop widget or load dialog."""
        logger.warning(f"Directory validation failed: {message}")
        self.status_bar.set_status_bar_message_timed(message, 5000)

    @Slot()
    def _on_project_name_clicked(self):
        """Open the loaded project's root directory in the OS file
        manager.

        Guards against a missing directory: a consolidated JSON saved
        on another machine can carry a ``ProjectRoot`` that does not
        exist here (or is unmounted), in which case the status bar
        reports the problem instead.
        """
        project_root = self._metadata.get("ProjectRoot", "")
        if not project_root or not Path(project_root).is_dir():
            self.status_bar.set_status_bar_message_timed(
                f"Project directory not found: {project_root or 'unknown'}",
                5000,
            )
            return
        logger.info(f"Opening project directory: {project_root}")
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(project_root)):
            logger.warning(
                f"QDesktopServices could not open: {project_root}"
            )
            self.status_bar.set_status_bar_message_timed(
                f"Failed to open project directory: {project_root}", 5000
            )

    @Slot(str)
    def _on_image_name_clicked(self, image_path: str):
        """Reveal the selected slice's image in the OS file manager.

        Mirrors ``_on_project_name_clicked``: on failure (missing file or a
        file manager that would not open) the status bar reports it instead
        of raising.
        """
        if not reveal_in_file_manager(image_path):
            self.status_bar.set_status_bar_message_timed(
                f"Image file not found: {image_path or 'unknown'}", 5000
            )

    # =========================================================================
    # Worker Signal Handlers
    # =========================================================================

    @Slot(int)
    def _on_parsing_started(self, total_images: int):
        """Handle parsing started. Setup UI for active parsing state.

        Auto-update refreshes run quietly: no progress bar, cancel
        button, or tab disabling — only the auto-update status label.
        """
        self._parse_in_flight = True
        if self._auto_refresh_active:
            logger.info(
                f"Auto-update refresh started: {total_images} images."
            )
            self.auto_update_groupbox.set_status("Updating...")
            return
        self.parsing_active.emit(True)
        self.tab_widget.setTabEnabled(1, False)
        logger.info(f"Parsing started: {total_images} images to parse.")
        # Catbug to color
        self._update_catbug_state()
        # Show and configure progress bar
        self.status_bar.set_progress_bar_range(0, total_images)
        self.status_bar.set_progress_bar_value(0)
        self.status_bar.set_progress_bar_visible(True)
        # Show cancel button
        self.status_bar.set_cancel_button_visible(True)
        # Park focus at the top before disabling the load buttons: if the
        # parse was launched from a load button (it holds focus),
        # disabling it would migrate focus down to the bottom Auto-Update
        # group and scroll the column to the bottom.
        self._park_right_column_focus()
        # Disable load buttons during parsing
        self.load_data_groupbox.load_project_dir_button.setEnabled(False)
        self.load_data_groupbox.load_json_file_button.setEnabled(False)

    @Slot(int, int)
    def _on_parsing_progress(self, current: int, total: int):
        """Handle per-image progress updates from the worker."""
        if self._auto_refresh_active:
            return
        self.status_bar.set_progress_bar_value(current)

    @Slot(str)
    def _on_status_message(self, message: str):
        """Handle status bar message updates from the worker."""
        if self._auto_refresh_active:
            return
        self.status_bar.set_status_bar_message(message)

    @Slot(str, int)
    def _on_status_message_timed(self, message: str, timeout: int):
        """Handle timed status bar message updates from the worker."""
        if self._auto_refresh_active:
            return
        self.status_bar.set_status_bar_message_timed(message, timeout)

    @Slot(str)
    def _on_parsing_completed(self, output_path: str):
        """Handle successful parsing completion. Load metadata and
        populate combo boxes.

        Auto-update refreshes keep the current view: metadata is
        reloaded in place instead of through the destructive
        _load_metadata path.
        """
        logger.info(f"Consolidated metadata written to: {output_path}")
        self._parse_in_flight = False
        if self._auto_refresh_active:
            if self._ui_busy:
                # A Display/Export loop is pumping events right now;
                # defer so the refresh cannot re-enter it mid-iteration.
                # _auto_refresh_active stays True so ticks are skipped.
                self._pending_refresh_path = output_path
                return
            self._apply_quiet_refresh(output_path)
            return
        if self._ui_busy:
            # A Display/Export loop is pumping events; loading now would
            # clear plots and swap metadata under the loop. Defer.
            self._pending_manual_load_path = output_path
            return
        self._reset_parsing_ui()
        self._load_metadata(output_path)
        # Track the temp file for delete button management
        self.load_data_groupbox.set_temp_file_path(output_path)

    @Slot(str)
    def _on_parsing_failed(self, message: str):
        """Handle parsing failure."""
        logger.error(f"Parsing failed: {message}")
        self._parse_in_flight = False
        if self._auto_refresh_active:
            # Keep the current metadata and view. The old baseline is
            # kept too (pending snapshot discarded), so the next tick
            # re-detects the change and retries the rebuild.
            self._auto_refresh_active = False
            self._pending_snapshot = None
            self.auto_update_groupbox.set_status(
                "Watching..." if self._auto_update_enabled else "Idle"
            )
            self._update_catbug_state()
            self.status_bar.set_status_bar_message_timed(
                "Auto-update: refresh failed; keeping current view.", 8000
            )
            return
        self.status_bar.set_status_bar_message_timed(message, 10000)
        self._reset_parsing_ui()

    @Slot()
    def _on_parsing_cancelled(self):
        """Handle parsing cancellation."""
        self._parse_in_flight = False
        if self._auto_refresh_active:
            # Reachable via the render-loop Cancel button (wired to the
            # worker with a DirectConnection). Keep the old baseline so
            # the next tick re-detects the change and retries.
            self._auto_refresh_active = False
            self._pending_snapshot = None
            self.auto_update_groupbox.set_status(
                "Watching..." if self._auto_update_enabled else "Idle"
            )
            self._update_catbug_state()
            return
        self._reset_parsing_ui()

    # =========================================================================
    # Auto-Update Handlers
    # =========================================================================

    @Slot(bool)
    def _on_auto_update_toggled(self, checked: bool):
        """Handle the auto-update checkbox toggle.

        Starts or stops the polling timer. On enable, an immediate scan
        records the baseline snapshot (no rebuild is triggered until a
        later scan differs from it).

        :param checked: True to start watching the project folder.
        """
        self._auto_update_enabled = checked
        if checked:
            self._last_snapshot = None
            self._auto_update_timer.start(
                self.auto_update_groupbox.interval_seconds() * 1000
            )
            self.auto_update_groupbox.set_status("Watching...")
            logger.info("Auto-update enabled.")
            # Kick an immediate baseline scan
            self._on_auto_update_tick()
        else:
            self._auto_update_timer.stop()
            self.auto_update_groupbox.set_status("Idle")
            logger.info("Auto-update disabled.")
        self._update_catbug_state()

    @Slot(int)
    def _on_auto_update_interval_changed(self, seconds: int):
        """Handle a polling interval change from the spinbox.

        :param seconds: New polling interval in seconds.
        """
        if self._auto_update_timer.isActive():
            self._auto_update_timer.setInterval(seconds * 1000)
        logger.info(f"Auto-update interval set to {seconds}s.")

    @Slot()
    def _on_auto_update_tick(self):
        """Request a background folder scan on each timer tick.

        Ticks are skipped (never queued) while a scan or parse is in
        flight, so slow disks or long parses cannot pile up work.
        """
        if (self._scan_in_flight or self._parse_in_flight
                or self._auto_refresh_active or self._closing):
            return
        if not self._metadata:
            return
        project_root = self._metadata.get("ProjectRoot", "")
        if not project_root:
            return
        self._scan_in_flight = True
        self._scan_requested_root = project_root
        self._request_scan.emit(
            project_root,
            self.config.root_directories_to_exclude,
            self.config.sub_directories_to_include,
            self.config.sub_directories_to_exclude
        )

    @Slot(dict)
    def _on_scan_snapshot_ready(self, snapshot: dict):
        """Compare the scan snapshot against the baseline and trigger a
        quiet metadata rebuild when the project folder has changed.

        :param snapshot: {relative_tif_path: mtime} from the scan worker.
        """
        self._scan_in_flight = False
        if self._closing or not self._auto_update_enabled:
            return
        # A manual load may have started while the scan was running;
        # never trigger (or baseline) against a parse in flight — the
        # next tick rescans once the parse finishes.
        if self._parse_in_flight or self._auto_refresh_active:
            return
        # A different project may have been loaded while the scan was
        # running; a stale snapshot of the old root must not become the
        # baseline for the new one (the next tick rescans the new root).
        current_root = self._metadata.get("ProjectRoot", "") \
            if self._metadata else ""
        if self._scan_requested_root != current_root:
            return

        if self._last_snapshot is None:
            # First scan after enable: record the baseline only
            self._last_snapshot = snapshot
            self.auto_update_groupbox.set_status("Watching...")
            return

        if snapshot == self._last_snapshot:
            self.auto_update_groupbox.set_status("Watching...")
            return

        # Change detected: rebuild the consolidated JSON via the
        # existing parsing worker (quietly — see _on_parsing_started).
        # The snapshot only becomes the baseline once the refresh
        # succeeds, so a failed rebuild is retried on the next tick.
        self._pending_snapshot = snapshot
        project_root = current_root
        if not project_root:
            return
        logger.info(
            "Auto-update: project folder changed; rebuilding metadata."
        )
        self._auto_refresh_active = True
        self._quiet_parse_generation = self._parse_generation
        self.auto_update_groupbox.set_status("Updating...")
        self._start_parsing.emit(
            project_root,
            self.config.root_directories_to_exclude,
            self.config.sub_directories_to_include,
            self.config.sub_directories_to_exclude,
            self.config.temp_json_directory_name,
            self.config.temp_consolidated_json_filename
        )

    @Slot(str)
    def _on_scan_failed(self, message: str):
        """Handle a failed folder scan (folder deleted or unmounted).

        Stops watching and informs the user via the status bar; never
        raises a dialog.

        :param message: Error description from the scan worker.
        """
        self._scan_in_flight = False
        if self._closing:
            return
        logger.warning(f"Auto-update stopped: {message}")
        self._stop_auto_update()
        self.status_bar.set_status_bar_message_timed(
            "Auto-update stopped: project folder unavailable.", 8000
        )

    def _stop_auto_update(self):
        """Stop watching and reset the auto-update controls.

        Silently unchecks the checkbox (no toggle signal) and disables
        the controls. Used when the project folder disappears or the
        loaded metadata is deleted.
        """
        self._auto_update_timer.stop()
        self._auto_update_enabled = False
        self._last_snapshot = None
        self._pending_snapshot = None
        self.auto_update_groupbox.set_checked_silent(False)
        self.auto_update_groupbox.set_controls_enabled(False)
        self.auto_update_groupbox.set_status("Idle")
        self._update_catbug_state()

    def _apply_quiet_refresh(self, output_path: str):
        """Apply a completed quiet rebuild.

        Refreshes the view in place, commits the pending folder
        baseline on success, and resets the refresh flags. The result
        is discarded when the loaded metadata changed while the rebuild
        was in flight (generation token mismatch) — applying it would
        silently swap the previous project back in.

        :param output_path: Path to the rebuilt consolidated JSON.
        """
        self._auto_refresh_active = False
        if self._quiet_parse_generation != self._parse_generation:
            logger.info(
                "Auto-update: discarding stale refresh result "
                "(metadata was replaced or deleted mid-rebuild)."
            )
            self._pending_snapshot = None
            self.auto_update_groupbox.set_status(
                "Watching..." if self._auto_update_enabled else "Idle"
            )
            self._update_catbug_state()
            return
        if self._refresh_metadata_in_place(output_path):
            # Commit the baseline only after a successful refresh so a
            # failed one is retried on the next tick.
            if self._pending_snapshot is not None:
                self._last_snapshot = self._pending_snapshot
            self.load_data_groupbox.set_temp_file_path(output_path)
        self._pending_snapshot = None
        self._update_catbug_state()

    def _apply_pending_quiet_refresh(self):
        """Apply a quiet refresh or manual load that completed while a
        Display/Export loop was pumping events (deferred in
        _on_parsing_completed). At most one of the two can be pending
        (a single parse worker).
        """
        if self._pending_manual_load_path is not None:
            path = self._pending_manual_load_path
            self._pending_manual_load_path = None
            self._reset_parsing_ui()
            self._load_metadata(path)
            self.load_data_groupbox.set_temp_file_path(path)
            return
        if self._pending_refresh_path is None:
            return
        path = self._pending_refresh_path
        self._pending_refresh_path = None
        self._apply_quiet_refresh(path)

    def _update_catbug_state(self):
        """Set the drop-widget image to color or grayscale.

        The image is colorized while a parse is running or auto-update
        is watching the project folder, and grayscale otherwise, so it
        doubles as the activity indicator for both.
        """
        drop_widget = self.dir_file_drop_groupbox.dir_file_drop_widget
        if self._parse_in_flight or self._auto_update_enabled:
            drop_widget.set_image_color()
        else:
            drop_widget.set_image_grayscale()

    def _refresh_metadata_in_place(self, file_path: str) -> bool:
        """Reload rebuilt metadata without disturbing the current view.

        Unlike _load_metadata, this preserves the displayed plots, the
        site/step/detector selection, the checked plot fields, and the
        slice ranges. Each displayed plot is re-extracted from the new
        metadata and updated in place; plots whose source data no longer
        exists are blanked but kept in the display area. Ranges that
        were pinned at the old data bounds follow the new bounds, so
        newly acquired slices appear; deliberately narrowed sub-ranges
        are preserved.

        :param file_path: Path to the rebuilt consolidated JSON.
        :return: True if the new metadata was applied.
        """
        new_metadata = load_consolidated_metadata(Path(file_path))
        if new_metadata is None:
            logger.error(
                f"Auto-update: failed to load rebuilt metadata: {file_path}"
            )
            self.auto_update_groupbox.set_status(
                "Watching..." if self._auto_update_enabled else "Idle"
            )
            self.status_bar.set_status_bar_message_timed(
                "Auto-update: could not read rebuilt metadata; "
                "keeping current view.", 8000
            )
            return False

        # --- Capture the current view state before swapping metadata ---
        ps = self.plot_selection_groupbox
        sr = self.slice_index_range_groupbox
        selected_site = ps.site_combobox.currentText()
        selected_step = ps.step_name_combobox.currentText()
        selected_detector = ps.detector_combobox.currentText()
        checked_labels = ps.select_plots_combobox.checked_items()
        global_start = sr.start_slice_spinbox.value()
        global_end = sr.end_slice_spinbox.value()
        old_global_min = sr.start_slice_spinbox.minimum()
        old_global_max = sr.end_slice_spinbox.maximum()
        all_plots = self.plots_tab.plot_display_area.get_all_plots()
        plot_ranges = {
            key: (widget.slice_start, widget.slice_end,
                  widget.slice_min, widget.slice_max)
            for key, widget in all_plots.items()
        }

        # --- Swap in the new metadata ---
        self._metadata = new_metadata
        self._metadata_file_path = Path(file_path)
        project_name = self._metadata.get("ProjectName", "")
        self.project_name_button.setText(project_name)
        self.project_name_button.setVisible(bool(project_name))
        self.project_parameters_tab.populate(
            self._metadata.get("ProjectParameters", {})
        )

        # --- Restore the combo cascade and checked plot fields ---
        self._restore_combo_selection(
            selected_site, selected_step, selected_detector, checked_labels
        )

        # --- Refresh displayed plots in place ---
        refreshed_count = 0
        stale_count = 0
        for composite_key, plot_widget in all_plots.items():
            detector_images = self._images_for_composite_key(composite_key)
            slice_indices = (
                get_slice_indices(detector_images) if detector_images else []
            )
            if not slice_indices:
                # Site/step/detector no longer exists or has no images:
                # blank the plot but keep it displayed. Zero its range
                # so it cannot contribute phantom bounds to the global
                # slice range union.
                plot_widget.clear_plot()
                plot_widget.set_slice_range(
                    start=0, end=0, min_val=0, max_val=0
                )
                stale_count += 1
                continue
            new_min = min(slice_indices)
            new_max = max(slice_indices)
            start_slice, end_slice, old_min, old_max = \
                plot_ranges[composite_key]
            # A range pinned at the old data bounds follows the new
            # bounds (so newly acquired slices appear); a deliberately
            # narrowed sub-range is preserved.
            if end_slice == old_max:
                end_slice = new_max
            if start_slice == old_min:
                start_slice = new_min
            # Clamp the result to the new available range
            start_slice = min(max(start_slice, new_min), new_max)
            end_slice = min(max(end_slice, new_min), new_max)
            plot_widget.set_slice_range(
                start=start_slice, end=end_slice,
                min_val=new_min, max_val=new_max
            )
            if self._replot_single(composite_key, plot_widget,
                                   start_slice, end_slice):
                refreshed_count += 1
            else:
                stale_count += 1

        # --- Restore the global slice range where still valid ---
        if all_plots:
            self._update_global_slice_range()
            g_min = sr.start_slice_spinbox.minimum()
            g_max = sr.end_slice_spinbox.maximum()
            # Same pinned-edge rule as per-plot ranges
            if global_end == old_global_max:
                global_end = g_max
            if global_start == old_global_min:
                global_start = g_min
            if (g_min <= global_start <= global_end <= g_max):
                sr.start_slice_spinbox.blockSignals(True)
                sr.end_slice_spinbox.blockSignals(True)
                sr.start_slice_spinbox.setValue(global_start)
                sr.end_slice_spinbox.setValue(global_end)
                sr.start_slice_spinbox.blockSignals(False)
                sr.end_slice_spinbox.blockSignals(False)

        # --- Reconcile the side panels and full-res windows ---
        self._reconcile_side_panels()
        self._reconcile_full_res_dialogs()

        # --- Report the outcome (status text only, never a dialog) ---
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.auto_update_groupbox.set_status(
            f"Updated {timestamp}" if self._auto_update_enabled else "Idle"
        )
        summary = f"Project updated: {refreshed_count} plot(s) refreshed"
        if stale_count:
            summary += f", {stale_count} without data"
        self.status_bar.set_status_bar_message_timed(f"{summary}.", 5000)
        logger.info(
            f"Auto-update refresh complete: {refreshed_count} refreshed, "
            f"{stale_count} stale."
        )
        return True

    def _reconcile_side_panels(self):
        """Re-sync the slice data panels after an in-place refresh.

        The metadata/execution-history/image panels and the Prev/Next
        navigation context hold data captured from the pre-refresh
        metadata. If the displayed image still exists in the refreshed
        active plot, the navigation context and panels are re-resolved
        against the new metadata; otherwise the panels are cleared
        (mirroring _on_plot_close_requested) so they cannot show
        deleted data or desync the navigation index.
        """
        sdg = self.plots_tab.slice_data_groupbox
        ivg = sdg.image_viewer_groupbox
        image_name = ivg._image_name
        if not image_name:
            return

        active = None
        if self._last_plot_key is not None:
            active = self.plots_tab.plot_display_area.get_plot(
                self._last_plot_key
            )
        if active is None or image_name not in active._image_names:
            # Reset the panels only; other plots' full-resolution
            # dialogs are handled by _reconcile_full_res_dialogs
            sdg.clear_all(close_dialogs=False)
            return

        # The image survived the refresh: rebuild the navigation
        # context from the refreshed plot and repopulate the panels
        # from the new metadata (guarded so the navigation context is
        # not reset by _on_slice_selected itself).
        site_name = active._site_name
        step_name = active._step_name
        detector = active._detector
        nav_names = list(active._image_names)
        nav_paths = self._resolve_image_paths(
            nav_names, site_name, step_name
        )
        ivg.set_navigation_context(
            image_names=nav_names,
            image_paths=nav_paths,
            site_name=site_name,
            step_name=step_name,
            detector=detector,
            composite_key=self._last_plot_key,
            plot_title=active._title.split("\n", 1)[0],
            values=list(active._values),
        )
        self._navigating = True
        self._on_slice_selected(image_name, site_name, step_name, detector)
        self._navigating = False
        if image_name in nav_names:
            active.highlight_point_by_index(nav_names.index(image_name))

    def _reconcile_full_res_dialogs(self):
        """Re-sync open full-resolution dialogs after plots change.

        Each open dialog is tied to a plot; after a replot or an
        in-place metadata refresh the plot's image list (and values)
        may have changed. Dialogs whose plot or displayed image no
        longer exists are closed; survivors get rebuilt navigation
        lists with their zoom preserved (an unchanged image path skips
        the redraw inside update_context).
        """
        ivg = self.plots_tab.slice_data_groupbox.image_viewer_groupbox
        for key in ivg.open_dialog_keys():
            dialog = ivg.get_dialog(key)
            if dialog is None:
                continue
            plot_widget = self.plots_tab.plot_display_area.get_plot(key)
            if (plot_widget is None
                    or dialog._image_name not in plot_widget._image_names):
                ivg.close_dialog_for(key)
                logger.info(
                    f"Closed full-resolution window for vanished "
                    f"plot/image: {key}"
                )
                continue
            nav_names = list(plot_widget._image_names)
            nav_paths = self._resolve_image_paths(
                nav_names, plot_widget._site_name, plot_widget._step_name
            )
            nav_index = nav_names.index(dialog._image_name)
            metadata, exec_history = self._lookup_image_data(
                dialog._image_name,
                plot_widget._site_name,
                plot_widget._step_name,
                plot_widget._detector,
            )
            dialog.update_context(
                image_path=nav_paths[nav_index],
                image_name=dialog._image_name,
                nav_image_names=nav_names,
                nav_image_paths=nav_paths,
                nav_index=nav_index,
                nav_site=plot_widget._site_name,
                nav_step=plot_widget._step_name,
                nav_detector=plot_widget._detector,
                metadata=metadata,
                exec_history=exec_history,
                nav_values=list(plot_widget._values),
                raise_window=False,
            )

    def _restore_combo_selection(
        self,
        site_name: str,
        step_name: str,
        detector: str,
        checked_labels: list[str]
    ):
        """Repopulate the combo cascade from the current metadata,
        re-selecting the prior site/step/detector where they still
        exist (falling back to the first entry otherwise) and
        re-checking the prior plot fields that are still available.

        :param site_name: Previously selected site name.
        :param step_name: Previously selected step name.
        :param detector: Previously selected detector name.
        :param checked_labels: Previously checked plot field labels.
        """
        ps = self.plot_selection_groupbox
        ps.site_combobox.clear()
        sites = self._metadata.get("Sites", [])
        ps.site_combobox.addItems([site["SiteName"] for site in sites])
        if ps.site_combobox.count() == 0:
            ps.step_name_combobox.clear()
            ps.detector_combobox.clear()
            ps.select_plots_combobox.clear_items()
            self._available_plot_fields = []
            return

        site_index = ps.site_combobox.findText(site_name)
        if site_index < 0:
            site_index = 0
        ps.site_combobox.setCurrentIndex(site_index)
        # Cascade populates steps/detectors/fields and auto-selects the
        # first entries (same pattern as _populate_sites)
        self._on_site_selected(site_index)

        step_index = ps.step_name_combobox.findText(step_name)
        if step_index >= 0 and \
                step_index != ps.step_name_combobox.currentIndex():
            ps.step_name_combobox.setCurrentIndex(step_index)
            self._on_step_selected(step_index)

        detector_index = ps.detector_combobox.findText(detector)
        if detector_index >= 0 and \
                detector_index != ps.detector_combobox.currentIndex():
            ps.detector_combobox.setCurrentIndex(detector_index)
            self._on_detector_selected(detector_index)

        # Re-check prior plot fields that still exist
        if checked_labels:
            ps.select_plots_combobox.set_checked_items_by_text(
                checked_labels
            )

    def _images_for_composite_key(self, composite_key: str) -> list | None:
        """Return the detector-filtered images for a composite key.

        :param composite_key: Plot key (site|step|detector|field_path).
        :return: List of image dicts, or None if the site/step no
                 longer exists in the loaded metadata.
        """
        if not self._metadata:
            return None
        parts = composite_key.split("|", 3)
        if len(parts) != 4:
            return None
        site_name, step_name, detector, _field_path = parts
        for site in self._metadata.get("Sites", []):
            if site.get("SiteName") != site_name:
                continue
            for step in site.get("Steps", []):
                if step.get("StepName") != step_name:
                    continue
                return filter_images_by_detector(
                    step.get("Images", []), detector
                )
        return None

    # =========================================================================
    # Combo Box Cascade Handlers
    # =========================================================================

    @Slot(int)
    def _on_site_selected(self, index: int):
        """Populate steps for the selected site and clear downstream."""
        if self._ui_busy:
            # A render/export loop is pumping events; mutating the
            # cascade under it would corrupt the loop's slice context.
            return
        ps = self.plot_selection_groupbox
        # Clear downstream combo boxes
        ps.step_name_combobox.clear()
        ps.detector_combobox.clear()
        ps.select_plots_combobox.clear_items()
        self._available_plot_fields = []

        sites = self._metadata.get("Sites", [])
        if index < 0 or index >= len(sites):
            return

        steps = sites[index].get("Steps", [])
        step_names = [step["StepName"] for step in steps]
        ps.step_name_combobox.addItems(step_names)
        # Auto-select first step and cascade to detector
        if step_names:
            ps.step_name_combobox.setCurrentIndex(0)
            self._on_step_selected(0)
        else:
            ps.step_name_combobox.setCurrentIndex(-1)
        logger.info(f"Site selected: {sites[index]['SiteName']} "
                     f"({len(step_names)} steps)")

    @Slot(int)
    def _on_step_selected(self, index: int):
        """Populate detectors for the selected step and clear downstream."""
        if self._ui_busy:
            return
        ps = self.plot_selection_groupbox
        # Clear downstream combo boxes
        ps.detector_combobox.clear()
        ps.select_plots_combobox.clear_items()
        self._available_plot_fields = []

        site_index = ps.site_combobox.currentIndex()
        sites = self._metadata.get("Sites", [])
        if site_index < 0 or site_index >= len(sites):
            return

        steps = sites[site_index].get("Steps", [])
        if index < 0 or index >= len(steps):
            return

        # Extract unique detectors from images in this step
        images = steps[index].get("Images", [])
        detectors = get_unique_detectors(images)
        ps.detector_combobox.addItems(detectors)
        # Auto-select first detector and cascade to populate plots
        if detectors:
            ps.detector_combobox.setCurrentIndex(0)
            self._on_detector_selected(0)
        else:
            ps.detector_combobox.setCurrentIndex(-1)
        logger.info(f"Step selected: {steps[index]['StepName']} "
                     f"({len(detectors)} detectors)")

    @Slot(int)
    def _on_detector_selected(self, index: int):
        """Populate available plots for the selected detector and update
        the slice index range spinboxes.
        """
        if self._ui_busy:
            return
        ps = self.plot_selection_groupbox
        ps.select_plots_combobox.clear_items()
        self._available_plot_fields = []

        site_index = ps.site_combobox.currentIndex()
        step_index = ps.step_name_combobox.currentIndex()
        detector = ps.detector_combobox.currentText()

        sites = self._metadata.get("Sites", [])
        if site_index < 0 or site_index >= len(sites):
            return
        steps = sites[site_index].get("Steps", [])
        if step_index < 0 or step_index >= len(steps):
            return

        images = steps[step_index].get("Images", [])
        detector_images = filter_images_by_detector(images, detector)
        # Keep the fields in the order the combobox presents them
        # (casefold-alphabetical), so everything downstream — combobox
        # population, plot display — inherits the same order.
        self._available_plot_fields = sorted(
            get_available_plot_fields(
                images=detector_images,
                plot_fields=self.config.plot_fields
            ),
            key=lambda field: field["Label"].casefold()
        )
        labels = [field["Label"] for field in self._available_plot_fields]
        ps.select_plots_combobox.add_checkable_items(labels)
        logger.info(f"Detector selected: {detector} "
                     f"({len(labels)} available plots)")

        # Update default slice range from the filtered images
        self._update_default_slice_range(detector_images)

    # =========================================================================
    # Display / Clear / Update Plot Handlers
    # =========================================================================

    @Slot()
    def _on_display_plots(self):
        """
        Handle the Display Plots button click.

        The render loop pumps events (processEvents), so it is guarded
        against re-entry, and a quiet auto-update refresh completing
        mid-render is deferred until the loop finishes. Rendering during
        a manual parse is blocked — both would fight over the shared
        progress bar and Cancel button (quiet refreshes render fine).
        """
        if self._parse_in_flight and not self._auto_refresh_active:
            self.status_bar.set_status_bar_message_timed(
                "Parsing in progress; please wait.", 3000
            )
            return
        if self._ui_busy:
            return
        self._ui_busy = True
        try:
            self._display_plots_impl()
        finally:
            self._ui_busy = False
            self._apply_pending_quiet_refresh()

    def _display_plots_impl(self):
        """
        Render the checked plot selections.

        Reads the checked plot selections, extracts data series from the
        loaded metadata for the current site/step/detector, respects the
        slice range from the global spinboxes, creates ASVPlotWidget instances,
        and adds them to the PlotsTab display area.

        Plots accumulate rather than replace, allowing comparisons of the
        same field across different site/step/detector combinations. Each
        plot is keyed by a composite key (site|step|detector|field_path)
        so duplicates are skipped with a status bar message.

        When "Link Slice Selection" is enabled, each newly created plot
        is initialized with the linked slice highlighted, provided that
        slice falls within the plot's index range and data.
        """
        ps = self.plot_selection_groupbox
        sr = self.slice_index_range_groupbox

        # Get checked plot labels from the multi-select combobox
        checked_labels = ps.select_plots_combobox.checked_items()
        if not checked_labels:
            self.status_bar.set_status_bar_message_timed(
                "No plots selected.", 3000
            )
            return

        # Match checked labels to available plot field dicts.
        # _available_plot_fields is already in combobox (alphabetical)
        # order, so the plots added by this click follow the selection
        # list. Plots accumulate across Display clicks, so the overall
        # stack reads in click order, not combobox order.
        checked = set(checked_labels)
        selected_fields = [
            field for field in self._available_plot_fields
            if field["Label"] in checked
        ]
        if not selected_fields:
            self.status_bar.set_status_bar_message_timed(
                "No matching plot fields found.", 3000
            )
            return

        # Get current combo box selections
        site_index = ps.site_combobox.currentIndex()
        step_index = ps.step_name_combobox.currentIndex()
        detector = ps.detector_combobox.currentText()

        # Validate that all three levels have been selected
        if site_index < 0 or step_index < 0 or not detector:
            self.status_bar.set_status_bar_message_timed(
                "Please select a site, step, and detector first.", 3000
            )
            return

        # Get current context names for titles and composite keys
        site_name = ps.site_combobox.currentText()
        step_name = ps.step_name_combobox.currentText()

        # Get images for the selected site/step, filtered by detector
        sites = self._metadata.get("Sites", [])
        steps = sites[site_index].get("Steps", [])
        images = steps[step_index].get("Images", [])
        detector_images = filter_images_by_detector(images, detector)

        # Get slice range from global spinboxes
        start_slice = sr.start_slice_spinbox.value()
        end_slice = sr.end_slice_spinbox.value()

        # Show determinate progress bar and cancel button for plot rendering
        self._render_cancelled = False
        total_fields = len(selected_fields)
        self.status_bar.set_status_bar_message(
            f"Rendering plots (0/{total_fields})..."
        )
        self.status_bar.set_progress_bar_range(0, total_fields)
        self.status_bar.set_progress_bar_value(0)
        self.status_bar.set_progress_bar_visible(True)
        self.status_bar.set_cancel_button_visible(True)

        # Create a plot widget for each selected field (accumulates with
        # existing plots to allow cross-dataset comparison)
        plot_count = 0
        skipped_count = 0
        cancelled = False
        for field_index, field in enumerate(selected_fields):
            field_path = field["Path"]
            field_label = field["Label"]
            field_unit = field.get("Unit", "")
            # Optional per-field display precision (null -> full precision)
            field_decimals = parse_decimal_places(field.get("DecimalPlaces"))
            # Optional categorical text y-axis (absent/false -> numeric)
            field_plot_as_text = parse_plot_as_text(field.get("PlotAsText"))

            # Composite key: allows the same field from different
            # site/step/detector combinations to coexist
            composite_key = (
                f"{site_name}|{step_name}|{detector}|{field_path}"
            )

            # Skip duplicates (same field + same context already displayed)
            if self.plots_tab.plot_display_area.get_plot(composite_key):
                skipped_count += 1
                self.status_bar.set_progress_bar_value(field_index + 1)
                QApplication.processEvents()
                if self._render_cancelled:
                    cancelled = True
                    break
                continue

            # Build the y-axis label: prefer the unit found in the actual
            # metadata values (e.g. "pA") over the config unit (e.g. "A").
            # An optional ConvertToUnit converts the values from that
            # source unit and relabels the axis; if it cannot be resolved
            # the original unit and values are kept (warned in the
            # resolver). Text fields have no unit — categories are
            # unitless strings, and suffix sniffing on them would misread
            # values like "5 things" as a number with a unit.
            if field_plot_as_text:
                requested_unit = parse_convert_to_unit(
                    field.get("ConvertToUnit")
                )
                if requested_unit is not None:
                    logger.warning(
                        "Ignoring ConvertToUnit on PlotAsText field %r",
                        field_label
                    )
                y_label = field_label
                conversion = None
            else:
                detected_unit = detect_unit_suffix(detector_images, field_path)
                unit, conversion = resolve_plot_unit_and_conversion(
                    field_unit, detected_unit, field.get("ConvertToUnit")
                )
                y_label = f"{field_label} ({unit})" if unit else field_label

            # Build the title with dataset context
            title = f"{field_label}\n{site_name} • {step_name} • {detector}"

            # Extract (slice_index, value, image_name) tuples
            slice_indices, values, image_names = extract_plot_data(
                images=detector_images,
                field_path=field_path,
                start_slice=start_slice,
                end_slice=end_slice,
                plot_as_text=field_plot_as_text
            )

            if not slice_indices:
                logger.warning(
                    f"No data for field '{field_label}' in slice range "
                    f"{start_slice}–{end_slice}."
                )
                self.status_bar.set_progress_bar_value(field_index + 1)
                QApplication.processEvents()
                if self._render_cancelled:
                    cancelled = True
                    break
                continue

            # Create the ASVPlotWidget
            plot_widget = ASVPlotWidget(
                title=title,
                y_label=y_label,
                show_trend=self.config.show_trend_line_by_default,
                decimals=field_decimals,
                plot_as_text=field_plot_as_text,
                conversion=conversion,
                parent=self.plots_tab.plot_display_area
            )
            plot_widget.set_context(site_name, step_name, detector)
            plot_widget.set_composite_key(composite_key)
            plot_widget.set_slice_range(
                start=start_slice,
                end=end_slice,
                min_val=self._default_slice_min,
                max_val=self._default_slice_max
            )
            plot_widget.slice_selected.connect(self._on_slice_selected)
            plot_widget.slice_deselected.connect(self._on_slice_deselected)
            plot_widget.close_requested.connect(self._on_plot_close_requested)
            plot_widget.slice_range_changed.connect(
                self._on_plot_slice_range_changed
            )
            # Plot the data (this also stores data for interaction handlers)
            plot_widget.plot_data(slice_indices, values, image_names)

            # Bring the newcomer into agreement with the linked slice
            # selection (harmless highlight-clear when the slice is
            # outside this plot's index range or absent from its data).
            # Resolved per plot: processEvents() below lets a mid-render
            # click move the linked selection, and later plots must
            # follow the current one, not a pre-loop snapshot.
            if self._slice_link_enabled:
                linked_idx = self._active_selected_slice_index()
                if linked_idx is not None:
                    plot_widget.highlight_point_by_slice_index(linked_idx)

            # Add to the display area (keyed by composite key)
            self.plots_tab.plot_display_area.add_plot(
                composite_key, plot_widget
            )
            plot_count += 1

            # Update progress bar and repaint the UI
            self.status_bar.set_progress_bar_value(field_index + 1)
            self.status_bar.set_status_bar_message(
                f"Rendering plots ({field_index + 1}/{total_fields})..."
            )
            QApplication.processEvents()

            # Check for cancellation after the UI has processed events
            if self._render_cancelled:
                cancelled = True
                break

        # Hide progress bar and cancel button after rendering
        self.status_bar.set_progress_bar_visible(False)
        self.status_bar.set_cancel_button_visible(False)

        if cancelled:
            logger.info(
                f"Plot rendering cancelled after {plot_count} of "
                f"{total_fields} plot(s)."
            )
            if plot_count > 0:
                self._set_plot_buttons_enabled(True)
                self._update_global_slice_range()
                self.status_bar.set_status_bar_message_timed(
                    f"Rendering cancelled. {plot_count} plot(s) displayed.",
                    5000
                )
            else:
                self.status_bar.set_status_bar_message_timed(
                    "Rendering cancelled.", 3000
                )
        elif plot_count > 0:
            self._set_plot_buttons_enabled(True)
            self._update_global_slice_range()
            self.status_bar.set_status_bar_message_timed(
                f"Displaying {plot_count} plot(s).", 3000
            )
            logger.info(f"Displayed {plot_count} plots.")
        elif skipped_count > 0:
            self.status_bar.set_status_bar_message_timed(
                f"Skipped {skipped_count} already displayed plot(s).", 3000
            )
        else:
            self.status_bar.set_status_bar_message_timed(
                "No data for the selected plots in the current slice range.",
                5000
            )

        # Update button states based on whether any plots remain
        # (covers the case where an Update removed plots that couldn't
        # be re-added with the new slice range)
        has_plots = self.plots_tab.plot_display_area.has_plots()
        self._set_plot_buttons_enabled(has_plots)

    @Slot()
    def _on_clear_plots(self):
        """Handle the Clear button click. Remove all plots from the
        display area and reset the plot selection combobox.
        """
        if self._ui_busy:
            # The render loop would silently re-add cleared plots
            self.status_bar.set_status_bar_message_timed(
                "Busy rendering; try clearing again in a moment.", 3000
            )
            return
        self._set_active_plot(None)
        self.plots_tab.clear_plots()
        self.plot_selection_groupbox.select_plots_combobox.clear_all_checks()
        self._set_plot_buttons_enabled(False)
        # Restore spinboxes to the combo box context range so the
        # user can immediately display new plots
        self._restore_default_spinbox_range()
        self.status_bar.set_status_bar_message_timed("Plots cleared.", 3000)
        logger.info("Plots cleared by user.")

    @Slot()
    def _on_export_plots(self):
        """
        Handle the Export button click.

        The export runs a modal dialog and pumps events, so it is
        guarded against re-entry, and a quiet auto-update refresh
        completing mid-export is deferred until the export finishes.
        Exporting during a manual parse is blocked (shared progress
        bar / Cancel button).
        """
        if self._parse_in_flight and not self._auto_refresh_active:
            self.status_bar.set_status_bar_message_timed(
                "Parsing in progress; please wait.", 3000
            )
            return
        if self._ui_busy:
            return
        self._ui_busy = True
        try:
            self._export_plots_impl()
        finally:
            self._ui_busy = False
            self._apply_pending_quiet_refresh()

    def _export_plots_impl(self):
        """
        Export all displayed plots.

        Opens a directory selection dialog and exports all displayed
        plots as PNG, SVG, and CSV files in a timestamped folder.
        """
        display_area = self.plots_tab.plot_display_area
        if not display_area.has_plots():
            self.status_bar.set_status_bar_message_timed(
                "No plots to export.", 3000
            )
            return

        all_plots = display_area.get_all_plots()
        total = len(all_plots)

        # Determine the starting browse directory:
        # prefer the parent of the loaded metadata file, fall back to home
        if (
            self._metadata_file_path
            and self._metadata_file_path.parent.exists()
        ):
            browse_dir = str(self._metadata_file_path.parent)
        else:
            browse_dir = str(Path.home())

        # Show progress bar for the export
        self.status_bar.set_status_bar_message(
            f"Exporting plots (0/{total})..."
        )
        self.status_bar.set_progress_bar_range(0, total)
        self.status_bar.set_progress_bar_value(0)
        self.status_bar.set_progress_bar_visible(True)

        def on_progress(current, total_count):
            self.status_bar.set_progress_bar_value(current)
            self.status_bar.set_status_bar_message(
                f"Exporting plots ({current}/{total_count})..."
            )
            QApplication.processEvents()

        result = export_all_plots(
            plot_widgets=all_plots,
            base_directory_name=self.config.export_plot_directory_name,
            default_browse_dir=browse_dir,
            parent_widget=self,
            progress_callback=on_progress,
        )

        # Hide progress bar
        self.status_bar.set_progress_bar_visible(False)

        if result.export_dir is not None:
            if result.ok_count == total:
                message = (
                    f"Exported {result.ok_count} plot(s) to: "
                    f"{result.export_dir.name}"
                )
            elif result.ok_count > 0:
                message = (
                    f"Exported {result.ok_count} of {total} plot(s) to: "
                    f"{result.export_dir.name} — see log for failures"
                )
            else:
                message = (
                    "Export failed: no plots could be saved — see log."
                )
            self.status_bar.set_status_bar_message_timed(message, 5000)
            logger.info(
                f"Plots exported to: {result.export_dir} "
                f"({result.ok_count}/{total} succeeded)"
            )
        elif result.error:
            self.status_bar.set_status_bar_message_timed(result.error, 8000)
        else:
            # User cancelled the dialog (no error)
            self.status_bar.set_status_bar_message_timed(
                "Export cancelled.", 3000
            )

    @Slot()
    def _on_cancel_rendering(self):
        """Handle the Cancel button click during plot rendering.

        Sets a flag that the rendering loop checks after each
        processEvents() call. Already-rendered plots are kept.
        """
        self._render_cancelled = True

    @Slot()
    def _on_update_slice_range(self):
        """Handle the global slice range Update button click.

        Applies the global spinbox start/end values to all displayed
        plots by updating each plot's per-plot spinboxes (silently)
        and re-extracting data for the new range.
        """
        if self._ui_busy:
            return
        display_area = self.plots_tab.plot_display_area
        if not display_area.has_plots():
            return

        sr = self.slice_index_range_groupbox
        global_start = sr.start_slice_spinbox.value()
        global_end = sr.end_slice_spinbox.value()

        all_plots = display_area.get_all_plots()
        updated_count = 0

        for composite_key, plot_widget in all_plots.items():
            # Update per-plot spinboxes silently (no auto-replot signal)
            plot_widget.set_slice_range(
                start=global_start,
                end=global_end,
                min_val=plot_widget.slice_min,
                max_val=plot_widget.slice_max
            )
            # Re-extract and replot data
            if self._replot_single(composite_key, plot_widget,
                                   global_start, global_end):
                updated_count += 1

        # Keep the side panels, Prev/Next navigation, and open
        # full-resolution windows in sync with the new image lists
        self._reconcile_side_panels()
        self._reconcile_full_res_dialogs()

        if updated_count > 0:
            self.status_bar.set_status_bar_message_timed(
                f"Updated slice range for {updated_count} plot(s).", 3000
            )
        logger.info(
            f"Global slice range updated: {global_start}–{global_end} "
            f"({updated_count} plots)"
        )

    @Slot(str, int, int)
    def _on_plot_slice_range_changed(
        self, composite_key: str, start_slice: int, end_slice: int
    ):
        """Handle a per-plot spinbox change (auto-replot).

        Re-extracts data for the given plot with the new slice range
        and updates the plot display.

        :param composite_key: Composite key of the plot to update.
        :param start_slice: New start slice index.
        :param end_slice: New end slice index.
        """
        plot_widget = self.plots_tab.plot_display_area.get_plot(composite_key)
        if plot_widget is None:
            return

        self._replot_single(composite_key, plot_widget,
                            start_slice, end_slice)
        # Keep the side panels and Prev/Next navigation in sync with
        # the plot's new image list
        if composite_key == self._last_plot_key:
            self._reconcile_side_panels()
        # Any plot's full-res window must follow its plot's new list
        self._reconcile_full_res_dialogs()

    def _set_active_plot(self, composite_key: str | None):
        """Set which plot is the active / driving plot and update its border.

        Sole writer of ``self._last_plot_key``. Deactivates the previously
        active plot's border, records the new key, then activates the new
        plot's border. The active plot is the one whose image list drives
        the full-resolution Prev / Next navigation and whose images
        populate the metadata, execution-history, and image panels.

        Idempotent and defensive: an unchanged key is a no-op, and lookups
        that miss (a plot no longer displayed) are skipped.

        :param composite_key: Composite key of the plot to make active, or
            None to clear the active plot (on close, clear, or reload).
        """
        if composite_key == self._last_plot_key:
            return

        display_area = self.plots_tab.plot_display_area
        # Deactivate the previously active plot if it is still displayed.
        if self._last_plot_key is not None:
            previous = display_area.get_plot(self._last_plot_key)
            if previous is not None:
                previous.set_active(False)

        self._last_plot_key = composite_key

        # Activate the new active plot if one was provided and is displayed.
        if composite_key is not None:
            current = display_area.get_plot(composite_key)
            if current is not None:
                current.set_active(True)

    @Slot(bool)
    def _on_slice_link_toggled(self, checked: bool):
        """Handle the "Link Slice Selection" checkbox toggle.

        Records whether slice selection is linked across plots. When
        enabled, a slice selected in one plot is propagated to all other
        displayed plots; the propagation itself is performed where the
        active slice selection changes.

        :param checked: True if link slice selection is enabled.
        """
        self._slice_link_enabled = checked
        logger.debug(
            "Slice selection link %s", "enabled" if checked else "disabled"
        )
        # Snap all plots to the active plot's current slice on enable, so
        # turning the link on immediately brings the plots into agreement.
        if checked:
            self._broadcast_slice_selection(
                self._active_selected_slice_index(),
                exclude_key=self._last_plot_key,
            )

    def _active_selected_slice_index(self) -> int | None:
        """Slice index currently selected on the active plot, or None.

        None when no plot is active, the active plot no longer exists,
        or it has no selected point.  This is the selection that
        "Link Slice Selection" mirrors across plots.
        """
        if self._last_plot_key is None:
            return None
        active = self.plots_tab.plot_display_area.get_plot(
            self._last_plot_key
        )
        if active is None:
            return None
        return active.selected_slice_index

    def _broadcast_slice_selection(self, slice_idx, exclude_key=None):
        """Propagate a slice selection to all other displayed plots.

        Used when "Link Slice Selection" is enabled. Every plot except
        ``exclude_key`` highlights its own point for ``slice_idx``, or
        clears its highlight if it has no point for that slice. The
        originating plot is excluded because it already shows the selection.

        :param slice_idx: Slice index to highlight across plots (no-op if
            None).
        :param exclude_key: Composite key of the originating plot to skip.
        """
        if slice_idx is None:
            return
        plots = self.plots_tab.plot_display_area.get_all_plots()
        for key, plot in plots.items():
            if key == exclude_key:
                continue
            plot.highlight_point_by_slice_index(slice_idx)

    def _broadcast_slice_deselection(self, exclude_key=None):
        """Clear the slice highlight on all other displayed plots.

        Counterpart to :meth:`_broadcast_slice_selection` for the
        linked-deselection case: every plot except ``exclude_key``
        clears its highlight programmatically. The clears emit no
        signals, so a broadcast cannot echo back into
        :meth:`_on_slice_deselected`.

        :param exclude_key: Composite key of the originating plot to
            skip (its highlight was already cleared widget-side).
        """
        plots = self.plots_tab.plot_display_area.get_all_plots()
        for key, plot in plots.items():
            if key == exclude_key:
                continue
            plot.clear_selection()

    @Slot(str, str, str, str)
    def _on_slice_selected(
        self, image_name: str, site_name: str, step_name: str, detector: str
    ):
        """
        Handle a data point click from any ASVPlotWidget.

        Looks up the full image metadata dictionary and populates the
        ImageMetadataGroupBox, ExecutionHistoryGroupBox, and
        ImageViewerGroupBox in the plots tab.  Last-selected-wins:
        each click replaces the previous metadata and history display.

        When triggered by a direct plot click (not by Prev / Next
        navigation), the image viewer's navigation context is updated
        so that Prev / Next steps through the same image list as the
        plot that was clicked.

        :param image_name: The clicked image's file name.
        :param site_name: Site name from the plot's stored context.
        :param step_name: Step name from the plot's stored context.
        :param detector: Detector name from the plot's stored context.
        """
        if not self._metadata or not image_name:
            return

        sdg = self.plots_tab.slice_data_groupbox

        # --- Update navigation context (only on direct plot clicks) ---
        if not self._navigating:
            sender = self.sender()
            if isinstance(sender, ASVPlotWidget):
                self._set_active_plot(sender._composite_key)
                nav_names = list(sender._image_names)
                nav_paths = self._resolve_image_paths(
                    nav_names, site_name, step_name
                )
                sdg.image_viewer_groupbox.set_navigation_context(
                    image_names=nav_names,
                    image_paths=nav_paths,
                    site_name=site_name,
                    step_name=step_name,
                    detector=detector,
                    composite_key=sender._composite_key,
                    plot_title=sender._title.split("\n", 1)[0],
                    values=list(sender._values),
                )
                # Propagate the selection to all other plots when linked.
                if self._slice_link_enabled:
                    self._broadcast_slice_selection(
                        sender.selected_slice_index,
                        exclude_key=sender._composite_key,
                    )

        # Walk the metadata tree to find the matching image
        for site in self._metadata.get("Sites", []):
            if site.get("SiteName") != site_name:
                continue
            for step in site.get("Steps", []):
                if step.get("StepName") != step_name:
                    continue
                for image in step.get("Images", []):
                    if image.get("ImageName") != image_name:
                        continue

                    # Resolve absolute image path from relative path + project
                    # root (shared by the file-name link and the image viewer).
                    relative_path = image.get("RelativePath", "")
                    project_root = self._metadata.get("ProjectRoot", "")
                    if relative_path and project_root:
                        image_path = Path(project_root) / relative_path
                    else:
                        image_path = None

                    # Update the shared slice info labels (file name becomes a
                    # "reveal in folder" link when the path resolved)
                    sdg.set_slice_info(
                        image_name, site_name, step_name, detector,
                        image_path=image_path,
                    )

                    # Populate image metadata groupbox
                    metadata = image.get("Metadata", {})
                    sdg.image_metadata_groupbox.populate(
                        image_name=image_name,
                        site_name=site_name,
                        step_name=step_name,
                        detector=detector,
                        metadata=metadata
                    )

                    # Populate execution history groupbox
                    exec_history = image.get("ExecutionHistory", {})
                    sdg.execution_history_groupbox.populate(
                        image_name=image_name,
                        site_name=site_name,
                        step_name=step_name,
                        detector=detector,
                        execution_history=exec_history
                    )

                    # Populate image viewer groupbox unconditionally:
                    # the viewer shows its own "Image file not found"
                    # placeholder for missing paths, and skipping it
                    # would leave the previous slice's image on screen.
                    sdg.image_viewer_groupbox.populate(
                        image_name=image_name,
                        site_name=site_name,
                        step_name=step_name,
                        detector=detector,
                        image_path=image_path,
                    )

                    logger.debug(
                        f"Metadata and execution history displayed "
                        f"for: {image_name}"
                    )
                    return

        logger.warning(f"Image not found in metadata: {image_name}")

    @Slot()
    def _on_slice_deselected(self):
        """Handle a user deselection (empty-space click) on a plot.

        The Slice Data panel mirrors the active plot's selected point,
        so a deselection on the active plot clears the shared panels,
        the Prev / Next navigation context, and the active-plot border
        — returning to the same neutral state as startup and plot
        close. Open full-resolution dialogs are comparison windows
        tied to their plots, not selection mirrors, and are left
        untouched (``close_dialogs=False``).

        With "Link Slice Selection" enabled the selection is global:
        a deselection on any plot clears every plot's highlight and
        resets the panels regardless of which plot originated it.
        Without linking, deselecting an inactive plot clears only that
        plot's own highlight (already done widget-side); the panels
        keep mirroring the active plot's intact selection.
        """
        sender = self.sender()
        if not isinstance(sender, ASVPlotWidget):
            return

        if self._slice_link_enabled:
            self._broadcast_slice_deselection(
                exclude_key=sender._composite_key
            )

        if (self._slice_link_enabled
                or sender._composite_key == self._last_plot_key):
            self.plots_tab.slice_data_groupbox.clear_all(
                close_dialogs=False
            )
            self._set_active_plot(None)

    @Slot(str, str, str, str)
    def _on_image_navigation(
        self, image_name: str, site_name: str, step_name: str, detector: str
    ):
        """
        Handle Prev / Next navigation from the ImageViewerGroupBox.

        Re-uses :meth:`_on_slice_selected` to update all panels
        (metadata, execution history, image viewer thumbnail), then
        syncs the plot highlight on the last-clicked plot widget.

        :param image_name: The navigated-to image file name.
        :param site_name: Site name from the navigation context.
        :param step_name: Step name from the navigation context.
        :param detector: Detector name from the navigation context.
        """
        # Guard flag prevents _on_slice_selected from resetting the
        # navigation context that the image viewer is stepping through.
        self._navigating = True
        self._on_slice_selected(image_name, site_name, step_name, detector)
        self._navigating = False

        # Sync the plot highlight
        if self._last_plot_key:
            plot_widget = self.plots_tab.plot_display_area.get_plot(
                self._last_plot_key
            )
            if plot_widget and image_name in plot_widget._image_names:
                idx = plot_widget._image_names.index(image_name)
                plot_widget.highlight_point_by_index(idx)
                # Keep the other plots in lockstep during navigation.
                if self._slice_link_enabled:
                    self._broadcast_slice_selection(
                        plot_widget.selected_slice_index,
                        exclude_key=self._last_plot_key,
                    )

    @Slot(str, str, str, str, str)
    def _on_dialog_navigation(
        self, composite_key: str, image_name: str,
        site_name: str, step_name: str, detector: str
    ):
        """Handle Prev / Next inside a full-resolution dialog.

        Highlights the navigated point on the plot the dialog is tied
        to (and broadcasts it when slice linking is enabled). Only when
        that plot is the active plot are the main-window side panels
        and thumbnail updated too — dialogs tied to other plots
        navigate independently without hijacking the shared panels.

        Promote on vacancy: if no plot is active (the selection was
        cleared by an empty-space click), the navigating dialog's plot
        is promoted to active and the navigation context is rebuilt
        for it, so the shared panels repopulate instead of desyncing
        from the highlight this navigation restores. The no-hijack
        rule above still holds whenever another plot owns the panels.

        :param composite_key: Key of the plot the dialog is tied to.
        :param image_name: The navigated-to image file name.
        :param site_name: Site name from the dialog's context.
        :param step_name: Step name from the dialog's context.
        :param detector: Detector name from the dialog's context.
        """
        plot_widget = self.plots_tab.plot_display_area.get_plot(
            composite_key
        )
        if (plot_widget is not None
                and image_name in plot_widget._image_names):
            plot_widget.highlight_point_by_index(
                plot_widget._image_names.index(image_name)
            )
            if self._slice_link_enabled:
                self._broadcast_slice_selection(
                    plot_widget.selected_slice_index,
                    exclude_key=composite_key,
                )
        # Promote on vacancy: after a user deselection no plot owns
        # the shared panels, so the navigating dialog's plot claims
        # them; the Prev / Next context (cleared with the panels) is
        # rebuilt from the plot, mirroring _reconcile_side_panels.
        if plot_widget is not None and self._last_plot_key is None:
            self._set_active_plot(composite_key)
            nav_names = list(plot_widget._image_names)
            nav_paths = self._resolve_image_paths(
                nav_names, site_name, step_name
            )
            ivg = self.plots_tab.slice_data_groupbox.image_viewer_groupbox
            ivg.set_navigation_context(
                image_names=nav_names,
                image_paths=nav_paths,
                site_name=site_name,
                step_name=step_name,
                detector=detector,
                composite_key=composite_key,
                plot_title=plot_widget._title.split("\n", 1)[0],
                values=list(plot_widget._values),
            )
        if composite_key == self._last_plot_key:
            # Guard flag prevents _on_slice_selected from resetting the
            # navigation context the dialog is stepping through.
            self._navigating = True
            self._on_slice_selected(
                image_name, site_name, step_name, detector
            )
            self._navigating = False

    # =========================================================================
    # Plot Close Handler
    # =========================================================================

    @Slot(str)
    def _on_plot_close_requested(self, composite_key: str):
        """Handle the close button click on a plot widget.

        Removes the plot from the display area and updates the global
        slice range to reflect the remaining plots.

        :param composite_key: The composite key of the plot to remove.
        """
        was_active = self._last_plot_key == composite_key
        if was_active:
            self._set_active_plot(None)

        self.plots_tab.plot_display_area.remove_plot(composite_key)
        logger.info(f"Plot closed: {composite_key}")

        # The window belongs to the plot: plot gone, window closes.
        # Other plots' comparison windows are untouched.
        sdg = self.plots_tab.slice_data_groupbox
        sdg.image_viewer_groupbox.close_dialog_for(composite_key)

        # Update button states and global range
        has_plots = self.plots_tab.plot_display_area.has_plots()
        self._set_plot_buttons_enabled(has_plots)
        if has_plots:
            self._update_global_slice_range()
            if was_active:
                # The driving plot was closed; reset the side panels so
                # the metadata/history/thumbnail stop tracking a plot
                # that is no longer displayed. Surviving plots keep
                # their full-resolution windows (close_dialogs=False).
                sdg.clear_all(close_dialogs=False)
        else:
            # Restore spinboxes to the combo box context range so the
            # user can immediately display new plots without re-selecting
            self._restore_default_spinbox_range()
            self.plots_tab.slice_data_groupbox.clear_all()
            self.status_bar.set_status_bar_message_timed(
                "All plots removed.", 3000
            )

    # =========================================================================
    # Replot Helper
    # =========================================================================

    def _replot_single(
        self,
        composite_key: str,
        plot_widget: ASVPlotWidget,
        start_slice: int,
        end_slice: int
    ) -> bool:
        """
        Re-extract data and update a single plot for a new slice range.

        Parses the composite key to recover the site/step/detector/field
        context, fetches the corresponding images from metadata, and
        calls plot_data on the widget.

        :param composite_key: The plot's composite key.
        :param plot_widget: The ASVPlotWidget to update.
        :param start_slice: New start slice index.
        :param end_slice: New end slice index.
        :return: True if the plot was successfully updated.
        """
        if not self._metadata:
            return False

        # Parse composite key: site_name|step_name|detector|field_path
        parts = composite_key.split("|", 3)
        if len(parts) != 4:
            logger.warning(f"Invalid composite key: {composite_key}")
            return False

        site_name, step_name, detector, field_path = parts

        # Walk metadata to find the images
        images = None
        for site in self._metadata.get("Sites", []):
            if site.get("SiteName") != site_name:
                continue
            for step in site.get("Steps", []):
                if step.get("StepName") != step_name:
                    continue
                images = step.get("Images", [])
                break
            if images is not None:
                break

        if images is None:
            logger.warning(
                f"Could not find images for: {site_name}/{step_name}"
            )
            return False

        detector_images = filter_images_by_detector(images, detector)
        slice_indices, values, image_names = extract_plot_data(
            images=detector_images,
            field_path=field_path,
            start_slice=start_slice,
            end_slice=end_slice,
            plot_as_text=plot_widget.plot_as_text
        )

        if not slice_indices:
            logger.warning(
                f"No data for '{field_path}' in range "
                f"{start_slice}–{end_slice}."
            )
            plot_widget.clear_plot()
            return False

        plot_widget.update_data(slice_indices, values, image_names)
        return True

    # =========================================================================
    # Global Slice Range Helpers
    # =========================================================================

    def _update_global_slice_range(self):
        """Update the global slice index range spinboxes to reflect the
        min/max across all currently displayed plots.

        The global range is the union of all per-plot spinbox ranges,
        allowing the user to set a common range that applies to every
        plot regardless of which dataset it came from.
        """
        display_area = self.plots_tab.plot_display_area
        all_plots = display_area.get_all_plots()

        if not all_plots:
            return

        # Blanked (stale) plots are excluded so their leftover ranges
        # cannot widen the union past any real data.
        plots_with_data = [
            pw for pw in all_plots.values() if pw.has_data
        ]
        if not plots_with_data:
            self._reset_global_spinboxes()
            return

        global_min = min(pw.slice_min for pw in plots_with_data)
        global_max = max(pw.slice_max for pw in plots_with_data)

        sr = self.slice_index_range_groupbox
        sr.start_slice_spinbox.blockSignals(True)
        sr.end_slice_spinbox.blockSignals(True)
        sr.start_slice_spinbox.update_range(global_min, global_max)
        sr.end_slice_spinbox.update_range(global_min, global_max)
        sr.start_slice_spinbox.setValue(global_min)
        sr.end_slice_spinbox.setValue(global_max)
        sr.start_slice_spinbox.blockSignals(False)
        sr.end_slice_spinbox.blockSignals(False)
        # Reset button style since these are programmatic changes
        sr.update_button.setStyleSheet(AppStyles.Button.default())

    def _reset_global_spinboxes(self):
        """Reset the global spinboxes to zero range.

        Signals are blocked to prevent the highlight from firing on the
        Update button when the values are being programmatically reset
        (e.g. during Clear or when all plots are removed).
        """
        sr = self.slice_index_range_groupbox
        sr.start_slice_spinbox.blockSignals(True)
        sr.end_slice_spinbox.blockSignals(True)
        sr.start_slice_spinbox.update_range(0, 0)
        sr.end_slice_spinbox.update_range(0, 0)
        sr.start_slice_spinbox.setValue(0)
        sr.end_slice_spinbox.setValue(0)
        sr.start_slice_spinbox.blockSignals(False)
        sr.end_slice_spinbox.blockSignals(False)
        sr.update_button.setStyleSheet(AppStyles.Button.default())

    def _restore_default_spinbox_range(self):
        """Restore the global spinboxes to the combo box context default range.

        Uses the stored _default_slice_min / _default_slice_max values
        that were set when the detector was selected. Signals are blocked
        to prevent the Update button highlight from firing.
        """
        sr = self.slice_index_range_groupbox
        sr.start_slice_spinbox.blockSignals(True)
        sr.end_slice_spinbox.blockSignals(True)
        sr.start_slice_spinbox.update_range(
            self._default_slice_min, self._default_slice_max
        )
        sr.end_slice_spinbox.update_range(
            self._default_slice_min, self._default_slice_max
        )
        sr.start_slice_spinbox.setValue(self._default_slice_min)
        sr.end_slice_spinbox.setValue(self._default_slice_max)
        sr.start_slice_spinbox.blockSignals(False)
        sr.end_slice_spinbox.blockSignals(False)
        sr.update_button.setStyleSheet(AppStyles.Button.default())

    # =========================================================================
    # Save / Delete Handlers
    # =========================================================================

    @Slot(str)
    def _on_save_metadata(self, dest_path: str):
        """Handle save request from the load data groupbox.

        Copies the source metadata JSON to the user-chosen destination.
        """
        if self._metadata_file_path is None:
            return
        if self._parse_in_flight or self._auto_refresh_active:
            self.status_bar.set_status_bar_message_timed(
                "Metadata is being rebuilt; try saving again in a moment.",
                5000
            )
            return

        dest = Path(dest_path)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self._metadata_file_path, dest)
            logger.info(f"Metadata saved to: {dest}")
            self.status_bar.set_status_bar_message_timed(
                f"Metadata saved: {dest.name}", 5000
            )
        except OSError:
            logger.error(f"Failed to save metadata to: {dest}", exc_info=True)
            self.status_bar.set_status_bar_message_timed(
                f"Failed to save metadata file.", 5000
            )

    @Slot()
    def _on_delete_temp_file(self):
        """Handle delete request from the load data groupbox.

        Deletes the temporary metadata JSON file and its parent
        directory if the directory is empty after deletion, then
        resets the entire UI to its initial startup state.
        """
        ldg = self.load_data_groupbox
        if self._ui_busy:
            # A render/export loop is pumping events; resetting the UI
            # under it leaves half-undone state when the loop resumes.
            self.status_bar.set_status_bar_message_timed(
                "Busy rendering; try deleting again in a moment.", 3000
            )
            return
        if self._parse_in_flight or self._auto_refresh_active:
            # Deleting mid-rebuild is futile (the worker rewrites the
            # file) and would leave the UI half-reset when the rebuild
            # completes.
            self.status_bar.set_status_bar_message_timed(
                "Cannot delete while a metadata rebuild is running.", 5000
            )
            return
        temp_path = ldg._temp_file_path

        if temp_path is None or not temp_path.exists():
            ldg.refresh_delete_button_state()
            return

        # The Delete button holds focus (the user just clicked it);
        # disabling it in the reset below would migrate focus to the
        # bottom Auto-Update group and scroll to the bottom. Park focus
        # at the top first so the scroll stays put.
        self._park_right_column_focus()

        # --- Delete the file ---
        try:
            parent_dir = temp_path.parent
            temp_path.unlink()
            logger.info(f"Deleted temp metadata file: {temp_path}")

            # Remove the parent directory if it is now empty
            if parent_dir.exists() and not any(parent_dir.iterdir()):
                parent_dir.rmdir()
                logger.info(f"Removed empty temp directory: {parent_dir}")

            self.status_bar.set_status_bar_message_timed(
                f"Deleted: {temp_path.name}", 5000
            )
        except OSError:
            logger.error(
                f"Failed to delete temp file: {temp_path}", exc_info=True
            )
            self.status_bar.set_status_bar_message_timed(
                "Failed to delete temp metadata file.", 5000
            )
            ldg.refresh_delete_button_state()
            return

        # --- Reset application state ---
        self._metadata = None
        self._metadata_file_path = None
        # Invalidate any in-flight quiet rebuild result (defensive; the
        # guard above blocks deletes while one is running).
        self._parse_generation += 1
        self._set_active_plot(None)
        self._available_plot_fields = []
        self._default_slice_min = 0
        self._default_slice_max = 0
        # Stop watching: the metadata backing the watch is gone
        self._stop_auto_update()

        # --- Reset UI to startup ---
        # Clear combo boxes and plots
        self._clear_all_combo_boxes()
        self.plots_tab.clear_plots()
        self.plots_tab.show_startup()
        self.project_parameters_tab.clear()
        self.project_name_button.setText("")
        self.project_name_button.setVisible(False)

        # Reset global spinboxes
        self._reset_global_spinboxes()

        # Reset all button states
        self._set_initial_button_states()
        ldg.set_save_enabled(False)
        ldg.set_temp_file_path(None)

        # The full UI reset re-lays-out the right column; keep it scrolled
        # to the top (same jump the manual load path guards against).
        self._reset_right_column_scroll()

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _resolve_image_paths(
        self,
        image_names: list[str],
        site_name: str,
        step_name: str,
    ) -> list[Path]:
        """
        Resolve absolute file paths for a list of image names.

        Walks the metadata tree to find matching images under the given
        site and step, combining each image's ``RelativePath`` with the
        project ``ProjectRoot``.

        :param image_names: Ordered list of image file names.
        :param site_name: Site name to search under.
        :param step_name: Step name to search under.
        :return: Parallel list of absolute ``Path`` objects.  Entries
            that could not be resolved are ``Path("")``.
        """
        project_root = self._metadata.get("ProjectRoot", "")
        if not project_root or not self._metadata:
            return [Path("")] * len(image_names)

        # Build a lookup from image name → relative path
        relative_map: dict[str, str] = {}
        for site in self._metadata.get("Sites", []):
            if site.get("SiteName") != site_name:
                continue
            for step in site.get("Steps", []):
                if step.get("StepName") != step_name:
                    continue
                for image in step.get("Images", []):
                    name = image.get("ImageName", "")
                    rel = image.get("RelativePath", "")
                    if name and rel:
                        relative_map[name] = rel
                break
            break

        return [
            Path(project_root) / relative_map[name]
            if name in relative_map else Path("")
            for name in image_names
        ]

    def _lookup_image_data(
        self,
        image_name: str,
        site_name: str,
        step_name: str,
        detector: str,
    ) -> tuple[dict, dict]:
        """
        Look up metadata and execution history for a single image.

        Used as a callback by the full-resolution dialog to populate
        its metadata panel when navigating between images.

        :param image_name: The image file name.
        :param site_name: Site name to search under.
        :param step_name: Step name to search under.
        :param detector: Detector name (unused for lookup but part of
            the callback signature for consistency).
        :return: Tuple of (metadata_dict, exec_history_dict).  Returns
            empty dicts if the image is not found.
        """
        if not self._metadata:
            return {}, {}

        for site in self._metadata.get("Sites", []):
            if site.get("SiteName") != site_name:
                continue
            for step in site.get("Steps", []):
                if step.get("StepName") != step_name:
                    continue
                for image in step.get("Images", []):
                    if image.get("ImageName") != image_name:
                        continue
                    return (
                        image.get("Metadata", {}),
                        image.get("ExecutionHistory", {}),
                    )
        return {}, {}

    def _set_initial_button_states(self):
        """Disable all plot-related buttons at startup."""
        ps = self.plot_selection_groupbox
        ps.display_plots_button.setEnabled(False)
        ps.clear_plots_button.setEnabled(False)
        ps.export_plots_button.setEnabled(False)
        self.slice_index_range_groupbox.update_button.setEnabled(False)

    def _set_plot_buttons_enabled(self, enabled: bool):
        """Enable or disable buttons that require plots to be displayed.

        :param enabled: True to enable Clear, Export, and Update buttons.
        """
        ps = self.plot_selection_groupbox
        ps.clear_plots_button.setEnabled(enabled)
        ps.export_plots_button.setEnabled(enabled)
        self.slice_index_range_groupbox.update_button.setEnabled(enabled)

    @Slot(list)
    def _on_plot_selection_changed(self, checked_items: list):
        """Enable Display button when at least one plot is checked."""
        self.plot_selection_groupbox.display_plots_button.setEnabled(
            len(checked_items) > 0
        )

    def _reset_parsing_ui(self):
        """Restore UI to idle state after parsing ends."""
        self._parse_in_flight = False
        # Catbug back to grayscale (unless auto-update is watching)
        self._update_catbug_state()
        # Hide progress bar and cancel button
        self.status_bar.set_progress_bar_visible(False)
        self.status_bar.set_cancel_button_visible(False)
        # Re-enable drops
        self.dir_file_drop_groupbox.dir_file_drop_widget.set_accepts_drops(True)
        # Re-enable load buttons
        self.load_data_groupbox.load_project_dir_button.setEnabled(True)
        self.load_data_groupbox.load_json_file_button.setEnabled(True)
        # Re-enable tabs and emit parsing inactive signal
        self.tab_widget.setTabEnabled(1, True)
        self.parsing_active.emit(False)

    # =========================================================================
    # Metadata Loading
    # =========================================================================

    def _load_metadata(self, file_path: str, metadata: dict | None = None):
        """Load consolidated metadata JSON and populate the site combo box.

        :param file_path: Path to the consolidated JSON file.
        :param metadata: Optional pre-parsed metadata dict (avoids a
                         second parse when the caller already loaded it).
        """
        if metadata is None:
            metadata = load_consolidated_metadata(Path(file_path))
        if metadata is None:
            logger.error(f"Failed to load metadata from: {file_path}")
            return

        self._metadata = metadata
        self._metadata_file_path = Path(file_path)
        # Park focus at the top before the combo/control state changes
        # below, so focus can't migrate into the bottom Auto-Update
        # group and scroll the column to the bottom.
        self._park_right_column_focus()
        # Invalidate any quiet rebuild that was started for the
        # previously loaded metadata (its result is now stale).
        self._parse_generation += 1
        self._set_active_plot(None)
        self._clear_all_combo_boxes()
        self._populate_sites()

        # Display the project name in the tab bar
        project_name = self._metadata.get("ProjectName", "")
        if project_name:
            self.project_name_button.setText(project_name)
            self.project_name_button.setVisible(True)
        else:
            self.project_name_button.setVisible(False)
        # Transition to plot area (hides startup label) and clear any
        # existing plots from a previous data load
        self.plots_tab.show_plot_area()
        self.plots_tab.clear_plots()
        self._set_plot_buttons_enabled(False)
        # Note: global spinboxes are already set by the auto-cascade in
        # _populate_sites → _on_detector_selected → _update_default_slice_range
        # Populate the Project Parameters tab
        project_params = self._metadata.get("ProjectParameters", {})
        self.project_parameters_tab.populate(project_params)
        # Enable save button now that metadata is loaded
        self.load_data_groupbox.set_save_enabled(True)
        # Enable auto-update only when the project folder exists on disk
        project_root = self._metadata.get("ProjectRoot", "")
        folder_available = bool(project_root) and Path(project_root).is_dir()
        if folder_available:
            self.auto_update_groupbox.set_controls_enabled(True)
            if self._auto_update_enabled:
                # A different project was loaded while watching:
                # re-baseline against the new folder on the next tick
                self._last_snapshot = None
        elif self._auto_update_enabled:
            self._stop_auto_update()
        else:
            self.auto_update_groupbox.set_controls_enabled(False)

        # Populating the right-column controls can leave the scroll area
        # parked at the bottom (a child widget's focus scrolls it into
        # view). Keep it at the top on a fresh load. This is the manual
        # load path only — the quiet auto-refresh preserves the view.
        self._reset_right_column_scroll()

    def _park_right_column_focus(self):
        """Move focus to the scroll area — a neutral, top-of-column
        target — before a load or reset changes control enabled-states.

        Enabling/disabling controls (notably the bottom Auto-Update
        group) migrates focus down the tab order; the scroll area then
        ensure-visibles the newly focused widget and jumps to the
        bottom. Parking focus at the top first prevents that migration,
        so the scroll never jumps (no visible flash)."""
        self.right_column_scroll_area.setFocus(
            Qt.FocusReason.OtherFocusReason
        )

    def _reset_right_column_scroll(self):
        """Return the right-column scroll area to the top. Applied now
        and again on the next event-loop tick, since a focus-driven
        ensureWidgetVisible can fire after the layout settles."""
        self.right_column_scroll_area.verticalScrollBar().setValue(0)
        QTimer.singleShot(0, self._scroll_right_column_to_top)

    def _scroll_right_column_to_top(self):
        self.right_column_scroll_area.verticalScrollBar().setValue(0)

    def _populate_sites(self):
        """Populate the site combo box from loaded metadata and auto-select
        the first site, step, and detector to cascade the combo boxes.
        """
        sites = self._metadata.get("Sites", [])
        site_names = [site["SiteName"] for site in sites]
        ps = self.plot_selection_groupbox
        ps.site_combobox.addItems(site_names)
        logger.info(f"Loaded metadata: {len(site_names)} sites")

        # Auto-select first site → step → detector
        if site_names:
            ps.site_combobox.setCurrentIndex(0)
            self._on_site_selected(0)
            if ps.step_name_combobox.count() > 0:
                ps.step_name_combobox.setCurrentIndex(0)
                self._on_step_selected(0)
                if ps.detector_combobox.count() > 0:
                    ps.detector_combobox.setCurrentIndex(0)
                    self._on_detector_selected(0)

    def _clear_all_combo_boxes(self):
        """Clear all combo boxes and reset available plot fields."""
        ps = self.plot_selection_groupbox
        ps.site_combobox.clear()
        ps.step_name_combobox.clear()
        ps.detector_combobox.clear()
        # clear_items removes the rows (not just the checks) so a
        # deleted project's fields cannot linger in the dropdown
        ps.select_plots_combobox.clear_items()
        self._available_plot_fields = []

    def _update_default_slice_range(self, images: list[dict]):
        """
        Update the default slice range and global spinboxes based on
        available images from the current combo box selection.

        Called when the detector combo box selection changes to set the
        initial range for new plot creation.

        :param images: List of image dicts (pre-filtered by detector).
        """
        sr = self.slice_index_range_groupbox
        slice_indices = get_slice_indices(images)

        if not slice_indices:
            self._default_slice_min = 0
            self._default_slice_max = 0
            sr.start_slice_spinbox.blockSignals(True)
            sr.end_slice_spinbox.blockSignals(True)
            sr.start_slice_spinbox.update_range(0, 0)
            sr.end_slice_spinbox.update_range(0, 0)
            sr.start_slice_spinbox.setValue(0)
            sr.end_slice_spinbox.setValue(0)
            sr.start_slice_spinbox.blockSignals(False)
            sr.end_slice_spinbox.blockSignals(False)
            return

        min_slice = min(slice_indices)
        max_slice = max(slice_indices)
        self._default_slice_min = min_slice
        self._default_slice_max = max_slice

        sr.start_slice_spinbox.blockSignals(True)
        sr.end_slice_spinbox.blockSignals(True)
        sr.start_slice_spinbox.update_range(min_slice, max_slice)
        sr.end_slice_spinbox.update_range(min_slice, max_slice)
        sr.start_slice_spinbox.setValue(min_slice)
        sr.end_slice_spinbox.setValue(max_slice)
        sr.start_slice_spinbox.blockSignals(False)
        sr.end_slice_spinbox.blockSignals(False)
        # Reset button style
        sr.update_button.setStyleSheet(AppStyles.Button.default())

    def cleanup(self):
        """Stop the worker threads and timers. Call from
        MainWindow.closeEvent.
        """
        self._closing = True
        # The full-resolution comparison windows are unparented
        # top-level windows (so they can stack behind the main window);
        # close them here or they would outlive the main window and
        # keep the application running.
        self.plots_tab.slice_data_groupbox.image_viewer_groupbox \
            .close_all_dialogs()
        # Stop the polling timer before tearing down the scan thread so
        # no new scan is requested mid-shutdown
        self._auto_update_timer.stop()
        # Ask any in-flight parse to stop so the wait below returns
        # promptly (the cancel event is checked between images).
        # request_cancel only sets a threading.Event, so calling it from
        # the main thread is safe.
        self._worker.request_cancel()
        self._scan_thread.quit()
        if not self._scan_thread.wait(10000):
            logger.warning("Scan thread did not stop in time.")
        self._worker_thread.quit()
        if not self._worker_thread.wait(10000):
            logger.warning("Parsing thread did not stop in time.")
        logger.info("Worker threads cleaned up.")