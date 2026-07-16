"""
Project Parameters Tab

Displays parsed project parameters from the ASV Project.AsvProject file.

Layout (left to right):
- Left sidebar group box:
    - Project name QLabel.
    - QComboBox for selecting the site.
    - QLabel showing site enabled status.
    - QLineEdit for searching/filtering site context metadata.
    - QTreeWidget showing the site-level context data (Slicing,
      Milling, Specimen, Fiducial settings, etc.).
- Right area (horizontally scrollable):
    - Dynamically generated RecipeGroupBox widgets arranged in a
      horizontal row. Each recipe card shows:
        - Recipe name as the group box title.
        - QLabel showing recipe enabled status.
        - QLineEdit for searching/filtering the recipe tree.
        - QTreeWidget showing recipe context, then each activity
          with its schedule and parameters as collapsible branches.

The tab starts in a placeholder state and is populated when
project parameter data is loaded.

Data structure expected by ``populate()``::

    {
        "ProjectName": "ASV Project ...",
        "Sites": [
            {
                "SiteName": "Site Name",
                "IsEnabledForExecution": true,
                "SiteContext": {
                    "Slicing": {"SliceThickness": ...},
                    "Milling": {...},
                    ...
                },
                "Recipes": [
                    {
                        "RecipeName": "SEM Imaging",
                        "RecipeType": "...",
                        "Schedule": {"IsEnabled": true, ...},
                        "RecipeContext": {...},
                        "Activities": [
                            {
                                "ActivityName": "Auto Focus",
                                "ActivityType": "...",
                                "Schedule": {"IsEnabled": true, ...},
                                "Parameters": {...}
                            },
                            ...
                        ]
                    },
                    ...
                ]
            }
        ]
    }
"""
import logging
from PySide6.QtWidgets import (
    QWidget, QGroupBox, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QLineEdit, QCheckBox,
    QTreeWidget, QTreeWidgetItem,
    QHeaderView, QAbstractItemView,
    QScrollArea,
)
from PySide6.QtCore import Qt, Slot
from script_modules.app_styles import AppStyles


logger = logging.getLogger(__name__)


# Placeholder / default text
_PLACEHOLDER_TAB_LABEL = AppStyles.AppText.PROJECT_PARAMETERS_DEFAULT_LABEL
_NO_DATA_LABEL = AppStyles.AppText.PROJECT_PARAMETERS_NO_DATA_LABEL

# Layout constants
_SIDEBAR_MINIMUM_WIDTH = AppStyles.Dimensions.SIDEBAR_MINIMUM_WIDTH
_SIDEBAR_MAXIMUM_WIDTH = AppStyles.Dimensions.SIDEBAR_MAXIMUM_WIDTH
_RECIPE_CARD_FIXED_WIDTH = AppStyles.Dimensions.RECIPE_CARD_FIXED_WIDTH


# =========================================================================
# Recipe Group Box
# =========================================================================

