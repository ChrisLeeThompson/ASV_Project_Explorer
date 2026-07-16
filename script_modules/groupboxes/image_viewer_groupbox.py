"""
Image Viewer GroupBox

This module handles the "Image Viewer" group box in the ASV Project Metadata
section.  It displays a downsampled thumbnail of the currently selected
slice image inside a lightweight matplotlib canvas (no toolbar).

A "Full Resolution" button opens a modeless dialog that loads the image at
full resolution with a NavigationToolbar2QT for zoom, pan, and save.
Each dialog is tied to the plot that was active when it was opened
(keyed by the plot's composite key), so multiple dialogs can be open
side by side for image comparison. A dialog follows slice clicks on
its own plot only; clicking the button with a different plot active
opens (or refocuses) that plot's dialog. Dialogs close with their
plot, and all close when new data is loaded.
An optional metadata panel on the left side of each dialog shows the
plot title, the slice's value on that plot, and the execution history
and image metadata for the currently displayed image, with
search/filter support.

Previous / Next buttons allow sequential browsing through the image
stack, emitting ``slice_navigation_requested`` so the parent tab can
update the plot highlight, metadata tree, and execution history in sync.

Layout (top to bottom inside the group box):
- QLabel for the file name of the selected image/slice.
- QLabel for the site, step, and detector context.
- FigureCanvasQTAgg displaying the thumbnail (grayscale, dark background).
- Button row: [Prev.] [Full Resolution] [Next]

The group box starts in a placeholder state ("No slice selected")
and is populated when the user clicks a data point in any plot.
"""
import functools
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Callable

import numpy as np
import tifffile
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure

from PySide6.QtWidgets import (
    QApplication, QGroupBox, QLayout, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QPushButton, QDialog, QSizePolicy,
    QScrollArea,
)
from PySide6.QtCore import Qt, Slot, Signal, QTimer
from PySide6.QtGui import QScreen
from script_modules.app_styles import AppStyles
from script_modules.file_reveal import reveal_in_file_manager
from script_modules.widgets.clickable_label import ClickableLabel
from script_modules.widgets.asv_plot_widget import format_point_value
from script_modules.widgets.button_widgets import (
    FullResolutionButton, PreviousButton, NextButton,
)
from script_modules.groupboxes.execution_history_groupbox import (
    ExecutionHistoryGroupBox,
)
from script_modules.groupboxes.histogram_groupbox import HistogramGroupBox
from script_modules.groupboxes.image_metadata_groupbox import (
    ImageMetadataGroupBox,
)
from script_modules.widgets.collapsible_panel_handle import (
    CollapsibleSplitter,
)
from script_modules.widgets.pan_zoom_interaction import PanZoomInteraction


logger = logging.getLogger(__name__)


# Placeholder text shown before any slice is selected
_PLACEHOLDER_FILE_NAME = "No slice selected"
_PLACEHOLDER_CONTEXT = ""

# Thumbnail parameters
_THUMBNAIL_MAX_DIM = 1024  # Max width or height in pixels for the thumbnail

# During an active wheel/drag gesture the full-res dialog displays a
# strided overview no larger than this, swapping the full array back
# ~250 ms after the gesture ends. Striding is pure pixel-picking
# (nearest-equivalent, no filtering); measured ~5.6x faster per draw
# than the full array for 8192^2 images (~2 fps -> ~11.5 fps).
_OVERVIEW_MAX_DIM = 2048
# Sample resolution used while dragging the histogram level lines.
# Contrast windowing needs global brightness, not spatial detail, so a
# coarser sample than the full image keeps the drag responsive (set_clim
# re-normalizes the whole displayed array each frame). Larger = sharper
# but slower per frame (~1536px ≈ 130 ms, 1024px ≈ 90 ms, 2048px ≈ 160 ms
# on a 4096px image); set this at or above the largest image dimension
# (e.g. 100000) to disable downsampling entirely (full-resolution, no
# pixelation, slower). Tuned here for clarity over raw speed.
_LEVELS_OVERVIEW_MAX_DIM = 1536
_OVERVIEW_REFINE_DELAY_MS = 250

# Metadata panel width inside the full-resolution dialog
_PANEL_WIDTH = 380


# ============================================================================
# Helpers
# ============================================================================

# Decode cache: {(str(path), mtime): full decoded array}, LRU-ordered
# and capped by total bytes. The thumbnail and the full-resolution
# dialog both load the same file through _load_image, and Prev/Next
# stepping revisits neighbors, so keeping the last few full decodes
# skips the expensive imread. Invalidated in
# ImageViewerGroupBox.clear_image() and released when the last dialog
# closes with no thumbnail active.
_DECODE_CACHE_MAX_BYTES = 512 * 1024 * 1024
_decode_cache: OrderedDict = OrderedDict()


def _trim_decode_cache():
    """Evict least-recently-used decodes until the cache fits the byte
    budget, always keeping the newest entry (even if it alone exceeds
    the budget — it is the image currently being displayed)."""
    total = sum(getattr(img, "nbytes", 0) for img in _decode_cache.values())
    while total > _DECODE_CACHE_MAX_BYTES and len(_decode_cache) > 1:
        _, evicted = _decode_cache.popitem(last=False)
        total -= getattr(evicted, "nbytes", 0)


