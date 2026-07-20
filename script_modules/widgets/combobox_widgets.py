"""
Module for combobox widgets.

Includes:
- CurrentItemDelegate: Popup delegate marking the combo's current item.
- StyledComboBox: Base styled combo box with placeholder text and eliding.
- CheckableComboBox: Multi-select combo box with checkboxes for each item.
- SiteComboBox, StepNameComboBox, DetectorComboBox: Single-select combo boxes.
- PlotTypeComboBox: Multi-select combo box for selecting plot types.
"""
from PySide6.QtWidgets import QComboBox, QStyledItemDelegate, QMenu
from PySide6.QtGui import QStandardItemModel, QStandardItem, QColor
from PySide6.QtCore import Qt, Signal
from script_modules.app_styles import AppStyles


class CurrentItemDelegate(QStyledItemDelegate):
    """
    Draws an accent bar down the current item's row in the popup.

    The popup's row highlight follows the mouse and the arrow keys, so
    it shows which row would be committed — not which one the combo is
    set to. This bar keeps the current setting locatable while the user
    browses a long list, and stays distinct from the highlight (which
    the stylesheet paints as a full-width accent row).

    The bar is painted over the finished row: the stylesheet's ::item
    rules would otherwise cover a background painted underneath. It is
    inset so it sits between the row separators rather than across them,
    and follows the layout direction (leading edge of the text).
    """

    def __init__(self, combo: QComboBox):
        super().__init__(combo)
        self._combo = combo
        self._inset = AppStyles.Dimensions.COMBOBOX_CURRENT_ITEM_BAR_INSET
        self._bar_width = AppStyles.Dimensions.COMBOBOX_CURRENT_ITEM_BAR_WIDTH
        self._bar_color = QColor(AppStyles.Colors.COMBO_CURRENT_ITEM_BG)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.row() != self._combo.currentIndex():
            return
        rect = option.rect
        height = rect.height() - 2 * self._inset
        if height <= 0:
            return
        if option.direction == Qt.LayoutDirection.RightToLeft:
            left = rect.right() - self._inset - self._bar_width + 1
        else:
            left = rect.left() + self._inset
        painter.fillRect(
            left,
            rect.top() + self._inset,
            self._bar_width,
            height,
            self._bar_color,
        )


class StyledComboBox(QComboBox):
    """
    Base single-select combo box with placeholder text.

    Opening the popup highlights the current item; while the user
    browses, an accent bar keeps marking it (see CurrentItemDelegate).
    """

    def __init__(self, parent=None, combobox_text: str = ""):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText(combobox_text)
        self.setCurrentIndex(-1)
        self.setItemDelegate(CurrentItemDelegate(self))
        # Set style
        self.setStyleSheet(AppStyles.ComboBox.default())


