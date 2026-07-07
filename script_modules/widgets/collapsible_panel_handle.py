"""
Collapsible Splitter

A ``QSplitter`` subclass with a custom handle that combines
drag-to-resize with click-to-collapse / expand functionality.
The handle renders a directional chevron arrow at its vertical
centre and supports hover highlighting.

Usage::

    splitter = CollapsibleSplitter(parent=self)
    splitter.addWidget(left_panel)
    splitter.addWidget(center)
    splitter.addWidget(right_panel)      # optional third pane
    splitter.set_click_collapsible(2)    # right pane collapses too
    splitter.setStretchFactor(1, 1)

By default the **first** child is click-collapsible (the historical
behaviour); further children can be registered with
``set_click_collapsible``.  Clicking the handle adjacent to a
registered child toggles it; dragging any handle resizes the panes
normally but never collapses them.  ``panel_toggled(index, expanded)``
fires for every registered child; the legacy ``toggled(expanded)``
signal still fires for child 0 only.

Legacy note
-----------
This module previously contained ``CollapsiblePanelHandle``
(a plain ``QWidget``).  That class has been replaced by
``CollapsibleSplitter`` / ``CollapsibleSplitterHandle`` which
provide the same click-to-collapse behaviour *plus* user-driven
resize via standard splitter dragging.
"""
import logging

from PySide6.QtWidgets import QSplitter, QSplitterHandle, QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath

from script_modules.app_styles import AppStyles


logger = logging.getLogger(__name__)


# Dimensions from the central style config
_ARROW_SIZE = AppStyles.Dimensions.SPLITTER_ARROW_SIZE
_PEN_WIDTH = AppStyles.Dimensions.SPLITTER_ARROW_PEN_WIDTH
_BORDER_RADIUS = AppStyles.Dimensions.SPLITTER_HANDLE_BORDER_RADIUS
_VERTICAL_INSET = AppStyles.Dimensions.SPLITTER_HANDLE_VERTICAL_INSET

# Pixel distance before a mouse-press is promoted to a drag.
# Below this threshold the gesture is treated as a click (toggle).
_DRAG_THRESHOLD = 5


# =====================================================================
# Custom Splitter Handle
# =====================================================================


