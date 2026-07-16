"""
Global Slice Selection GroupBox

This module handles the global slice selection group box. It contains a
single control:

- "Link Slice Selection" checkbox: when checked, selecting a slice in one
  plot is propagated to every other displayed plot, so each plot highlights
  its own point for the same slice index (where that slice is present).

This group box owns only the control and its checked state; the parent tab
reads the state and performs the cross-plot propagation.
"""
from PySide6.QtWidgets import QGroupBox, QGridLayout, QLabel, QCheckBox
from PySide6.QtCore import Qt
from script_modules.app_styles import AppStyles


class GlobalSliceSelectionGroupBox(QGroupBox):

    def __init__(self, parent=None):
        super().__init__(parent)
        # Set title
        self.setTitle("Global Slice Selection")
        # Set focus policy
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Create widgets
        self._create_widgets()
        # Setup layout
        self._setup_layout()

    def _create_widgets(self):
        # Create widgets
        self.link_label = QLabel("Link Slice Selection")
        self.link_checkbox = QCheckBox(parent=self)
        # Set styles
        self.link_label.setStyleSheet(AppStyles.Label.default())
        self.link_checkbox.setStyleSheet(AppStyles.CheckBox.default())

    def _setup_layout(self):
        main_layout = QGridLayout(self)
        main_layout.addWidget(
            self.link_label, 0, 0, alignment=Qt.AlignmentFlag.AlignLeft
        )
        main_layout.addWidget(
            self.link_checkbox, 0, 1, alignment=Qt.AlignmentFlag.AlignRight
        )
        # Set margins
        main_layout.setContentsMargins(
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN
        )
        # Set layout and style
        self.setLayout(main_layout)
        self.setStyleSheet(AppStyles.GroupBox.with_title())