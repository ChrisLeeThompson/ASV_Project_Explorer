"""
Pan / Zoom Canvas Interaction

Shared mouse interaction for a matplotlib Axes embedded in Qt:
scroll-wheel zoom centered on the cursor, left-drag panning, and
double-click reset to the owner's fit view.

Used by ASVPlotWidget (metadata plots) and FullResolutionDialog (the
full-resolution image window) so the two behave identically and fixes
land in one place. The owner keeps its own notion of the "fit" view
(plot: original data limits; image: fit-to-image limits) and hands it
in via ``get_fit_limits``; optional hooks carry the plot-only behaviors
(click annotation, hover highlight, annotation hiding).

While a matplotlib toolbar tool (Pan or Zoom) is engaged, the drag /
click / hover handlers defer to the toolbar; scroll-zoom stays active
except during an active toolbar drag (whose gesture would silently
revert or misanchor a mid-drag wheel zoom).
"""
import logging

from PySide6.QtCore import Qt, QTimer

logger = logging.getLogger(__name__)


# Per-notch zoom base: span multiplier for one full wheel notch inward.
# Fractional / multi-notch scroll steps scale exponentially (base ** step),
# so zoom-out (step < 0) is the exact inverse of zoom-in.
_ZOOM_BASE = 0.8

# Zoom span clamp, relative to the owner's fit view: zoom-in stops when
# the span falls below MIN_SPAN_FRACTION of the fit span (~4 data pixels
# on an 8k image; far beyond that, float precision degrades and
# matplotlib silently snaps near-singular limits back out), and zoom-out
# stops at MAX_SPAN_FACTOR times the fit span.
_MIN_SPAN_FRACTION = 5e-4
_MAX_SPAN_FACTOR = 10.0

# Debounce for recording a wheel-zoom burst into the toolbar's view
# history: one push per burst, once no tick has arrived for this long.
_WHEEL_HISTORY_FLUSH_MS = 750


def install_stale_draw_guard(canvas):
    """Defuse matplotlib's zero-delay draw timer for a canvas that Qt
    is about to delete.

    ``FigureCanvasQT.draw_idle`` schedules ``QTimer.singleShot(0,
    self._draw_idle)`` — a fire-and-forget callback that cannot be
    cancelled and is not tied to the canvas's Qt lifetime. If the
    canvas is deleted with a draw pending (e.g. the user wheel-zooms
    and immediately closes a WA_DeleteOnClose dialog), the stale
    callback still fires and calls ``self.height()`` on the freed C++
    widget — a RuntimeError at best, silent heap corruption at worst
    (observed as intermittent 0xC0000374 crashes in the test suite).

    ``_draw_idle`` checks the pure-Python ``_draw_pending`` flag before
    touching any C++ state, so clearing the flag when Qt reports the
    destruction makes the stale callback a harmless no-op. Writing an
    attribute on the Python wrapper is safe after C++ deletion.
    """
    def _cancel_pending_draw(*_args):
        canvas._draw_pending = False

    canvas.destroyed.connect(_cancel_pending_draw)


