"""
ASV Plot Widget

Module for creating matplotlib plot widgets for ASV metadata visualization.
Each widget wraps a FigureCanvasQTAgg and provides:
- Data plotting with regression line and statistics
- Scroll-wheel zoom (centered on cursor)
- Click-and-drag panning
- Double-click to reset view
- Matplotlib navigation toolbar (Home/Back/Forward, Pan, Zoom-to-rectangle,
  Subplots, Save). Inactive by default so the custom mouse interactions
  above stay the primary controls; when a toolbar tool is engaged the
  drag/click/hover handlers defer to it while scroll-zoom remains active.
- Hover highlight on data points (color change + enlarged marker)
- Click-on-point annotation tooltip (slice number, filename, value)
  with a persistent select highlight marker
- Datetime support for acquisition time plots
- slice_selected signal emitted on point click with image name and
  dataset context (site, step, detector) for metadata display.
- Close button to remove individual plots from the display area.
- Per-plot start/end slice range spinboxes with auto-replot on change.
  The slice_range_changed signal is emitted when the user adjusts either
  spinbox, allowing the parent tab to re-extract data and update the plot.
"""
import logging
from pathlib import Path
from datetime import datetime
import numpy as np
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QSizePolicy, QPushButton, QLabel, QCheckBox
)
from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtGui import QIcon
from script_modules.app_styles import AppStyles, ASSETS_DIR
from script_modules.metadata_query import round_plot_values
from script_modules.widgets.pan_zoom_interaction import PanZoomInteraction
from script_modules.widgets.spinbox_widgets import StartSliceSpinBox, EndSliceSpinBox


logger = logging.getLogger(__name__)


def format_point_value(value) -> str:
    """Format a plotted data value for display.

    Shared by the plot annotation tooltip and the full-resolution
    window's value label, so both always show identical text.

    :param value: A parsed metadata value (float, int, or datetime).
    :return: Display string.
    """
    if isinstance(value, datetime):
        return value.strftime("%d-%m-%Y %H:%M:%S")
    if isinstance(value, (int, float)):
        return f"{value}"
    return str(value)


