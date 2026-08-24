"""
Execution History Group Box

Displays parsed execution history for a selected slice.
The data is parsed from the ASV ExecutionHistory.json file.

Layout (top to bottom):
- QLabel for the file name of the selected image/slice.
- QLabel for the site, step, and detector context.
- Search row: [QLineEdit (search)] [QCheckBox (Expand All)]
- QTreeWidget with two columns (Activity/Field, Value) showing:
    - Activities listed in execution order (sorted by ExecutionOrder).
    - Each activity shows child rows for status, calculated duration,
      recipe, timestamps, and activity-specific result data
      (e.g. working distance values, fiducial match scores).

The group box starts in a placeholder state ("No slice selected")
and is populated when the user clicks a data point in any plot.
"""
import logging
from datetime import datetime
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
    QLineEdit, QCheckBox, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QAbstractItemView, QPushButton,
)
from PySide6.QtCore import Qt, Slot
from script_modules.app_styles import AppStyles


logger = logging.getLogger(__name__)


# Placeholder text shown before any slice is selected
_PLACEHOLDER_FILE_NAME = "No slice selected"
_PLACEHOLDER_CONTEXT = ""


class ExecutionHistoryGroupBox(QGroupBox):
    """Group box that displays execution history for a selected slice."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Slice Execution History")
        self._create_widgets()
        self._setup_layout()
        self._connect_signals()

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _create_widgets(self):
        """Create labels and tree widget."""
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

        # Search field (hidden until execution history is populated)
        self.search_line_edit = QLineEdit()
        self.search_line_edit.setPlaceholderText("Search")
        self.search_line_edit.setStyleSheet(AppStyles.LineEdit.search())

        # Expand All checkbox (unchecked — tree starts collapsed)
        self.expand_all_checkbox = QCheckBox("Expand All")
        self.expand_all_checkbox.setStyleSheet(AppStyles.CheckBox.default())
        self.expand_all_checkbox.setChecked(False)

        # Search row container: [search field] [Expand All checkbox]
        self._search_row = QWidget()
        search_row_layout = QHBoxLayout(self._search_row)
        search_row_layout.setContentsMargins(0, 0, 0, 0)
        search_row_layout.setSpacing(4)
        search_row_layout.addWidget(self.search_line_edit, 1)
        search_row_layout.addWidget(self.expand_all_checkbox)
        self._search_row.setVisible(False)

        # Execution history tree widget
        self.history_tree = QTreeWidget()
        self.history_tree.setHeaderLabels(["", ""])
        self.history_tree.setColumnCount(2)
        self.history_tree.setRootIsDecorated(True)
        self.history_tree.setItemsExpandable(True)
        self.history_tree.setExpandsOnDoubleClick(True)
        self.history_tree.setAlternatingRowColors(False)
        self.history_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.history_tree.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.history_tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.history_tree.setStyleSheet(AppStyles.TreeWidget.metadata())

        # Header: interactive field column, auto-fit value column
        header = self.history_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive
        )
        header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.history_tree.setVisible(False)

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
        layout.addWidget(self.history_tree, 1)  # stretch factor
        self.setStyleSheet(AppStyles.GroupBox.with_title())

    def _connect_signals(self):
        """Connect search field and expand checkbox to handlers."""
        self.search_line_edit.textChanged.connect(
            self._on_search_text_changed
        )
        self.expand_all_checkbox.toggled.connect(
            self._on_expand_all_toggled
        )

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def populate(
        self,
        image_name: str,
        site_name: str,
        step_name: str,
        detector: str,
        execution_history: dict,
    ):
        """
        Populate the group box with execution history for a selected image.

        :param image_name: The image file name.
        :param site_name: The site name.
        :param step_name: The step name.
        :param detector: The detector name.
        :param execution_history: The image's ExecutionHistory dict.
            Expected structure (keyed by recipe name)::

                {
                    "SEM Imaging": {
                        "Auto Focus": {
                            "ExecutionOrder": 5,
                            "StartedAt": "...",
                            "FinishedAt": "...",
                            "CalculatedDuration": "13.0s",
                            "Status": "Finished",
                            "Message": "",
                            "Data": {
                                "OriginalWd": 0.00410,
                                "FoundWd": 0.00408,
                                ...
                            }
                        },
                        ...
                    },
                    "Milling": {
                        "Slicing": { ... }
                    }
                }
        """
        self.file_name_label.setText(image_name)
        self.context_label.setText(
            f"{site_name}  •  {step_name}  •  {detector}"
        )
        self.history_tree.setVisible(True)
        self._search_row.setVisible(True)
        self._build_tree(execution_history)
        # Reapply active search filter after rebuilding the tree
        self._reapply_search_filter()
        logger.debug(f"Execution history populated for: {image_name}")

    def clear_history(self):
        """Reset the group box to its placeholder state."""
        self.file_name_label.setText(_PLACEHOLDER_FILE_NAME)
        self.context_label.setText(_PLACEHOLDER_CONTEXT)
        self.search_line_edit.clear()
        self._search_row.setVisible(False)
        self.history_tree.clear()
        self.history_tree.setVisible(False)

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

    def _build_tree(self, execution_history: dict):
        """
        Build the tree widget from an execution history dictionary.

        Flattens all activities across recipes, sorts by ExecutionOrder,
        and displays each activity with child rows for status, duration,
        recipe, timestamps, and activity-specific result data.

        :param execution_history: ExecutionHistory dict keyed by
            recipe name, with activity dicts as values.
        """
        self.history_tree.clear()

        if not execution_history:
            placeholder = QTreeWidgetItem(["No execution history available"])
            self.history_tree.addTopLevelItem(placeholder)
            return

        self.history_tree.setUpdatesEnabled(False)

        # Flatten all activities across recipes into a sortable list
        activities = self._flatten_activities(execution_history)

        # Sort by ExecutionOrder (pre-computed by the parser)
        activities.sort(key=lambda a: a.get("ExecutionOrder", 0))

        # Deferred list of (item, column, widget) tuples that require
        # setItemWidget — must be applied after addTopLevelItem so that
        # the item is already in the tree when the call is made.
        self._pending_item_widgets: list[tuple] = []

        # Build tree items
        for activity in activities:
            activity_name = activity.get("ActivityName", "Unknown")
            recipe_name = activity.get("_recipe_name", "")
            order = activity.get("ExecutionOrder", "")
            status = activity.get("Status", "")
            message = activity.get("Message", "")
            duration = activity.get("CalculatedDuration", "")
            started_at = activity.get("StartedAt", "")
            finished_at = activity.get("FinishedAt", "")
            data = activity.get("Data", {})

            # Top-level item: "1  Slicing"
            activity_item = QTreeWidgetItem([f"{order}  {activity_name}"])

            # Bold the activity name for visual distinction
            font = activity_item.font(0)
            font.setBold(True)
            activity_item.setFont(0, font)

            # Child: Status
            if status:
                activity_item.addChild(
                    QTreeWidgetItem(["Status", status])
                )

            # Child: Calculated duration
            if duration:
                activity_item.addChild(
                    QTreeWidgetItem(["CalculatedDuration", duration])
                )

            # Child: Recipe name
            if recipe_name:
                activity_item.addChild(
                    QTreeWidgetItem(["Recipe", recipe_name])
                )

            # Child: Error message (only shown when present)
            if message:
                activity_item.addChild(
                    QTreeWidgetItem(["Message", message])
                )

            # Child: Timestamps
            if started_at:
                display_time = self._format_timestamp(started_at)
                activity_item.addChild(
                    QTreeWidgetItem(["Started At", display_time])
                )
            if finished_at:
                display_time = self._format_timestamp(finished_at)
                activity_item.addChild(
                    QTreeWidgetItem(["Finished At", display_time])
                )

            # Children: Activity-specific result data
            if isinstance(data, dict):
                self._add_data_children(activity_item, data)

            self.history_tree.addTopLevelItem(activity_item)

        # Apply deferred setItemWidget calls now that all items are in the tree
        for item, col, widget in self._pending_item_widgets:
            self.history_tree.setItemWidget(item, col, widget)
        self._pending_item_widgets.clear()

        # Respect the Expand All checkbox state
        if self.expand_all_checkbox.isChecked():
            self.history_tree.expandAll()
        else:
            self.history_tree.collapseAll()

        self.history_tree.resizeColumnToContents(0)
        self.history_tree.resizeColumnToContents(1)
        self.history_tree.setUpdatesEnabled(True)

    def _flatten_activities(self, execution_history: dict) -> list[dict]:
        """
        Flatten the recipe-keyed execution history into a list of
        activity dicts, each annotated with its recipe name.

        :param execution_history: ExecutionHistory dict keyed by
            recipe name.
        :return: List of activity dicts with ``_recipe_name`` added.
        """
        activities = []
        for recipe_name, recipe_activities in execution_history.items():
            if not isinstance(recipe_activities, dict):
                continue
            for activity_name, activity_data in recipe_activities.items():
                if not isinstance(activity_data, dict):
                    continue
                entry = dict(activity_data)
                entry["ActivityName"] = activity_name
                entry["_recipe_name"] = recipe_name
                activities.append(entry)
        return activities

    def _add_data_children(
        self, parent_item: QTreeWidgetItem, data: dict
    ):
        """
        Add activity-specific result data as child tree items.

        Handles nested dicts by creating branch nodes. Skips
        ``$type`` fields from the raw JSON.

        :param parent_item: The parent activity QTreeWidgetItem.
        :param data: The activity's result Data dict.
        """
        for key, value in data.items():
            # Skip .NET type annotations
            if key == "$type":
                continue

            # SharpnessData: replace the raw list with a button that opens
            # the AutofocusSharpnessDialog.  The sibling WD fields are
            # read from the same data dict.
            if key == "SharpnessData" and isinstance(value, list) and value:
                found_wd     = data.get("FoundWd")
                optimized_wd = data.get("OptimizedWd")
                sharpness_item = QTreeWidgetItem(["Sharpness Results"])
                btn = QPushButton("Show Results")
                btn.setStyleSheet(AppStyles.Button.default())
                btn.clicked.connect(
                    lambda checked=False,
                           sd=value,
                           fwd=found_wd,
                           owd=optimized_wd: self._open_sharpness_dialog(sd, fwd, owd)
                )
                parent_item.addChild(sharpness_item)
                # Defer setItemWidget — item must be in the tree first
                self._pending_item_widgets.append((sharpness_item, 1, btn))
                continue

            if isinstance(value, dict):
                branch = QTreeWidgetItem([str(key)])
                self._add_data_children(branch, value)
                parent_item.addChild(branch)
            elif isinstance(value, list):
                branch = QTreeWidgetItem([str(key)])
                for i, item in enumerate(value):
                    child = QTreeWidgetItem([f"[{i}]"])
                    if isinstance(item, dict):
                        self._add_data_children(child, item)
                    else:
                        child.setText(1, str(item))
                    branch.addChild(child)
                parent_item.addChild(branch)
            else:
                leaf = QTreeWidgetItem([str(key), str(value)])
                parent_item.addChild(leaf)

    # -----------------------------------------------------------------
    # Sharpness Dialog
    # -----------------------------------------------------------------

    def _open_sharpness_dialog(
        self,
        sharpness_data: list[dict],
        found_wd: float | None,
        optimized_wd: float | None,
    ) -> None:
        """
        Open the AutofocusSharpnessDialog for the given sharpness data.

        Imported locally to keep the module load lightweight and avoid
        any potential circular-import issues.

        :param sharpness_data: List of sharpness point dicts from the parser.
        :param found_wd: Found working distance in metres, or ``None``.
        :param optimized_wd: Optimized working distance in metres, or ``None``.
        """
        from script_modules.autofocus_sharpness_dialog import (
            AutofocusSharpnessDialog,
        )
        dlg = AutofocusSharpnessDialog(
            sharpness_data=sharpness_data,
            found_wd=found_wd,
            optimized_wd=optimized_wd,
            parent=self,
        )
        dlg.exec()
        # Modal close only hides the dialog; schedule deletion so the
        # dialog and its matplotlib Figure are released.
        dlg.deleteLater()

    # -----------------------------------------------------------------
    # Formatting Helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _format_timestamp(timestamp: str) -> str:
        """
        Format an ISO timestamp for display.

        Converts to "HH:MM:SS" format for brevity in the tree.
        Returns the raw string if parsing fails.

        :param timestamp: ISO format timestamp string.
        :return: Formatted time string.
        """
        if not timestamp:
            return ""
        try:
            dt = datetime.fromisoformat(timestamp)
            return dt.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            return timestamp

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
            self.history_tree.expandAll()
        else:
            self.history_tree.collapseAll()

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
        for i in range(self.history_tree.topLevelItemCount()):
            top_item = self.history_tree.topLevelItem(i)
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
            self._set_all_visible(True)
            # Respect checkbox state when clearing the search
            if self.expand_all_checkbox.isChecked():
                self.history_tree.expandAll()
            else:
                self.history_tree.collapseAll()
            return

        for i in range(self.history_tree.topLevelItemCount()):
            top_item = self.history_tree.topLevelItem(i)
            self._filter_item(top_item, search)

    def _filter_item(self, item: QTreeWidgetItem, search: str) -> bool:
        """
        Recursively filter a tree item and its children.

        :param item: The tree item to evaluate.
        :param search: Lowercase search text.
        :return: True if this item or any descendant matches.
        """
        item_matches = (
            search in item.text(0).lower()
            or search in item.text(1).lower()
        )

        child_matches = False
        for i in range(item.childCount()):
            if self._filter_item(item.child(i), search):
                child_matches = True

        visible = item_matches or child_matches
        item.setHidden(not visible)
        return visible

    def _set_all_visible(self, visible: bool):
        """Set visibility on all items in the tree."""
        for i in range(self.history_tree.topLevelItemCount()):
            self._set_item_visible(
                self.history_tree.topLevelItem(i), visible
            )

    def _set_item_visible(self, item: QTreeWidgetItem, visible: bool):
        """Recursively set visibility on an item and its children."""
        item.setHidden(not visible)
        for i in range(item.childCount()):
            self._set_item_visible(item.child(i), visible)