class CheckableComboBox(QComboBox):
    """
    A combo box where each item has a checkbox for multi-selection.
    The dropdown stays open while the user clicks checkboxes.
    Checked items are displayed as a comma-separated list in the line edit.
    Right-click the dropdown list to Select All or Deselect All.
    """
    selection_changed = Signal(list)  # Emits list of checked item texts

    def __init__(self, parent=None, combobox_text: str = ""):
        super().__init__(parent)
        self._placeholder_text = combobox_text
        # Setup model
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        # Use a delegate so items render properly with checkboxes
        self.setItemDelegate(QStyledItemDelegate(self))
        # Make editable for placeholder / line edit control, but read-only
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText(combobox_text)
        # Size policy
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(12)
        # Max visible items before scrolling
        self.setMaxVisibleItems(10)
        # Connect model changes to update display
        self._model.itemChanged.connect(self._on_item_changed)
        self.view().clicked.connect(self._toggle_item)
        # Enable right-click context menu on dropdown list
        self.view().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view().customContextMenuRequested.connect(self._show_context_menu)
        # Set style (combines combobox + checkbox indicator styles)
        self.setStyleSheet(AppStyles.ComboBox.checkable())

    def add_checkable_item(self, text: str, checked: bool = False):
        """Add a single checkable item."""
        item = QStandardItem(text)
        item.setCheckable(True)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        # Prevent item from being "selected" in the normal combobox sense
        item.setSelectable(False)
        self._model.appendRow(item)

    def add_checkable_items(self, items: list[str]):
        """Add multiple checkable items, all unchecked."""
        self._model.blockSignals(True)
        for text in items:
            self.add_checkable_item(text)
        self._model.blockSignals(False)
        self.setCurrentIndex(-1)
        self.lineEdit().clear()
        # Items are added unchecked; announce the empty selection so the
        # Display button reflects "no plots selected" after a repopulate.
        self.selection_changed.emit(self.checked_items())

    def checked_items(self) -> list[str]:
        """Return list of checked item texts."""
        checked = []
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                checked.append(item.text())
        return checked

    def set_item_checked(self, index: int, checked: bool):
        """Set the check state of an item by index."""
        item = self._model.item(index)
        if item:
            item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )

    def set_checked_items_by_text(self, texts: list[str]):
        """Check every item whose text appears in the given list.

        Items not in the list keep their current state. Used to restore
        a prior selection after the items have been repopulated.
        """
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if item.text() in texts:
                item.setCheckState(Qt.CheckState.Checked)

    def select_all_checks(self):
        """Check all items and update display."""
        self._model.blockSignals(True)
        for row in range(self._model.rowCount()):
            self._model.item(row).setCheckState(Qt.CheckState.Checked)
        self._model.blockSignals(False)
        # Update display text and emit signal
        checked = self.checked_items()
        total = self._model.rowCount()
        self.lineEdit().setText(f"{len(checked)} of {total} selected")
        self.selection_changed.emit(checked)

    def clear_all_checks(self):
        """Uncheck all items and reset display to placeholder."""
        self._model.blockSignals(True)
        for row in range(self._model.rowCount()):
            self._model.item(row).setCheckState(Qt.CheckState.Unchecked)
        self._model.blockSignals(False)
        self.lineEdit().clear()  # Shows placeholder
        self.selection_changed.emit([])

    def clear_items(self):
        """Remove all items from the model."""
        self._model.clear()
        self.lineEdit().clear()
        # Announce the now-empty selection so listeners (e.g. the Display
        # button enable/disable slot) stay in sync after a clear.
        self.selection_changed.emit(self.checked_items())

    def _on_item_changed(self, item: QStandardItem):
        """Update the line edit text and emit signal when checkboxes change."""
        checked = self.checked_items()
        total = self._model.rowCount()
        if checked:
            self.lineEdit().setText(f"{len(checked)} of {total} selected")
        else:
            self.lineEdit().clear()  # Shows placeholder
        self.selection_changed.emit(checked)
    
    def _toggle_item(self, index):
        """Toggle checkbox when clicking anywhere on the item row."""
        item = self._model.itemFromIndex(index)
        if item and item.isCheckable():
            item.setCheckState(
                Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )

    def _show_context_menu(self, position):
        """Show right-click context menu with Select All / Deselect All."""
        if self._model.rowCount() == 0:
            return
        menu = QMenu(self.view())
        menu.setStyleSheet(AppStyles.ComboBox.context_menu())
        select_all_action = menu.addAction("Select All")
        deselect_all_action = menu.addAction("Deselect All")
        action = menu.exec(self.view().viewport().mapToGlobal(position))
        if action == select_all_action:
            self.select_all_checks()
        elif action == deselect_all_action:
            self.clear_all_checks()

    def hidePopup(self):
        """Override to keep dropdown open while clicking checkboxes."""
        # Only close if the user clicks outside the popup
        if not self.view().underMouse():
            super().hidePopup()


# ---- Single-select combo boxes ----

class SiteComboBox(StyledComboBox):

    def __init__(self, parent=None):
        super().__init__(parent, combobox_text="Select Site")


class StepNameComboBox(StyledComboBox):

    def __init__(self, parent=None):
        super().__init__(parent, combobox_text="Select Step")


class DetectorComboBox(StyledComboBox):

    def __init__(self, parent=None):
        super().__init__(parent, combobox_text="Select Detector")


# ---- Multi-select combo boxes ----

class SelectPlotsComboBox(CheckableComboBox):

    def __init__(self, parent=None):
        super().__init__(parent, combobox_text="Select Plots")