class PanZoomInteraction:
    """
    Owns the scroll-zoom / drag-pan / double-click-reset handlers for
    one Axes. Connections live for the canvas's lifetime; Qt tears the
    canvas and handlers down together.

    :param ax: The matplotlib Axes to operate on.
    :param canvas: The FigureCanvas the Axes lives on.
    :param toolbar: The NavigationToolbar2QT paired with the canvas
        (or None). Used for the tool-engaged check and Home seeding.
    :param get_fit_limits: Callable returning ``(xlim, ylim)`` for the
        reset view, either of which may be None when no fit view is
        available yet (reset is then a no-op).
    :param on_click: Optional ``callable(event)`` fired on a left-button
        release inside the Axes when no drag occurred (click-to-annotate).
    :param on_hover: Optional ``callable(event)`` fired on mouse move
        while not panning (hover highlight).
    :param on_reset: Optional ``callable()`` fired when the view is
        reset via double-click (hide annotation).
    :param on_press_outside: Optional ``callable()`` fired on a button
        press outside the Axes (hide annotation).
    :param on_interactive_view_change: Optional ``callable()`` fired
        after each wheel tick or drag-pan step changes the limits,
        BEFORE the draw is requested — the owner may swap in a cheaper
        representation for the duration of the gesture (the image
        window's decimated overview).
    """

    def __init__(
        self,
        ax,
        canvas,
        toolbar,
        get_fit_limits,
        on_click=None,
        on_hover=None,
        on_reset=None,
        on_press_outside=None,
        on_interactive_view_change=None,
    ):
        self._ax = ax
        self._canvas = canvas
        self._toolbar = toolbar
        self._get_fit_limits = get_fit_limits
        self._on_click = on_click
        self._on_hover = on_hover
        self._on_reset = on_reset
        self._on_press_outside = on_press_outside
        self._on_interactive_view_change = on_interactive_view_change

        # Drag-pan state
        self._panning = False
        self._pan_start = None
        self._drag_occurred = False

        # True while a toolbar Pan/Zoom *drag* is in progress. Wheel
        # zoom must pause for the drag: toolbar pan recomputes limits
        # from a snapshot frozen at press (a mid-drag wheel zoom is
        # silently reverted on the next pixel of motion), and a wheel
        # zoom mid-rubber-band shifts the data under the pixel-anchored
        # zoom rectangle. Scroll-zoom with a tool merely engaged
        # (button up) stays available.
        self._toolbar_drag_active = False

        # Debounced push of a wheel-zoom burst into the toolbar history,
        # so Back/Forward include wheel-zoomed views (one entry per
        # burst, pushed at gesture end like the toolbar's own tools).
        # Parented to the canvas so Qt stops and deletes it with the
        # canvas — no cross-object destroyed() hookup needed, and no
        # pending timeout can outlive the widgets it would touch.
        self._history_timer = QTimer(canvas)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(_WHEEL_HISTORY_FLUSH_MS)
        self._history_timer.timeout.connect(self.push_history)

        canvas.mpl_connect("scroll_event", self._on_scroll)
        canvas.mpl_connect("button_press_event", self._on_mouse_press)
        canvas.mpl_connect("button_release_event", self._on_mouse_release)
        canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        canvas.mpl_connect("figure_leave_event", self._on_figure_leave)

        # Interactive canvases draw constantly and (for the full-res
        # dialogs) die via WA_DeleteOnClose mid-session, so they are
        # exactly the canvases exposed to matplotlib's stale-draw-timer
        # hazard. Guard them here, the one place both widgets attach.
        install_stale_draw_guard(canvas)

    # -----------------------------------------------------------------
    # State
    # -----------------------------------------------------------------

    @property
    def panning(self) -> bool:
        """True while a left-drag pan is in progress."""
        return self._panning

    def _navigation_tool_active(self) -> bool:
        """Return True when a matplotlib toolbar tool (Pan or Zoom) is
        engaged, so the drag/click/hover handlers defer to it.
        Scroll-zoom stays active regardless."""
        return bool(self._toolbar is not None and self._toolbar.mode)

    # -----------------------------------------------------------------
    # Toolbar Home seeding
    # -----------------------------------------------------------------

    def seed_toolbar_home(self):
        """Make the toolbar Home button reset to the current view.

        The custom scroll-zoom / drag-pan handlers do not touch the
        toolbar's view history, so the owner seeds the fit view after
        each (re)display. Convenience only — double-click reset does
        not depend on it — so a matplotlib version quirk is logged,
        not raised.
        """
        if self._toolbar is None:
            return
        self._history_timer.stop()
        try:
            self._toolbar.update()
            self._toolbar.push_current()
        except Exception:
            logger.debug("Could not seed toolbar Home view.", exc_info=True)

    def push_history(self):
        """Record the current view in the toolbar history (end of a
        wheel burst, drag-pan, or reset) so Back/Forward step through
        the views these gestures produced.

        Skipped when the stack's current entry already holds this Axes'
        live view — repeated resets at the fit view, or a debounced
        wheel push landing after Home/Back restored the same view,
        would otherwise pile up duplicate entries and truncate the
        Forward branch (Back becomes an enabled-but-dead button).
        """
        self._history_timer.stop()
        if self._toolbar is None:
            return
        try:
            if self._current_view_already_recorded():
                return
            self._toolbar.push_current()
        except Exception:
            logger.debug("Could not push toolbar view history.",
                         exc_info=True)

    def _current_view_already_recorded(self) -> bool:
        """True when the nav stack's current entry stores this Axes'
        live view. Reads the toolbar's private stack; any structural
        mismatch reports False so the push simply proceeds."""
        try:
            entries = self._toolbar._nav_stack()
            if entries is None:
                return False
            entry = entries.get(self._ax)
            if entry is None:
                return False
            return entry[0] == self._ax._get_view()
        except Exception:
            return False

    # -----------------------------------------------------------------
    # Zoom (scroll wheel)
    # -----------------------------------------------------------------

    def _on_scroll(self, event):
        """Zoom in/out centered on the cursor position (scroll wheel)."""
        if self._toolbar_drag_active:
            if self._navigation_tool_active():
                return
            # Stale flag: the tool was disengaged before the release
            # reached us. Self-heal so wheel zoom cannot stay dead.
            self._toolbar_drag_active = False
        if event.inaxes != self._ax:
            return
        xdata = event.xdata
        ydata = event.ydata
        if xdata is None or ydata is None:
            return

        # Scale by the scroll distance, not the event count: precision
        # touchpads deliver many fractional steps per gesture and older
        # wheels one integer step per notch. step's sign carries the
        # direction (positive = zoom in).
        step = getattr(event, "step", None)
        if not step:
            step = 1 if event.button == "up" else -1
        zoom_factor = _ZOOM_BASE ** step

        cur_xlim = self._ax.get_xlim()
        cur_ylim = self._ax.get_ylim()
        factor_x, factor_y = self._clamped_factors(
            zoom_factor, cur_xlim, cur_ylim
        )
        if factor_x == 1.0 and factor_y == 1.0:
            return

        new_width = (cur_xlim[1] - cur_xlim[0]) * factor_x
        new_height = (cur_ylim[1] - cur_ylim[0]) * factor_y

        # Keep the cursor's data point fixed on screen (relative-position
        # math is orientation-safe, so imshow's inverted y is preserved)
        rel_x = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
        rel_y = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])
        self._ax.set_xlim(xdata - new_width * (1 - rel_x),
                          xdata + new_width * rel_x)
        self._ax.set_ylim(ydata - new_height * (1 - rel_y),
                          ydata + new_height * rel_y)
        if self._on_interactive_view_change is not None:
            self._on_interactive_view_change()
        self._canvas.draw_idle()
        self._history_timer.start()

    def _clamped_factors(self, requested, cur_xlim, cur_ylim):
        """Per-axis zoom factors, clamped so the resulting span lands
        exactly on the fit-relative bound instead of dropping the event
        (a large coalesced wheel step must still act, and an axis
        already at a bound must not block the other axis). (1.0, 1.0)
        means nothing can move. No-op passthrough when the owner has
        no fit view yet."""
        fit_xlim, fit_ylim = self._get_fit_limits()
        if fit_xlim is None or fit_ylim is None:
            return requested, requested
        return (self._clamp_axis_factor(requested, cur_xlim, fit_xlim),
                self._clamp_axis_factor(requested, cur_ylim, fit_ylim))

    @staticmethod
    def _clamp_axis_factor(requested, cur_lim, fit_lim):
        """Clamp one axis's zoom factor to the min/max span bounds.
        Spans are compared by magnitude so imshow's inverted (negative)
        y span is handled."""
        fit_span = abs(fit_lim[1] - fit_lim[0])
        cur_span = abs(cur_lim[1] - cur_lim[0])
        if not (fit_span > 0 and cur_span > 0):
            return requested
        if requested < 1.0:
            # Zoom in: the span may not fall below the floor. An axis
            # already at/below it holds still (factor 1).
            floor = (fit_span * _MIN_SPAN_FRACTION) / cur_span
            return max(requested, min(floor, 1.0))
        ceiling = (fit_span * _MAX_SPAN_FACTOR) / cur_span
        return min(requested, max(ceiling, 1.0))

    # -----------------------------------------------------------------
    # Pan (left drag) and double-click reset
    # -----------------------------------------------------------------

    def _on_mouse_press(self, event):
        """Start panning, or reset the view on double-click."""
        # A press ends any wheel burst: flush the pending history push
        # now so the burst's result is recorded at the gesture boundary
        # (the debounce firing mid-drag would record a transient view).
        if self._history_timer.isActive():
            self.push_history()
        if self._navigation_tool_active():
            # The toolbar owns this drag; pause wheel zoom until release.
            self._toolbar_drag_active = True
            return
        if event.inaxes != self._ax:
            if self._on_press_outside is not None:
                self._on_press_outside()
            return
        if event.dblclick:
            self.reset_view()
            return
        if event.button == 1:
            self._panning = True
            self._pan_start = (event.xdata, event.ydata)
            self._drag_occurred = False

    def _on_mouse_move(self, event):
        """Pan while the left button is held; otherwise hover."""
        if self._navigation_tool_active():
            return
        if self._panning and self._pan_start is not None:
            if not self._left_button_still_down(event):
                # Failsafe: the release never reached us (grab broken by
                # a popup or window deactivation mid-drag).
                self._end_pan()
                return
            if event.inaxes != self._ax or event.xdata is None:
                return

            dx = event.xdata - self._pan_start[0]
            dy = event.ydata - self._pan_start[1]
            if abs(dx) > 0 or abs(dy) > 0:
                self._drag_occurred = True

            cur_xlim = self._ax.get_xlim()
            cur_ylim = self._ax.get_ylim()
            self._ax.set_xlim(cur_xlim[0] - dx, cur_xlim[1] - dx)
            self._ax.set_ylim(cur_ylim[0] - dy, cur_ylim[1] - dy)
            if self._on_interactive_view_change is not None:
                self._on_interactive_view_change()
            self._canvas.draw_idle()
            return

        if self._on_hover is not None:
            self._on_hover(event)

    def _on_mouse_release(self, event):
        """Stop panning; fire the click hook if no drag occurred."""
        # Always clear the toolbar-drag flag — the tool may have been
        # toggled off mid-drag, and a stuck flag would kill scroll-zoom.
        self._toolbar_drag_active = False
        if self._navigation_tool_active():
            return
        if event.button == 1 and self._panning:
            self._panning = False
            if (self._on_click is not None
                    and not self._drag_occurred
                    and event.inaxes == self._ax):
                self._on_click(event)
            elif self._drag_occurred:
                self.push_history()
            self._pan_start = None

    def _on_figure_leave(self, event):
        """Failsafe: end a pan whose release was lost. During a normal
        drag Qt's implicit grab suppresses leave events, so this only
        fires once the gesture is genuinely over or broken."""
        self._end_pan()

    def _end_pan(self):
        """Reset all drag state — including the toolbar-drag flag, so a
        release lost DURING a toolbar drag cannot leave wheel zoom
        suppressed until the next click."""
        self._panning = False
        self._pan_start = None
        self._toolbar_drag_active = False

    @staticmethod
    def _left_button_still_down(event) -> bool:
        """True unless the Qt-side event positively reports the left
        button is up. Events without a Qt backing (tests, other
        backends) are treated as still-down."""
        gui_event = getattr(event, "guiEvent", None)
        buttons = getattr(gui_event, "buttons", None)
        if buttons is None:
            return True
        try:
            return bool(buttons() & Qt.MouseButton.LeftButton)
        except Exception:
            return True

    def reset_view(self):
        """Reset the axes to the owner's fit view (double-click handler;
        the toolbar Home button does the same via seed_toolbar_home)."""
        fit_xlim, fit_ylim = self._get_fit_limits()
        if fit_xlim is not None and fit_ylim is not None:
            # Flush a pending wheel push first so the zoomed view lands
            # in history and Back can return to it after the reset.
            if self._history_timer.isActive():
                self.push_history()
            self._ax.set_xlim(fit_xlim)
            self._ax.set_ylim(fit_ylim)
            if self._on_reset is not None:
                self._on_reset()
            self._canvas.draw_idle()
            self.push_history()
