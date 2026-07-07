"""
Plot Selection GroupBox

This module handles the plot selection / controls group box.
The group box includes:
- Combo box for selecting the site.
- Combo box for selecting the step (from the selected site).
- Combo box for selecting the detector type (from the selected step).
- Combo box for selecting the plot(s) to generate (from the selected detector type).
- Button to update the plots based on the selected plots.
- Button to clear the selected / displayed plots.
- Button to export the currently displayed plots as PNG and SVG files (along with CSV data).
"""
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QVBoxLayout,
)
from PySide6.QtCore import Qt
from script_modules.app_styles import AppStyles
from script_modules.widgets.combobox_widgets import (
    SiteComboBox, StepNameComboBox, DetectorComboBox, SelectPlotsComboBox
)
from script_modules.widgets.button_widgets import (
    DisplayPlotsButton, ClearButton, ExportPlotsButton
)


class PlotSelectionGroupBox(QGroupBox):

    def __init__(self, plot_fields: list[dict] = None, parent=None):
        super().__init__(parent)
        self.plot_fields: list[dict] = plot_fields or []
        # Self set title
        self.setTitle("Plot Selection")
        # Set focus policy
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Create widgets
        self._create_widgets()
        # Setup layout
        self._setup_layout()
    
    def _create_widgets(self):
        # Combo boxes
        self.site_combobox = SiteComboBox(parent=self)
        self.step_name_combobox = StepNameComboBox(parent=self)
        self.detector_combobox = DetectorComboBox(parent=self)
        self.select_plots_combobox = SelectPlotsComboBox(parent=self)
        # Buttons
        self.display_plots_button = DisplayPlotsButton(parent=self)
        self.clear_plots_button = ClearButton(parent=self)
        self.export_plots_button = ExportPlotsButton(parent=self)
    
    def _setup_layout(self):
        # Layouts
        main_layout = QVBoxLayout(self)
        update_clear_button_layout = QHBoxLayout()
        # Add widgets to layouts
        main_layout.addWidget(self.site_combobox)
        main_layout.addWidget(self.step_name_combobox)
        main_layout.addWidget(self.detector_combobox)
        main_layout.addWidget(self.select_plots_combobox)
        update_clear_button_layout.addWidget(self.display_plots_button)
        update_clear_button_layout.addWidget(self.clear_plots_button)
        main_layout.addLayout(update_clear_button_layout)
        main_layout.addWidget(self.export_plots_button)
        # Set layout margins and spacing
        main_layout.setContentsMargins(
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN
        )
        main_layout.setSpacing(AppStyles.Dimensions.LAYOUT_VSPACING)
        # Set layout and group box style
        self.setLayout(main_layout)
        self.setStyleSheet(AppStyles.GroupBox.with_title())