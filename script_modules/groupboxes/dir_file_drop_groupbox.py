"""
Dir/File Drop GroupBox

This module handles the directory / file drop group box.
The group box includes:
- The dir file drop widget, which is a QLabel that supports drag and drop of directories and JSON files.
- The group box is used in the "Plots" tab of the ASV Project Metadata section.
"""
from pathlib import Path
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QSizePolicy
)
from PySide6.QtCore import Qt
from script_modules.app_styles import AppStyles, ASSETS_DIR
from script_modules.widgets.dir_file_drop_widget import DirFileDropLabel


class DirFileDropGroupBox(QGroupBox):

    def __init__(self, validation_files: list[str] = None, parent=None):
        super().__init__(parent)
        self.validation_files: list[str] = validation_files or []
        # Script assets paths
        self._color_path = ASSETS_DIR / "catbug_color_2.png"
        self._grayscale_path = ASSETS_DIR / "catbug_grayscale_2.png"
        # Create widgets
        self._create_widgets()
        # Setup layout
        self._setup_layout()
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )

    def _create_widgets(self):
        self.dir_file_drop_widget = DirFileDropLabel(
            color_path=self._color_path,
            grayscale_path=self._grayscale_path,
            scale_factor=2.0,
            validation_files=self.validation_files,
            parent=self
        )

    def _setup_layout(self):
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.dir_file_drop_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        main_layout.setContentsMargins(
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN
        )
        self.setLayout(main_layout)
        self.setStyleSheet(AppStyles.GroupBox.default())
