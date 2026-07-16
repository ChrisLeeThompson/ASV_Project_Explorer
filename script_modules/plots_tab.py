"""
Plots Tab

Module handles the "Plots" tab of the ASV Project Metadata section.
The tab contains two states:

Startup:
    A centered label with instructions for the user.

Active (after data is loaded):
    A horizontal split layout:
    - Left: SliceDataGroupBox containing the ImageViewerGroupBox,
      ExecutionHistoryGroupBox, and ImageMetadataGroupBox, populated
      when a data point is clicked.
    - Handle: CollapsibleSplitterHandle — a custom splitter handle
      that is draggable for resize and clickable to toggle the
      slice data panel visibility.
    - Right: PlotDisplayArea (scrollable container for plot widgets).

Controls (combo boxes, buttons, spinboxes) live in the parent
ASVProjectMetadataTab right column — this tab only manages the
display surface.

Lifecycle
---------
- Startup:  Startup container visible, plot content hidden.
- Data loaded:  Startup container hidden, plot content shown.
  The slice data group box shows placeholder text until a data
  point is clicked.
- Clear clicked:  Plots cleared, slice data reset to placeholder.
  Plot content remains visible.
- New data loaded:  Plots cleared, slice data reset to placeholder.
  Plot content remains visible.
"""
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel
)
from PySide6.QtCore import Qt
from script_modules.app_styles import AppStyles
from script_modules.groupboxes.plot_display_area_groupbox import PlotDisplayArea
from script_modules.groupboxes.slice_data_groupbox import SliceDataGroupBox
from script_modules.widgets.collapsible_panel_handle import CollapsibleSplitter



logger = logging.getLogger(__name__)


class PlotsTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        # Create widgets
        self._create_widgets()
        # Setup layout
        self._setup_layout()

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _create_widgets(self):
        """Create the startup container and the plot content area."""
        # ---- Startup container ----
        self._startup_container = QWidget()
        startup_layout = QVBoxLayout(self._startup_container)
        startup_layout.setContentsMargins(0, 0, 0, 0)
        startup_layout.setSpacing(0)

        self.startup_plot_area_label = QLabel(
            AppStyles.AppText.STARTUP_PLOT_AREA_LABEL
        )
        self.startup_plot_area_label.setStyleSheet(
            AppStyles.Label.large_label()
        )
        self.startup_plot_area_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft
        )

        startup_layout.addStretch(1)
        startup_layout.addWidget(
            self.startup_plot_area_label,
            alignment=Qt.AlignmentFlag.AlignHCenter
        )
        startup_layout.addStretch(3)

        # ---- Plot content container (shown after data loads) ----
        self._plot_content_container = QWidget()
        content_layout = QVBoxLayout(self._plot_content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Left: slice data (image viewer, execution history, metadata)
        self.slice_data_groupbox = SliceDataGroupBox(parent=self)

        # Right: plot display area
        self.plot_display_area = PlotDisplayArea(parent=self)

        # Collapsible splitter: combines drag-to-resize with
        # click-to-collapse on the left panel.
        self.panel_splitter = CollapsibleSplitter(
            parent=self._plot_content_container
        )
        self.panel_splitter.addWidget(self.slice_data_groupbox)
        self.panel_splitter.addWidget(self.plot_display_area)
        self.panel_splitter.setStretchFactor(0, 1)
        self.panel_splitter.setStretchFactor(1, 2)

        content_layout.addWidget(self.panel_splitter)

        # Start hidden
        self._plot_content_container.setVisible(False)

    def _setup_layout(self):
        """Place the startup container and plot content in the main layout."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._startup_container)
        main_layout.addWidget(self._plot_content_container)
        self.setStyleSheet(AppStyles.Window.tabs())

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def show_plot_area(self):
        """
        Transition from startup to the plot content area.

        Hides the startup container and shows the horizontal split
        layout with plots on the left and the metadata panel on the
        right. Called once when data is first loaded — the plot content
        stays visible for the remainder of the session.
        """
        if not self._plot_content_container.isVisible():
            self._startup_container.setVisible(False)
            self._plot_content_container.setVisible(True)
            # Set initial left-panel width now that the splitter
            # is visible and has its actual geometry.
            left = AppStyles.Dimensions.SLICE_DATA_INITIAL_WIDTH
            total = self.panel_splitter.width()
            self.panel_splitter.setSizes([left, total - left])
            logger.debug("Switched to plot content area.")

    def show_startup(self):
        """
        Transition back to the startup label.

        Hides the plot content area and shows the startup container.
        Called when loaded data is discarded (e.g. temp file deleted)
        to return the UI to its initial state.
        """
        if not self._startup_container.isVisible():
            self._plot_content_container.setVisible(False)
            self._startup_container.setVisible(True)
            logger.debug("Switched back to startup label.")

    def clear_plots(self):
        """
        Clear all plot widgets and reset the metadata and history panels.

        The plot content area remains visible — the startup label
        does not return. Use this when the user clicks Clear or
        when new data is loaded.
        """
        self.plot_display_area.clear_plots()
        self.slice_data_groupbox.clear_all()
        logger.debug("Cleared all plots and slice data.")