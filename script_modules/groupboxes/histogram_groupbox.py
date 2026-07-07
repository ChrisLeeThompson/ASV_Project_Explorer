"""
Histogram GroupBox

Right-side panel of the full-resolution image dialog: a vertical image
histogram (intensity on the Y axis, 0/data-min at the bottom; log-scaled
counts extending horizontally) with two draggable level lines that set
the displayed black and white points.

Each line carries a value box at its right edge showing its pixel
value; the box doubles as a drag handle. The lines may pass each other
— the dialog renders black-point > white-point as an inverted image
(reversed colormap), which some biologists prefer for SEM data
(brightfield-TEM-like contrast).

Per the project convention the groupbox owns only widgets and drag
state and exposes Signals; the parent dialog computes defaults and
applies the levels to the image artist:

- ``levels_changed(black_point, white_point)`` — emitted live during a
  drag and on release, always in (black, white) order regardless of
  which line is on top.
- ``levels_reset()`` — the Reset button was clicked; the dialog
  responds by calling :meth:`set_levels` with the image defaults.

Styling mirrors the metadata plots' look (dark background, pink trace,
cyan interactive lines) but uses its own ``HISTOGRAM_*`` constants in
``AppStyles`` so the panel can be tuned independently. All colors and
style dimensions come from ``AppStyles``.
"""
import logging

import numpy as np
import matplotlib.transforms as mtransforms
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QPushButton, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal

from script_modules.app_styles import AppStyles
from script_modules.widgets.pan_zoom_interaction import (
    install_stale_draw_guard,
)


logger = logging.getLogger(__name__)


# Histogram resolution (bins over the image's data range)
_BINS = 256

# Fraction of the data range used to keep the two levels from being
# exactly equal while one line passes the other (a degenerate range
# would break the image norm mid-crossing).
_LEVEL_EPSILON_FRACTION = 1.0 / 4096.0

_PLACEHOLDER = "No histogram"