class RecipeGroupBox(QGroupBox):
    """
    A single recipe card displaying recipe context and activities
    in a searchable tree widget.

    Each card has a fixed width and takes full available height,
    designed to sit inside a horizontal scroll area alongside
    sibling recipe cards.
    """

    def __init__(self, recipe_data: dict, parent=None):
        """
        Create and populate a recipe card.

        :param recipe_data: A single recipe dict from the parsed
            project parameters.
        :param parent: Parent widget.
        """
        super().__init__(parent)
        self._recipe_data = recipe_data

        recipe_name = recipe_data.get("RecipeName", "Unknown Recipe")
        self.setTitle(recipe_name)
        self.setFixedWidth(_RECIPE_CARD_FIXED_WIDTH)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._create_widgets()
        self._setup_layout()
        self._connect_signals()
        self._build_tree()

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _create_widgets(self):
        """Create the enabled label, search field, and tree widget."""
        # Enabled / disabled label
        schedule = self._recipe_data.get("Schedule", {})
        is_enabled = schedule.get("IsEnabled", False)
        enabled_text = "Enabled: true" if is_enabled else "Enabled: false"
        self.enabled_label = QLabel(enabled_text)
        self.enabled_label.setStyleSheet(AppStyles.Label.default())

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

        # Tree widget
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", ""])
        self.tree.setColumnCount(2)
        self.tree.setRootIsDecorated(True)
        self.tree.setItemsExpandable(True)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setAlternatingRowColors(False)
        self.tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.tree.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setStyleSheet(AppStyles.TreeWidget.metadata())

        # Header: interactive field column, stretched value column
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive
        )
        header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )

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
        layout.addWidget(self.enabled_label)
        layout.addWidget(self._search_row)
        layout.addWidget(self.tree, 1)  # stretch factor
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
    # Tree Building
    # -----------------------------------------------------------------

    def _build_tree(self):
        """
        Build the tree from recipe data.

        Structure:
        - Recipe Schedule (if has fields beyond IsEnabled)
        - Recipe Context sections (e.g. ImagingContext)
        - Each Activity as a collapsible branch:
            - Schedule fields
            - Parameters
        """
        self.tree.clear()
        self.tree.setUpdatesEnabled(False)

        bold_font = self.tree.font()
        bold_font.setBold(True)

        # --- Recipe-level schedule (beyond IsEnabled) ---
        schedule = self._recipe_data.get("Schedule", {})
        schedule_display = {
            k: v for k, v in schedule.items()
            if k != "IsEnabled"
        }
        if schedule_display:
            schedule_item = QTreeWidgetItem(["Schedule"])
            schedule_item.setFont(0, bold_font)
            self._add_dict_children(schedule_item, schedule_display)
            self.tree.addTopLevelItem(schedule_item)

        # --- Recipe context (e.g. ImagingContext) ---
        recipe_context = self._recipe_data.get("RecipeContext", {})
        if recipe_context:
            context_item = QTreeWidgetItem(["Recipe Context"])
            context_item.setFont(0, bold_font)
            self._add_dict_children(context_item, recipe_context)
            self.tree.addTopLevelItem(context_item)

        # --- Activities ---
        activities = self._recipe_data.get("Activities", [])
        for activity in activities:
            activity_name = activity.get("ActivityName", "Unknown")
            activity_item = QTreeWidgetItem([activity_name])
            activity_item.setFont(0, bold_font)

            # Activity schedule
            act_schedule = activity.get("Schedule", {})
            if act_schedule:
                sched_branch = QTreeWidgetItem(["Schedule"])
                self._add_dict_children(sched_branch, act_schedule)
                activity_item.addChild(sched_branch)

            # Activity parameters
            parameters = activity.get("Parameters", {})
            if parameters:
                params_branch = QTreeWidgetItem(["Parameters"])
                self._add_dict_children(params_branch, parameters)
                activity_item.addChild(params_branch)

            self.tree.addTopLevelItem(activity_item)

        # Respect the Expand All checkbox state
        if self.expand_all_checkbox.isChecked():
            self.tree.expandAll()
        else:
            self.tree.collapseAll()

        self.tree.resizeColumnToContents(0)
        self.tree.resizeColumnToContents(1)
        self.tree.setUpdatesEnabled(True)

        # Center the column divider
        self.tree.header().resizeSection(
            0, self.tree.viewport().width() // 2
        )

    def _add_dict_children(
        self, parent_item: QTreeWidgetItem, data: dict
    ):
        """
        Recursively add dictionary entries as child tree items.

        :param parent_item: The parent QTreeWidgetItem.
        :param data: Dictionary of values to add.
        """
        for key, value in data.items():
            if isinstance(value, dict):
                branch = QTreeWidgetItem([str(key)])
                self._add_dict_children(branch, value)
                parent_item.addChild(branch)
            elif isinstance(value, list):
                branch = QTreeWidgetItem([str(key)])
                for i, item in enumerate(value):
                    child = QTreeWidgetItem([f"[{i}]"])
                    if isinstance(item, dict):
                        self._add_dict_children(child, item)
                    else:
                        child.setText(1, str(item))
                    branch.addChild(child)
                parent_item.addChild(branch)
            else:
                leaf = QTreeWidgetItem([str(key), str(value)])
                parent_item.addChild(leaf)

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
            self.tree.expandAll()
        else:
            self.tree.collapseAll()

    # -----------------------------------------------------------------
    # Search / Filter
    # -----------------------------------------------------------------

    @Slot(str)
    def _on_search_text_changed(self, text: str):
        """
        Filter tree items based on search text.

        :param text: Current search text.
        """
        search = text.strip().lower()

        if not search:
            self._set_all_visible(True)
            # Respect checkbox state when clearing the search
            if self.expand_all_checkbox.isChecked():
                self.tree.expandAll()
            else:
                self.tree.collapseAll()
            return

        for i in range(self.tree.topLevelItemCount()):
            top_item = self.tree.topLevelItem(i)
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
        for i in range(self.tree.topLevelItemCount()):
            self._set_item_visible(
                self.tree.topLevelItem(i), visible
            )

    def _set_item_visible(self, item: QTreeWidgetItem, visible: bool):
        """Recursively set visibility on an item and its children."""
        item.setHidden(not visible)
        for i in range(item.childCount()):
            self._set_item_visible(item.child(i), visible)


