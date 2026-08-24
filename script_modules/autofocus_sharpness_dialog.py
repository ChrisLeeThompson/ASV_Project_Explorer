"""
Autofocus Sharpness Dialog

Modal dialog that displays a sharpness histogram plot from an Auto Focus
execution result. Shows the three sharpness curves (G1, G2, G3) against
working distance, with vertical marker lines for the Found WD and the
Optimized WD.

When Found WD and Optimized WD are identical, only the Optimized WD line
is drawn to avoid visual overlap.  When they differ, both are shown with
distinct colors and dashed lines.

Hovering highlights the nearest plotted point; clicking it pins a tooltip
with that point's working distance and the sharpness score of the curve
it belongs to.  The tooltip is pinned rather than hover-only because this
dialog is modal: reading a WD against the Execution History tree behind it
means dragging the dialog aside, which a hover tooltip would not survive.

"""
import logging
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSizePolicy,
)
from script_modules.app_styles import AppStyles
from script_modules.widgets.pan_zoom_interaction import PanZoomInteraction


logger = logging.getLogger(__name__)


# ── Sharpness curve colors ──────────────────────────────────────────────────
# G-number convention (confirmed by the user, July 2026):
# G1 = Fine, G2 = Medium, G3 = Coarse.
_COLOR_COARSE   = AppStyles.Colors.COLOR_COARSE   # G3 (Coarse) curve
_COLOR_MEDIUM   = AppStyles.Colors.COLOR_MEDIUM   # G2 (Medium) curve
_COLOR_FINE     = AppStyles.Colors.COLOR_FINE     # G1 (Fine) curve
_COLOR_FOUND_WD = AppStyles.Colors.COLOR_FOUND_WD # Found WD marker
_COLOR_OPT_WD   = AppStyles.Colors.COLOR_OPT_WD   # Optimized / corrected WD marker

# One entry per plotted curve: (legend label, color, key in the raw JSON
# point).  Single source of truth for the draw order, the legend text, the
# required-key filter AND the tooltip, so the tooltip can never name a curve
# the plot does not draw or read a value out of the wrong key.  Ordered
# coarse-to-fine: matplotlib draws later entries on top, and Fine is the
# curve read most often.
_CURVES = (
    ("Coarse (G3)", _COLOR_COARSE, "SharpnessG3"),
    ("Medium (G2)", _COLOR_MEDIUM, "SharpnessG2"),
    ("Fine (G1)",   _COLOR_FINE,   "SharpnessG1"),
)

# Keys a raw JSON point must carry to be plottable.  Derived from _CURVES so
# the filter and the extraction can never drift apart.
_REQUIRED_KEYS = ("Wd",) + tuple(key for _, _, key in _CURVES)

# Working distances arrive from the ASV JSON in metres; every WD this dialog
# displays is in millimetres.
_M_TO_MM = 1000.0

# Tolerance for treating FoundWd == OptimizedWd (metres)
_WD_EQUALITY_TOL = 1e-9

# Axes fraction past which the tooltip box flips to the opposite side of its
# point so it is not clipped at the figure edge.  Geometry policy rather than
# styling, so it lives here beside _WD_EQUALITY_TOL.
_TOOLTIP_FLIP_FRACTION = 0.75


def _format_wd_mm(wd_mm: float) -> str:
    """Format a working distance (already in millimetres) for display.

    One definition for the marker lines' legend labels and for the point
    tooltip, so the WD a user reads off a marker line is character-for-
    character the WD shown on a selected point.  Four decimals resolves
    the sub-micron steps of an AF sweep at millimetre working distances.

    :param wd_mm: Working distance in millimetres.
    :return: e.g. ``"4.0219 mm"``.
    """
    return f"{wd_mm:.4f} mm"


