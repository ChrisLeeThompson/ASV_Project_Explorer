"""
Module for styled button widgets.
"""
from PySide6.QtWidgets import QPushButton
from script_modules.app_styles import AppStyles


class StyledButton(QPushButton):

    def __init__(self, parent=None, button_text: str = ""):
        super().__init__(parent)
        self.setText(button_text)
        self.setStyleSheet(AppStyles.Button.default())


class LoadASVDataButton(StyledButton):

    def __init__(self, parent=None):
        super().__init__(parent, "Load ASV Project")


class LoadJSONFileButton(StyledButton):

    def __init__(self, parent=None):
        super().__init__(parent, "Load Metadata File")


class DeleteJSONFileButton(StyledButton):

    def __init__(self, parent=None):
        super().__init__(parent, "Delete Temp Metadata File")
        self.setToolTip(AppStyles.AppToolTips.DELETE_TEMP_METADATA_BUTTON)


class SaveJSONFileButton(StyledButton):

    def __init__(self, parent=None):
        super().__init__(parent, "Save Metadata File")


class CancelButton(StyledButton):

    def __init__(self, parent=None):
        super().__init__(parent, "Cancel")
        self.setFixedWidth(AppStyles.Dimensions.SPINBOX_WIDTH)


class DisplayPlotsButton(StyledButton):

    def __init__(self, parent=None):
        super().__init__(parent, "Display")


class UpdateButton(StyledButton):

    def __init__(self, parent=None):
        super().__init__(parent, "Update Plots")


class ClearButton(StyledButton):

    def __init__(self, parent=None):
        super().__init__(parent, "Clear")


class ExportPlotsButton(StyledButton):

    def __init__(self, parent=None):
        super().__init__(parent, "Export Plots")
        self.setToolTip(AppStyles.AppToolTips.EXPORT_PLOTS_BUTTON)


class FullResolutionButton(StyledButton):

    def __init__(self, parent=None):
        super().__init__(parent, "Full Resolution")
        self.setToolTip(AppStyles.AppToolTips.FULL_RESOLUTION_BUTTON)


class PreviousButton(StyledButton):

    def __init__(self, parent=None):
        super().__init__(parent, "Prev.")


class NextButton(StyledButton):

    def __init__(self, parent=None):
        super().__init__(parent, "Next")