def _load_image(path: Path, max_dim: int | None = None) -> np.ndarray | None:
    """
    Load a TIFF image, optionally downsampling via stride for speed.

    The full decode is cached (byte-capped LRU, keyed by path and
    mtime) so consecutive loads of the same file — e.g. thumbnail then
    full-resolution view, or Prev/Next stepping back to a neighbor —
    decode only once.  The ``max_dim`` stride is applied after the
    cache lookup.

    :param path: Absolute path to the .tif file.
    :param max_dim: If provided, downsample so neither axis exceeds
        this value.  Uses stride-based subsampling (no interpolation)
        for maximum speed.
    :return: 2-D numpy array (grayscale) or 3-D array (RGB/RGBA),
        or None on failure.
    """
    try:
        cache_key = (str(path), path.stat().st_mtime)
    except OSError:
        logger.error(f"Failed to read image: {path}", exc_info=True)
        return None

    img = _decode_cache.get(cache_key)
    if img is None:
        try:
            img = tifffile.imread(str(path))
        except Exception:
            logger.error(f"Failed to read image: {path}", exc_info=True)
            return None
        _decode_cache[cache_key] = img
        _trim_decode_cache()
    else:
        _decode_cache.move_to_end(cache_key)

    if max_dim is not None and img.ndim >= 2:
        h, w = img.shape[:2]
        factor = max(1, max(h, w) // max_dim)
        if factor > 1:
            img = img[::factor, ::factor]

    return img


def _style_axes_dark(ax, show_axis: bool = False):
    """
    Apply a dark theme to matplotlib axes consistent with the app.

    :param ax: The matplotlib Axes to style.
    :param show_axis: If False, hides the axis ticks and labels
        entirely (cleaner for the embedded thumbnail).
    """
    ax.set_facecolor(AppStyles.Colors.PLOT_BG)
    if not show_axis:
        ax.set_axis_off()
    else:
        ax.tick_params(
            colors=AppStyles.Colors.PLOT_SPINE_COLOR, labelsize=8
        )
        for spine in ax.spines.values():
            spine.set_color(AppStyles.Colors.PLOT_SPINE_COLOR)


# ============================================================================
# Full Resolution Dialog
# ============================================================================

class FullResolutionDialog(QDialog):
    """
    Modeless dialog for viewing an image at full resolution.

    Provides a NavigationToolbar2QT for zoom, pan, home reset, and
    save-to-file.  Previous / Next buttons allow stepping through the
    image stack without closing the dialog.

    An optional metadata panel on the left displays the execution
    history and image metadata for the currently displayed image.
    The panel can be toggled via a button in the toolbar row.

    The dialog is non-blocking so the user can continue to interact
    with the main window (e.g. switch between tabs).  If the user
    clicks a different plot data point, :meth:`update_context` swaps
    the image and navigation state in place.

    The dialog opens at 80 % of the screen size with the image fitted
    to the view.
    """

    # Emitted when Previous / Next is clicked inside the dialog.
    # Args: composite_key, image_name, site_name, step_name, detector
    slice_navigated = Signal(str, str, str, str, str)

    def __init__(
        self,
        image_path: Path,
        image_name: str,
        nav_image_names: list[str] | None = None,
        nav_image_paths: list[Path] | None = None,
        nav_index: int = -1,
        nav_site: str = "",
        nav_step: str = "",
        nav_detector: str = "",
        metadata: dict | None = None,
        exec_history: dict | None = None,
        metadata_lookup: Callable | None = None,
        composite_key: str = "",
        plot_title: str = "",
        nav_values: list | None = None,
        parent=None,
    ):
        """
        :param image_path: Absolute path to the initial .tif file.
        :param image_name: Display name of the initial image.
        :param nav_image_names: Ordered image names for navigation.
        :param nav_image_paths: Parallel list of absolute paths.
        :param nav_index: Current position in the navigation list.
        :param nav_site: Site name for navigation signal emission.
        :param nav_step: Step name for navigation signal emission.
        :param nav_detector: Detector name for navigation signal emission.
        :param metadata: Initial image metadata dict for the panel.
        :param exec_history: Initial execution history dict for the panel.
        :param metadata_lookup: Optional callable
            ``(image_name, site, step, detector) -> (metadata, exec_history)``
            used to refresh the panel when navigating.
        :param composite_key: Key of the plot this dialog is tied to
            (site|step|detector|field_path). Fixed for the dialog's life.
        :param plot_title: One-line plot label (field label) shown in
            the window title and the metadata panel.
        :param nav_values: Plot values parallel to ``nav_image_names``
            (for the panel's value line).
        :param parent: Parent widget.
        """
        super().__init__(parent)
        self._composite_key = composite_key
        self._plot_title = plot_title
        self.setWindowTitle(self._window_title_for(image_name))
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._image_path = image_path
        self._image_name = image_name

        # Navigation state
        self._nav_image_names = list(nav_image_names or [])
        self._nav_image_paths = list(nav_image_paths or [])
        self._nav_values = list(nav_values or [])
        self._nav_index = nav_index
        self._nav_site = nav_site
        self._nav_step = nav_step
        self._nav_detector = nav_detector

        # Metadata panel callback
        self._metadata_lookup = metadata_lookup

        # One-shot guard so the nav-button width is aligned to the
        # splitter's real (clamped) left width exactly once, on first show.
        self._nav_width_synced = False

        # _fit_xlim/_fit_ylim hold the current image's fit-to-image
        # limits, recomputed on every successful display and used by
        # the double-click reset (see PanZoomInteraction, wired in
        # _connect_signals). _image_displayed is False while the axes
        # show the load-failure placeholder, whose default limits must
        # never be preserved onto a real image.
        self._fit_xlim = None
        self._fit_ylim = None
        self._image_displayed = False

        # Gesture-time samples: while wheel/drag events stream in, the
        # AxesImage shows a strided subsample of the current image and
        # the refine timer swaps the full array back once the gesture
        # ends. _overview (≤2048px) is used for zoom/pan; the coarser
        # _levels_overview (≤1024px) for contrast windowing. Either is
        # None when the image is already small enough. _displayed_sample
        # is the array currently swapped in (None = full resolution).
        self._image_artist = None
        self._full_img = None
        self._overview = None
        self._levels_overview = None
        self._displayed_sample = None
        self._refine_timer = QTimer(self)
        self._refine_timer.setSingleShot(True)
        self._refine_timer.setInterval(_OVERVIEW_REFINE_DELAY_MS)
        self._refine_timer.timeout.connect(self._restore_full_res)

        # Histogram levels: (black_point, white_point) in data units,
        # or None for the autoscale default. black > white renders the
        # inverted image (reversed colormap). Persists across Prev/Next
        # like zoom; reset on a fresh (non-preserved) display.
        # _data_range caches the full image's (min, max) — the Reset
        # default — captured from the autoscaled clim at imshow time.
        self._levels: tuple[float, float] | None = None
        self._data_range: tuple[float, float] | None = None

        # Size the dialog to 80 % of the primary screen
        self._set_initial_size()

        # Apply dark background
        self.setStyleSheet(
            f"QDialog {{ background-color: {AppStyles.Colors.MAIN_BG}; }}"
        )

        # Build UI
        self._create_widgets()
        self._create_metadata_panel()
        self._create_histogram_panel()
        self._setup_layout()
        self._connect_signals()

        # Load and display the image (full resolution)
        self._display_image()
        self._update_nav_button_states()

        # Populate the metadata panel with initial data
        self._populate_metadata_panel(
            image_name, nav_site, nav_step, nav_detector,
            metadata or {}, exec_history or {},
        )

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _set_initial_size(self):
        """Size the dialog to 80 % of the screen and center it there.

        The dialog is unparented (an owned window would always stack
        above the main window on Windows — see _open_full_resolution),
        so it cannot rely on a parent for screen or placement."""
        screen = self.screen() or QApplication.primaryScreen()
        geometry = QScreen.availableGeometry(screen)
        self.resize(
            int(geometry.width() * 0.8), int(geometry.height() * 0.8)
        )
        self.move(geometry.center() - self.rect().center())

    def _create_widgets(self):
        """Create navigation buttons, matplotlib figure, canvas, and toolbar."""
        # Previous / Next buttons for stack navigation
        self.prev_button = QPushButton("Previous")
        self.prev_button.setStyleSheet(AppStyles.Button.default())
        self.next_button = QPushButton("Next")
        self.next_button.setStyleSheet(AppStyles.Button.default())

        # Matplotlib figure and canvas
        self.figure = Figure(
            facecolor=AppStyles.Colors.MAIN_BG,
            constrained_layout=True,
        )
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.ax = self.figure.add_subplot(111)
        _style_axes_dark(self.ax, show_axis=True)

        # Histogram panel toggle (top row, right of the toolbar)
        self.histogram_button = QPushButton("Histogram")
        self.histogram_button.setCheckable(True)
        self.histogram_button.setStyleSheet(AppStyles.Button.toggle())

        # Navigation toolbar (zoom, pan, home, save)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.toolbar.setStyleSheet(AppStyles.ToolBar.navigation())
        AppStyles.apply_toolbar_icon_color(self.toolbar)
        # Reserve a minimum width for the x/y coordinate readout so it never
        # clips (a floor that holds regardless of how the toolbar is laid out
        # in the top row).
        if hasattr(self.toolbar, "locLabel"):
            self.toolbar.locLabel.setMinimumWidth(
                AppStyles.Dimensions.FULL_RES_TOOLBAR_READOUT_MIN_WIDTH
            )

    def _create_metadata_panel(self):
        """Create the collapsible left panel with execution history
        and image metadata groupboxes."""
        self._metadata_panel = QGroupBox()
        self._metadata_panel.setTitle("Slice Data")
        self._metadata_panel.setStyleSheet(AppStyles.GroupBox.with_title_flush())
        self._metadata_panel.setMinimumWidth(
            AppStyles.Dimensions.SLICE_DATA_MINIMUM_WIDTH
        )

        # Plot identity: the tied plot's title and the slice's value on
        # that plot (above the file name, so the user can read
        # plot → value → image at a glance when comparing windows)
        self._panel_plot_title_label = QLabel(self._plot_title)
        self._panel_plot_title_label.setStyleSheet(
            AppStyles.Label.default()
        )
        self._panel_plot_title_label.setWordWrap(True)
        self._panel_plot_title_label.setVisible(bool(self._plot_title))

        self._panel_value_label = QLabel(self._current_value_text())
        self._panel_value_label.setStyleSheet(AppStyles.Label.default())
        self._panel_value_label.setWordWrap(True)
        self._panel_value_label.setVisible(bool(self._plot_title))

        # Shared file name and context labels
        # File name doubles as a "reveal in folder" link: normal text that
        # turns blue on hover (see _populate_metadata_panel / _on_file_name_clicked).
        self._panel_file_name_label = ClickableLabel(_PLACEHOLDER_FILE_NAME)
        self._panel_file_name_label.clicked.connect(self._on_file_name_clicked)

        self._panel_context_label = QLabel(_PLACEHOLDER_CONTEXT)
        self._panel_context_label.setStyleSheet(AppStyles.Label.default())
        self._panel_context_label.setWordWrap(True)

        # Execution history groupbox (embedded style, own search)
        self._panel_exec_history = ExecutionHistoryGroupBox(
            parent=self._metadata_panel
        )
        self._panel_exec_history.set_visibility_of_file_name(False)
        self._panel_exec_history.set_visibility_of_context(False)
        self._panel_exec_history.setStyleSheet(
            AppStyles.GroupBox.embedded()
        )

        # Image metadata groupbox (embedded style, own search)
        self._panel_image_metadata = ImageMetadataGroupBox(
            parent=self._metadata_panel
        )
        self._panel_image_metadata.set_visibility_of_file_name(False)
        self._panel_image_metadata.set_visibility_of_context(False)
        self._panel_image_metadata.setStyleSheet(
            AppStyles.GroupBox.embedded()
        )

        # Scroll area containing both groupboxes
        scroll_container = QWidget()
        container_layout = QVBoxLayout(scroll_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(AppStyles.Dimensions.LAYOUT_VSPACING)
        container_layout.addWidget(self._panel_exec_history, 1)
        container_layout.addWidget(self._panel_image_metadata, 1)

        scroll_area = QScrollArea()
        scroll_area.setWidget(scroll_container)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll_area.setStyleSheet(AppStyles.ScrollArea.embedded())

        # Assemble the panel layout
        panel_layout = QVBoxLayout(self._metadata_panel)
        panel_layout.setContentsMargins(
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
        )
        panel_layout.setSpacing(AppStyles.Dimensions.LAYOUT_VSPACING)
        panel_layout.addWidget(self._panel_plot_title_label)
        panel_layout.addWidget(self._panel_value_label)
        panel_layout.addWidget(self._panel_file_name_label)
        panel_layout.addWidget(self._panel_context_label)
        panel_layout.addWidget(scroll_area, 1)

    def _create_histogram_panel(self):
        """Create the collapsible right panel with the image histogram
        and its level controls."""
        self._histogram_box = HistogramGroupBox(parent=self)
        self._histogram_box.setStyleSheet(
            AppStyles.GroupBox.with_title_flush_right()
        )

    def _setup_layout(self):
        """
        Arrange controls in two rows:

        Top row (always visible):
            [Previous | Next] ---- [NavigationToolbar] [Histogram]

        Content row (collapsible splitter):
            [metadata panel] | handle | [canvas] | handle | [histogram]

        The nav button container tracks the splitter's left-panel
        width so the two columns stay aligned during drag.  When
        the panel is collapsed, the buttons retain their last width
        and remain fully accessible.  The histogram panel starts
        collapsed; the Histogram toggle button and its splitter
        handle both expand it.
        """
        # The splitter clamps the left pane up to the metadata panel's
        # minimum width, so the nav-button column and the splitter's
        # initial left size must start at that clamped value — otherwise
        # the toolbar opens misaligned until the panel is toggled.
        initial_panel_width = max(
            _PANEL_WIDTH, AppStyles.Dimensions.SLICE_DATA_MINIMUM_WIDTH
        )

        # ---- Top row: nav buttons + toolbar (always visible) ----
        self._nav_button_container = QWidget()
        self._nav_button_container.setFixedWidth(initial_panel_width)
        nav_layout = QHBoxLayout(self._nav_button_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)
        nav_layout.addWidget(self.prev_button, 1)
        nav_layout.addWidget(self.next_button, 1)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(AppStyles.Dimensions.SPLITTER_HANDLE_WIDTH)
        top_row.addWidget(self._nav_button_container)
        # Toolbar stretches to fill the row so its x/y readout sits at the far
        # right (against the Histogram button). The readout still has a reserved
        # minimum width (see _create_display) so it never clips.
        top_row.addWidget(self.toolbar, 1)
        top_row.addWidget(self.histogram_button)

        # Center pane: wrap the canvas so it keeps left/right breathing
        # room from the splitter handles (matches the groupbox-to-window
        # spacing).  The wrapper is transparent, so the side gaps show the
        # dialog's MAIN_BG, blending with the figure facecolor.
        self._canvas_container = QWidget()
        canvas_container_layout = QHBoxLayout(self._canvas_container)
        canvas_container_layout.setContentsMargins(
            AppStyles.Dimensions.IMAGE_VIEWER_SIDE_MARGIN,
            0,
            AppStyles.Dimensions.IMAGE_VIEWER_SIDE_MARGIN,
            0,
        )
        canvas_container_layout.addWidget(self.canvas)

        # ---- Content row: collapsible splitter ----
        self._panel_splitter = CollapsibleSplitter(parent=self)
        self._panel_splitter.addWidget(self._metadata_panel)
        self._panel_splitter.addWidget(self._canvas_container)
        self._panel_splitter.addWidget(self._histogram_box)
        self._panel_splitter.setStretchFactor(0, 0)
        self._panel_splitter.setStretchFactor(1, 1)
        self._panel_splitter.setStretchFactor(2, 0)
        # Right panel: click-collapsible like the left one, starting
        # collapsed until the Histogram button (or handle) opens it.
        # It opens at its minimum width (most compact); the user can
        # widen it by dragging the handle.
        self._panel_splitter.set_click_collapsible(2)
        self._panel_splitter.set_preferred_size(
            2, AppStyles.Dimensions.HISTOGRAM_PANEL_MINIMUM_WIDTH
        )
        self._panel_splitter.setSizes(
            [initial_panel_width, self.width() - initial_panel_width, 0]
        )
        # setSizes alone cannot reach 0 (the histogram groupbox has a
        # minimum width); this collapses it silently past the minimum.
        self._panel_splitter.initialize_collapsed(2)

        # Sync nav button width with left panel on drag / expand
        self._panel_splitter.splitterMoved.connect(
            self._on_splitter_moved
        )
        self._panel_splitter.toggled.connect(
            self._on_splitter_toggled
        )
        # Histogram panel ↔ toggle button sync (either can drive)
        self._panel_splitter.panel_toggled.connect(
            self._on_panel_toggled
        )
        self.histogram_button.toggled.connect(
            self._on_histogram_button_toggled
        )

        # ---- Main layout ----
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
        )
        layout.setSpacing(AppStyles.Dimensions.LAYOUT_VSPACING)
        layout.addLayout(top_row)
        layout.addWidget(self._panel_splitter, 1)

    def _connect_signals(self):
        """Connect Previous / Next buttons and canvas interaction."""
        self.prev_button.clicked.connect(self._on_previous)
        self.next_button.clicked.connect(self._on_next)
        # Canvas interaction (shared with the plots): scroll to zoom,
        # drag to pan, double-click to reset. Connections live for the
        # dialog's lifetime; WA_DeleteOnClose tears down canvas and
        # handlers together.
        self._interaction = PanZoomInteraction(
            self.ax, self.canvas, self.toolbar,
            get_fit_limits=lambda: (self._fit_xlim, self._fit_ylim),
            on_interactive_view_change=self._on_interactive_view_change,
        )
        # Histogram level lines → image windowing
        self._histogram_box.levels_changed.connect(self._on_levels_changed)
        self._histogram_box.levels_reset.connect(self._on_levels_reset)

    def showEvent(self, event):                        # noqa: N802
        """Align the nav-button column to the splitter's real left width
        once the window is first shown.

        The splitter only applies the metadata panel's minimum-width
        clamp during its layout pass, so the true left width isn't known
        until after this event.  Defer the sync to the next event-loop
        tick so it reads the settled geometry rather than the pre-clamp
        value.
        """
        super().showEvent(event)
        if not self._nav_width_synced:
            self._nav_width_synced = True
            QTimer.singleShot(0, self._sync_nav_button_width)

    # -----------------------------------------------------------------
    # Splitter ↔ Nav Button Width Sync
    # -----------------------------------------------------------------

    def _sync_nav_button_width(self):
        """Match the nav-button column width to the splitter's real
        left-panel width so the toolbar stays aligned with the canvas.

        No-ops when the panel is collapsed (width 0) so the buttons keep
        their last width and remain usable.
        """
        left_width = self._panel_splitter.sizes()[0]
        if left_width > 0:
            self._nav_button_container.setFixedWidth(left_width)

    def _on_splitter_moved(self, pos: int, index: int):
        """Keep the nav button container aligned with the left panel
        when the user drags the splitter handle."""
        self._sync_nav_button_width()

    def _on_splitter_toggled(self, expanded: bool):
        """Re-sync the nav button container width when the panel is
        expanded (restored from collapse).  On collapse the buttons
        keep their current width so they remain usable."""
        if expanded:
            self._sync_nav_button_width()

    # -----------------------------------------------------------------
    # Metadata Panel
    # -----------------------------------------------------------------

    def _window_title_for(self, image_name: str) -> str:
        """Build the window title: plot label + image name, so windows
        for different plots are distinguishable in the taskbar."""
        if self._plot_title:
            return f"{self._plot_title} — {image_name}"
        return f"Full Resolution — {image_name}"

    def _current_value_text(self) -> str:
        """Formatted plot value for the current navigation position,
        matching the plot annotation's formatting exactly."""
        if 0 <= self._nav_index < len(self._nav_values):
            return format_point_value(self._nav_values[self._nav_index])
        return "—"

    @Slot()
    def _on_file_name_clicked(self):
        """Reveal the current image in the OS file manager. This dialog is a
        standalone window with no status bar, so failures are logged by the
        helper rather than surfaced here."""
        reveal_in_file_manager(self._image_path)

    def _image_title_text(self) -> str:
        """Title line above the image: the tied plot's title, the
        slice's value on that plot, and the file name, so the user can
        read plot → value → image at a glance when comparing windows.

        Falls back to the bare file name when the dialog has no plot
        context.  Separator matches the context label's convention.
        """
        if self._plot_title:
            return (
                f"{self._plot_title}  •  {self._current_value_text()}"
                f"  •  {self._image_name}"
            )
        return self._image_name

    def _populate_metadata_panel(
        self,
        image_name: str,
        site_name: str,
        step_name: str,
        detector: str,
        metadata: dict,
        exec_history: dict,
    ):
        """
        Populate the metadata panel with data for the current image.

        :param image_name: The image file name.
        :param site_name: Site name.
        :param step_name: Step name.
        :param detector: Detector name.
        :param metadata: Image metadata dict.
        :param exec_history: Execution history dict.
        """
        self._panel_value_label.setText(self._current_value_text())
        # File name is a "reveal in folder" link when a path is known.
        self._panel_file_name_label.setText(image_name)
        self._panel_file_name_label.set_clickable(bool(self._image_path))
        self._panel_file_name_label.setToolTip(
            AppStyles.AppToolTips.IMAGE_NAME_LINK if self._image_path else ""
        )
        self._panel_context_label.setText(
            f"{site_name}  •  {step_name}  •  {detector}"
        )
        if exec_history:
            self._panel_exec_history.populate(
                image_name, site_name, step_name, detector, exec_history,
            )
        else:
            self._panel_exec_history.clear_history()

        if metadata:
            self._panel_image_metadata.populate(
                image_name, site_name, step_name, detector, metadata,
            )
        else:
            self._panel_image_metadata.clear_metadata()

    # -----------------------------------------------------------------
    # Public API — in-place update
    # -----------------------------------------------------------------

    def update_context(
        self,
        image_path: Path,
        image_name: str,
        nav_image_names: list[str],
        nav_image_paths: list[Path],
        nav_index: int,
        nav_site: str,
        nav_step: str,
        nav_detector: str,
        metadata: dict | None = None,
        exec_history: dict | None = None,
        nav_values: list | None = None,
        raise_window: bool = True,
    ):
        """
        Replace the dialog's content with a new image and navigation
        context, without closing and reopening the window.

        Called by :class:`ImageViewerGroupBox` when the user clicks a
        different plot data point while the dialog is already open.

        :param image_path: Absolute path to the new .tif file.
        :param image_name: Display name of the new image.
        :param nav_image_names: Updated ordered image names.
        :param nav_image_paths: Parallel list of absolute paths.
        :param nav_index: Current position in the new navigation list.
        :param nav_site: Site name.
        :param nav_step: Step name.
        :param nav_detector: Detector name.
        :param metadata: Image metadata dict for the panel.
        :param exec_history: Execution history dict for the panel.
        :param nav_values: Plot values parallel to ``nav_image_names``
            (None leaves the current values unchanged).
        :param raise_window: If False, skip raising the window — used by
            bulk reconcile updates so N dialogs are not all raised.
        """
        # Detect whether the image actually changed.  When the dialog's
        # own Prev/Next triggers navigation, the signal round-trips
        # through the parent tab and arrives back here via
        # populate() → update_context().  At that point
        # _navigate_to_current() has already loaded the image with
        # zoom preservation, so we skip the redundant (and
        # zoom-resetting) redraw.
        image_changed = (image_path != self._image_path)

        self._image_path = image_path
        self._image_name = image_name
        self._nav_image_names = list(nav_image_names)
        self._nav_image_paths = list(nav_image_paths)
        if nav_values is not None:
            self._nav_values = list(nav_values)
        self._nav_index = nav_index
        self._nav_site = nav_site
        self._nav_step = nav_step
        self._nav_detector = nav_detector

        self.setWindowTitle(self._window_title_for(image_name))
        self._update_nav_button_states()

        # Only reload when the image actually changed (i.e. the user
        # clicked a different data point on the plot).
        if image_changed:
            self._display_image()

        self._populate_metadata_panel(
            image_name, nav_site, nav_step, nav_detector,
            metadata or {}, exec_history or {},
        )

        # Bring the dialog to the front without stealing keyboard focus
        # from the main window — the user may be actively working in a
        # tab and just wants the image to refresh in the background.
        if raise_window:
            self.raise_()

    # -----------------------------------------------------------------
    # Navigation
    # -----------------------------------------------------------------

    @Slot()
    def _on_previous(self):
        """Navigate to the previous image in the stack."""
        if self._nav_index <= 0 or not self._nav_image_names:
            return
        self._nav_index -= 1
        self._navigate_to_current()

    @Slot()
    def _on_next(self):
        """Navigate to the next image in the stack."""
        if (self._nav_index >= len(self._nav_image_names) - 1
                or not self._nav_image_names):
            return
        self._nav_index += 1
        self._navigate_to_current()

    def _navigate_to_current(self):
        """Load the image at ``_nav_index``, update the metadata panel,
        and emit the signal."""
        self._image_name = self._nav_image_names[self._nav_index]
        self._image_path = self._nav_image_paths[self._nav_index]
        self.setWindowTitle(self._window_title_for(self._image_name))
        self._update_nav_button_states()
        self._display_image(preserve_view=True)

        # Update the metadata panel via the lookup callback
        if self._metadata_lookup:
            metadata, exec_history = self._metadata_lookup(
                self._image_name,
                self._nav_site,
                self._nav_step,
                self._nav_detector,
            )
            self._populate_metadata_panel(
                self._image_name,
                self._nav_site,
                self._nav_step,
                self._nav_detector,
                metadata,
                exec_history,
            )

        self.slice_navigated.emit(
            self._composite_key,
            self._image_name,
            self._nav_site,
            self._nav_step,
            self._nav_detector,
        )

    def _update_nav_button_states(self):
        """Enable / disable Previous and Next based on position."""
        has_nav = (
            len(self._nav_image_names) > 1 and self._nav_index >= 0
        )
        self.prev_button.setEnabled(has_nav and self._nav_index > 0)
        self.prev_button.setVisible(has_nav)
        self.next_button.setEnabled(
            has_nav
            and self._nav_index < len(self._nav_image_names) - 1
        )
        self.next_button.setVisible(has_nav)

    # -----------------------------------------------------------------
    # Image Display
    # -----------------------------------------------------------------

    def _display_image(self, preserve_view: bool = False):
        """Load and render the full-resolution image.

        :param preserve_view: If True, save and restore the current
            zoom level and pan position after redrawing.  Used during
            Previous / Next navigation so the user can stay zoomed
            into a region of interest while stepping through the
            image stack.  Ignored when the previous display failed —
            the failure placeholder's default limits are meaningless
            and must not be carried onto a real image.
        """
        # Save current view limits before clearing (if preserving)
        preserve = preserve_view and self._image_displayed
        saved_xlim = self.ax.get_xlim() if preserve else None
        saved_ylim = self.ax.get_ylim() if preserve else None

        # Histogram levels follow the same persistence rule as the
        # zoom: kept across Prev/Next, reset on a fresh display.
        if not preserve:
            self._levels = None

        self.ax.clear()
        _style_axes_dark(self.ax, show_axis=True)

        img = _load_image(self._image_path, max_dim=None)
        if img is None:
            self._image_displayed = False
            self._image_artist = None
            self._full_img = None
            self._overview = None
            self._levels_overview = None
            self._displayed_sample = None
            self._refine_timer.stop()
            self._data_range = None
            self.histogram_button.setEnabled(False)
            self._histogram_box.clear()
            self.ax.text(
                0.5, 0.5,
                "Failed to load image",
                ha="center", va="center",
                color=AppStyles.Colors.TEXT_PRIMARY,
                fontsize=12,
                transform=self.ax.transAxes,
            )
            self.canvas.draw_idle()
            return

        # Recompute the fit-to-image limits for THIS image (y inverted:
        # imshow puts the origin top-left). Done on every successful
        # display so double-click reset and toolbar Home never point at
        # a previous image's extent after navigating across images of
        # different dimensions.
        height, width = img.shape[:2]
        fit_xlim = (-0.5, width - 0.5)
        fit_ylim = (height - 0.5, -0.5)
        fit_changed = (fit_xlim != self._fit_xlim
                       or fit_ylim != self._fit_ylim)
        self._fit_xlim = fit_xlim
        self._fit_ylim = fit_ylim

        is_grayscale = img.ndim == 2
        cmap = "gray" if is_grayscale else None
        # nearest = raw pixel picking at every zoom level: no filtering
        # or antialiasing of the microscopy data, and ~5x cheaper per
        # draw than the antialiased default on multi-megapixel images.
        self._image_artist = self.ax.imshow(img, cmap=cmap, aspect="equal",
                                            interpolation="nearest")

        # Gesture-time samples (see _show_gesture_sample): strided
        # pixel-picking, built once per image. set_data swaps keep the
        # artist's extent and norm, so a sample stretches over the full
        # image rectangle at identical brightness. Ceil-division so any
        # image larger than the cap gets a sample (plain floor division
        # left 2049-4095px images with none). The levels sample is
        # coarser — contrast windowing needs no spatial detail.
        self._full_img = img
        self._overview = self._build_sample(img, _OVERVIEW_MAX_DIM)
        self._levels_overview = self._build_sample(
            img, _LEVELS_OVERVIEW_MAX_DIM
        )
        self._displayed_sample = None

        # Histogram windowing: imshow just autoscaled the norm to the
        # full image's (min, max) — capture it as the Reset default.
        # _levels holds the user's LITERAL window (persistent intent,
        # like the saved zoom limits); it is clamped into each image's
        # range only when applied/displayed, never stored back — so a
        # window survives a round-trip through an image it falls outside
        # of, and an out-of-range image never pins its range as a
        # phantom window on later images. set_clim only acts on
        # colormapped images, so RGB disables the panel but keeps
        # _levels (survives a gray → RGB → gray step, like zoom).
        if is_grayscale:
            self._data_range = tuple(
                float(v) for v in self._image_artist.get_clim()
            )
            if self._levels is not None:
                self._apply_levels()
            self.histogram_button.setEnabled(True)
            self.histogram_button.setToolTip("")
        else:
            self._data_range = None
            self.histogram_button.setEnabled(False)
            self.histogram_button.setToolTip("Grayscale images only")
        self.ax.set_title(
            self._image_title_text(),
            color=AppStyles.Colors.TEXT_PRIMARY,
            fontsize=10,
            pad=6,
        )

        # Restore saved view limits for zoom / pan preservation
        if saved_xlim is not None and saved_ylim is not None:
            self.ax.set_xlim(saved_xlim)
            self.ax.set_ylim(saved_ylim)
            if fit_changed:
                self._reseed_home_preserving(saved_xlim, saved_ylim)
        else:
            # Fresh image: the imshow autoscale already shows the fit
            # view; seed it as the toolbar Home (the per-image
            # ax.clear() plus custom scroll/pan would otherwise leave
            # Home pointing at a stale view or doing nothing).
            self._interaction.seed_toolbar_home()

        self._image_displayed = True
        self._refresh_histogram()
        self.canvas.draw_idle()
        logger.debug(
            f"Full-resolution image displayed: {self._image_name} "
            f"({img.shape})"
        )

    def _reseed_home_preserving(self, view_xlim, view_ylim):
        """Reseed the toolbar Home view to the new image's fit limits
        while keeping the given (preserved) view current: Home restores
        the fit, Back steps from the view to the fit."""
        self.ax.set_xlim(self._fit_xlim)
        self.ax.set_ylim(self._fit_ylim)
        self._interaction.seed_toolbar_home()
        self.ax.set_xlim(view_xlim)
        self.ax.set_ylim(view_ylim)
        self._interaction.push_history()

    # -----------------------------------------------------------------
    # Gesture-time overview (wheel/drag responsiveness on large images)
    # -----------------------------------------------------------------

    @staticmethod
    def _build_sample(img, max_dim):
        """Strided pixel-picking sample no larger than ``max_dim`` on
        either axis, or None when the image is already that small.
        Ceil-division so any image larger than the cap gets a sample."""
        longest = max(img.shape[:2])
        factor = max(1, -(-longest // max_dim))  # ceil division
        return img[::factor, ::factor].copy() if factor > 1 else None

    @property
    def _showing_overview(self) -> bool:
        """True while any reduced gesture sample is displayed."""
        return self._displayed_sample is not None

    def _show_gesture_sample(self, sample):
        """Swap the artist to ``sample`` for the duration of a gesture;
        the refine timer restores full resolution once events stop
        arriving. No-op when the image has no sample (already small)."""
        if sample is None or self._image_artist is None:
            return
        if self._displayed_sample is not sample:
            self._image_artist.set_data(sample)
            self._displayed_sample = sample
        self._refine_timer.start()

    def _on_interactive_view_change(self):
        """Zoom/pan gesture callback (PanZoomInteraction): show the
        spatial overview while the gesture streams."""
        self._show_gesture_sample(self._overview)

    def _restore_full_res(self):
        """Swap the full-resolution array back after a gesture ends."""
        if self._displayed_sample is None or self._image_artist is None:
            return
        self._image_artist.set_data(self._full_img)
        self._displayed_sample = None
        self.canvas.draw_idle()

    # -----------------------------------------------------------------
    # Histogram levels (contrast windowing)
    # -----------------------------------------------------------------

    @Slot(bool)
    def _on_histogram_button_toggled(self, checked: bool):
        """Histogram toolbar button drives the right panel."""
        self._panel_splitter.set_panel_expanded(2, checked)

    def _on_panel_toggled(self, index: int, expanded: bool):
        """Keep the Histogram button in sync when the panel is toggled
        via its splitter handle, and populate the panel lazily on
        expand (the histogram is never computed while hidden)."""
        if index != 2:
            return
        self.histogram_button.blockSignals(True)
        self.histogram_button.setChecked(expanded)
        self.histogram_button.blockSignals(False)
        if expanded:
            self._refresh_histogram()

    def _refresh_histogram(self):
        """Recompute the histogram panel for the current image. Lazy:
        skipped while the panel is collapsed (done on expand instead)."""
        if not self._panel_splitter.is_panel_expanded(2):
            return
        if (self._full_img is None or self._full_img.ndim != 2
                or self._data_range is None):
            self._histogram_box.clear()
            return
        # The strided overview has an identical histogram shape at a
        # fraction of the cost; the full image's exact (min, max) is
        # passed alongside so the axis and reset levels are exact.
        source = (self._overview if self._overview is not None
                  else self._full_img)
        self._histogram_box.set_histogram(
            source, data_range=self._data_range
        )
        # Show the window clamped into this image's range (what the
        # artist displays); the dialog keeps the unclamped intent.
        black, white = self._display_levels() or self._data_range
        self._histogram_box.set_levels(black, white)

    @staticmethod
    def _clamp_levels(levels, data_range):
        """Clamp (black, white) into the data range for display,
        preserving their order (and therefore the polarity). If clamping
        collapses them onto the same boundary — a window entirely
        outside a narrower image's range — fall back to the full range
        so the norm never degenerates to a zero-width span. The result
        is used only for the current image; the caller keeps the
        unclamped window as the persistent intent."""
        dmin, dmax = data_range
        black, white = levels
        black = min(max(black, dmin), dmax)
        white = min(max(white, dmin), dmax)
        if black == white:
            return (dmin, dmax)
        return (black, white)

    def _display_levels(self):
        """The current window clamped into the current image's range —
        what the artist and the panel lines actually show (None until a
        window and an image are both present)."""
        if self._levels is None or self._data_range is None:
            return None
        return self._clamp_levels(self._levels, self._data_range)

    def _apply_levels(self):
        """Apply the current window (clamped to this image's range) to
        the image artist. matplotlib rejects vmin > vmax, so inversion
        (black point dragged above the white point) is expressed through
        the reversed colormap — mathematically identical and switchable
        live mid-drag."""
        display = self._display_levels()
        if self._image_artist is None or display is None:
            return
        black, white = display
        self._image_artist.set_clim(min(black, white), max(black, white))
        self._image_artist.set_cmap("gray" if black <= white else "gray_r")

    @Slot(float, float)
    def _on_levels_changed(self, black: float, white: float):
        """Live windowing while a level line is dragged."""
        self._levels = (black, white)
        if self._image_artist is None:
            return
        self._apply_levels()
        # Same gesture path as wheel/drag, but with the coarser levels
        # sample (windowing needs no spatial detail): show it while drag
        # events stream in; the refine timer restores full resolution
        # once the gesture ends.
        self._show_gesture_sample(self._levels_overview)
        self.canvas.draw_idle()

    @Slot()
    def _on_levels_reset(self):
        """Reset button: image defaults (data min → max, normal
        polarity) — identical to the autoscale display."""
        self._levels = None
        if self._image_artist is None or self._data_range is None:
            return
        data_min, data_max = self._data_range
        self._image_artist.set_clim(data_min, data_max)
        self._image_artist.set_cmap("gray")
        self._histogram_box.set_levels(data_min, data_max)
        self.canvas.draw_idle()


# ============================================================================
# Image Viewer GroupBox
# ============================================================================

class ImageViewerGroupBox(QGroupBox):
    """
    Group box that displays a thumbnail preview of the selected slice
    image, with a button to open a full-resolution viewer dialog and
    Previous / Next buttons for sequential stack browsing.
    """

    # Emitted when Prev / Next is clicked.
    # Args: image_name, site_name, step_name, detector
    slice_navigation_requested = Signal(str, str, str, str)

    # Emitted when Prev / Next is clicked inside a full-resolution
    # dialog. Args: composite_key, image_name, site_name, step_name,
    # detector — the key identifies the plot the dialog is tied to.
    dialog_navigation_requested = Signal(str, str, str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Image Viewer")
        self._image_path: Path | None = None
        self._image_name: str = ""

        # Navigation state (the ACTIVE plot's context: source for the
        # thumbnail Prev/Next and for newly opened full-res dialogs)
        self._nav_image_names: list[str] = []
        self._nav_image_paths: list[Path] = []
        self._nav_values: list = []
        self._nav_index: int = -1
        self._nav_site: str = ""
        self._nav_step: str = ""
        self._nav_detector: str = ""
        self._nav_composite_key: str = ""
        self._nav_plot_title: str = ""

        # Metadata lookup callback (set by the parent tab)
        self._metadata_lookup: Callable | None = None

        # Open full-resolution dialogs, keyed by the composite key of
        # the plot each is tied to (one dialog per plot)
        self._dialogs: dict[str, FullResolutionDialog] = {}

        self._create_widgets()
        self._setup_layout()
        self._connect_signals()

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _create_widgets(self):
        """Create labels, canvas, and full-resolution button."""
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # File name label
        self.file_name_label = QLabel(_PLACEHOLDER_FILE_NAME)
        self.file_name_label.setStyleSheet(AppStyles.Label.default())
        self.file_name_label.setWordWrap(True)

        # Site / step / detector context label
        self.context_label = QLabel(_PLACEHOLDER_CONTEXT)
        self.context_label.setStyleSheet(AppStyles.Label.default())
        self.context_label.setWordWrap(True)

        # Matplotlib canvas for the thumbnail — wrapped in a QWidget
        # container to prevent the native canvas surface from painting
        # over sibling widgets (e.g. the Full Resolution button).
        self._canvas_container = QWidget()
        canvas_layout = QVBoxLayout(self._canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)

        self.figure = Figure(
            facecolor=AppStyles.Colors.GROUPBOX_BG,
            constrained_layout=True,
        )
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.canvas.setMinimumHeight(AppStyles.Dimensions.IMAGE_VIEWER_CANVAS_MINIMUM_HEIGHT)
        self._canvas_container.setMaximumHeight(AppStyles.Dimensions.IMAGE_VIEWER_CANVAS_CONTAINER_MAXIMUM_HEIGHT)
        self.ax = self.figure.add_subplot(111)
        _style_axes_dark(self.ax)

        canvas_layout.addWidget(self.canvas)
        self._canvas_container.setVisible(False)

        # Full-resolution button
        self.full_res_button = FullResolutionButton(parent=self)

        # Previous / Next navigation buttons
        self.prev_button = PreviousButton(parent=self)
        self.next_button = NextButton(parent=self)

        # Button row container: [Prev] [Full Resolution] [Next]
        self._button_row = QWidget()
        button_layout = QHBoxLayout(self._button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(4)
        button_layout.addWidget(self.prev_button)
        button_layout.addWidget(self.full_res_button, 1)  # stretch
        button_layout.addWidget(self.next_button)
        self._button_row.setVisible(False)

    def _setup_layout(self):
        """Stack widgets vertically inside the group box."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
        )
        layout.setSpacing(AppStyles.Dimensions.LAYOUT_VSPACING)
        layout.addWidget(self.file_name_label)
        layout.addWidget(self.context_label)
        layout.addWidget(self._canvas_container, 1)  # stretch factor
        layout.addWidget(self._button_row)
        self.setStyleSheet(AppStyles.GroupBox.with_title())

    def _connect_signals(self):
        """Connect buttons and double-click shortcut."""
        self.full_res_button.clicked.connect(self._open_full_resolution)
        self.prev_button.clicked.connect(self._on_previous)
        self.next_button.clicked.connect(self._on_next)
        self.canvas.mpl_connect("button_press_event", self._on_canvas_dblclick)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def set_metadata_lookup(self, callback: Callable | None):
        """
        Store a metadata lookup callback for the full resolution dialog.

        The callback signature is::

            (image_name, site_name, step_name, detector) -> (metadata_dict, exec_history_dict)

        :param callback: Callable or None to disable.
        """
        self._metadata_lookup = callback

    def populate(
        self,
        image_name: str,
        site_name: str,
        step_name: str,
        detector: str,
        image_path: Path,
    ):
        """
        Display a thumbnail preview of the selected image.

        If a navigation context has been set via
        :meth:`set_navigation_context`, the current index is updated
        to match ``image_name`` and the Prev / Next button states are
        refreshed.

        :param image_name: The image file name.
        :param site_name: The site name.
        :param step_name: The step name.
        :param detector: The detector name.
        :param image_path: Absolute path to the .tif file on disk.
        """
        self._image_name = image_name
        self._image_path = image_path

        self.file_name_label.setText(image_name)
        self.context_label.setText(
            f"{site_name}  •  {step_name}  •  {detector}"
        )

        # Sync navigation index if context is available
        if image_name in self._nav_image_names:
            self._nav_index = self._nav_image_names.index(image_name)
        self._update_nav_button_states()

        # Load and display thumbnail
        self._display_thumbnail()

        # Show interactive controls
        self._canvas_container.setVisible(True)
        self._button_row.setVisible(True)

        # If the active plot has an open full-resolution dialog, update
        # it in place. Dialogs tied to OTHER plots are never touched —
        # each window follows only its own plot.
        dialog = self._dialogs.get(self._nav_composite_key)
        if dialog is not None:
            metadata = {}
            exec_history = {}
            if self._metadata_lookup:
                metadata, exec_history = self._metadata_lookup(
                    image_name, self._nav_site,
                    self._nav_step, self._nav_detector,
                )
            dialog.update_context(
                image_path=image_path,
                image_name=image_name,
                nav_image_names=self._nav_image_names,
                nav_image_paths=self._nav_image_paths,
                nav_index=self._nav_index,
                nav_site=self._nav_site,
                nav_step=self._nav_step,
                nav_detector=self._nav_detector,
                metadata=metadata,
                exec_history=exec_history,
                nav_values=self._nav_values,
            )

        logger.debug(f"Image viewer populated for: {image_name}")

    def set_navigation_context(
        self,
        image_names: list[str],
        image_paths: list[Path],
        site_name: str,
        step_name: str,
        detector: str,
        composite_key: str = "",
        plot_title: str = "",
        values: list | None = None,
    ):
        """
        Set the ordered image list for Prev / Next navigation.

        Called when a data point is clicked on a plot.  The list should
        match the plot's data series (same detector filter and slice
        range) so that navigation steps through the same images the
        plot displays.

        :param image_names: Ordered list of image file names.
        :param image_paths: Parallel list of absolute paths to the
            .tif files on disk.
        :param site_name: Site name for the navigation context.
        :param step_name: Step name for the navigation context.
        :param detector: Detector name for the navigation context.
        :param composite_key: Key of the plot this context came from
            (ties newly opened full-res dialogs to that plot).
        :param plot_title: One-line plot label for dialog titles.
        :param values: Plot values parallel to ``image_names``.
        """
        self._nav_image_names = list(image_names)
        self._nav_image_paths = list(image_paths)
        self._nav_values = list(values or [])
        self._nav_site = site_name
        self._nav_step = step_name
        self._nav_detector = detector
        self._nav_composite_key = composite_key
        self._nav_plot_title = plot_title
        # Index will be synced in the next populate() call
        self._nav_index = -1
        logger.debug(
            f"Navigation context set: {len(image_names)} images "
            f"({site_name} • {step_name} • {detector})"
        )

    def clear_image(self, close_dialogs: bool = True):
        """Reset the group box to its placeholder state.

        :param close_dialogs: If False, open full-resolution dialogs
            are left alone — used when only the active plot's panel
            state is being reset (e.g. the active plot closed while
            other plots keep their comparison windows).
        """
        if close_dialogs:
            self.close_all_dialogs()
        _decode_cache.clear()
        self._image_path = None
        self._image_name = ""
        self.file_name_label.setText(_PLACEHOLDER_FILE_NAME)
        self.context_label.setText(_PLACEHOLDER_CONTEXT)
        self.ax.clear()
        _style_axes_dark(self.ax)
        self.canvas.draw_idle()
        self._canvas_container.setVisible(False)
        self._button_row.setVisible(False)
        # Reset navigation
        self._nav_image_names = []
        self._nav_image_paths = []
        self._nav_values = []
        self._nav_index = -1
        self._nav_site = ""
        self._nav_step = ""
        self._nav_detector = ""
        self._nav_composite_key = ""
        self._nav_plot_title = ""
    
    def set_visibility_of_file_name(self, visible: bool):
        """
        Show or hide the file name label.

        :param visible: True to show the file name, False to hide it.
        """
        self.file_name_label.setVisible(visible)
    
    def set_visibility_of_context(self, visible: bool):
        """
        Show or hide the site/step/detector context label.

        :param visible: True to show the context, False to hide it.
        """
        self.context_label.setVisible(visible)

    # -----------------------------------------------------------------
    # Prev / Next Navigation
    # -----------------------------------------------------------------

    @Slot()
    def _on_previous(self):
        """Navigate to the previous image in the stack."""
        if self._nav_index <= 0 or not self._nav_image_names:
            return
        self._nav_index -= 1
        image_name = self._nav_image_names[self._nav_index]
        self._update_nav_button_states()
        self.slice_navigation_requested.emit(
            image_name, self._nav_site, self._nav_step, self._nav_detector
        )

    @Slot()
    def _on_next(self):
        """Navigate to the next image in the stack."""
        if (self._nav_index >= len(self._nav_image_names) - 1
                or not self._nav_image_names):
            return
        self._nav_index += 1
        image_name = self._nav_image_names[self._nav_index]
        self._update_nav_button_states()
        self.slice_navigation_requested.emit(
            image_name, self._nav_site, self._nav_step, self._nav_detector
        )

    def _update_nav_button_states(self):
        """Enable / disable Prev and Next based on current position."""
        has_nav = len(self._nav_image_names) > 1 and self._nav_index >= 0
        self.prev_button.setEnabled(
            has_nav and self._nav_index > 0
        )
        self.next_button.setEnabled(
            has_nav and self._nav_index < len(self._nav_image_names) - 1
        )

    # -----------------------------------------------------------------
    # Thumbnail Display
    # -----------------------------------------------------------------

    def _display_thumbnail(self):
        """Load and render a downsampled thumbnail on the embedded canvas."""
        self.ax.clear()
        _style_axes_dark(self.ax)

        if self._image_path is None or not self._image_path.is_file():
            self.ax.text(
                0.5, 0.5,
                "Image file not found",
                ha="center", va="center",
                color=AppStyles.Colors.TEXT_DISABLED,
                fontsize=10,
                transform=self.ax.transAxes,
            )
            self.canvas.draw_idle()
            return

        img = _load_image(self._image_path, max_dim=_THUMBNAIL_MAX_DIM)
        if img is None:
            self.ax.text(
                0.5, 0.5,
                "Failed to load image",
                ha="center", va="center",
                color=AppStyles.Colors.TEXT_DISABLED,
                fontsize=10,
                transform=self.ax.transAxes,
            )
            self.canvas.draw_idle()
            return

        cmap = "gray" if img.ndim == 2 else None
        self.ax.imshow(img, cmap=cmap, aspect="equal")
        self.canvas.draw_idle()

        logger.debug(
            f"Thumbnail displayed: {self._image_name} "
            f"(original → downsampled {img.shape})"
        )

    # -----------------------------------------------------------------
    # Full Resolution Viewer
    # -----------------------------------------------------------------

    @Slot()
    def _open_full_resolution(self):
        """Open or refocus the full-resolution dialog for the active plot.

        Each dialog is tied to the plot whose slice is currently shown
        (one dialog per plot, keyed by composite key), so windows for
        different plots can stay open side by side for comparison. If
        the active plot's dialog is already open, it is updated to the
        current slice and brought to the front; otherwise a new
        modeless dialog is created.
        """
        if self._image_path is None or not self._image_path.is_file():
            logger.warning("No valid image path for full resolution view.")
            return

        # Look up metadata for the current image
        metadata = {}
        exec_history = {}
        if self._metadata_lookup:
            metadata, exec_history = self._metadata_lookup(
                self._image_name,
                self._nav_site,
                self._nav_step,
                self._nav_detector,
            )

        # Reuse the active plot's dialog if it is still open
        key = self._nav_composite_key
        existing = self._dialogs.get(key)
        if existing is not None:
            existing.update_context(
                image_path=self._image_path,
                image_name=self._image_name,
                nav_image_names=self._nav_image_names,
                nav_image_paths=self._nav_image_paths,
                nav_index=self._nav_index,
                nav_site=self._nav_site,
                nav_step=self._nav_step,
                nav_detector=self._nav_detector,
                metadata=metadata,
                exec_history=exec_history,
                nav_values=self._nav_values,
            )
            existing.activateWindow()
            return

        # Create a new modeless dialog tied to the active plot.
        # Deliberately UNPARENTED: on Windows an owned window always
        # stacks above its owner, which made the comparison windows
        # sit permanently on top of the main window. As independent
        # top-level windows they can go behind the main window (and
        # each gets its own taskbar entry). The metadata tab's
        # cleanup() closes them at shutdown so they cannot outlive
        # the application.
        dialog = FullResolutionDialog(
            image_path=self._image_path,
            image_name=self._image_name,
            nav_image_names=self._nav_image_names,
            nav_image_paths=self._nav_image_paths,
            nav_index=self._nav_index,
            nav_site=self._nav_site,
            nav_step=self._nav_step,
            nav_detector=self._nav_detector,
            metadata=metadata,
            exec_history=exec_history,
            metadata_lookup=self._metadata_lookup,
            composite_key=key,
            plot_title=self._nav_plot_title,
            nav_values=self._nav_values,
            parent=None,
        )
        # Connect dialog navigation → keyed relay so the parent tab can
        # route highlights/panels to the plot this dialog is tied to.
        dialog.slice_navigated.connect(self._on_dialog_navigated)
        # Drop the registry entry when the dialog is closed by the user
        # (partial binds the key; destroyed may pass the QObject).
        dialog.destroyed.connect(
            functools.partial(self._on_dialog_destroyed, key)
        )

        self._dialogs[key] = dialog
        dialog.show()

    def _on_dialog_navigated(
        self, composite_key: str, image_name: str,
        site_name: str, step_name: str, detector: str
    ):
        """
        Handle Previous / Next inside a full-resolution dialog.

        Syncs the thumbnail's navigation index only when the dialog is
        tied to the active plot, then re-emits the keyed
        ``dialog_navigation_requested`` so the parent tab routes the
        plot highlight (and, for the active plot, the panel updates).
        """
        if (composite_key == self._nav_composite_key
                and image_name in self._nav_image_names):
            self._nav_index = self._nav_image_names.index(image_name)
            self._update_nav_button_states()
        self.dialog_navigation_requested.emit(
            composite_key, image_name, site_name, step_name, detector
        )

    def _on_dialog_destroyed(self, key: str, obj=None):
        """Drop the registry entry when a dialog is destroyed.

        No-op when a close path already popped the key. When the
        destroyed QObject is delivered, identity is checked so a
        newer dialog reopened under the same key is never popped by
        the old dialog's queued destroyed signal.
        """
        current = self._dialogs.get(key)
        if current is None:
            return
        if obj is None or current is obj:
            self._dialogs.pop(key, None)
            self._maybe_release_decode_cache()

    def close_dialog_for(self, composite_key: str):
        """Close the full-resolution dialog tied to the given plot,
        if one is open. Called by the parent tab when a plot closes.
        """
        dialog = self._dialogs.pop(composite_key, None)
        if dialog is not None:
            dialog.close()
        self._maybe_release_decode_cache()

    def close_all_dialogs(self):
        """Close every open full-resolution dialog."""
        dialogs = list(self._dialogs.values())
        self._dialogs.clear()
        for dialog in dialogs:
            dialog.close()
        self._maybe_release_decode_cache()

    def _maybe_release_decode_cache(self):
        """Free the decode cache once nothing can use it: no open
        full-resolution dialogs and no active thumbnail. The last full
        decode can be ~134 MB (8k uint16) and would otherwise live
        until the next data load."""
        if not self._dialogs and self._image_path is None:
            _decode_cache.clear()

    def open_dialog_keys(self) -> list[str]:
        """Composite keys of all currently open full-res dialogs."""
        return list(self._dialogs.keys())

    def get_dialog(self, composite_key: str):
        """The open dialog tied to the given plot, or None."""
        return self._dialogs.get(composite_key)

    def _on_canvas_dblclick(self, event):
        """Open full resolution on double-click of the thumbnail canvas."""
        if event.dblclick and self._image_path is not None:
            self._open_full_resolution()