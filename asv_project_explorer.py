"""
ASV Project Explorer
.
This application is designed to help users explore Thermo Scientific Auto Slice And View (ASV) project metadata.
.
The application has two main tabs:
1. ASV Project Metadata: explore project metadata, including plots of metadata, images, and project parameters.
2. Single Image Metadata: view and search metadata from .tif and .png images generated from a Thermo Scientific DualBeam microscope.
.
ASV version 5.11 was used as the basis for the parsing algorithms (projects from older versions may not parse correctly).
AutoScript 4.13 was used to develop the application, and no additional dependencies are required beyond what is included with AutoScript 4.13.
.
The code was written with assistance from Claude AI.
.
If you have any questions or suggestions for improvements, please contact me (Chris Thompson on GitHub: ChrisLeeThompson).
.
Thank you,
Chris Thompson
.
July 1, 2026
.
.
MIT License
.
Copyright 2026 Christopher Thompson
.
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”),
to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
.
The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
.
THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

import logging
import sys
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QMainWindow, QApplication,
    QTabWidget, QMessageBox
)
from PySide6.QtCore import Slot
from PySide6.QtGui import QFont, QIcon, QCloseEvent
from script_modules.app_styles import AppStyles, ICON_PATH
from script_modules.config_manager import ConfigManager
from script_modules.asv_project_metadata_tab import ASVProjectMetadataTab
from script_modules.single_image_metadata_tab import SingleImageMetadataTab
from script_modules.widgets.status_bar_widget import StatusBarWidget


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        # Set window title and size
        self.setWindowTitle(AppStyles.AppText.WINDOW_TITLE)
        # Request the default size, clamped to the current screen's
        # available area (excludes the taskbar), and center the window.
        # The right column scrolls internally, so the content minimum
        # can no longer force the window taller than the screen.
        avail = QApplication.primaryScreen().availableGeometry()
        width = min(
            AppStyles.Dimensions.WINDOW_WIDTH, int(avail.width() * 0.85)
        )
        height = min(
            AppStyles.Dimensions.WINDOW_HEIGHT, int(avail.height() * 0.90)
        )
        x = avail.x() + (avail.width() - width) // 2
        y = avail.y() + (avail.height() - height) // 2
        self.setGeometry(x, y, width, height)
        self.setMinimumSize(1000, 600)
        # Set window icon
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        # Set main window style
        self.setStyleSheet(AppStyles.Window.window())
        # Create configuration file manager. A broken user-edited config
        # would otherwise abort startup with no window and no message
        # (silent under pythonw), so surface the error in a dialog.
        config_path = Path(__file__).parent / "config_files" / "ASVProjectExplorerConfig.json"
        try:
            self.config = ConfigManager(config_path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(
                self,
                "Configuration Error",
                f"Could not load the configuration file:\n{config_path}"
                f"\n\n{exc}"
            )
            raise
        # Create tab widget and set style
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(AppStyles.Window.tabs())
        self.setCentralWidget(self.tab_widget)
        # Initialize status bar
        self._create_status_bar()
        # Initialize tabs
        self._create_tabs()
        # Set main window margins
        self.setContentsMargins(
            AppStyles.Dimensions.MAIN_WINDOW_MARGIN,
            AppStyles.Dimensions.MAIN_WINDOW_MARGIN,
            AppStyles.Dimensions.MAIN_WINDOW_MARGIN,
            AppStyles.Dimensions.MAIN_WINDOW_MARGIN
        )
    
    def _create_tabs(self):
        """Initialize and add tabs to the tab widget."""
        self.asv_project_metadata_tab = ASVProjectMetadataTab(
            config=self.config,
            status_bar=self.status_bar
        )
        self.single_image_metadata_tab = SingleImageMetadataTab(
            status_bar=self.status_bar
        )
        self.tab_widget.addTab(
            self.asv_project_metadata_tab, "ASV Project Metadata"
        )
        self.tab_widget.addTab(
            self.single_image_metadata_tab, "Single Image Metadata"
        )
        # Cross-tab disabling: when either tab is busy, disable the other
        self.asv_project_metadata_tab.parsing_active.connect(
            self._on_processing_active
        )
        self.single_image_metadata_tab.processing_active.connect(
            self._on_processing_active
        )
    
    def _create_status_bar(self):
        """Initialize the status bar."""
        self.status_bar = StatusBarWidget(parent=self)
        self.setStatusBar(self.status_bar)
    
    @Slot(bool)
    def _on_processing_active(self, active: bool):
        """Enable/disable non-active tabs based on processing state.

        When any tab signals that it is busy, all *other* tabs are
        disabled.  When it signals idle, they are re-enabled.
        """
        current = self.tab_widget.currentIndex()
        for i in range(self.tab_widget.count()):
            if i != current:
                self.tab_widget.setTabEnabled(i, not active)
    
    def closeEvent(self, event: QCloseEvent):
        """Clean up worker threads on application exit."""
        self.asv_project_metadata_tab.cleanup()
        self.single_image_metadata_tab.cleanup()
        super().closeEvent(event)


def setup_logging():
    """Configure logging for the application."""
    logging.basicConfig(
        format="%(asctime)s:\t%(levelname)s:\t%(name)s\t%(funcName)s:\t%(message)s", 
        level=logging.INFO,
        force=True
    )
    logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.INFO)


def main():
    """Main function to run the application."""

    setup_logging()

    app=QApplication(sys.argv)
    font = app.font()
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()