def _format_wd_m(wd_m: float) -> str:
    """Format the raw working distance in metres, exactly as the
    Execution History tree renders it.

    That tree (and the image-metadata tree) display these values through
    a plain ``str()`` — full round-trip precision, no rounding, no fixed
    width.  Reproducing that here rather than rounding makes the
    comparison this tooltip exists for a literal character match instead
    of a mental conversion, which is why the value is carried in metres
    all the way from the JSON rather than being derived back from the
    millimetre figure (that round trip would drift in the last digits).

    :param wd_m: Working distance in metres, as parsed from the JSON.
    :return: e.g. ``"0.004021949308419559 m"``.
    """
    return f"{wd_m} m"


def _format_sharpness(value: float) -> str:
    """Format a sharpness score for the point tooltip.

    Four significant digits rather than fixed decimals: the Coarse curve
    routinely runs orders of magnitude above the Fine curve, and a fixed
    ``.3f`` would print either a wall of trailing zeros or a flat
    ``0.000``.  Matches HistogramGroupBox._format_value.

    :param value: A raw ``SharpnessGn`` value.
    :return: e.g. ``"8.628"``.
    """
    return f"{value:.4g}"


class AutofocusSharpnessDialog(QDialog):
    """
    Modal dialog showing the sharpness histogram from an Auto Focus result.

    :param sharpness_data: List of dicts, each containing ``Wd`` (metres),
        ``SharpnessG1``, ``SharpnessG2``, and ``SharpnessG3``.
    :param found_wd: Working distance (metres) found by the AF algorithm,
        or ``None`` if not available.
    :param optimized_wd: Optimized / corrected working distance (metres)
        that was actually applied, or ``None`` if not available.
    :param activity_context: Optional string appended to the window title
        for context (e.g. ``"Slice 42  •  Site 1"``).
    :param parent: Optional parent widget.
    """

    def __init__(
        self,
        sharpness_data: list[dict],
        found_wd: float | None,
        optimized_wd: float | None,
        activity_context: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._sharpness_data = sharpness_data
        self._found_wd = found_wd
        self._optimized_wd = optimized_wd
        self._activity_context = activity_context

        # ── Plotted series, retained for the point hit test ───────────
        # The shared x values (millimetres) plus one y list per entry of
        # _CURVES, in the same order.  _wd_m carries the same working
        # distances in their original metres so the tooltip can quote the
        # raw value the Execution History tree shows.  All stay empty on
        # the no-data path — that is what makes every point handler inert
        # there without a second guard in each one.
        self._wd_mm: list[float] = []
        self._wd_m: list[float] = []
        self._curve_values: list[list[float]] = []

        # ── Tooltip artists, created by _plot only when there is data ─
        self._annotation = None
        self._hover_scatter = None
        self._select_scatter = None

        # (curve index, point index) pinned by a click, and the one under
        # the cursor.  _hovered is the redraw guard: motion that does not
        # change it never touches the canvas.
        self._selected = None
        self._hovered = None

        # Fit view for double-click reset / toolbar Home.  PanZoomInteraction
        # reads None as "no fit view yet" and makes reset a no-op.
        self._fit_xlim = None
        self._fit_ylim = None

        self._interaction = None

        self._setup_window()
        self._create_widgets()
        self._setup_layout()
        # Before _plot: _plot ends by seeding the toolbar Home view
        # through the interaction, so the interaction must already exist.
        self._connect_events()
        self._plot()

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _setup_window(self):
        """Configure dialog title, initial size, and base stylesheet."""
        title = "Sharpness Histogram"
        if self._activity_context:
            title = f"{title}  —  {self._activity_context}"
        self.setWindowTitle(title)
        self.setMinimumSize(680, 460)
        self.resize(780, 520)
        self.setModal(True)
        self.setStyleSheet(
            f"background-color: {AppStyles.Colors.MAIN_BG};"
            f"color: {AppStyles.Colors.TEXT_PRIMARY};"
        )

    def _create_widgets(self):
        """Create the matplotlib figure, canvas, and navigation toolbar."""
        # ── Figure & canvas ──────────────────────────────────────────
        self.figure = Figure(
            facecolor=AppStyles.Colors.MAIN_BG,
            constrained_layout=True,
        )
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self.ax = self.figure.add_subplot(111)
        self._style_axes(self.ax)

        # ── Navigation toolbar ───────────────────────────────────────
        # The shared stylesheet rather than a local copy of it.  Beyond the
        # AppStyles convention, it is the only one that styles the :checked
        # state — and that matters here, because engaging Pan or Zoom
        # changes how this canvas behaves (PanZoomInteraction defers its
        # click and hover handling to the toolbar tool), so the user has to
        # be able to see which tool is armed.
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.toolbar.setStyleSheet(AppStyles.ToolBar.navigation())
        AppStyles.apply_toolbar_icon_color(self.toolbar)

    def _setup_layout(self):
        """Arrange toolbar, canvas, and close button vertically."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
        )
        layout.setSpacing(AppStyles.Dimensions.LAYOUT_VSPACING)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        layout.addLayout(button_row)

    # -----------------------------------------------------------------
    # Interaction
    # -----------------------------------------------------------------

    def _connect_events(self):
        """Wire the shared scroll-zoom / drag-pan / double-click-reset
        interaction, with the click and hover hooks that drive the tooltip.

        Reusing PanZoomInteraction rather than raw mpl_connect calls buys
        deference to an engaged toolbar Pan/Zoom tool, click-vs-drag
        discrimination (``on_click`` fires on release only when no drag
        occurred, so panning never pins a tooltip), the fit-limit zoom
        clamp, and ``install_stale_draw_guard`` on this canvas — which
        this feature makes mandatory: the dialog now redraws on user input
        and is ``deleteLater``'d the instant ``exec()`` returns (see
        docs/review-findings.md F23), exactly the pending-draw-after-
        deletion hazard the guard defuses.

        Binding the interaction to an attribute is load-bearing, not
        stylistic: ``mpl_connect`` stores bound methods as weak references,
        so an unreferenced PanZoomInteraction is collected on the next gc
        pass and all five of its connections silently vanish.

        A view change does not dismiss the tooltip — it is anchored to a
        data point, so it pans and zooms *with* the plot and stays
        correct, and matplotlib hides it automatically once its anchor
        leaves the axes.  It does need re-placing, though, which is what
        the limits callbacks are for.
        """
        self._interaction = PanZoomInteraction(
            self.ax, self.canvas, self.toolbar,
            get_fit_limits=lambda: (self._fit_xlim, self._fit_ylim),
            on_click=self._show_annotation,
            on_hover=self._update_hover,
            on_press_outside=self._hide_annotation,
        )

        # A pinned point can be panned or zoomed into the top-right of the
        # frame, where the tooltip has to flip to stay on screen.  The
        # limits callbacks fire before the redraw, so the new offset lands
        # in the same frame as the new view (a draw_event handler would be
        # one frame late).  They also catch the toolbar's own Pan / Zoom /
        # Home / Back / Forward, which PanZoomInteraction's hooks never see.
        self.ax.callbacks.connect("xlim_changed", self._on_view_changed)
        self.ax.callbacks.connect("ylim_changed", self._on_view_changed)

        # PanZoomInteraction consumes figure_leave_event for its pan
        # failsafe and does not forward it; a fast exit off the canvas
        # delivers no final out-of-axes motion event and would strand the
        # hover marker.  Only the hover marker — a pinned tooltip is meant
        # to survive the cursor leaving, which is the point of clicking.
        self.canvas.mpl_connect("figure_leave_event", self._on_figure_leave)

    # -----------------------------------------------------------------
    # Plotting
    # -----------------------------------------------------------------

    def _plot(self):
        """Render the sharpness curves and WD marker lines, and retain the
        plotted series for the point tooltip."""
        ax = self.ax
        # Filter to well-formed points — raw JSON entries may be missing
        # keys, which would otherwise raise KeyError during extraction.
        data = [
            pt for pt in self._sharpness_data
            if all(k in pt for k in _REQUIRED_KEYS)
        ]

        if not data:
            ax.text(
                0.5, 0.5,
                "No sharpness data available",
                ha="center", va="center",
                transform=ax.transAxes,
                color=AppStyles.Colors.TEXT_PRIMARY,
                fontsize=AppStyles.Dimensions.PLOT_TITLE_FONT_SIZE,
            )
            # Deliberately no tooltip artists: _wd_mm stays empty, so every
            # point handler short-circuits.  The fit view is still captured
            # below, so wheel zoom stays clamped on the placeholder.
            self._finish_plot()
            return

        # ── Extract series (WD: metres → mm) ─────────────────────────
        # Retained on the instance: the hit test then searches exactly the
        # coordinates that were plotted, so it cannot drift from the
        # picture, and it indexes the *filtered* list rather than the raw
        # one (which would report the wrong WD).  _curve_values is
        # parallel to _CURVES.
        self._wd_m = [pt["Wd"] for pt in data]
        self._wd_mm = [wd * _M_TO_MM for wd in self._wd_m]
        self._curve_values = [
            [pt[key] for pt in data] for _, _, key in _CURVES
        ]

        point_style = dict(marker="o", markersize=4, linewidth=AppStyles.Dimensions.PLOT_LINE_WIDTH)

        for (label, color, _), values in zip(_CURVES, self._curve_values):
            ax.plot(self._wd_mm, values, color=color, label=label,
                    **point_style)

        # ── Vertical WD markers ───────────────────────────────────────
        found_wd     = self._found_wd
        optimized_wd = self._optimized_wd

        # Decide whether Found WD and Optimized WD are distinct
        both_present  = found_wd is not None and optimized_wd is not None
        values_differ = (
            both_present
            and abs(found_wd - optimized_wd) > _WD_EQUALITY_TOL
        )

        if values_differ:
            # Draw both lines with their respective colors
            self._draw_wd_marker(found_wd, _COLOR_FOUND_WD, "Found WD")
            self._draw_wd_marker(optimized_wd, _COLOR_OPT_WD, "Optimized WD")
        elif optimized_wd is not None:
            # Identical values (or only OptimizedWd present) — one line suffices
            self._draw_wd_marker(optimized_wd, _COLOR_OPT_WD, "Optimized WD")
        elif found_wd is not None:
            # Only FoundWd available
            self._draw_wd_marker(found_wd, _COLOR_FOUND_WD, "Found WD")

        # ── Labels, title, and legend ─────────────────────────────────
        spine_color = AppStyles.Colors.PLOT_SPINE_COLOR

        ax.set_xlabel("Working Distance (mm)", color=spine_color)
        ax.set_ylabel("Sharpness Score",       color=spine_color)
        ax.set_title(
            "Sharpness Histogram",
            color=spine_color,
            fontsize=AppStyles.Dimensions.PLOT_TITLE_FONT_SIZE
        )
        ax.legend(
            facecolor=AppStyles.Colors.GROUPBOX_BG,
            edgecolor=AppStyles.Colors.PLOT_SPINE_COLOR,
            labelcolor=AppStyles.Colors.TEXT_PRIMARY,
            fontsize=AppStyles.Dimensions.PLOT_ANNOTATION_FONT_SIZE,
        )

        self._create_point_artists()
        self._finish_plot()

    def _draw_wd_marker(self, wd_m: float, color: str, name: str) -> None:
        """Draw one dashed vertical working-distance marker line.

        The line position and its legend label are derived from the same
        millimetre value, so the line can never sit at a WD different from
        the one its own label states.

        :param wd_m: Working distance in metres (as it arrives from the
            ASV execution-history JSON).
        :param color: Marker line color from AppStyles.
        :param name: Legend prefix, e.g. ``"Found WD"``.
        """
        wd_mm = wd_m * _M_TO_MM
        self.ax.axvline(
            x=wd_mm,
            color=color,
            linewidth=AppStyles.Dimensions.PLOT_LINE_WIDTH,
            linestyle="--",
            label=f"{name} ({_format_wd_mm(wd_mm)})",
        )

    def _finish_plot(self) -> None:
        """Request the first draw and capture the fit view.

        ``get_xlim`` settles the pending autoscale without forcing a draw,
        so the fit limits are real ones.  They feed PanZoomInteraction's
        zoom clamp and double-click reset; seeding the toolbar makes its
        Home button reset to the same view, which it otherwise would not
        because the custom wheel and drag handlers never push onto the
        toolbar's view history.  Both run on the no-data path too, so
        wheel zoom over the placeholder stays clamped.
        """
        self.canvas.draw_idle()
        self._fit_xlim = self.ax.get_xlim()
        self._fit_ylim = self.ax.get_ylim()
        self._interaction.seed_toolbar_home()

    # -----------------------------------------------------------------
    # Point tooltip
    # -----------------------------------------------------------------

    def _create_point_artists(self) -> None:
        """Create the hidden tooltip box and the hover / select markers.

        ``set_in_layout(False)`` is load-bearing, not cosmetic: under
        ``constrained_layout`` an in-layout annotation counts toward the
        axes' tight bbox, so a tooltip box overhanging an edge re-fits
        the axes — measured at a 0.92 -> 0.78 collapse in axes width, a
        visible jump that also moves every point out from under the
        hover marker still tracking the cursor.  ``_place_annotation``'s
        edge flip normally keeps the box inside and would mask this, but
        that depends on the flip threshold being right for the box's
        actual size; excluding the box from the layout makes the
        guarantee unconditional.
        """
        offset = AppStyles.Dimensions.PLOT_TOOLTIP_OFFSET_PT
        self._annotation = self.ax.annotate(
            "",
            xy=(0, 0),
            xytext=(offset, offset),
            textcoords="offset points",
            bbox=dict(
                boxstyle="round,pad=0.4",
                fc=AppStyles.Colors.INPUT_BG,
                ec=AppStyles.Colors.PLOT_SPINE_COLOR,
                alpha=0.9,
            ),
            color=AppStyles.Colors.TEXT_PRIMARY,
            fontsize=AppStyles.Dimensions.PLOT_ANNOTATION_FONT_SIZE,
            # Line justification defaults to following horizontalalignment,
            # which the edge flip changes — the same tooltip would read
            # left-justified in the middle of the plot and right-justified
            # at the right edge. Pin it so the numbers always line up.
            multialignment="left",
            visible=False,
            zorder=101,          # above the legend
        )
        self._annotation.set_in_layout(False)

        marker_style = dict(
            s=AppStyles.Dimensions.PLOT_HIGHLIGHT_MARKER_SIZE,
            color=AppStyles.Colors.BUTTON_HOVER,
            visible=False,
        )
        # The select marker sits above the hover marker so a click on the
        # point already under the cursor does not leave the two fighting.
        self._hover_scatter = self.ax.scatter([], [], zorder=5, **marker_style)
        self._select_scatter = self.ax.scatter([], [], zorder=6, **marker_style)

    def _find_point(self, event):
        """Nearest plotted marker to the event, x-column first then curve.

        Display pixels rather than normalized-axes distance, for two
        reasons specific to this plot.  This plot is wide and short, so a
        single normalized threshold reaches noticeably further
        horizontally than vertically; and the three curves share one
        linear y-axis while differing by orders of magnitude, so the lower
        two collapse toward the bottom of the frame and the hit test has
        to separate markers only a few *pixels* apart.  Same convention as
        HistogramGroupBox._hit_test.

        Column first, then curve: WD is what the user is reading, so the
        x snap must hold still under small vertical jitter; only
        deliberate vertical movement switches which curve is picked.

        Non-finite values transform to nan pixels, and every nan
        comparison is False, so they can never match — no explicit
        filtering needed.

        :param event: Matplotlib mouse event.
        :return: ``(curve index, point index)``, or None if nothing is
            within the grab radius.
        """
        if not self._wd_mm or event.x is None or event.y is None:
            return None

        radius = AppStyles.Dimensions.PLOT_HOVER_HIT_RADIUS_PX
        transform = self.ax.transData.transform
        # One batched transform per curve rather than per point.  All three
        # share the same x pixels, so the column search uses the first.
        pixels = [
            transform(list(zip(self._wd_mm, values)))
            for values in self._curve_values
        ]

        point_index = None
        best = float("inf")
        for index, (px, _) in enumerate(pixels[0]):
            distance = abs(event.x - px)
            if distance <= radius and distance < best:
                best = distance
                point_index = index
        if point_index is None:
            return None

        curve_index = None
        best = float("inf")
        for index, curve_pixels in enumerate(pixels):
            distance = abs(event.y - curve_pixels[point_index][1])
            # "<=" on the tie so an exact overlap resolves to the LAST
            # curve in _CURVES — the one matplotlib drew on top, and
            # therefore the one the user can actually see.
            if distance <= radius and distance <= best:
                best = distance
                curve_index = index
        if curve_index is None:
            return None
        return (curve_index, point_index)

    def _show_annotation(self, event) -> None:
        """Pin the tooltip on the clicked point, or clear the selection
        when the click lands on empty space inside the axes.

        :param event: Matplotlib mouse event (from PanZoomInteraction's
            ``on_click`` hook, which fires only on a release that was not
            a drag, so panning never pins a tooltip).
        """
        if self._annotation is None:
            return

        found = self._find_point(event)
        if found is None:
            self._hide_annotation()
            return

        curve_index, point_index = found
        self._selected = found
        wd_mm = self._wd_mm[point_index]
        value = self._curve_values[curve_index][point_index]

        self._annotation.xy = (wd_mm, value)
        self._annotation.set_text(self._tooltip_text(curve_index, point_index))
        self._place_annotation(wd_mm, value)
        self._annotation.set_visible(True)

        self._select_scatter.set_offsets([[wd_mm, value]])
        self._select_scatter.set_visible(True)
        # The hover marker would only sit underneath the select marker.
        self._hover_scatter.set_visible(False)
        self._hovered = None

        self.canvas.draw_idle()

    def _hide_annotation(self) -> None:
        """Clear the pinned tooltip (empty-space click, or a press outside
        the axes).

        Early-returns when nothing is pinned, so wiring it to every
        dismissal path costs nothing on the common path.
        """
        if self._selected is None:
            return
        self._selected = None
        self._annotation.set_visible(False)
        self._select_scatter.set_visible(False)
        self.canvas.draw_idle()

    def _update_hover(self, event) -> None:
        """Move the hover marker onto the nearest point, so the user can
        see the points are clickable.  Never touches the pinned tooltip.

        Redraws only on a transition — a different point, or the marker
        appearing / disappearing.  Motion that stays within the same
        point's grab radius, or crosses empty space with the marker
        already hidden, is a pure no-op: a slow sweep across the plot
        delivers hundreds of motion events and a full draw of this figure
        costs tens of milliseconds.

        :param event: Matplotlib motion event (from PanZoomInteraction's
            ``on_hover`` hook, which already suppressed it if a drag-pan
            or a toolbar tool is in progress).
        """
        if self._hover_scatter is None:
            return

        found = None
        if event.inaxes == self.ax:
            found = self._find_point(event)
        if found == self._hovered:
            return
        self._hovered = found

        if found is None:
            self._hover_scatter.set_visible(False)
        else:
            curve_index, point_index = found
            self._hover_scatter.set_offsets([[
                self._wd_mm[point_index],
                self._curve_values[curve_index][point_index],
            ]])
            self._hover_scatter.set_visible(True)
        self.canvas.draw_idle()

    def _on_figure_leave(self, event) -> None:
        """Hide the hover marker when the cursor leaves the figure.

        The pinned tooltip and its select marker deliberately survive —
        reading a WD against the Execution History tree behind this modal
        dialog means dragging the dialog aside, and the value has to still
        be on screen when the user gets there.
        """
        if self._hover_scatter is None or self._hovered is None:
            return
        self._hovered = None
        self._hover_scatter.set_visible(False)
        self.canvas.draw_idle()

    def _on_view_changed(self, _ax) -> None:
        """Re-flip the pinned tooltip after a pan, zoom, or reset.

        No redraw is requested: whatever changed the limits is already
        drawing, and this runs before that draw.

        :param _ax: The Axes, supplied by matplotlib's limits callback.
        """
        if self._selected is None:
            return
        curve_index, point_index = self._selected
        self._place_annotation(
            self._wd_mm[point_index],
            self._curve_values[curve_index][point_index],
        )

    def _tooltip_text(self, curve_index: int, point_index: int) -> str:
        """Three-line tooltip: the point's WD in millimetres, the same WD
        in raw metres, then the selected curve only.

        Both units, because the two things being compared disagree: this
        plot's axis is in millimetres, while the Execution History tree
        and the image metadata print metres.  The metres line is the raw
        value, so it can be matched against the tree character for
        character; it gets its own line because at full precision it is
        longer than everything else in the box.

        Only the clicked curve appears.  The user is reading one score
        against one working distance, and with the three curves often
        orders of magnitude apart, listing all three would bury the one
        being pointed at.  The curve name is the same string as its legend
        entry, so the tooltip and the legend always agree.

        :param curve_index: Index into ``_CURVES`` / ``_curve_values``.
        :param point_index: Index into ``_wd_mm`` / ``_wd_m``.
        :return: e.g. ``"WD: 4.0219 mm\\n(0.0040219 m)\\nFine (G1): 8.628"``.
        """
        label = _CURVES[curve_index][0]
        value = self._curve_values[curve_index][point_index]
        return (
            f"WD: {_format_wd_mm(self._wd_mm[point_index])}\n"
            f"({_format_wd_m(self._wd_m[point_index])})\n"
            f"{label}: {_format_sharpness(value)}"
        )

    def _place_annotation(self, x: float, y: float) -> None:
        """Offset the tooltip box away from the nearest axes edge.

        The box sits up-and-right of its point by default.  In the top or
        right quarter of the frame that pushes it into the thin
        constrained_layout margin and clips it — exactly at the last point
        of the sweep and at the Coarse curve's peak, two of the points
        most worth reading.  The flip needs the text alignment as well as
        the sign of the offset: with ``ha="left"`` a negative dx merely
        slides the box left, it still grows rightward from there.

        :param x: Point x in data coordinates (millimetres).
        :param y: Point y in data coordinates (sharpness score).
        """
        # transLimits is the data -> axes-fraction transform, so this
        # tracks pan and zoom without needing a renderer.
        x_fraction, y_fraction = self.ax.transLimits.transform((x, y))
        flip_x = x_fraction > _TOOLTIP_FLIP_FRACTION
        flip_y = y_fraction > _TOOLTIP_FLIP_FRACTION
        offset = AppStyles.Dimensions.PLOT_TOOLTIP_OFFSET_PT

        self._annotation.set_horizontalalignment("right" if flip_x else "left")
        self._annotation.set_verticalalignment("top" if flip_y else "bottom")
        self._annotation.set_position((
            -offset if flip_x else offset,
            -offset if flip_y else offset,
        ))

    # -----------------------------------------------------------------
    # Styling
    # -----------------------------------------------------------------

    @staticmethod
    def _style_axes(ax) -> None:
        """Apply dark theme to axes consistent with the rest of the app."""
        ax.set_facecolor(AppStyles.Colors.MAIN_BG)
        spine_color = AppStyles.Colors.PLOT_SPINE_COLOR
        ax.tick_params(colors=spine_color, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(spine_color)