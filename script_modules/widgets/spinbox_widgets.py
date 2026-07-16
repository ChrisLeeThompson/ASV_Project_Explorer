"""
Module for spin box components.

Includes:
- StyledSpinBox: Base styled integer spin box.
- StartSliceSpinBox: Spin box for selecting the start slice index.
- EndSliceSpinBox: Spin box for selecting the end slice index.
"""
from PySide6.QtWidgets import QSpinBox
from PySide6.QtCore import Qt
from script_modules.app_styles import AppStyles


class StyledSpinBox(QSpinBox):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(AppStyles.SpinBox.default())
        self.setMinimumWidth(AppStyles.Dimensions.SPINBOX_WIDTH)
        # Store parent reference for focus transfer
        self._parent = parent

    def keyPressEvent(self, event):
        """Handle key press events, transfer focus on Enter or Return."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._parent:
                self._parent.setFocus()
        else:
            super().keyPressEvent(event)

    def update_range(self, min_val: int, max_val: int):
        """Update the spin box range and suffix."""
        self.setMinimum(min_val)
        self.setMaximum(max_val)
        self.setSuffix(f" / {max_val}")


class StartSliceSpinBox(StyledSpinBox):

    def __init__(self, parent=None, min_val: int = 0, max_val: int = 0):
        super().__init__(parent)
        self.setMinimum(min_val)
        self.setMaximum(max_val)
        self.setValue(min_val)
        self.setSuffix(f" / {max_val}")


class EndSliceSpinBox(StyledSpinBox):

    def __init__(self, parent=None, min_val: int = 0, max_val: int = 0):
        super().__init__(parent)
        self.setMinimum(min_val)
        self.setMaximum(max_val)
        self.setValue(max_val)
        self.setSuffix(f" / {max_val}")