class CollapsibleSplitterHandle(QSplitterHandle):
    """Custom splitter handle that paints a chevron indicator and
    distinguishes *click* (toggle collapse) from *drag* (resize).

    The handle background and arrow colours are taken from
    ``AppStyles.Splitter`` so that every visual property is defined
    in ``app_styles``.
    """

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._hovered = False
        self._pressed = False
        self._press_pos = None
        self._dragged = False

        self.setMouseTracking(True)

        # Colours
        self._color_normal = QColor(AppStyles.Splitter.HANDLE_COLOR)
        self._color_hover = QColor(AppStyles.Splitter.HANDLE_HOVER_COLOR)
        self._color_pressed = QColor(AppStyles.Splitter.HANDLE_PRESSED_COLOR)
        self._color_arrow = QColor(AppStyles.Splitter.ARROW_COLOR)

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    @property
    def _index(self) -> int:
        """This handle's index in the splitter (handle *i* sits between
        children *i-1* and *i*)."""
        splitter = self.splitter()
        if splitter is not None:
            for i in range(1, splitter.count()):
                if splitter.handle(i) is self:
                    return i
        return 1

    def _target_index(self) -> int | None:
        """The click-collapsible child adjacent to this handle, or None.

        The child on the handle's left is preferred, so a middle pane
        flanked by two registered panes is never ambiguous."""
        splitter = self.splitter()
        if not isinstance(splitter, CollapsibleSplitter):
            return None
        i = self._index
        if splitter.is_click_collapsible(i - 1):
            return i - 1
        if splitter.is_click_collapsible(i):
            return i
        return None

    def _chevron_points_right(self) -> bool:
        """Chevron direction for the adjacent target's side and state.

        Left-side target:  ◀ expanded (click collapses leftward),
                           ▶ collapsed (click expands rightward).
        Right-side target: mirrored.
        """
        splitter = self.splitter()
        target = self._target_index()
        if splitter is None or target is None:
            return False
        sizes = splitter.sizes()
        collapsed = target < len(sizes) and sizes[target] == 0
        if target == self._index - 1:  # target on the handle's left
            return collapsed
        return not collapsed

    # -----------------------------------------------------------------
    # Paint
    # -----------------------------------------------------------------

    def paintEvent(self, event):                       # noqa: N802
        """Draw a rounded-rect background and a centred chevron."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Inset the painted area vertically so the handle aligns
        # with the adjacent groupbox (which has top/bottom CSS margins).
        rect = self.rect().adjusted(0, _VERTICAL_INSET, 0, -_VERTICAL_INSET)
        cx = rect.center().x()
        cy = rect.center().y()

        # --- Background ---
        if self._pressed:
            bg = self._color_pressed
        elif self._hovered:
            bg = self._color_hover
        else:
            bg = self._color_normal

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, _BORDER_RADIUS, _BORDER_RADIUS)

        # --- Chevron arrow (centred) ---
        painter.setPen(QPen(self._color_arrow, _PEN_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        path = QPainterPath()
        if self._chevron_points_right():
            # Right-pointing chevron ▶
            path.moveTo(cx - _ARROW_SIZE / 2, cy - _ARROW_SIZE)
            path.lineTo(cx + _ARROW_SIZE / 2, cy)
            path.lineTo(cx - _ARROW_SIZE / 2, cy + _ARROW_SIZE)
        else:
            # Left-pointing chevron ◀
            path.moveTo(cx + _ARROW_SIZE / 2, cy - _ARROW_SIZE)
            path.lineTo(cx - _ARROW_SIZE / 2, cy)
            path.lineTo(cx + _ARROW_SIZE / 2, cy + _ARROW_SIZE)

        painter.drawPath(path)
        painter.end()

    # -----------------------------------------------------------------
    # Mouse events — distinguish click from drag
    # -----------------------------------------------------------------

    def mousePressEvent(self, event):                  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._dragged = False
            self._pressed = True
            self.update()
            # Do NOT call super — that arms the QSplitter's internal
            # drag machinery which fires on the slightest mouse movement.
            # We drive drag ourselves via moveSplitter() once the
            # threshold is crossed.
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):                   # noqa: N802
        if self._press_pos is not None:
            if not self._dragged:
                delta = (
                    event.position().toPoint() - self._press_pos
                ).manhattanLength()
                if delta >= _DRAG_THRESHOLD:
                    self._dragged = True
            if self._dragged:
                # Map mouse x to splitter coordinates and move.
                splitter = self.splitter()
                pos = self.mapToParent(
                    event.position().toPoint()
                ).x()
                splitter.moveSplitter(pos, self._index)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):                # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            was_click = not self._dragged and self._press_pos is not None
            self._pressed = False
            self._press_pos = None
            self._dragged = False
            self.update()

            if was_click:
                splitter = self.splitter()
                target = self._target_index()
                if isinstance(splitter, CollapsibleSplitter) and target is not None:
                    splitter.toggle_panel(target)
            return  # fully handled — skip super
        super().mouseReleaseEvent(event)

    # -----------------------------------------------------------------
    # Hover events
    # -----------------------------------------------------------------

    def enterEvent(self, event):                       # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):                       # noqa: N802
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)


# =====================================================================
# Collapsible Splitter
# =====================================================================


class CollapsibleSplitter(QSplitter):
    """Horizontal ``QSplitter`` whose custom handles support
    click-to-collapse on registered child widgets.

    Child 0 is registered by default (the historical left-panel
    behaviour); additional children — e.g. a right-side panel — are
    registered with :meth:`set_click_collapsible`.  Dragging a handle
    resizes the panes normally but never collapses them — collapse is
    only triggered by a click.  When collapsed, the previous sizes are
    saved per panel and restored on the next click.

    :param parent: Parent widget.
    """

    # Legacy signal: emitted when the FIRST child is toggled.
    toggled = Signal(bool)

    # Emitted when any registered child is toggled; ``True`` = expanded.
    panel_toggled = Signal(int, bool)

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._click_collapsible: set[int] = {0}
        # Only the toggled panel's own width is saved (not the whole
        # sizes list): restoring a full snapshot would resurrect the
        # OTHER registered panel's stale collapsed/expanded state.
        self._saved_widths: dict[int, int] = {}
        self._preferred_sizes: dict[int, int] = {}
        # Tracked expanded state per registered panel. panel_toggled is
        # emitted from _sync_panel_states exactly once per REAL
        # transition, regardless of what caused it — click, API call,
        # or a handle drag pulling a collapsed panel open.
        self._panel_states: dict[int, bool] = {}

        self.setHandleWidth(
            AppStyles.Dimensions.SPLITTER_HANDLE_WIDTH
        )

        # Prevent drag-to-collapse — collapse only via click.
        self.setChildrenCollapsible(False)

        # Handle drags can expand a collapsed panel (0 → min width);
        # detect those transitions too.
        self.splitterMoved.connect(self._sync_panel_states)

    # -----------------------------------------------------------------
    # QSplitter override
    # -----------------------------------------------------------------

    def createHandle(self):                            # noqa: N802
        """Return a ``CollapsibleSplitterHandle`` instead of the
        default ``QSplitterHandle``."""
        return CollapsibleSplitterHandle(self.orientation(), self)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def set_click_collapsible(self, index: int):
        """Register the child at ``index`` as click-collapsible via
        its adjacent handle."""
        self._click_collapsible.add(index)

    def is_click_collapsible(self, index: int) -> bool:
        return index in self._click_collapsible

    def set_preferred_size(self, index: int, width: int):
        """Width used the first time ``index`` is expanded with no
        previously saved sizes (defaults to a third of the total)."""
        self._preferred_sizes[index] = width

    @property
    def expanded(self) -> bool:
        """Whether the left (first) panel is currently visible."""
        return self.is_panel_expanded(0)

    def is_panel_expanded(self, index: int) -> bool:
        sizes = self.sizes()
        return 0 <= index < len(sizes) and sizes[index] > 0

    def toggle_left_panel(self):
        """Toggle the left panel between collapsed and expanded."""
        self.toggle_panel(0)

    def set_expanded(self, expanded: bool):
        """Programmatically expand or collapse the left panel."""
        self.set_panel_expanded(0, expanded)

    def toggle_panel(self, index: int):
        """Toggle the registered panel at ``index``."""
        self._ensure_baseline()
        if self.is_panel_expanded(index):
            self._collapse(index)
        else:
            self._expand(index)

    def set_panel_expanded(self, index: int, expanded: bool):
        """Programmatically expand or collapse the panel at ``index``."""
        self._ensure_baseline()
        if expanded and not self.is_panel_expanded(index):
            self._expand(index)
        elif not expanded and self.is_panel_expanded(index):
            self._collapse(index)

    def initialize_collapsed(self, index: int):
        """Start the panel at ``index`` collapsed, without emitting
        toggle signals or saving sizes (constructor use). ``setSizes``
        alone cannot do this: the child's minimum width clamps a zero
        size unless ``collapsible`` is temporarily enabled."""
        self._ensure_baseline()
        sizes = self.sizes()
        if index >= len(sizes):
            return
        if sizes[index] > 0:
            sizes[self._neighbor_index(index)] += sizes[index]
            sizes[index] = 0
            self._set_sizes_preserving_collapsed(sizes)
        self._panel_states[index] = False  # baseline, no emission
        self._refresh_handles()

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _neighbor_index(self, index: int) -> int:
        """The pane that absorbs / donates space for ``index`` — its
        inward neighbor (toward the stretch pane in the middle)."""
        return index + 1 if index == 0 else index - 1

    def _ensure_baseline(self):
        """Record the current expanded state of registered panels that
        have not been observed yet, without emitting (so the first real
        transition after construction is detected correctly)."""
        for index in self._click_collapsible:
            if index < self.count() and index not in self._panel_states:
                self._panel_states[index] = self.is_panel_expanded(index)

    def _set_sizes_preserving_collapsed(self, sizes: list[int]):
        """``setSizes`` with Qt's min-width clamp disabled for every
        registered panel meant to sit at zero width.

        Without this, requesting 0 for a non-collapsible child is
        silently clamped UP to its minimum width — collapsing one panel
        would pop the other collapsed panel open.
        """
        zero_panels = [
            i for i in self._click_collapsible
            if i < len(sizes) and sizes[i] == 0
        ]
        for i in zero_panels:
            self.setCollapsible(i, True)
        try:
            self.setSizes(sizes)
        finally:
            for i in zero_panels:
                self.setCollapsible(i, False)

    def _collapse(self, index: int):
        """Collapse the panel at ``index`` to zero width, giving its
        space to the inward neighbor. Only this panel's own width is
        saved for the next expand."""
        sizes = self.sizes()
        if index >= len(sizes) or sizes[index] == 0:
            return
        self._saved_widths[index] = sizes[index]
        sizes[self._neighbor_index(index)] += sizes[index]
        sizes[index] = 0
        self._set_sizes_preserving_collapsed(sizes)
        self._sync_panel_states()
        logger.debug(f"Panel {index} collapsed.")

    def _expand(self, index: int):
        """Restore the panel at ``index`` to its previously saved
        width (or its preferred / default width on first expand),
        taking the space from the inward neighbor and leaving all
        other panes untouched.

        The target is requested at its full wanted width (never gated
        on how much the neighbor can spare), so it always leaves the
        zero-width set — Qt's min-width clamp and redistribution then
        honor it even when the splitter is smaller than the sum of the
        panes' minimums.
        """
        sizes = self.sizes()
        if index >= len(sizes) or sizes[index] > 0:
            return
        total = sum(sizes)
        want = self._saved_widths.pop(
            index, self._preferred_sizes.get(index, total // 3)
        )
        neighbor = self._neighbor_index(index)
        sizes[index] = want
        sizes[neighbor] = max(0, sizes[neighbor] - want)
        self._set_sizes_preserving_collapsed(sizes)
        self._sync_panel_states()
        logger.debug(f"Panel {index} expanded.")

    def _sync_panel_states(self, *_args):
        """Detect real expanded-state transitions of registered panels
        — whatever caused them — and emit ``panel_toggled`` once per
        change (plus the legacy ``toggled`` for child 0). Also
        refreshes the handle chevrons."""
        for index in sorted(self._click_collapsible):
            if index >= self.count():
                continue
            expanded = self.is_panel_expanded(index)
            previous = self._panel_states.get(index)
            self._panel_states[index] = expanded
            if previous is None or previous == expanded:
                continue
            self.panel_toggled.emit(index, expanded)
            if index == 0:
                self.toggled.emit(expanded)
        self._refresh_handles()

    def _refresh_handles(self):
        """Repaint all handles so the chevron directions update."""
        for i in range(1, self.count()):
            handle = self.handle(i)
            if handle is not None:
                handle.update()


# =====================================================================
# Legacy CollapsiblePanelHandle (kept for backward compatibility)
# =====================================================================
# The full-resolution image viewer dialog still uses this plain-
# widget toggle strip.  New code should prefer CollapsibleSplitter.

# Legacy handle dimensions
_LEGACY_HANDLE_WIDTH = AppStyles.Dimensions.COLLAPSIBLE_HANDLE_WIDTH
_LEGACY_ARROW_SIZE = AppStyles.Dimensions.COLLAPSIBLE_ARROW_SIZE
_LEGACY_PEN_WIDTH = AppStyles.Dimensions.COLLAPSIBLE_ARROW_PEN_WIDTH


class CollapsiblePanelHandle(QWidget):
    """A thin vertical strip that toggles visibility of a target widget.

    .. deprecated::
        Use :class:`CollapsibleSplitter` for new layouts.  This class
        is retained so that existing consumers (e.g. the full-resolution
        image viewer dialog) continue to work without modification.

    :param target: The widget whose visibility is toggled.
    :param initially_expanded: Whether the target starts visible.
    :param parent: Parent widget.
    """

    toggled = Signal(bool)

    def __init__(
        self,
        target: QWidget | None = None,
        initially_expanded: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._target = target
        self._expanded = initially_expanded
        self._hovered = False

        self.setFixedWidth(_LEGACY_HANDLE_WIDTH)
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Expanding,
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

        self._color_bg = QColor(AppStyles.Colors.MAIN_BG)
        self._color_hover = QColor(AppStyles.Colors.GROUPBOX_BG)
        self._color_arrow = QColor(AppStyles.Colors.TEXT_PRIMARY)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    @property
    def expanded(self) -> bool:
        """Whether the target panel is currently visible."""
        return self._expanded

    def set_target(self, target: QWidget):
        self._target = target

    def set_expanded(self, expanded: bool):
        if expanded != self._expanded:
            self._expanded = expanded
            if self._target is not None:
                self._target.setVisible(self._expanded)
            self.update()
            self.toggled.emit(self._expanded)

    # -----------------------------------------------------------------
    # Events
    # -----------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_expanded(not self._expanded)
        else:
            super().mousePressEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        cx = rect.center().x()
        cy = rect.center().y()

        bg = self._color_hover if self._hovered else self._color_bg
        painter.fillRect(rect, bg)

        painter.setPen(QPen(self._color_arrow, _LEGACY_PEN_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        path = QPainterPath()
        if self._expanded:
            path.moveTo(cx + _LEGACY_ARROW_SIZE / 2, cy - _LEGACY_ARROW_SIZE)
            path.lineTo(cx - _LEGACY_ARROW_SIZE / 2, cy)
            path.lineTo(cx + _LEGACY_ARROW_SIZE / 2, cy + _LEGACY_ARROW_SIZE)
        else:
            path.moveTo(cx - _LEGACY_ARROW_SIZE / 2, cy - _LEGACY_ARROW_SIZE)
            path.lineTo(cx + _LEGACY_ARROW_SIZE / 2, cy)
            path.lineTo(cx - _LEGACY_ARROW_SIZE / 2, cy + _LEGACY_ARROW_SIZE)

        painter.drawPath(path)
        painter.end()