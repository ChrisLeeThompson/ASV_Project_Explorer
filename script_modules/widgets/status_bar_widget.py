"""
Status Bar

This module handles the status bar.
The status bar includes:
- A QLabel to display messages to the user.
- A QProgressBar to show progress during parsing and loading operations.
- A Stop button during parsing/loading that allows the user to cancel the operation.

Message contract: a persistent message (``set_status_bar_message``)
becomes the base message. A timed message overlays it and, when its
timeout expires, the base message is restored — so click feedback shown
during a long operation (e.g. "Parsing in progress; please wait.")
gives way to the operation's own message instead of leaving the bar
blank. Call ``clear_base_message`` when an operation ends so its final
base message cannot resurface after a later timed message expires.
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
        # Last persistent message; restored when a timed message expires.
        self._base_message = ""
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
        """Set the status bar QLabel text and record it as the base
        message that timed messages revert to."""
        # Stop any pending timed-message timeout so a stale timeout
        # cannot blank this persistent message later.
        self._message_timer.stop()
        self._base_message = message
        self.status_bar_label.setText(message)

    @Slot(str, int)
    def set_status_bar_message_timed(self, message: str, timeout: int):
        """Overlay the status bar QLabel with a message that reverts
        to the base message after the timeout."""
        self._message_timer.stop()
        self.status_bar_label.setText(message)
        self._message_timer.start(timeout)

    def clear_base_message(self):
        """Mark the current operation as over: forget the base message.

        A timed message that is still displayed keeps showing and
        expires to the now-empty base; with no timed message active
        the label is blanked immediately.
        """
        self._base_message = ""
        if not self._message_timer.isActive():
            self.status_bar_label.setText("")

    def _clear_status_bar_message(self):
        self.status_bar_label.setText(self._base_message)

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