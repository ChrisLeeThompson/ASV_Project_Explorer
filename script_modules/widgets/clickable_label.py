"""
Clickable Label

A QLabel that reads as normal body text but behaves like the project-title
link: white at rest, accent-blue on hover (with a pointing-hand cursor) and a
darker blue while pressed, emitting ``clicked`` on release. Because it is a
plain QLabel underneath it keeps word-wrap and the standard label margins, so
it is a drop-in replacement for a file-name label with no layout shift.

When made non-clickable (``set_clickable(False)``) it is inert: plain white
text, arrow cursor, and no hover/press/click — used for the placeholder or
unresolved-path state.
"""
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt, Signal

from script_modules.app_styles import AppStyles


class ClickableLabel(QLabel):
    """A hover-highlighting, clickable QLabel styled via AppStyles."""

    clicked = Signal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self._clickable = False
        self._pressed = False
        self._apply_color(AppStyles.Colors.TEXT_PRIMARY)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def set_clickable(self, clickable: bool):
        """Enable or disable the link behaviour.

        When disabled the label shows plain white text with the default
        cursor and ignores mouse interaction.
        """
        self._clickable = clickable
        self._pressed = False
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if clickable
            else Qt.CursorShape.ArrowCursor
        )
        self._apply_color(AppStyles.Colors.TEXT_PRIMARY)

    # -----------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------

    def _apply_color(self, color: str):
        self.setStyleSheet(AppStyles.Label.clickable(color))

    # -----------------------------------------------------------------
    # Events
    # -----------------------------------------------------------------

    def enterEvent(self, event):
        if self._clickable:
            self._apply_color(AppStyles.Colors.BUTTON_HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._clickable:
            self._pressed = False
            self._apply_color(AppStyles.Colors.TEXT_PRIMARY)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._apply_color(AppStyles.Colors.BUTTON_PRESSED)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if (self._clickable and self._pressed
                and event.button() == Qt.MouseButton.LeftButton):
            self._pressed = False
            inside = self.rect().contains(event.position().toPoint())
            # Restore hover colour if released over the label, else rest.
            self._apply_color(
                AppStyles.Colors.BUTTON_HOVER if inside
                else AppStyles.Colors.TEXT_PRIMARY
            )
            if inside:
                self.clicked.emit()
        super().mouseReleaseEvent(event)
