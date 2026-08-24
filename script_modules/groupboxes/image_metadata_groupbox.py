"""
Image Metadata GroupBox

Displays all parsed metadata for a selected slice index in the Plots tab.

Layout (top to bottom):
- QLabel for the image file name.
- QLabel for the site, step, and detector context.
- Search row: [QLineEdit (search)] [QCheckBox (Expand All)]
- QTreeWidget with two columns (Field, Value) showing the full
  metadata tree.

The group box starts in a placeholder state ("No slice selected")
and is populated when the user clicks a data point in any plot.
"""
import logging
import math
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
    QLineEdit, QCheckBox, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QAbstractItemView
)
from PySide6.QtCore import Qt, Slot, QTimer
from script_modules.app_styles import AppStyles


logger = logging.getLogger(__name__)


# Placeholder text shown before any slice is selected
_PLACEHOLDER_FILE_NAME = "No slice selected"
_PLACEHOLDER_CONTEXT = ""

# Dot-separated metadata paths whose numeric leaf values are in radians.
# These will be displayed as both radians and degrees in the tree.
_RADIAN_FIELD_PATHS: frozenset[str] = frozenset({
    "ASVXMLMetadata.StageSettings.StagePosition.Rotation",
    "ASVXMLMetadata.StageSettings.StagePosition.Tilt.Alpha",
})


