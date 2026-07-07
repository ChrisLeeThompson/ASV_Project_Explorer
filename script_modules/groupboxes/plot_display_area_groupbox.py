"""
Plot Display Area GroupBox

Scrollable container for ASV plot widgets. Wraps a QScrollArea inside a
QGroupBox so the entire plot region can be styled as a single visual unit.

Plot widgets are stacked vertically and scroll as a group. The container
keeps a reference dict of plot widgets keyed by their field name, making
it straightforward to add, remove, or update individual plots when the
user changes their selection in the SelectPlotsComboBox.

Lifecycle
---------
The PlotsTab owns this widget and manages its visibility:
- Hidden at startup (startup label shown instead).
- Shown when data is loaded and the user requests plots.
- Plots accumulate across Display clicks, keyed by composite key
  (site|step|detector|field_path) to allow cross-dataset comparison.
- Cleared when the user clicks Clear or loads new data.
"""
import logging
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QScrollArea, QWidget
)
from PySide6.QtCore import Qt
from script_modules.app_styles import AppStyles


logger = logging.getLogger(__name__)


class PlotDisplayArea(QGroupBox):
    """
    Scrollable container that holds vertically stacked ASVPlotWidget
    instances inside a styled QGroupBox.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # Plot widget registry: {field_name: ASVPlotWidget}
        self._plot_widgets: dict = {}
        # Build UI
        self._create_scroll_area()
        self._setup_layout()
        # Set focus policy
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # -------------------------------------------------------------------------
    # Setup
    # -------------------------------------------------------------------------

    def _create_scroll_area(self):
        """Create the scroll area and its permanent inner container."""
        # Inner container — lives for the lifetime of the widget.
        # Plot widgets are added to / removed from its layout.
        self._plot_container = QWidget()
        self._plot_layout = QVBoxLayout(self._plot_container)
        self._plot_layout.setContentsMargins(0, 0, 0, 0)
        self._plot_layout.setSpacing(4)
        # Stretch at the bottom keeps plots pushed to the top
        self._plot_layout.addStretch()

        # Scroll area
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidget(self._plot_container)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll_area.setStyleSheet(AppStyles.ScrollArea.default())

    def _setup_layout(self):
        """Place the scroll area inside this groupbox."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._scroll_area)
        self.setStyleSheet(AppStyles.GroupBox.plot_area_flush())

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def add_plot(self, field_name: str, plot_widget: QWidget):
        """
        Add a plot widget to the display area.

        If a widget with the same field_name already exists it is replaced.

        :param field_name: Metadata field name used as the registry key.
        :param plot_widget: The ASVPlotWidget to display.
        """
        # Replace existing widget for this field if present
        if field_name in self._plot_widgets:
            self.remove_plot(field_name)

        self._plot_widgets[field_name] = plot_widget
        # Insert before the trailing stretch, with a stretch factor of 1 so
        # plots share the available height (and a lone plot fills it up to its
        # maximum). The trailing stretch absorbs any leftover once plots cap.
        insert_index = self._plot_layout.count() - 1  # before stretch
        self._plot_layout.insertWidget(insert_index, plot_widget, 1)
        plot_widget.setVisible(True)
        logger.debug("Added plot: %s", field_name)

    def remove_plot(self, field_name: str):
        """
        Remove a plot widget from the display area by field name.

        The widget is removed from the layout, orphaned (parent set to
        None), and scheduled for deletion via deleteLater() so the
        widget, its canvas, and its Figure are released once the event
        loop runs. Callers must not use the widget after removal.

        :param field_name: Metadata field name to remove.
        """
        widget = self._plot_widgets.pop(field_name, None)
        if widget is None:
            return
        self._plot_layout.removeWidget(widget)
        widget.setParent(None)
        widget.deleteLater()
        logger.debug("Removed plot: %s", field_name)

    def clear_plots(self):
        """
        Remove all plot widgets from the display area.

        Widgets are scheduled for deletion (via remove_plot) and must
        not be reused after this call.
        """
        for field_name in list(self._plot_widgets.keys()):
            self.remove_plot(field_name)
        logger.debug("Cleared all plots")

    def has_plots(self) -> bool:
        """Return True if any plot widgets are currently displayed."""
        return len(self._plot_widgets) > 0

    def get_plot(self, field_name: str) -> QWidget | None:
        """
        Get a plot widget by field name.

        :param field_name: Metadata field name.
        :return: The ASVPlotWidget or None if not found.
        """
        return self._plot_widgets.get(field_name)

    def get_field_names(self) -> list[str]:
        """Return a list of field names currently displayed."""
        return list(self._plot_widgets.keys())

    def get_all_plots(self) -> dict:
        """
        Return a shallow copy of the plot widget registry.

        :return: Dict of {composite_key: ASVPlotWidget}.
        """
        return dict(self._plot_widgets)

    @property
    def plot_count(self) -> int:
        """Number of plot widgets currently displayed."""
        return len(self._plot_widgets)