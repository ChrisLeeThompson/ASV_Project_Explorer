"""
Auto-Update GroupBox

This module handles the auto-update group box. It contains:

- "Auto-Update Folder" checkbox: when checked, the parent tab periodically
  scans the loaded ASV project folder for new/changed image files and
  quietly rebuilds the metadata and refreshes the displayed plots.
- Interval spin box: the polling period in seconds.
- Status label: shows the current watch state ("Idle", "Watching...",
  "Updating...", "Updated HH:MM:SS").

This group box owns only the controls and their state; the parent tab
performs the actual folder scanning and refresh.

Control State Management
------------------------
- All controls are disabled until the parent tab enables them (a project
  folder must be loaded and exist on disk).
- The parent tab can programmatically uncheck the checkbox without
  triggering the toggle signal (e.g. when the project folder disappears).
"""
from PySide6.QtWidgets import QGroupBox, QGridLayout, QLabel, QCheckBox
from PySide6.QtCore import Qt, Signal
from script_modules.app_styles import AppStyles
from script_modules.widgets.spinbox_widgets import StyledSpinBox


# Polling interval bounds and default (seconds)
INTERVAL_MIN_SECONDS = 15
INTERVAL_MAX_SECONDS = 3600
INTERVAL_DEFAULT_SECONDS = 60


class AutoUpdateGroupBox(QGroupBox):

    # Emitted when the user toggles the auto-update checkbox.
    auto_update_toggled = Signal(bool)

    # Emitted when the user changes the polling interval (seconds).
    interval_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Set title
        self.setTitle("Auto-Update")
        # Set focus policy
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Create widgets
        self._create_widgets()
        # Setup layout
        self._setup_layout()
        # Connect signals
        self._connect_signals()
        # Disabled until a project folder is loaded
        self.set_controls_enabled(False)

    def _create_widgets(self):
        # Create widgets
        self.enable_label = QLabel("Auto-Update Folder")
        self.enable_checkbox = QCheckBox(parent=self)
        self.interval_label = QLabel("Interval")
        self.interval_spinbox = StyledSpinBox(parent=self)
        self.interval_spinbox.setMinimum(INTERVAL_MIN_SECONDS)
        self.interval_spinbox.setMaximum(INTERVAL_MAX_SECONDS)
        self.interval_spinbox.setValue(INTERVAL_DEFAULT_SECONDS)
        self.interval_spinbox.setSuffix(" s")
        self.status_label = QLabel("Idle")
        # Set styles
        self.enable_label.setStyleSheet(AppStyles.Label.default())
        self.interval_label.setStyleSheet(AppStyles.Label.default())
        self.enable_checkbox.setStyleSheet(AppStyles.CheckBox.default())
        self.status_label.setStyleSheet(AppStyles.Label.default())

    def _setup_layout(self):
        main_layout = QGridLayout(self)
        main_layout.addWidget(
            self.enable_label, 0, 0, alignment=Qt.AlignmentFlag.AlignLeft
        )
        main_layout.addWidget(
            self.enable_checkbox, 0, 1, alignment=Qt.AlignmentFlag.AlignRight
        )
        main_layout.addWidget(
            self.interval_label, 1, 0, alignment=Qt.AlignmentFlag.AlignLeft
        )
        main_layout.addWidget(
            self.interval_spinbox, 1, 1, alignment=Qt.AlignmentFlag.AlignRight
        )
        main_layout.addWidget(
            self.status_label, 2, 0, 1, 2,
            alignment=Qt.AlignmentFlag.AlignLeft
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

    def _connect_signals(self):
        self.enable_checkbox.toggled.connect(self.auto_update_toggled)
        self.interval_spinbox.valueChanged.connect(self.interval_changed)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def set_controls_enabled(self, enabled: bool):
        """Enable or disable the auto-update controls.

        Called by the parent tab when a project folder becomes available
        (enabled) or is removed/deleted (disabled).

        :param enabled: True when a live project folder is loaded.
        """
        self.enable_checkbox.setEnabled(enabled)
        self.interval_spinbox.setEnabled(enabled)

    def set_checked_silent(self, checked: bool):
        """Set the checkbox state without emitting the toggle signal.

        Used by the parent tab to programmatically stop auto-update
        (e.g. when the project folder is deleted or unmounted).

        :param checked: New checkbox state.
        """
        self.enable_checkbox.blockSignals(True)
        self.enable_checkbox.setChecked(checked)
        self.enable_checkbox.blockSignals(False)

    def set_status(self, text: str):
        """Update the status label text.

        :param text: Status text (e.g. "Watching...", "Updated 12:30:05").
        """
        self.status_label.setText(text)

    def is_auto_enabled(self) -> bool:
        """Return True if the auto-update checkbox is checked."""
        return self.enable_checkbox.isChecked()

    def interval_seconds(self) -> int:
        """Return the current polling interval in seconds."""
        return self.interval_spinbox.value()
