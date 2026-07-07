"""
Slice Index Range GroupBox

This module handles the global slice index range selection group box.
The group box includes:
- Spin boxes for the start and end slice indices, with dynamic range
  based on the min/max across all currently displayed plots.
- Cross-constraint: start cannot exceed end, end cannot go below start.
- Update button to apply the new slice range to all displayed plots.
- Update button border highlight when spin box values change (reset on click).
"""
from PySide6.QtWidgets import (
    QGroupBox, QGridLayout, QLabel
)
from PySide6.QtCore import Qt
from script_modules.app_styles import AppStyles
from script_modules.widgets.spinbox_widgets import StartSliceSpinBox, EndSliceSpinBox
from script_modules.widgets.button_widgets import UpdateButton


class SliceIndexRangeGroupBox(QGroupBox):

    def __init__(self, parent=None):
        super().__init__(parent)
        # Set title
        self.setTitle("Global Slice Index Range")
        # Set focus policy
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Create widgets
        self._create_widgets()
        # Setup layout
        self._setup_layout()
        # Connect signals
        self._connect_signals()
    
    def _create_widgets(self):
        # Create widgets
        self.slice_index_start_label = QLabel("Start")
        self.slice_index_end_label = QLabel("End")
        self.start_slice_spinbox = StartSliceSpinBox(parent=self)
        self.end_slice_spinbox = EndSliceSpinBox(parent=self)
        self.update_button = UpdateButton(parent=self)
        self.update_button.setFixedWidth(AppStyles.Dimensions.SPINBOX_WIDTH)
        # Set styles
        self.slice_index_start_label.setStyleSheet(AppStyles.Label.default())
        self.slice_index_end_label.setStyleSheet(AppStyles.Label.default())
    
    def _setup_layout(self):
        main_layout = QGridLayout(self)
        main_layout.addWidget(self.slice_index_start_label, 0, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        main_layout.addWidget(self.start_slice_spinbox, 0, 1, alignment=Qt.AlignmentFlag.AlignRight)
        main_layout.addWidget(self.slice_index_end_label, 1, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        main_layout.addWidget(self.end_slice_spinbox, 1, 1, alignment=Qt.AlignmentFlag.AlignRight)
        main_layout.addWidget(self.update_button, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)
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

    def _connect_signals(self):
        """Connect spin box signals for cross-constraint and button highlight."""
        # Cross-constraint: start cannot exceed end, end cannot go below start
        self.start_slice_spinbox.valueChanged.connect(
            lambda val: self.end_slice_spinbox.setMinimum(val)
        )
        self.end_slice_spinbox.valueChanged.connect(
            lambda val: self.start_slice_spinbox.setMaximum(val)
        )
        # Highlight update button when either spin box value changes
        self.start_slice_spinbox.valueChanged.connect(self._highlight_update_button)
        self.end_slice_spinbox.valueChanged.connect(self._highlight_update_button)
        # Reset button style after click
        self.update_button.clicked.connect(self._reset_update_button)

    def _highlight_update_button(self):
        """Apply a border highlight to indicate pending changes.
        Only highlights when the button is enabled (plots are displayed).
        """
        if self.update_button.isEnabled():
            self.update_button.setStyleSheet(AppStyles.Button.update_highlight())

    def _reset_update_button(self):
        """Reset the update button to its default style."""
        self.update_button.setStyleSheet(AppStyles.Button.default())