# =========================================================================
# Site Context Group Box (Left Sidebar)
# =========================================================================

class SiteContextGroupBox(QGroupBox):
    """
    Left sidebar group box showing project name, site selector,
    enabled status, and a searchable tree of site-level context.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Site Parameters")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumWidth(_SIDEBAR_MINIMUM_WIDTH)
        self.setMaximumWidth(_SIDEBAR_MAXIMUM_WIDTH)
        self._create_widgets()
        self._setup_layout()
        self._connect_signals()

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _create_widgets(self):
        """Create combo box, search field, and tree widget."""
        # Site selector combo box
        self.site_combobox = QComboBox()
        self.site_combobox.setStyleSheet(AppStyles.ComboBox.default())
        self.site_combobox.setPlaceholderText("Select site")

        # Site enabled label
        self.enabled_label = QLabel("")
        self.enabled_label.setStyleSheet(AppStyles.Label.default())
        self.enabled_label.setVisible(False)

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

        # Site context tree widget
        self.context_tree = QTreeWidget()
        self.context_tree.setHeaderLabels(["", ""])
        self.context_tree.setColumnCount(2)
        self.context_tree.setRootIsDecorated(True)
        self.context_tree.setItemsExpandable(True)
        self.context_tree.setExpandsOnDoubleClick(True)
        self.context_tree.setAlternatingRowColors(False)
        self.context_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.context_tree.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.context_tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.context_tree.setStyleSheet(AppStyles.TreeWidget.metadata())

        # Header: interactive field column, stretched value column
        header = self.context_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive
        )
        header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.context_tree.setVisible(False)

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
        layout.addWidget(self.site_combobox)
        layout.addWidget(self.enabled_label)
        layout.addWidget(self._search_row)
        layout.addWidget(self.context_tree, 1)  # stretch factor
        self.setStyleSheet(AppStyles.GroupBox.site_params_with_title())

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

    def populate_site_context(
        self, site_context: dict, is_enabled: bool
    ):
        """
        Populate the tree with site-level context data.

        :param site_context: The SiteContext dict for the selected site.
        :param is_enabled: Whether the site is enabled for execution.
        """
        # Enabled label
        enabled_text = (
            "Enabled: true" if is_enabled else "Enabled: false"
        )
        self.enabled_label.setText(enabled_text)
        self.enabled_label.setVisible(True)

        # Search field
        self.search_line_edit.clear()
        self._search_row.setVisible(True)

        # Build tree
        self.context_tree.setVisible(True)
        self._build_tree(site_context)

        # Center the column divider
        self.context_tree.header().resizeSection(
            0, self.context_tree.viewport().width() // 2
        )
        logger.debug("Site context tree populated.")

    def clear_context(self):
        """Reset the sidebar to its empty state."""
        self.enabled_label.setVisible(False)
        self.search_line_edit.clear()
        self._search_row.setVisible(False)
        self.context_tree.clear()
        self.context_tree.setVisible(False)

    # -----------------------------------------------------------------
    # Tree Building
    # -----------------------------------------------------------------

    def _build_tree(self, site_context: dict):
        """
        Build the tree widget from a site context dictionary.

        Each top-level key (e.g. Slicing, Milling) becomes a
        collapsible branch.

        :param site_context: The SiteContext dict.
        """
        self.context_tree.clear()
        self.context_tree.setUpdatesEnabled(False)

        bold_font = self.context_tree.font()
        bold_font.setBold(True)

        for section_name, section_data in site_context.items():
            section_item = QTreeWidgetItem([str(section_name)])
            section_item.setFont(0, bold_font)
            if isinstance(section_data, dict):
                self._add_dict_children(section_item, section_data)
            else:
                section_item.setText(1, str(section_data))
            self.context_tree.addTopLevelItem(section_item)

        # Respect the Expand All checkbox state
        if self.expand_all_checkbox.isChecked():
            self.context_tree.expandAll()
        else:
            self.context_tree.collapseAll()

        self.context_tree.resizeColumnToContents(0)
        self.context_tree.resizeColumnToContents(1)
        self.context_tree.setUpdatesEnabled(True)

    def _add_dict_children(
        self, parent_item: QTreeWidgetItem, data: dict
    ):
        """
        Recursively add dictionary entries as child tree items.

        :param parent_item: The parent QTreeWidgetItem.
        :param data: Dictionary of values to add.
        """
        for key, value in data.items():
            if isinstance(value, dict):
                branch = QTreeWidgetItem([str(key)])
                self._add_dict_children(branch, value)
                parent_item.addChild(branch)
            elif isinstance(value, list):
                branch = QTreeWidgetItem([str(key)])
                for i, item in enumerate(value):
                    child = QTreeWidgetItem([f"[{i}]"])
                    if isinstance(item, dict):
                        self._add_dict_children(child, item)
                    else:
                        child.setText(1, str(item))
                    branch.addChild(child)
                parent_item.addChild(branch)
            else:
                leaf = QTreeWidgetItem([str(key), str(value)])
                parent_item.addChild(leaf)

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
            self.context_tree.expandAll()
        else:
            self.context_tree.collapseAll()

    # -----------------------------------------------------------------
    # Search / Filter
    # -----------------------------------------------------------------

    @Slot(str)
    def _on_search_text_changed(self, text: str):
        """
        Filter tree items based on search text.

        :param text: Current search text.
        """
        search = text.strip().lower()

        if not search:
            self._set_all_visible(True)
            # Respect checkbox state when clearing the search
            if self.expand_all_checkbox.isChecked():
                self.context_tree.expandAll()
            else:
                self.context_tree.collapseAll()
            return

        for i in range(self.context_tree.topLevelItemCount()):
            top_item = self.context_tree.topLevelItem(i)
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
        for i in range(self.context_tree.topLevelItemCount()):
            self._set_item_visible(
                self.context_tree.topLevelItem(i), visible
            )

    def _set_item_visible(self, item: QTreeWidgetItem, visible: bool):
        """Recursively set visibility on an item and its children."""
        item.setHidden(not visible)
        for i in range(item.childCount()):
            self._set_item_visible(item.child(i), visible)


# =========================================================================
# Project Parameters Tab
# =========================================================================

class ProjectParametersTab(QWidget):
    """
    Tab widget displaying project parameters from the ASV project file.

    Contains a left sidebar (SiteContextGroupBox) and a horizontally
    scrollable area of recipe cards (RecipeGroupBox widgets).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_parameters: dict = {}
        self._recipe_widgets: list[RecipeGroupBox] = []
        self._create_widgets()
        self._setup_layout()
        self._connect_signals()

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _create_widgets(self):
        """Create the startup label and content containers."""
        # ---- Startup container (shown before data is loaded) ----
        self._startup_container = QWidget()
        startup_layout = QVBoxLayout(self._startup_container)
        startup_layout.setContentsMargins(0, 0, 0, 0)
        startup_layout.setSpacing(0)

        self.startup_label = QLabel(_PLACEHOLDER_TAB_LABEL)
        self.startup_label.setStyleSheet(AppStyles.Label.large_label())
        self.startup_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        startup_layout.addStretch(1)
        startup_layout.addWidget(
            self.startup_label,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )
        startup_layout.addStretch(3)

        # ---- No-data container (data loaded but no project params) ----
        self._no_data_container = QWidget()
        no_data_layout = QVBoxLayout(self._no_data_container)
        no_data_layout.setContentsMargins(0, 0, 0, 0)
        no_data_layout.setSpacing(0)

        self.no_data_label = QLabel(_NO_DATA_LABEL)
        self.no_data_label.setStyleSheet(AppStyles.Label.large_label())
        self.no_data_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        no_data_layout.addStretch(1)
        no_data_layout.addWidget(
            self.no_data_label,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )
        no_data_layout.addStretch(3)

        # Start hidden
        self._no_data_container.setVisible(False)

        # ---- Content container (shown after data loads) ----
        self._content_container = QWidget()
        content_layout = QHBoxLayout(self._content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Left sidebar: site context
        self.site_context_groupbox = SiteContextGroupBox(parent=self)

        # Right area: horizontally scrollable recipe cards
        self._recipe_scroll_container = QWidget()
        self._recipe_scroll_layout = QHBoxLayout(
            self._recipe_scroll_container
        )
        self._recipe_scroll_layout.setContentsMargins(0, 4, 0, 4)
        self._recipe_scroll_layout.setSpacing(
            AppStyles.Dimensions.LAYOUT_VSPACING
        )
        self._recipe_scroll_layout.addStretch()

        self._recipe_scroll_area = QScrollArea()
        self._recipe_scroll_area.setWidget(self._recipe_scroll_container)
        self._recipe_scroll_area.setWidgetResizable(True)
        self._recipe_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._recipe_scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._recipe_scroll_area.setStyleSheet(
            AppStyles.ScrollArea.default()
        )

        # Assemble left + right
        content_layout.addWidget(self.site_context_groupbox)
        content_layout.addWidget(self._recipe_scroll_area, 1)

        # Start hidden
        self._content_container.setVisible(False)

    def _setup_layout(self):
        """Place startup and content containers in the main layout."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._startup_container)
        main_layout.addWidget(self._no_data_container)
        main_layout.addWidget(self._content_container)
        self.setStyleSheet(AppStyles.Window.tabs())

    def _connect_signals(self):
        """Connect the site combo box selection signal."""
        self.site_context_groupbox.site_combobox.currentIndexChanged.connect(
            self._on_site_selected
        )

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def populate(self, project_parameters: dict):
        """
        Populate the tab with project parameter data.

        Stores the data, populates the site combo box, and
        auto-selects the first site. If the data has no sites,
        shows the no-data placeholder instead.

        :param project_parameters: The full ProjectParameters dict
            from the parsed project file.
        """
        self._project_parameters = project_parameters

        if not project_parameters or not project_parameters.get("Sites"):
            logger.info("No project parameters to display.")
            self._show_no_data()
            return

        # Transition to full content
        self._show_content()

        # Populate site combo box
        sites = project_parameters.get("Sites", [])
        combo = self.site_context_groupbox.site_combobox
        combo.blockSignals(True)
        combo.clear()
        for site in sites:
            combo.addItem(site.get("SiteName", "Unknown Site"))
        combo.blockSignals(False)

        # Auto-select first site
        if combo.count() > 0:
            combo.setCurrentIndex(0)
            self._on_site_selected(0)

        logger.info(
            f"Project parameters tab populated: {len(sites)} site(s)."
        )

    def clear(self):
        """Reset the tab to its startup state."""
        self._project_parameters = {}
        self._clear_recipe_cards()
        self.site_context_groupbox.site_combobox.clear()
        self.site_context_groupbox.clear_context()
        self._show_startup()

    # -----------------------------------------------------------------
    # State Transitions
    # -----------------------------------------------------------------

    def _show_startup(self):
        """Show the startup placeholder (no data loaded)."""
        self._content_container.setVisible(False)
        self._no_data_container.setVisible(False)
        self._startup_container.setVisible(True)

    def _show_no_data(self):
        """Show the no-data message (data loaded, no project params)."""
        self._startup_container.setVisible(False)
        self._content_container.setVisible(False)
        self._no_data_container.setVisible(True)

    def _show_content(self):
        """Show the full content area (sidebar + recipe cards)."""
        self._startup_container.setVisible(False)
        self._no_data_container.setVisible(False)
        self._content_container.setVisible(True)

    # -----------------------------------------------------------------
    # Site Selection Handler
    # -----------------------------------------------------------------

    @Slot(int)
    def _on_site_selected(self, index: int):
        """
        Handle site combo box selection. Populates the site context
        tree and generates recipe cards for the selected site.

        :param index: Selected site index.
        """
        sites = self._project_parameters.get("Sites", [])
        if index < 0 or index >= len(sites):
            self.site_context_groupbox.clear_context()
            self._clear_recipe_cards()
            return

        site = sites[index]

        # Populate site context tree
        site_context = site.get("SiteContext", {})
        is_enabled = site.get("IsEnabledForExecution", False)
        self.site_context_groupbox.populate_site_context(
            site_context, is_enabled
        )

        # Generate recipe cards
        recipes = site.get("Recipes", [])
        self._build_recipe_cards(recipes)

        logger.debug(
            f"Site selected: {site.get('SiteName', '?')} "
            f"({len(recipes)} recipes)"
        )

    # -----------------------------------------------------------------
    # Recipe Card Management
    # -----------------------------------------------------------------

    def _build_recipe_cards(self, recipes: list[dict]):
        """
        Clear existing recipe cards and create new ones for the
        given list of recipes.

        :param recipes: List of recipe dicts from the selected site.
        """
        self._clear_recipe_cards()

        for recipe_data in recipes:
            card = RecipeGroupBox(recipe_data, parent=self)
            # Insert before the trailing stretch
            self._recipe_scroll_layout.insertWidget(
                self._recipe_scroll_layout.count() - 1, card
            )
            self._recipe_widgets.append(card)

    def _clear_recipe_cards(self):
        """Remove all recipe card widgets from the scroll area."""
        for card in self._recipe_widgets:
            self._recipe_scroll_layout.removeWidget(card)
            card.deleteLater()
        self._recipe_widgets.clear()