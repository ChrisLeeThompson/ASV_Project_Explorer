"""
Status Bar

This module handles the status bar.
The status bar includes:
- A QLabel to display messages to the user.
- A QProgressBar to show progress during parsing and loading operations.
- A Stop button during parsing/loading that allows the user to cancel the operation.

"""
from PySide6.QtWidgets import (
    QStatusBar, QLabel, QProgressBar,
    QWidget, QSizePolicy
)
from PySide6.QtCore import QTimer, Signal, Slot
from script_modules.app_styles import AppStyles
from script_modules.widgets.button_widgets import CancelButton


class StatusBarWidget(QStatusBar):

    # Signal emitted when the Stop button is clicked.
    cancel_button_clicked_signal: Signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self._clear_status_bar_message)
        # Create widgets
        self._create_widgets()
        # Setup connections
        self._connect_widgets()
        # Setup layout
        self._setup_layout()
        # Set initial state
        self._set_initial_state()

    def _create_widgets(self):
        self.status_bar_label = QLabel()
        self.status_bar_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.progress_bar = QProgressBar()
        self.cancel_button = CancelButton()
        # Set styles
        self.status_bar_label.setStyleSheet(AppStyles.Label.status_bar())
        self.progress_bar.setStyleSheet(AppStyles.ProgressBar.default())

    def _connect_widgets(self):
        self.cancel_button.clicked.connect(self.cancel_button_clicked_signal.emit)

    def _setup_layout(self):
        self.addWidget(self.status_bar_label, 3)
        self.addWidget(self.progress_bar, 2)
        spacer = QWidget()
        spacer.setStyleSheet("background: transparent; border: none;")
        self.addPermanentWidget(spacer, 1)
        self.addPermanentWidget(self.cancel_button)
        self.setStyleSheet(AppStyles.StatusBar.default())

    def _set_initial_state(self):
        self.set_status_bar_message_timed(
            AppStyles.AppText.STATUS_BAR_STARTUP,
            AppStyles.AppText.STATUS_BAR_STARTUP_TIMEOUT_MS,
        )
        self.set_progress_bar_visible(False)
        self.set_cancel_button_visible(False)

    @Slot(str)
    def set_status_bar_message(self, message: str):
        """Set the status bar QLabel text."""
        # Stop any pending timed-message timeout so a stale timeout
        # cannot blank this persistent message later.
        self._message_timer.stop()
        self.status_bar_label.setText(message)

    @Slot(str, int)
    def set_status_bar_message_timed(self, message: str, timeout: int):
        """Set the status bar QLabel text with a timeout."""
        self._message_timer.stop()
        self.status_bar_label.setText(message)
        self._message_timer.start(timeout)

    def _clear_status_bar_message(self):
        self.status_bar_label.setText("")

    @Slot(bool)
    def set_progress_bar_visible(self, visible: bool):
        """Set the progress bar visibility."""
        self.progress_bar.setVisible(visible)

    @Slot(bool)
    def set_cancel_button_visible(self, visible: bool):
        """Set the Cancel button visibility."""
        self.cancel_button.setVisible(visible)

    @Slot(int, int)
    def set_progress_bar_range(self, minimum: int, maximum: int):
        """Set the progress bar range."""
        self.progress_bar.setRange(minimum, maximum)

    @Slot(int)
    def set_progress_bar_value(self, value: int):
        """Set the progress bar value."""
        self.progress_bar.setValue(value)