class ImageMetadataGroupBox(QGroupBox):
    """
    Group box that displays image metadata for a selected slice index.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Image Metadata")
        self._create_widgets()
        self._setup_layout()
        self._connect_signals()

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _create_widgets(self):
        """Create labels, search field, expand checkbox, and tree widget."""
        # Set focus policy
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # File name label
        self.file_name_label = QLabel(_PLACEHOLDER_FILE_NAME)
        self.file_name_label.setStyleSheet(AppStyles.Label.default())
        self.file_name_label.setWordWrap(True)

        # Site / step / detector context label
        self.context_label = QLabel(_PLACEHOLDER_CONTEXT)
        self.context_label.setStyleSheet(AppStyles.Label.default())
        self.context_label.setWordWrap(True)

        # Search field
        self.search_line_edit = QLineEdit()
        self.search_line_edit.setPlaceholderText("Search")
        self.search_line_edit.setStyleSheet(AppStyles.LineEdit.search())

        # Expand All checkbox (checked — tree starts expanded)
        self.expand_all_checkbox = QCheckBox("Expand All")
        self.expand_all_checkbox.setStyleSheet(AppStyles.CheckBox.default())
        self.expand_all_checkbox.setChecked(True)

        # Search row container: [search field] [Expand All checkbox]
        self._search_row = QWidget()
        search_row_layout = QHBoxLayout(self._search_row)
        search_row_layout.setContentsMargins(0, 0, 0, 0)
        search_row_layout.setSpacing(4)
        search_row_layout.addWidget(self.search_line_edit, 1)
        search_row_layout.addWidget(self.expand_all_checkbox)
        self._search_row.setVisible(False)

        # Metadata tree widget
        self.metadata_tree = QTreeWidget()
        self.metadata_tree.setHeaderLabels(["", ""])
        self.metadata_tree.setColumnCount(2)
        self.metadata_tree.setRootIsDecorated(True)
        self.metadata_tree.setItemsExpandable(True)
        self.metadata_tree.setExpandsOnDoubleClick(True)
        self.metadata_tree.setAlternatingRowColors(False)
        self.metadata_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.metadata_tree.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.metadata_tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.metadata_tree.setStyleSheet(AppStyles.TreeWidget.metadata())
        # Header: no labels, interactive field column, auto-fit value column
        header = self.metadata_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive
        )
        header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.metadata_tree.setVisible(False)

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
        layout.addWidget(self._search_row)
        layout.addWidget(self.metadata_tree, 1)  # stretch factor
        self.setStyleSheet(AppStyles.GroupBox.with_title())

    def _connect_signals(self):
        """Connect search field and expand checkbox to handlers."""
        self.search_line_edit.textChanged.connect(self._on_search_text_changed)
        self.expand_all_checkbox.toggled.connect(self._on_expand_all_toggled)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def populate(
        self,
        image_name: str,
        site_name: str,
        step_name: str,
        detector: str,
        metadata: dict
    ):
        """
        Populate the group box with metadata for a selected image.

        :param image_name: The image file name.
        :param site_name: The site name.
        :param step_name: The step name.
        :param detector: The detector name.
        :param metadata: The image's Metadata dict (contains
            MicroscopeMetadata, ASVXMLMetadata, etc.).
        """
        self.file_name_label.setText(image_name)
        self.context_label.setText(
            f"{site_name}  •  {step_name}  •  {detector}"
        )
        self._search_row.setVisible(True)
        self.metadata_tree.setVisible(True)
        self._build_tree(metadata)
        # Reapply active search filter after rebuilding the tree
        self._reapply_search_filter()
        logger.debug(f"Metadata populated for: {image_name}")

    def clear_metadata(self):
        """Reset the group box to its placeholder state."""
        self.file_name_label.setText(_PLACEHOLDER_FILE_NAME)
        self.context_label.setText(_PLACEHOLDER_CONTEXT)
        self.search_line_edit.clear()
        self._search_row.setVisible(False)
        self.metadata_tree.clear()
        self.metadata_tree.setVisible(False)

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
    # Tree Building
    # -----------------------------------------------------------------

    def _build_tree(self, metadata: dict):
        """
        Build the tree widget from a nested metadata dictionary.

        Dict values become parent nodes; leaf values (str, int, float,
        list, etc.) become items with the value in the second column.
        Expand/collapse state is controlled by the Expand All checkbox.

        :param metadata: Nested metadata dictionary.
        """
        self.metadata_tree.clear()
        self.metadata_tree.setUpdatesEnabled(False)

        bold_font = self.metadata_tree.font()
        bold_font.setBold(True)

        for key, value in metadata.items():
            top_item = QTreeWidgetItem([str(key)])
            top_item.setFont(0, bold_font)
            self._add_children(top_item, value, path=str(key))
            self.metadata_tree.addTopLevelItem(top_item)

        # Respect the Expand All checkbox state
        if self.expand_all_checkbox.isChecked():
            self.metadata_tree.expandAll()
        else:
            self.metadata_tree.collapseAll()

        self.metadata_tree.resizeColumnToContents(1)
        self.metadata_tree.setUpdatesEnabled(True)
        # Defer the column-divider positioning so Qt has finished the
        # layout pass and viewport().width() returns the real value.
        QTimer.singleShot(0, self._center_column_divider)

    def _center_column_divider(self):
        """Position the column divider at the centre of the visible
        tree area.  Called via a deferred timer so the viewport has
        its final geometry."""
        half_width = self.metadata_tree.viewport().width() // 2
        if half_width > 0:
            self.metadata_tree.setColumnWidth(0, half_width)

    def _add_children(self, parent_item: QTreeWidgetItem, value, path: str = ""):
        """
        Recursively add child items to a parent tree item.

        :param parent_item: The parent QTreeWidgetItem.
        :param value: The value to add — dict, list, or leaf.
        :param path: Dot-separated path to the current node, used to
            identify fields that require unit conversion (e.g. radians).
        """
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                child_path = f"{path}.{child_key}" if path else str(child_key)
                if isinstance(child_value, (dict, list)):
                    # Nested dict or list — create a branch and recurse
                    branch = QTreeWidgetItem([str(child_key)])
                    self._add_children(branch, child_value, child_path)
                    parent_item.addChild(branch)
                else:
                    # Leaf value
                    display_value = self._format_leaf_value(child_path, child_value)
                    leaf = QTreeWidgetItem([str(child_key), display_value])
                    parent_item.addChild(leaf)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                child = QTreeWidgetItem([f"[{i}]"])
                self._add_children(child, item, path)
                parent_item.addChild(child)
        else:
            # Direct leaf value on the parent itself
            parent_item.setText(1, self._format_leaf_value(path, value))

    def _format_leaf_value(self, path: str, value) -> str:
        """
        Format a leaf metadata value for display.

        For fields listed in _RADIAN_FIELD_PATHS, numeric values are
        shown as both radians and degrees: e.g. "0.1745 rad (10.00°)".
        All other values are returned as plain strings.

        :param path: Dot-separated path to the leaf node.
        :param value: The raw metadata value.
        :return: Formatted string for display in the tree.
        """
        if path in _RADIAN_FIELD_PATHS:
            try:
                rad = float(value)
                deg = math.degrees(rad)
                return f"{rad:.4f} rad ({deg:.2f}°)"
            except (TypeError, ValueError):
                pass
        return str(value)

    # -----------------------------------------------------------------
    # Expand All Checkbox
    # -----------------------------------------------------------------

    @Slot(bool)
    def _on_expand_all_toggled(self, checked: bool):
        """
        Expand or collapse all tree items based on checkbox state.

        :param checked: True to expand all, False to collapse all.
        """
        if checked:
            self.metadata_tree.expandAll()
        else:
            self.metadata_tree.collapseAll()

    # -----------------------------------------------------------------
    # Search / Filter
    # -----------------------------------------------------------------

    def _reapply_search_filter(self):
        """
        Reapply the current search text after a tree rebuild.

        Preserves the active filter when stepping between slices.
        """
        search = self.search_line_edit.text().strip().lower()
        if not search:
            return
        for i in range(self.metadata_tree.topLevelItemCount()):
            top_item = self.metadata_tree.topLevelItem(i)
            self._filter_item(top_item, search)

    @Slot(str)
    def _on_search_text_changed(self, text: str):
        """
        Filter tree items based on search text.

        An item is visible if its key or value contains the search text
        (case-insensitive). Parent items remain visible if any descendant
        matches.

        :param text: Current search text.
        """
        search = text.strip().lower()

        if not search:
            # Show everything, respect checkbox state
            self._set_all_visible(True)
            if self.expand_all_checkbox.isChecked():
                self.metadata_tree.expandAll()
            else:
                self.metadata_tree.collapseAll()
            return

        # Walk all top-level items
        for i in range(self.metadata_tree.topLevelItemCount()):
            top_item = self.metadata_tree.topLevelItem(i)
            self._filter_item(top_item, search)

    def _filter_item(self, item: QTreeWidgetItem, search: str) -> bool:
        """
        Recursively filter a tree item and its children.

        :param item: The tree item to evaluate.
        :param search: Lowercase search text.
        :return: True if this item or any descendant matches.
        """
        # Check this item's text (both columns)
        item_matches = (
            search in item.text(0).lower()
            or search in item.text(1).lower()
        )

        # Check children recursively
        child_matches = False
        for i in range(item.childCount()):
            if self._filter_item(item.child(i), search):
                child_matches = True

        visible = item_matches or child_matches
        item.setHidden(not visible)
        return visible

    def _set_all_visible(self, visible: bool):
        """
        Set visibility on all items in the tree.

        :param visible: True to show all, False to hide all.
        """
        for i in range(self.metadata_tree.topLevelItemCount()):
            self._set_item_visible(
                self.metadata_tree.topLevelItem(i), visible
            )

    def _set_item_visible(self, item: QTreeWidgetItem, visible: bool):
        """Recursively set visibility on an item and its children."""
        item.setHidden(not visible)
        for i in range(item.childCount()):
            self._set_item_visible(item.child(i), visible)