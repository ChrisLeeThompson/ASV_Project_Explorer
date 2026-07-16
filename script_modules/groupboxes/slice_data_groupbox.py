"""
Slice Data GroupBox

Composite group box that combines the ImageViewerGroupBox,
ExecutionHistoryGroupBox, and ImageMetadataGroupBox into a single
scrollable panel with shared file name and context labels at the top.

Layout::

    SliceDataGroupBox (QGroupBox, titled "Slice Data")
    ├── file_name_label          (selected image file name)
    ├── context_label            (site • step • detector)
    └── QScrollArea
        └── container QWidget
            ├── ImageViewerGroupBox      (untitled, embedded style)
            ├── ExecutionHistoryGroupBox  (titled, embedded style)
            └── ImageMetadataGroupBox    (titled, embedded style)

The individual child group boxes have their own file name and context
labels hidden to avoid redundancy.  The parent group box manages the
shared labels and delegates populate/clear calls to each child.

The group box starts in a placeholder state ("No slice selected")
and is populated when the user clicks a data point in any plot.
"""
import logging
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QWidget,
    QLabel, QScrollArea,
)
from PySide6.QtCore import Qt, Signal
from script_modules.app_styles import AppStyles
from script_modules.widgets.clickable_label import ClickableLabel
from script_modules.groupboxes.image_viewer_groupbox import ImageViewerGroupBox
from script_modules.groupboxes.execution_history_groupbox import ExecutionHistoryGroupBox
from script_modules.groupboxes.image_metadata_groupbox import ImageMetadataGroupBox


logger = logging.getLogger(__name__)


# Placeholder text shown before any slice is selected
_PLACEHOLDER_FILE_NAME = AppStyles.AppText.SLICE_DATA_GROUPBOX_DEFAULT_LABEL
_PLACEHOLDER_CONTEXT = ""


class SliceDataGroupBox(QGroupBox):
    """
    Composite group box that embeds the image viewer, execution
    history, and image metadata panels inside a single scrollable
    container with shared context labels.
    """

    # Emitted with the absolute image path when the file-name link is clicked.
    image_link_activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Slice Data")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumWidth(AppStyles.Dimensions.SLICE_DATA_MINIMUM_WIDTH)
        # Absolute path of the currently shown image (drives the file-name
        # link); empty when no slice is selected or the path is unresolved.
        self._current_image_path = ""
        self._create_widgets()
        self._setup_layout()

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _create_widgets(self):
        """Create shared labels and embedded child group boxes."""
        # Shared file name label — a "reveal in folder" link when an image
        # path is available (see set_slice_info): normal text that turns blue
        # on hover, like the project-title link.
        self.file_name_label = ClickableLabel(_PLACEHOLDER_FILE_NAME)
        self.file_name_label.clicked.connect(self._on_file_name_clicked)

        # Shared site / step / detector context label
        self.context_label = QLabel(_PLACEHOLDER_CONTEXT)
        self.context_label.setStyleSheet(AppStyles.Label.default())
        self.context_label.setWordWrap(True)

        # --- Image Viewer (untitled — the image is self-describing) ---
        self.image_viewer_groupbox = ImageViewerGroupBox(parent=self)
        self.image_viewer_groupbox.setTitle("")
        self.image_viewer_groupbox.set_visibility_of_file_name(False)
        self.image_viewer_groupbox.set_visibility_of_context(False)
        self.image_viewer_groupbox.setStyleSheet(
            AppStyles.GroupBox.embedded_untitled()
        )

        # --- Execution History (titled section header) ---
        self.execution_history_groupbox = ExecutionHistoryGroupBox(
            parent=self
        )
        self.execution_history_groupbox.set_visibility_of_file_name(False)
        self.execution_history_groupbox.set_visibility_of_context(False)
        self.execution_history_groupbox.setStyleSheet(
            AppStyles.GroupBox.embedded()
        )

        # --- Image Metadata (titled section header) ---
        self.image_metadata_groupbox = ImageMetadataGroupBox(parent=self)
        self.image_metadata_groupbox.set_visibility_of_file_name(False)
        self.image_metadata_groupbox.set_visibility_of_context(False)
        self.image_metadata_groupbox.setStyleSheet(
            AppStyles.GroupBox.embedded()
        )

        # --- Scroll area with inner container ---
        self._scroll_container = QWidget()
        container_layout = QVBoxLayout(self._scroll_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(AppStyles.Dimensions.LAYOUT_VSPACING)
        container_layout.addWidget(self.image_viewer_groupbox, 0)
        container_layout.addWidget(self.execution_history_groupbox, 1)
        self.execution_history_groupbox.setMinimumHeight(AppStyles.Dimensions.EXECUTION_HISTORY_MINIMUM_HEIGHT)
        container_layout.addWidget(self.image_metadata_groupbox, 1)
        self.image_metadata_groupbox.setMinimumHeight(AppStyles.Dimensions.IMAGE_METADATA_MINIMUM_HEIGHT)
        # container_layout.addStretch()

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidget(self._scroll_container)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll_area.setStyleSheet(AppStyles.ScrollArea.embedded())

    def _setup_layout(self):
        """Stack shared labels above the scroll area."""
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
        layout.addWidget(self._scroll_area, 1)  # stretch factor
        self.setStyleSheet(AppStyles.GroupBox.with_title_flush())

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def set_slice_info(
        self,
        image_name: str,
        site_name: str,
        step_name: str,
        detector: str,
        image_path=None,
    ):
        """
        Update the shared file name and context labels.

        Called by the parent tab when a slice is selected (before
        populating each child group box individually).

        :param image_name: The image file name.
        :param site_name: The site name.
        :param step_name: The step name.
        :param detector: The detector name.
        :param image_path: Absolute path to the image file (str or Path).
            When provided, the file name becomes a clickable "reveal in
            folder" link; when None/empty it shows as plain text.
        """
        self._current_image_path = str(image_path) if image_path else ""
        self.file_name_label.setText(image_name)
        self.file_name_label.set_clickable(bool(self._current_image_path))
        self.file_name_label.setToolTip(
            AppStyles.AppToolTips.IMAGE_NAME_LINK
            if self._current_image_path else ""
        )
        self.context_label.setText(
            f"{site_name}  •  {step_name}  •  {detector}"
        )

    def _on_file_name_clicked(self):
        """Relay a file-name link click to the parent tab, which performs
        the reveal (groupbox owns the widget; the tab does the work)."""
        if self._current_image_path:
            self.image_link_activated.emit(self._current_image_path)

    def clear_all(self, close_dialogs: bool = True):
        """Reset the shared labels and all child group boxes.

        :param close_dialogs: If False, open full-resolution dialogs
            are left alone (only the panels reset) — used when the
            active plot goes away but other plots keep their
            comparison windows.
        """
        self._current_image_path = ""
        self.file_name_label.setText(_PLACEHOLDER_FILE_NAME)
        self.file_name_label.set_clickable(False)
        self.file_name_label.setToolTip("")
        self.context_label.setText(_PLACEHOLDER_CONTEXT)
        self.image_viewer_groupbox.clear_image(close_dialogs=close_dialogs)
        self.execution_history_groupbox.clear_history()
        self.image_metadata_groupbox.clear_metadata()