class ASVPlotWidget(QWidget):
    """
    Widget for displaying a single ASV metadata plot with interactive
    zoom, pan, and point-click annotation.
    """

    # Emitted when a data point is clicked.
    # Args: image_name, site_name, step_name, detector
    slice_selected = Signal(str, str, str, str)

    # Emitted when the close button is clicked.
    # Args: composite_key
    close_requested = Signal(str)

    # Emitted when the user adjusts per-plot slice range spinboxes.
    # Args: composite_key, start_slice, end_slice
    slice_range_changed = Signal(str, int, int)

    # Emitted when the user deselects the slice point by clicking
    # empty space inside the axes or pressing outside them. User
    # gestures only: programmatic highlight clears (linked-broadcast
    # updates, clear_selection, clear_plot) never emit this, so a
    # propagated deselection cannot echo back into the parent tab.
    slice_deselected = Signal()

    def __init__(
        self, title: str, y_label: str, show_trend: bool = True,
        decimals: int | None = None, parent=None
    ):
        """
        Initialize the plot widget.

        :param title: Plot title displayed above the axes.
        :param y_label: Y-axis label (the metadata field name).
        :param show_trend: Initial state of the per-plot "Trend line"
            checkbox (shows/hides the fit line + slope/R² text).
        :param decimals: Number of decimal places to round plotted values
            to (from the field's config), or None for full precision.
        :param parent: Parent widget.
        """
        super().__init__(parent)
        self._title = title
        self._y_label = y_label
        self._show_trend_default = show_trend
        self._decimals = decimals

        # Dataset context (set by caller after construction)
        self._site_name = ""
        self._step_name = ""
        self._detector = ""
        self._composite_key = ""

        # Plot data (stored for interaction handlers)
        self._slice_numbers = []
        self._values = []
        self._image_names = []

        # Fit view for double-click reset / toolbar Home (captured per
        # plot_data; the pan/zoom handlers live in PanZoomInteraction)
        self._original_xlim = None
        self._original_ylim = None

        # Active-plot state: True when this plot is the driver (its image
        # list feeds the full-resolution navigation and the side panels).
        # Reflected visually by the active border via set_active().
        self._active = False

        # Annotation
        self._annotation = None

        # Hover / select highlight scatter artists (created per plot_data)
        self._hover_scatter = None
        self._select_scatter = None

        # Stats-overlay artists toggled by the "Trend Line" checkbox: the
        # dashed fit line (numeric plots only) and the top-right stats box
        # (slope/R² for numeric, "Avg. Cycle Time" for datetime).
        self._regression_line = None
        self._stats_text = None

        # Slice index of the currently selected/highlighted point (None if
        # nothing is selected). Exposed via selected_slice_index and used by
        # the cross-plot "Link Slice Selection" broadcast.
        self._selected_slice_index = None

        # Guard to prevent duplicate slice_range_changed emissions
        # during cross-constraint updates
        self._replot_guard = False

        # Build widget
        self._create_matplotlib_components()
        self._create_spinboxes()
        self._setup_layout()
        self._connect_events()
        self._connect_spinbox_signals()

    # -------------------------------------------------------------------------
    # Setup
    # -------------------------------------------------------------------------

    def _create_matplotlib_components(self):
        """Create the matplotlib figure, canvas, and axes."""
        self.figure = Figure(
            facecolor=AppStyles.Colors.MAIN_BG,
            constrained_layout=True
        )
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.ax = self.figure.add_subplot(111)
        self._style_axes()

        # Reduce render artifacts at plot edges
        self.figure.patch.set_antialiased(False)
        self.ax.patch.set_antialiased(False)
        self.figure.set_dpi(110)
        self.canvas.setStyleSheet(
            f"background-color: {AppStyles.Colors.MAIN_BG};"
        )

        # Navigation toolbar (Home/Back/Forward, Pan, Zoom-to-rectangle,
        # Subplots, Save). Inactive by default; while a tool is engaged
        # PanZoomInteraction's drag/click/hover handlers defer to it,
        # and scroll-zoom stays available.
        # coordinates=False drops the x/y readout: it is noise for the
        # per-slice metadata plots (the click tooltip already reports the
        # slice number and value). The full-resolution image toolbar keeps it.
        self.toolbar = NavigationToolbar2QT(
            self.canvas, self, coordinates=False
        )
        self.toolbar.setStyleSheet(AppStyles.ToolBar.navigation())
        AppStyles.apply_toolbar_icon_color(self.toolbar)

    def _style_axes(self):
        """Apply visual styling to the axes."""
        ax = self.ax
        ax.set_facecolor(AppStyles.Colors.MAIN_BG)

        # Spines
        ax.spines["left"].set_color(AppStyles.Colors.PLOT_SPINE_COLOR)
        ax.spines["bottom"].set_color(AppStyles.Colors.PLOT_SPINE_COLOR)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        # Label and title colors
        ax.xaxis.label.set_color(AppStyles.Colors.TEXT_PRIMARY)
        ax.yaxis.label.set_color(AppStyles.Colors.TEXT_PRIMARY)
        ax.title.set_color(AppStyles.Colors.TEXT_PRIMARY)

        # Tick colors
        ax.tick_params(axis="x", colors=AppStyles.Colors.PLOT_SPINE_COLOR)
        ax.tick_params(axis="y", colors=AppStyles.Colors.PLOT_SPINE_COLOR)

        # Set integer x-axis locators for slice numbers
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))

    def _create_spinboxes(self):
        """Create the per-plot start/end slice spinboxes and the
        "Trend line" checkbox that sits between them."""
        self._start_label = QLabel("Start")
        self._start_label.setStyleSheet(AppStyles.Label.default())
        self._end_label = QLabel("End")
        self._end_label.setStyleSheet(AppStyles.Label.default())
        self._start_spinbox = StartSliceSpinBox(parent=self)
        self._end_spinbox = EndSliceSpinBox(parent=self)

        # Trend-line toggle (fit line + slope/R² text). Label on the left,
        # indicator box on the right (RightToLeft layout direction).
        self._trend_checkbox = QCheckBox(AppStyles.AppText.TREND_LINE_CHECKBOX)
        self._trend_checkbox.setStyleSheet(AppStyles.CheckBox.default())
        self._trend_checkbox.setChecked(self._show_trend_default)
        self._trend_checkbox.setToolTip(AppStyles.AppToolTips.TREND_LINE_CHECKBOX)
        self._trend_checkbox.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    def _setup_layout(self):
        """Setup widget layout inside a groupbox container: the navigation
        toolbar on top, the canvas in the middle, the per-plot slice range
        spinboxes below, and a close button overlaid in the top-right
        corner."""
        self._group_box = QGroupBox()
        group_box_layout = QVBoxLayout()
        group_box_layout.setContentsMargins(4, 6, 4, 4)

        # Navigation toolbar — placed at the top of the plot card. With the
        # coordinate readout disabled the buttons sit at the left, leaving
        # the top-right corner free for the overlaid close button. Left-
        # aligned so that when resizeEvent caps the toolbar width its left
        # edge stays fixed, which keeps the width math in resizeEvent stable.
        group_box_layout.addWidget(
            self.toolbar, 0, Qt.AlignmentFlag.AlignLeft
        )

        # Canvas
        group_box_layout.addWidget(self.canvas)

        # Slice range spinbox row
        spinbox_row = QHBoxLayout()
        spinbox_row.setContentsMargins(4, 0, 4, 0)
        spinbox_row.addWidget(self._start_label)
        spinbox_row.addWidget(self._start_spinbox)
        spinbox_row.addStretch()
        spinbox_row.addWidget(self._trend_checkbox)
        spinbox_row.addStretch()
        spinbox_row.addWidget(self._end_label)
        spinbox_row.addWidget(self._end_spinbox)
        group_box_layout.addLayout(spinbox_row)

        self._group_box.setLayout(group_box_layout)
        self._group_box.setStyleSheet(AppStyles.GroupBox.plot())

        # Close button — overlaid in the top-right corner
        _close_icon = str(ASSETS_DIR / "cross_light-gray.svg")
        self._close_button = QPushButton(self._group_box)
        self._close_button.setIcon(QIcon(_close_icon))
        self._close_button.setIconSize(QSize(16, 16))
        self._close_button.setFixedSize(24, 24)
        self._close_button.setStyleSheet(AppStyles.Button.plot_close())
        self._close_button.clicked.connect(self._on_close_clicked)
        self._close_button.raise_()

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._group_box)
        self.setLayout(layout)
        # Expand to fill the display area between a minimum and a capped
        # maximum height. The container's per-plot stretch factor drives the
        # fill/share; the Expanding policy makes that intent explicit.
        self.setMinimumHeight(AppStyles.Dimensions.PLOT_MINIMUM_HEIGHT)
        self.setMaximumHeight(AppStyles.Dimensions.PLOT_MAXIMUM_HEIGHT)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def _connect_events(self):
        """Wire the shared scroll-zoom / drag-pan / double-click-reset
        interaction, with hooks for this widget's annotation and hover
        behavior.

        No ``on_reset`` hook is passed: a double-click zoom reset is a
        view change only and preserves the selected point (the
        annotation is anchored in data coordinates, so it survives the
        reset). A press outside the axes is a deselection gesture and
        routes through :meth:`_on_user_deselect` so the parent tab is
        notified.
        """
        self._interaction = PanZoomInteraction(
            self.ax, self.canvas, self.toolbar,
            get_fit_limits=lambda: (self._original_xlim, self._original_ylim),
            on_click=self._show_annotation,
            on_hover=self._update_hover,
            on_press_outside=self._on_user_deselect,
        )

    def _connect_spinbox_signals(self):
        """Connect per-plot spinbox signals for cross-constraint and
        auto-replot."""
        # Cross-constraint: start cannot exceed end, end cannot go below start
        self._start_spinbox.valueChanged.connect(
            lambda val: self._end_spinbox.setMinimum(val)
        )
        self._end_spinbox.valueChanged.connect(
            lambda val: self._start_spinbox.setMaximum(val)
        )
        # Auto-replot on user change
        self._start_spinbox.valueChanged.connect(
            self._on_slice_spinbox_changed
        )
        self._end_spinbox.valueChanged.connect(
            self._on_slice_spinbox_changed
        )
        # Trend-line show/hide toggle
        self._trend_checkbox.toggled.connect(self._on_trend_toggled)

    def resizeEvent(self, event):
        """Reposition the close button and cap the toolbar width when the
        widget is resized, so the toolbar's background band ends just left
        of the overlaid close button rather than running underneath it."""
        super().resizeEvent(event)
        if hasattr(self, "_close_button"):
            # Offset accounts for the groupbox stylesheet margin (8px) and
            # border (2px) so the button sits inside the visible border.
            self._close_button.move(
                self._group_box.width() - self._close_button.width() - 14, 12
            )
            # Re-assert z-order so the button stays above the canvas
            # after splitter-driven relayouts.
            self._close_button.raise_()

            # Cap the toolbar width so its background band ends just left of
            # the close button instead of running underneath it. Geometry-
            # driven (reads the button's actual position) so it tracks the
            # close button across splitter-driven relayouts. Both widgets are
            # children of self._group_box, so their x() values share a
            # coordinate space. Idempotent: the left-aligned toolbar's x() is
            # fixed and the button's x() depends only on the group box width,
            # so recomputing on each resize yields the same cap.
            toolbar_close_gap = 6
            max_toolbar_width = (
                self._close_button.x() - toolbar_close_gap - self.toolbar.x()
            )
            self.toolbar.setMaximumWidth(max(0, max_toolbar_width))

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def plot_data(
        self,
        slice_numbers: list,
        values: list,
        image_names: list | None = None
    ):
        """
        Plot data on the axes with regression line and statistics.

        :param slice_numbers: X-axis values (slice indices).
        :param values: Y-axis values (metadata field values).
        :param image_names: Optional list of image filenames (same length
            as slice_numbers) for annotation tooltips.
        """
        # Round to the field's configured precision (no-op when None) up front
        # so the axis line, regression, tooltips, and full-res label all use
        # the same rounded values.
        values = round_plot_values(values, self._decimals)
        self._slice_numbers = slice_numbers
        self._values = values
        self._image_names = image_names or []
        # New data invalidates any previous point selection
        self._selected_slice_index = None

        self.ax.clear()
        self._style_axes()

        if not slice_numbers or not values:
            self.canvas.draw_idle()
            return

        # --- Plot data points ---
        self.ax.plot(
            slice_numbers, values, "o-",
            color=AppStyles.Colors.PLOT_LINE_COLOR,
            linewidth=AppStyles.Dimensions.PLOT_LINE_WIDTH,
            markersize=4,
            alpha=0.9,
            label="Data",
            zorder=3
        )

        # --- Hover / select highlight markers (hidden until interaction) ---
        highlight_size = AppStyles.Dimensions.PLOT_HIGHLIGHT_MARKER_SIZE
        highlight_color = AppStyles.Colors.BUTTON_HOVER
        self._hover_scatter = self.ax.scatter(
            [], [], s=highlight_size, color=highlight_color,
            zorder=5, visible=False
        )
        self._select_scatter = self.ax.scatter(
            [], [], s=highlight_size, color=highlight_color,
            zorder=6, visible=False
        )

        # --- Statistics overlay ---
        # The "Trend Line" checkbox toggles the stats box (+ the dashed fit
        # line when present). The stats box shows slope/R² for numeric data
        # or "Avg. Cycle Time" for datetime data.
        is_datetime = self._is_datetime_data(values)
        self._regression_line = None
        self._stats_text = None
        info_text = None

        if is_datetime and len(values) >= 2:
            info_text = self._build_cycle_time_text(values)
        elif not is_datetime and len(values) >= 2:
            regression = self._compute_regression(slice_numbers, values)
            if regression is not None:
                slope, r_squared, x_line, y_line = regression
                self._regression_line, = self.ax.plot(
                    x_line, y_line, "--",
                    color=AppStyles.Colors.PLOT_INTERACTIVE_LINE_COLOR,
                    linewidth=1.5,
                    alpha=0.7,
                    label="Linear Fit",
                    zorder=2
                )
                info_text = f"Slope: {slope:.4g}\nR² = {r_squared:.4f}"

        if info_text:
            text_artist = self.ax.text(
                0.98, 0.98, info_text,
                transform=self.ax.transAxes,
                verticalalignment="top",
                horizontalalignment="right",
                bbox=dict(
                    boxstyle="round, pad=0.5",
                    facecolor=AppStyles.Colors.INPUT_BG,
                    edgecolor=AppStyles.Colors.PLOT_SPINE_COLOR,
                    alpha=0.8
                ),
                fontsize=9,
                color=AppStyles.Colors.TEXT_PRIMARY,
                zorder=100
            )
            self._stats_text = text_artist

        # The checkbox toggles the stats box (and the trend line when
        # present); enable it whenever there is a stats box to toggle.
        self._apply_trend_visibility()
        self._trend_checkbox.setEnabled(self._stats_text is not None)

        # --- Labels and title ---
        self.ax.set_xlabel("Slice Number")
        self.ax.set_ylabel(self._y_label)
        self.ax.set_title(
            self._title,
            fontsize=AppStyles.Dimensions.PLOT_TITLE_FONT_SIZE
        )

        # --- Annotation (hidden until click) ---
        self._create_annotation()

        # Store original limits for double-click reset
        self.canvas.draw_idle()
        self._original_xlim = self.ax.get_xlim()
        self._original_ylim = self.ax.get_ylim()
        # Seed the toolbar Home view so it resets to these same limits.
        # The custom scroll-zoom/drag-pan handlers never push onto the
        # toolbar's view history, so without this Home would do nothing
        # (or restore a stale view) after wheel-only zooming.
        self._interaction.seed_toolbar_home()

    def update_data(
        self,
        slice_numbers: list,
        values: list,
        image_names: list | None = None
    ):
        """
        Update the plot with new data (e.g., after slice range change).
        Convenience alias for plot_data.

        :param slice_numbers: X-axis values.
        :param values: Y-axis values.
        :param image_names: Optional image filenames for tooltips.
        """
        self.plot_data(slice_numbers, values, image_names)

    def set_context(self, site_name: str, step_name: str, detector: str):
        """
        Store the dataset context for this plot widget.

        Called after construction so the slice_selected signal can
        carry the site, step, and detector information.

        :param site_name: The site name.
        :param step_name: The step name.
        :param detector: The detector name.
        """
        self._site_name = site_name
        self._step_name = step_name
        self._detector = detector

    def set_composite_key(self, key: str):
        """
        Store the composite key used to identify this plot in the
        PlotDisplayArea registry.

        :param key: Composite key string (site|step|detector|field_path).
        """
        self._composite_key = key

    def set_slice_range(
        self, start: int, end: int, min_val: int, max_val: int
    ):
        """
        Set the per-plot slice range spinboxes without triggering
        the slice_range_changed signal.

        Used during initial plot creation and by the global slice
        range Update button.

        :param start: Start slice index.
        :param end: End slice index.
        :param min_val: Minimum available slice index.
        :param max_val: Maximum available slice index.
        """
        # Clamp requested values into the available range before any
        # spinbox calls so the cross-constraint bounds below stay valid.
        start = min(max(start, min_val), max_val)
        end = min(max(end, min_val), max_val)
        if start > end:
            start = end
        self._start_spinbox.blockSignals(True)
        self._end_spinbox.blockSignals(True)
        self._start_spinbox.update_range(min_val, max_val)
        self._end_spinbox.update_range(min_val, max_val)
        self._start_spinbox.setValue(start)
        self._end_spinbox.setValue(end)
        # Restore cross-constraints after programmatic set
        self._end_spinbox.setMinimum(start)
        self._start_spinbox.setMaximum(end)
        self._start_spinbox.blockSignals(False)
        self._end_spinbox.blockSignals(False)

    def set_active(self, active: bool):
        """Toggle the active-plot border.

        The active plot is the one currently driving the full-resolution
        image navigation and the metadata / execution-history / image
        panels. When active the plot card's border is recoloured to the
        active accent; when inactive it returns to the default
        (background-coloured, effectively invisible) border. The border
        width is unchanged either way, so there is no layout shift.

        Idempotent: re-setting the current state is a no-op.

        :param active: True to show the active border, False to clear it.
        """
        if active == self._active:
            return
        self._active = active
        if active:
            self._group_box.setStyleSheet(AppStyles.GroupBox.plot_active())
        else:
            self._group_box.setStyleSheet(AppStyles.GroupBox.plot())

    @property
    def selected_slice_index(self):
        """Slice index of the currently selected point, or None."""
        return self._selected_slice_index

    @property
    def slice_start(self) -> int:
        """Current start slice index from the spinbox."""
        return self._start_spinbox.value()

    @property
    def slice_end(self) -> int:
        """Current end slice index from the spinbox."""
        return self._end_spinbox.value()

    @property
    def slice_min(self) -> int:
        """Minimum available slice index from the spinbox range."""
        return self._start_spinbox.minimum()

    @property
    def slice_max(self) -> int:
        """Maximum available slice index from the end spinbox range."""
        return self._end_spinbox.maximum()

    @property
    def has_data(self) -> bool:
        """True if the plot currently displays data (not blanked)."""
        return bool(self._slice_numbers)

    def clear_plot(self):
        """Clear the plot and reset to styled empty axes."""
        self.ax.clear()
        self._style_axes()
        self._slice_numbers = []
        self._values = []
        self._image_names = []
        self._annotation = None
        self._selected_slice_index = None
        self._hover_scatter = None
        self._select_scatter = None
        self._original_xlim = None
        self._original_ylim = None
        self.canvas.draw_idle()

    def highlight_point_by_index(self, idx: int):
        """
        Programmatically highlight a data point by list index.

        Updates the annotation tooltip and select-highlight scatter
        without emitting ``slice_selected``.  Used by Prev / Next
        image navigation to keep the plot highlight in sync with the
        image viewer.

        :param idx: Index into ``_slice_numbers`` / ``_values`` /
            ``_image_names``.
        """
        if idx < 0 or idx >= len(self._slice_numbers):
            return

        slice_num = self._slice_numbers[idx]
        value = self._values[idx]
        self._selected_slice_index = slice_num

        # Build tooltip text (mirrors _show_annotation logic)
        lines = [f"Slice: {slice_num}", format_point_value(value)]

        display_y = (
            mdates.date2num(value) if isinstance(value, datetime) else value
        )

        # Update annotation
        if self._annotation:
            self._annotation.xy = (slice_num, display_y)
            self._annotation.set_text("\n".join(lines))
            self._annotation.set_visible(True)

        # Update select highlight, hide hover highlight
        if self._select_scatter:
            self._select_scatter.set_offsets([[slice_num, display_y]])
            self._select_scatter.set_visible(True)
        if self._hover_scatter:
            self._hover_scatter.set_visible(False)

        self.canvas.draw_idle()

    def highlight_point_by_slice_index(self, slice_idx: int):
        """Highlight this plot's point for a given slice index, or clear it.

        Used when "Link Slice Selection" is enabled: this plot highlights
        its own point for ``slice_idx``. If this plot has no point for that
        slice — sparse data, or filtered out by this plot's own slice range
        — the highlight is cleared so no stale selection is shown.

        :param slice_idx: The slice index to highlight across plots.
        """
        if slice_idx in self._slice_numbers:
            self.highlight_point_by_index(self._slice_numbers.index(slice_idx))
        else:
            self._hide_annotation()
            self.canvas.draw_idle()

    def clear_selection(self):
        """Programmatically clear the selected point and its annotation.

        Does not emit ``slice_deselected`` — used by the parent tab to
        propagate a user deselection across plots when "Link Slice
        Selection" is enabled without the broadcast echoing back.
        """
        self._hide_annotation()

    # -------------------------------------------------------------------------
    # Per-plot spinbox handler
    # -------------------------------------------------------------------------

    def _on_slice_spinbox_changed(self):
        """Emit slice_range_changed when the user adjusts a spinbox.

        A guard prevents duplicate emissions when cross-constraint
        updates cascade (e.g. changing start updates end's minimum,
        which may trigger end's valueChanged).
        """
        if self._replot_guard:
            return
        self._replot_guard = True
        self.slice_range_changed.emit(
            self._composite_key,
            self._start_spinbox.value(),
            self._end_spinbox.value()
        )
        self._replot_guard = False

    def _apply_trend_visibility(self):
        """Show/hide the trend line + slope/R² text per the checkbox.

        No-op when the artists don't exist (e.g. datetime plots or too
        few points), so it is safe to call unconditionally.
        """
        show = self._trend_checkbox.isChecked()
        if self._regression_line is not None:
            self._regression_line.set_visible(show)
        if self._stats_text is not None:
            self._stats_text.set_visible(show)

    def _on_trend_toggled(self, checked: bool):
        """Toggle the trend line + slope/R² text without a full replot,
        so the current zoom/pan is preserved."""
        self._apply_trend_visibility()
        self.canvas.draw_idle()

    def _on_close_clicked(self):
        """Handle the close button click. Emit close_requested signal."""
        self.close_requested.emit(self._composite_key)

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------

    @staticmethod
    def _is_datetime_data(values: list) -> bool:
        """Check if values contain datetime objects."""
        return values and isinstance(values[0], datetime)

    @staticmethod
    def _build_cycle_time_text(values: list) -> str | None:
        """
        Calculate average cycle time for datetime data.

        :param values: List of datetime values.
        :return: Formatted string or None if calculation fails.
        """
        try:
            start = min(values)
            end = max(values)
            intervals = len(values) - 1
            avg_seconds = (end - start).total_seconds() / intervals

            hours = int(avg_seconds // 3600)
            minutes = int((avg_seconds % 3600) // 60)
            seconds = avg_seconds % 60
            return f"Avg. Cycle Time:\n{hours:02d}:{minutes:02d}:{seconds:05.2f}"
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    def _compute_regression(
        self, slice_numbers: list, values: list
    ) -> tuple | None:
        """
        Compute a degree-1 linear fit and its R² (pure — no drawing).

        :param slice_numbers: X-axis values.
        :param values: Y-axis values.
        :return: ``(slope, r_squared, x_line, y_line)`` where x_line/y_line
            are the sampled fit-line coordinates, or None if the fit fails.
        """
        try:
            x = np.array(slice_numbers, dtype=float)
            y = np.array(values, dtype=float)

            coefficients = np.polyfit(x, y, 1)
            y_pred = np.polyval(coefficients, x)

            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared = 1.0 if ss_tot == 0 else max(0.0, min(1.0, 1 - ss_res / ss_tot))

            x_line = np.linspace(x.min(), x.max(), 100)
            y_line = np.polyval(coefficients, x_line)
            return float(coefficients[0]), float(r_squared), x_line, y_line
        except (TypeError, ValueError, np.linalg.LinAlgError):
            return None

    # -------------------------------------------------------------------------
    # Annotation Tooltip
    # -------------------------------------------------------------------------

    def _create_annotation(self):
        """Create the hidden annotation used for click tooltips."""
        self._annotation = self.ax.annotate(
            "",
            xy=(0, 0),
            xytext=(10, 10),
            textcoords="offset points",
            bbox=dict(
                boxstyle="round,pad=0.4",
                fc=AppStyles.Colors.INPUT_BG,
                ec=AppStyles.Colors.PLOT_SPINE_COLOR,
                alpha=0.9
            ),
            color=AppStyles.Colors.TEXT_PRIMARY,
            fontsize=9,
            visible=False,
            zorder=101
        )

    def _show_annotation(self, event):
        """
        Find the closest data point to the click and show the annotation.

        Clicking empty space in the axes clears the selection and
        emits ``slice_deselected`` so the parent tab can reset the
        panels that mirror it.

        :param event: Matplotlib mouse event.
        """
        if not self._slice_numbers or not self._values or not self._annotation:
            return

        closest = self._find_closest_point(event.xdata, event.ydata)
        if closest is None:
            self._on_user_deselect()
            return

        idx, slice_num, value = closest
        self._selected_slice_index = slice_num

        # Build tooltip text
        lines = [f"Slice: {slice_num}", format_point_value(value)]

        display_y = mdates.date2num(value) if isinstance(value, datetime) else value

        self._annotation.xy = (slice_num, display_y)
        self._annotation.set_text("\n".join(lines))
        self._annotation.set_visible(True)

        # Show select highlight, hide hover highlight
        if self._select_scatter:
            self._select_scatter.set_offsets([[slice_num, display_y]])
            self._select_scatter.set_visible(True)
        if self._hover_scatter:
            self._hover_scatter.set_visible(False)

        self.canvas.draw_idle()

        # Emit signal for the metadata groupbox
        image_name = self._image_names[idx] if idx < len(self._image_names) else ""
        self.slice_selected.emit(
            image_name, self._site_name, self._step_name, self._detector
        )

    def _hide_annotation(self):
        """Hide the annotation tooltip and select highlight."""
        self._selected_slice_index = None
        needs_redraw = False
        if self._annotation and self._annotation.get_visible():
            self._annotation.set_visible(False)
            needs_redraw = True
        if self._select_scatter and self._select_scatter.get_visible():
            self._select_scatter.set_visible(False)
            needs_redraw = True
        if needs_redraw:
            self.canvas.draw_idle()

    def _on_user_deselect(self):
        """Clear the selection in response to a user gesture and notify.

        Wraps :meth:`_hide_annotation` and emits ``slice_deselected``.
        Only user gestures route here (an empty-space click inside the
        axes, a press outside them); programmatic clears call
        :meth:`clear_selection` / :meth:`_hide_annotation` directly and
        never emit. Emission is unconditional: under linked selection
        this plot may carry no local highlight while a linked selection
        exists elsewhere, and the gesture must still deselect it.
        """
        self._hide_annotation()
        self.slice_deselected.emit()

    def _find_closest_point(
        self, x: float, y: float, threshold: float = 0.05
    ) -> tuple | None:
        """
        Find the data point closest to (x, y) in normalized axes coordinates.

        :param x: Click x in data coordinates.
        :param y: Click y in data coordinates.
        :param threshold: Maximum normalized distance to match.
        :return: (index, slice_number, value) or None.
        """
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()
        x_range = xlim[1] - xlim[0]
        y_range = ylim[1] - ylim[0]

        if x_range == 0 or y_range == 0:
            return None

        min_dist = float("inf")
        closest = None

        for i, (sn, val) in enumerate(zip(self._slice_numbers, self._values)):
            val_num = mdates.date2num(val) if isinstance(val, datetime) else val
            dx = (x - sn) / x_range
            dy = (y - val_num) / y_range
            dist = (dx ** 2 + dy ** 2) ** 0.5

            if dist < min_dist and dist < threshold:
                min_dist = dist
                closest = (i, sn, val)

        return closest

    def _update_hover(self, event):
        """Show or hide the hover highlight based on cursor proximity
        to a data point.

        :param event: Matplotlib mouse event.
        """
        if (event.inaxes != self.ax or not self._hover_scatter
                or not self._slice_numbers):
            if self._hover_scatter and self._hover_scatter.get_visible():
                self._hover_scatter.set_visible(False)
                self.canvas.draw_idle()
            return

        closest = self._find_closest_point(event.xdata, event.ydata)
        if closest is None:
            if self._hover_scatter.get_visible():
                self._hover_scatter.set_visible(False)
                self.canvas.draw_idle()
            return

        _, slice_num, value = closest
        display_y = mdates.date2num(value) if isinstance(value, datetime) else value
        self._hover_scatter.set_offsets([[slice_num, display_y]])
        self._hover_scatter.set_visible(True)
        self.canvas.draw_idle()