class HistogramGroupBox(QGroupBox):
    """Vertical image histogram with draggable black/white level lines.

    The dialog feeds it image data via :meth:`set_histogram` (typically
    the decimated overview — visually identical, ~20 ms) and keeps the
    lines in sync with the image artist via :meth:`set_levels`.
    """

    # Live level updates: (black_point, white_point) in data units,
    # in that order regardless of which line is above the other.
    levels_changed = Signal(float, float)

    # Reset button clicked; the dialog supplies the defaults.
    levels_reset = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Histogram")
        self.setMinimumWidth(
            AppStyles.Dimensions.HISTOGRAM_PANEL_MINIMUM_WIDTH
        )

        # Data state
        self._data_min: float | None = None
        self._data_max: float | None = None
        self._integer_values = False

        # Level state (data units); None until the first histogram
        self._black: float | None = None
        self._white: float | None = None

        # Artists (recreated per set_histogram)
        self._black_line = None
        self._white_line = None
        self._black_box = None
        self._white_box = None

        # Drag state: None, "black", or "white". _drag_moved guards the
        # release emit so a motionless click does not pin the levels.
        self._dragging: str | None = None
        self._drag_moved = False
        # Cursor currently applied to the canvas (avoids re-setting it on
        # every hover motion event).
        self._hover_cursor = None
        # constrained_layout is frozen after the first settled draw so a
        # level drag can't reflow the axes; re-thawed per set_histogram.
        self._layout_frozen = False

        self._create_widgets()
        self._setup_layout()
        self._connect_signals()
        # No draw request at construction: the panel starts collapsed
        # (zero-width canvas breaks constrained_layout), and expanding
        # repaints via the canvas resize event anyway.
        self._show_placeholder(request_draw=False)

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _create_widgets(self):
        """Create the Reset button and the histogram canvas."""
        self.reset_button = QPushButton("Reset")
        self.reset_button.setStyleSheet(AppStyles.Button.default())
        self.reset_button.setEnabled(False)

        self.figure = Figure(
            facecolor=AppStyles.Colors.GROUPBOX_BG,
            constrained_layout=True,
        )
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.ax = self.figure.add_subplot(111)
        self._style_axes()

        # This canvas draws during level drags and lives in a
        # WA_DeleteOnClose dialog — exactly the stale-draw-timer
        # hazard class (see install_stale_draw_guard): a draw pending
        # at close would fire on the freed C++ canvas.
        install_stale_draw_guard(self.canvas)

    def _setup_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
        )
        layout.setSpacing(AppStyles.Dimensions.LAYOUT_VSPACING)
        layout.addWidget(self.reset_button)
        layout.addWidget(self.canvas, 1)

    def _connect_signals(self):
        self.reset_button.clicked.connect(self.levels_reset)
        self.canvas.mpl_connect("button_press_event", self._on_mouse_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.canvas.mpl_connect("button_release_event", self._on_mouse_release)
        self.canvas.mpl_connect("figure_leave_event", self._on_figure_leave)
        # Freeze constrained_layout after the first settled draw (Part 5);
        # a panel resize thaws it so the y-label width re-fits.
        self.canvas.mpl_connect("draw_event", self._freeze_layout_once)
        self.canvas.mpl_connect("resize_event", self._thaw_layout)

    def _style_axes(self):
        """Dark plot styling, matching the metadata plots."""
        ax = self.ax
        ax.set_facecolor(AppStyles.Colors.HISTOGRAM_BG)
        # Counts magnitude is not meaningful to read off (log-scaled);
        # hide the x ticks and keep small white intensity ticks on y.
        ax.tick_params(
            axis="y", colors=AppStyles.Colors.PLOT_SPINE_COLOR,
            labelsize=AppStyles.Dimensions.HISTOGRAM_TICK_LABEL_SIZE,
        )
        ax.tick_params(axis="x", bottom=False, labelbottom=False)
        for spine in ax.spines.values():
            spine.set_color(AppStyles.Colors.PLOT_SPINE_COLOR)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def set_histogram(self, img: np.ndarray, data_range=None):
        """Compute and display the histogram of ``img`` (2-D grayscale).

        Keeps the current levels if set (clamped into the new data
        range), otherwise initializes them to the data range. The
        dialog passes the decimated overview when one exists, along
        with ``data_range=(min, max)`` from the FULL image so the axis
        and reset levels are exact even though the strided sample may
        miss the extremes.
        """
        if img is None or img.size == 0:
            self.clear()
            return

        # Re-fit the axes to this image's y-label widths, then let the
        # next draw re-freeze the layout (Part 5).
        self._thaw_layout()

        if data_range is not None:
            data_min, data_max = (float(v) for v in data_range)
        else:
            data_min = float(img.min())
            data_max = float(img.max())
        if data_max <= data_min:
            data_max = data_min + 1.0  # flat image: avoid zero-width bins
        self._data_min = data_min
        self._data_max = data_max
        self._integer_values = np.issubdtype(img.dtype, np.integer)

        counts, edges = np.histogram(
            img, bins=_BINS, range=(data_min, data_max)
        )
        centers = (edges[:-1] + edges[1:]) / 2.0
        log_counts = np.log1p(counts)

        self.ax.clear()
        self._style_axes()
        self.ax.plot(
            log_counts, centers,
            color=AppStyles.Colors.HISTOGRAM_TRACE_COLOR,
            linewidth=AppStyles.Dimensions.HISTOGRAM_TRACE_WIDTH,
        )
        self.ax.fill_betweenx(
            centers, 0, log_counts,
            color=AppStyles.Colors.HISTOGRAM_TRACE_COLOR,
            alpha=AppStyles.Dimensions.HISTOGRAM_FILL_ALPHA,
        )
        x_max = float(log_counts.max()) if counts.any() else 1.0
        self.ax.set_xlim(0, x_max * 1.05)
        self.ax.set_ylim(data_min, data_max)

        # Initialize or clamp the levels into the new data range
        if self._black is None or self._white is None:
            self._black, self._white = data_min, data_max
        else:
            self._black = min(max(self._black, data_min), data_max)
            self._white = min(max(self._white, data_min), data_max)

        self._rebuild_level_artists()
        self.reset_button.setEnabled(True)
        self._request_draw()

    def set_levels(self, black: float, white: float):
        """Programmatically move the level lines (dialog-driven sync;
        does NOT emit ``levels_changed``)."""
        if self._data_min is None:
            return
        self._black = min(max(float(black), self._data_min), self._data_max)
        self._white = min(max(float(white), self._data_min), self._data_max)
        self._update_level_artists()
        self._request_draw()

    def current_levels(self) -> tuple[float, float] | None:
        """The (black_point, white_point) levels, or None before the
        first histogram."""
        if self._black is None or self._white is None:
            return None
        return (self._black, self._white)

    def clear(self):
        """Reset to the placeholder state (no image / failed load)."""
        self._data_min = None
        self._data_max = None
        self._black = None
        self._white = None
        self._black_line = self._white_line = None
        self._black_box = self._white_box = None
        self._dragging = None
        self._set_cursor(Qt.CursorShape.ArrowCursor)
        self.reset_button.setEnabled(False)
        self._show_placeholder()

    # -----------------------------------------------------------------
    # Level line artists
    # -----------------------------------------------------------------

    def _rebuild_level_artists(self):
        """Create the level lines and value boxes on freshly drawn axes."""
        line_kwargs = dict(
            color=AppStyles.Colors.HISTOGRAM_LEVEL_LINE_COLOR,
            linewidth=AppStyles.Dimensions.HISTOGRAM_LEVEL_LINE_WIDTH,
        )
        self._black_line = self.ax.axhline(self._black, **line_kwargs)
        self._white_line = self.ax.axhline(self._white, **line_kwargs)

        # Value boxes: pinned to the right edge (x in axes coords),
        # riding their line (y in data coords). They double as drag
        # handles via the shared y-distance hit test.
        box_transform = mtransforms.blended_transform_factory(
            self.ax.transAxes, self.ax.transData
        )
        text_kwargs = dict(
            transform=box_transform,
            ha="right", va="center",
            fontsize=AppStyles.Dimensions.HISTOGRAM_VALUE_FONT_SIZE,
            color=AppStyles.Colors.HISTOGRAM_VALUE_TEXT_COLOR,
            bbox=dict(
                boxstyle=(
                    f"round,pad="
                    f"{AppStyles.Dimensions.HISTOGRAM_VALUE_BOX_PAD}"
                ),
                facecolor=AppStyles.Colors.HISTOGRAM_VALUE_BOX_BG,
                edgecolor=AppStyles.Colors.HISTOGRAM_LEVEL_LINE_COLOR,
                linewidth=AppStyles.Dimensions.HISTOGRAM_VALUE_BOX_EDGE_WIDTH,
            ),
            zorder=10,
        )
        self._black_box = self.ax.text(
            0.97, self._black, self._format_value(self._black), **text_kwargs
        )
        self._white_box = self.ax.text(
            0.97, self._white, self._format_value(self._white), **text_kwargs
        )

    def _update_level_artists(self):
        """Move the existing lines/boxes to the current levels."""
        if self._black_line is None:
            return
        self._black_line.set_ydata([self._black, self._black])
        self._white_line.set_ydata([self._white, self._white])
        self._black_box.set_position((0.97, self._black))
        self._black_box.set_text(self._format_value(self._black))
        self._white_box.set_position((0.97, self._white))
        self._white_box.set_text(self._format_value(self._white))

    def _format_value(self, value: float) -> str:
        if self._integer_values:
            return f"{value:.0f}"
        return f"{value:.4g}"

    def _show_placeholder(self, request_draw: bool = True):
        self.ax.clear()
        self._style_axes()
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.ax.text(
            0.5, 0.5, _PLACEHOLDER,
            ha="center", va="center",
            color=AppStyles.Colors.TEXT_DISABLED,
            fontsize=AppStyles.Dimensions.HISTOGRAM_PLACEHOLDER_FONT_SIZE,
            transform=self.ax.transAxes,
        )
        if request_draw:
            self._request_draw()

    def _freeze_layout_once(self, event):
        """Lock the axes position after the first settled draw so a
        level drag can't trigger a constrained_layout reflow (which
        would shift the top/bottom edges). No-op until the canvas has a
        real size."""
        if self._layout_frozen:
            return
        if self.canvas.width() <= 1 or self.canvas.height() <= 1:
            return
        self._layout_frozen = True
        self.figure.set_layout_engine("none")

    def _thaw_layout(self, event=None):
        """Re-enable constrained_layout so the axes re-fit (new image's
        y-label width, or a panel resize); the next draw re-freezes."""
        self._layout_frozen = False
        self.figure.set_layout_engine("constrained")

    def _request_draw(self):
        """Redraw unless the canvas is collapsed to (near-)zero size —
        constrained_layout divides by zero on a zero-width figure, and
        expanding the panel triggers a fresh paint via the canvas
        resize event regardless."""
        if self.canvas.width() > 1 and self.canvas.height() > 1:
            self.canvas.draw_idle()

    # -----------------------------------------------------------------
    # Line dragging
    # -----------------------------------------------------------------

    def _level_epsilon(self) -> float:
        return (self._data_max - self._data_min) * _LEVEL_EPSILON_FRACTION

    def _hit_test(self, event) -> str | None:
        """Which line (or its value box) the event grabs, if any.

        Works in display pixels so it catches an edge line even when the
        click lands just outside the axes (``event.inaxes`` is None but
        ``event.x/y`` are still set). The vertical radius covers both
        the thin line and the value box centered on it; the horizontal
        check keeps left-margin (y-tick-label) clicks from grabbing.
        """
        if self._black is None or event.x is None or event.y is None:
            return None
        radius = AppStyles.Dimensions.HISTOGRAM_HIT_RADIUS_PX
        bbox = self.ax.get_window_extent()
        if not (bbox.x0 - radius <= event.x <= bbox.x1 + radius):
            return None
        hits = {}
        for which, value in (("black", self._black), ("white", self._white)):
            _, line_py = self.ax.transData.transform((0, value))
            distance = abs(event.y - line_py)
            if distance <= radius:
                hits[which] = distance
        if not hits:
            return None
        return min(hits, key=hits.get)

    def _event_data_y(self, event) -> float | None:
        """Data-space y of an event, even when the cursor has strayed
        past the top/bottom spine (``event.ydata`` is then None)."""
        if event.ydata is not None:
            return float(event.ydata)
        if event.x is None or event.y is None:
            return None
        return float(
            self.ax.transData.inverted().transform((event.x, event.y))[1]
        )

    def _on_mouse_press(self, event):
        # No inaxes gate: an edge line sits on a spine, so a valid grab
        # can land just outside the axes (hit test works in display px).
        if event.button != 1:
            return
        self._dragging = self._hit_test(event)
        self._drag_moved = False

    def _on_mouse_move(self, event):
        if self._dragging is None:
            self._update_hover_cursor(event)
            return

        data_y = self._event_data_y(event)
        if data_y is None:
            return
        value = min(max(data_y, self._data_min), self._data_max)

        # Lines may pass each other freely (black above white inverts
        # the image); only exact equality is nudged apart so the range
        # never degenerates mid-crossing. Nudge toward the interior so
        # the result stays within [data_min, data_max] even when both
        # levels are pinned to a boundary (a past-spine drag onto the
        # other line at data_max would otherwise escape the range).
        other = self._white if self._dragging == "black" else self._black
        if value == other:
            eps = self._level_epsilon() or 1e-9
            midpoint = (self._data_min + self._data_max) / 2
            value = other - eps if other >= midpoint else other + eps

        if self._dragging == "black":
            self._black = value
        else:
            self._white = value

        self._drag_moved = True
        self._update_level_artists()
        self._request_draw()
        self.levels_changed.emit(self._black, self._white)

    def _on_mouse_release(self, event):
        # Only the left button ends a level drag; a stray middle/right
        # release mid-drag must not abort it. Only a drag that actually
        # moved emits — a motionless click would otherwise pin the
        # autoscale default and needlessly trigger the overview swap.
        if event.button != 1:
            return
        if self._dragging is not None and self._drag_moved:
            self.levels_changed.emit(self._black, self._white)
        self._dragging = None
        self._drag_moved = False

    # -----------------------------------------------------------------
    # Hover cursor
    # -----------------------------------------------------------------

    def _update_hover_cursor(self, event):
        """Show a vertical double-headed arrow over a draggable line."""
        over_line = self._hit_test(event) is not None
        cursor = (Qt.CursorShape.SizeVerCursor if over_line
                  else Qt.CursorShape.ArrowCursor)
        self._set_cursor(cursor)

    def _on_figure_leave(self, event):
        self._set_cursor(Qt.CursorShape.ArrowCursor)

    def _set_cursor(self, cursor):
        if cursor != self._hover_cursor:
            self._hover_cursor = cursor
            self.canvas.setCursor(cursor)
