"""
Central repository for application styles and tool tips.
"""
from pathlib import Path

from script_modules import __version__


# =====================================================================
# Asset Paths
# =====================================================================

# Centralized asset directory path. All modules that need icon
# or image assets should reference this rather than computing
# their own relative paths.
ASSETS_DIR = Path(__file__).parent.parent / "script_assets"
ICON_PATH = ASSETS_DIR / "catbug_waiting_color.png"


# =====================================================================
# Scrollbar Style Helpers
# =====================================================================

def _vertical_scrollbar(bg_color: str, prefix: str = "") -> str:
    """Generate a vertical scrollbar CSS block.

    :param bg_color: Background color for the scrollbar track.
    :param prefix: Optional parent selector prefix
        (e.g. ``"QTextEdit "``). Include a trailing space.
    :return: CSS string for a styled vertical scrollbar.
    """
    p = prefix
    return f"""
            {p}QScrollBar:vertical {{
                background-color: {bg_color};
                width: {StyleDimensions.SCROLLBAR_WIDTH};
                margin: 0px;
                border-radius: 6px;
            }}
            {p}QScrollBar::handle:vertical {{
                background-color: {StyleColors.BUTTON_BG};
                border-radius: 4px;
                min-height: {StyleDimensions.SCROLLBAR_HANDLE_MIN};
                margin: 2px;
                border: none;
            }}
            {p}QScrollBar::handle:vertical:hover {{
                background-color: {StyleColors.BUTTON_HOVER};
            }}
            {p}QScrollBar::handle:vertical:pressed {{
                background-color: {StyleColors.BUTTON_PRESSED};
            }}
            {p}QScrollBar::add-line:vertical,
            {p}QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            {p}QScrollBar::add-page:vertical,
            {p}QScrollBar::sub-page:vertical {{
                background: none;
            }}"""


def _horizontal_scrollbar(bg_color: str, prefix: str = "") -> str:
    """Generate a horizontal scrollbar CSS block.

    :param bg_color: Background color for the scrollbar track.
    :param prefix: Optional parent selector prefix.
        Include a trailing space if non-empty.
    :return: CSS string for a styled horizontal scrollbar.
    """
    p = prefix
    return f"""
            {p}QScrollBar:horizontal {{
                background-color: {bg_color};
                height: {StyleDimensions.SCROLLBAR_WIDTH};
                margin: 0px;
                border-radius: 6px;
            }}
            {p}QScrollBar::handle:horizontal {{
                background-color: {StyleColors.BUTTON_BG};
                border-radius: 4px;
                min-width: {StyleDimensions.SCROLLBAR_HANDLE_MIN};
                margin: 2px;
                border: none;
            }}
            {p}QScrollBar::handle:horizontal:hover {{
                background-color: {StyleColors.BUTTON_HOVER};
            }}
            {p}QScrollBar::handle:horizontal:pressed {{
                background-color: {StyleColors.BUTTON_PRESSED};
            }}
            {p}QScrollBar::add-line:horizontal,
            {p}QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            {p}QScrollBar::add-page:horizontal,
            {p}QScrollBar::sub-page:horizontal {{
                background: none;
            }}"""


class StyleColors:
    
    MAIN_BG = "#273945"
    GROUPBOX_BG = "#34454f"
    INPUT_BG = "#1f2d36"
    INPUT_BORDER = "#0f1e28"
    BUTTON_BG = "#476273"
    BUTTON_HOVER = "#2ea2ec"
    BUTTON_PRESSED = "#1F6FA1"
    BUTTON_DISABLED = "#3d5462"
    TEXT_PRIMARY = "#ffffff"
    TEXT_DISABLED = "#8498a4"
    UPDATE_PLOT_BUTTON_NEW_DATA = "#009900" # "#00ff85"
    ACTIVE_PLOT_BORDER = "#2ea2ec"  # Border accent for the active/driving plot card
    COMBO_CURRENT_ITEM_BG = BUTTON_HOVER  # Popup accent: highlighted row / current-item marker
    # Plot colors
    PLOT_BG = "#000000"
    PLOT_INTERACTIVE_LINE_COLOR = "#04f5ff"
    PLOT_LINE_COLOR = "#eb70a9" # plot line color, v2.5: #38003c, catbug: a1c7ea (blue), bright_blue: 9df1ed, catbug (glove): eb70a9, TEM blue: #00CEC8
    PLOT_SPINE_COLOR = "#ffffff"
    # Autofocus sharpness histogram colors
    # G-number convention (confirmed by the user, July 2026):
    # G1 = Fine, G2 = Medium, G3 = Coarse.
    COLOR_COARSE   = "#2c9e2d"   # G3 (Coarse) curve
    COLOR_MEDIUM   = "#ff7f0e"   # G2 (Medium) curve
    COLOR_FINE     = "#1f77b4"   # G1 (Fine) curve
    COLOR_FOUND_WD = "#d62728"   # Found WD marker
    COLOR_OPT_WD   = "#9261ae"   # Optimized / corrected WD marker
    # Image histogram panel (full-resolution dialog contrast windowing).
    # Independent of the metadata-plot colors so the panel can be tuned
    # on its own; the dark axes frame stays shared (PLOT_BG /
    # PLOT_SPINE_COLOR / TEXT_DISABLED placeholder).
    HISTOGRAM_TRACE_COLOR      = "#eb70a9"   # log-count trace + fill
    HISTOGRAM_LEVEL_LINE_COLOR = "#2ea2ec" #"#04f5ff"   # draggable black/white level lines
    HISTOGRAM_VALUE_TEXT_COLOR = "#ffffff"   # value box text
    HISTOGRAM_VALUE_BOX_BG     = "#1f2d36"   # value box background
    HISTOGRAM_BG               = "#1f2d36"   # plot-area background (behind the trace)

class StyleDimensions:

    WINDOW_WIDTH = 1640
    WINDOW_HEIGHT = 1240
    BORDER_RADIUS_LARGE = "8.0px"
    BORDER_RADIUS_SMALL = "4.0px"
    MARGIN = "8px"
    PADDING = "4px"
    MAIN_WINDOW_MARGIN = 4
    TAB_PADDING = "10px"
    FONT_SIZE_NORMAL = "11pt"
    FONT_SIZE_LARGE = "14pt"
    FONT_SIZE_EXTRA_LARGE = "16pt"
    SPINBOX_WIDTH = 180
    LAYOUT_CONTENTS_MARGIN = 8
    LAYOUT_HSPACING = 60
    LAYOUT_VSPACING = 10
    CHECKBOX_SPACING = "16px"
    RESULT_LABEL_MARGIN = "2px"
    COMBOBOX_WIDTH = 180
    COMBOBOX_CURRENT_ITEM_BAR_WIDTH = 4  # Marker bar on the popup's current item
    # Width of the ::item borders (the popup's row separators), in px.
    # Interpolated into ComboBoxStyles.default().
    COMBOBOX_ITEM_BORDER = 1
    # Inset of the marker bar from the row edges. Equal to the row-separator
    # width so the bar sits between the separators; raise it to shorten the
    # bar within the row.
    COMBOBOX_CURRENT_ITEM_BAR_INSET = COMBOBOX_ITEM_BORDER
    SCROLLBAR_WIDTH = "12px"
    SCROLLBAR_HANDLE_MIN = "30px"
    # Plot dimensions
    PLOT_MINIMUM_HEIGHT = 360
    # A single plot grows to fill the display area up to this cap; beyond it
    # (very tall monitors) the extra space becomes whitespace below the plot.
    # Tunable — raise to fill taller windows, lower for a more compact plot.
    PLOT_MAXIMUM_HEIGHT = 800
    PLOT_LINE_WIDTH = 1.0
    PLOT_TITLE_FONT_SIZE = 11
    PLOT_HIGHLIGHT_MARKER_SIZE = 50  # scatter 's' parameter (points²)
    # Image viewer dimensions
    IMAGE_VIEWER_CANVAS_MINIMUM_HEIGHT = 160
    IMAGE_VIEWER_CANVAS_CONTAINER_MAXIMUM_HEIGHT = 200
    IMAGE_VIEWER_SIDE_MARGIN = 8  # L/R breathing room around the center image
    # Minimum width reserved for the full-resolution toolbar's x/y (and
    # intensity) coordinate readout, so it never clips regardless of the
    # toolbar layout. Tunable — raise if long readouts (large/RGB images) clip.
    FULL_RES_TOOLBAR_READOUT_MIN_WIDTH = 240
    # Execution history dimensions
    EXECUTION_HISTORY_MINIMUM_HEIGHT = 300
    # Image metadata dimensions
    IMAGE_METADATA_MINIMUM_HEIGHT = 400
    # Slice data panel dimensions
    SLICE_DATA_MINIMUM_WIDTH = 420
    SLICE_DATA_INITIAL_WIDTH = 420
    # Histogram panel (full-resolution dialog, right side)
    HISTOGRAM_PANEL_WIDTH = 280
    HISTOGRAM_PANEL_MINIMUM_WIDTH = 220
    # Histogram trace / level-line / value-box styling
    HISTOGRAM_TRACE_WIDTH = 1.0
    HISTOGRAM_LEVEL_LINE_WIDTH = 1.2
    HISTOGRAM_FILL_ALPHA = 0.35
    HISTOGRAM_VALUE_FONT_SIZE = 8
    HISTOGRAM_VALUE_BOX_PAD = 0.25
    HISTOGRAM_VALUE_BOX_EDGE_WIDTH = 0.8
    HISTOGRAM_TICK_LABEL_SIZE = 8
    HISTOGRAM_PLACEHOLDER_FONT_SIZE = 9
    HISTOGRAM_HIT_RADIUS_PX = 12
    # Project parameters tab dimensions
    SIDEBAR_MINIMUM_WIDTH = 500
    SIDEBAR_MAXIMUM_WIDTH = 560
    RECIPE_CARD_FIXED_WIDTH = 560
    # Plot export dimensions
    EXPORT_PNG_DPI = 200
    # Splitter dimensions
    SPLITTER_HANDLE_WIDTH = 8
    SPLITTER_ARROW_SIZE = 4
    SPLITTER_ARROW_PEN_WIDTH = 1.5
    SPLITTER_HANDLE_BORDER_RADIUS = 2
    SPLITTER_ADJACENT_MARGIN = "4px"
    SPLITTER_ADJACENT_BORDER_RADIUS = "4px"
    SPLITTER_HANDLE_VERTICAL_INSET = 4
    # Collapsible handle dimensions
    COLLAPSIBLE_HANDLE_WIDTH = 8
    COLLAPSIBLE_ARROW_SIZE = SPLITTER_ARROW_SIZE
    COLLAPSIBLE_ARROW_PEN_WIDTH = SPLITTER_ARROW_PEN_WIDTH


class StyleFonts:

    FONT_COURIER = "Courier"


class ApplicationText:

    WINDOW_TITLE = f"ASV Project Explorer {__version__}"

    STARTUP_PLOT_AREA_LABEL = "Drop an ASV project directory or previously generated JSON metadata file\n" + \
                              "onto Catbug to explore ASV metadata.\n\n" + \
                              "Alternatively, use the Load ASV Project button or the Load Metadata File button to begin."
    
    SLICE_DATA_GROUPBOX_DEFAULT_LABEL = "No slice selected."

    PROJECT_PARAMETERS_DEFAULT_LABEL = "Load an ASV project to view project parameters."

    PROJECT_PARAMETERS_NO_DATA_LABEL = "No project parameters available in the loaded data."

    SINGLE_IMAGE_METADATA_FILE_NAME = ""
    
    SINGLE_IMAGE_METADATA_DROP = "Drag and drop a single SEM/FIB .tif or ASV .png image to display its metadata."

    TREND_LINE_CHECKBOX = "Trend Line"


class ToolTips:

    EXPORT_PLOTS_BUTTON = "Export all displayed plots as PNG, SVG, and CSV."

    FULL_RESOLUTION_BUTTON = "Open the image at full resolution with zoom and pan controls."

    DELETE_TEMP_METADATA_BUTTON =  "Delete the auto generated temporary metadata file and directory. Only available for auto-generated metadata files."

    PROJECT_NAME_BUTTON = "Open the project directory."

    IMAGE_NAME_LINK = "Open containing directory."

    TREND_LINE_CHECKBOX = "Show/hide the trend line and statistics overlay (average + slope / R², or average cycle time)."


class WindowStyles:

    @staticmethod
    def window() -> str:
        return f"""
            QMainWindow {{
                background-color: {StyleColors.MAIN_BG}
            }}
        """
    
    @staticmethod
    def tabs() -> str:
        return f"""
            QTabWidget::pane {{
                border: 1px solid {StyleColors.MAIN_BG};
                background-color: {StyleColors.MAIN_BG};
            }}
            QTabBar::tab {{
                background: {StyleColors.MAIN_BG};
                color: {StyleColors.TEXT_PRIMARY};
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                margin: {StyleDimensions.MARGIN};
                padding: {StyleDimensions.TAB_PADDING};
            }}
            QTabBar::tab:hover {{
                color: {StyleColors.BUTTON_HOVER};
            }}
            QTabBar::tab:selected {{
                background-color: {StyleColors.GROUPBOX_BG};
                margin: {StyleDimensions.MARGIN};
                padding: {StyleDimensions.TAB_PADDING};
            }}
        """


class LabelStyles:

    @staticmethod
    def default() -> str:
        return f"""
            QLabel {{
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                color: {StyleColors.TEXT_PRIMARY};
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
            }}
            QToolTip {{
                background-color: {StyleColors.BUTTON_BG};
                color: {StyleColors.TEXT_PRIMARY};
                /*border: 1px solid #ffffff;*/
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                padding: {StyleDimensions.PADDING};
                font-size: {StyleDimensions.FONT_SIZE_LARGE};
            }}
        """

    @staticmethod
    def large_label() -> str:
        return f"""
            QLabel {{
                font-size: {StyleDimensions.FONT_SIZE_LARGE};
                color: {StyleColors.TEXT_PRIMARY};
            }}
            QToolTip {{
                background-color: {StyleColors.BUTTON_BG};
                color: {StyleColors.TEXT_PRIMARY};
                /*border: 1px solid #ffffff;*/
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                padding: {StyleDimensions.PADDING};
                font-size: {StyleDimensions.FONT_SIZE_LARGE};
            }}
        """
    
    @staticmethod
    def status_bar() -> str:
        return f"""
            QLabel {{
                font-size: {StyleDimensions.FONT_SIZE_LARGE};
                background-color: {StyleColors.MAIN_BG};
                color: {StyleColors.TEXT_PRIMARY};
                margin-left: {StyleDimensions.MARGIN};
                padding-left: {StyleDimensions.PADDING};
            }}
        """

    @staticmethod
    def clickable(color: str = StyleColors.TEXT_PRIMARY) -> str:
        """Stylesheet for a ClickableLabel — identical geometry to
        ``default()`` (same font and left/right margins, so the label does
        not shift) but with a parameterised text ``color`` that the widget
        swaps between rest / hover / pressed states.
        """
        return f"""
            QLabel {{
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                color: {color};
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
            }}
            QToolTip {{
                background-color: {StyleColors.BUTTON_BG};
                color: {StyleColors.TEXT_PRIMARY};
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                padding: {StyleDimensions.PADDING};
                font-size: {StyleDimensions.FONT_SIZE_LARGE};
            }}
        """


class GroupBoxStyles:

    @staticmethod
    def default() -> str:
        return f"""
            QGroupBox {{
                /* border: 1px solid {StyleColors.INPUT_BORDER}; */
                border-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
                background-color: {StyleColors.GROUPBOX_BG};
                margin-top: "4px";
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
                margin-bottom: "4px";
                padding-top: {StyleDimensions.PADDING};
                padding-left: {StyleDimensions.PADDING};
                padding-right: {StyleDimensions.PADDING};
                padding-bottom: {StyleDimensions.PADDING};
            }}
        """

    @staticmethod
    def with_title() -> str:
        return f"""
            QGroupBox {{
                /* border: 1px solid {StyleColors.INPUT_BORDER}; */
                border-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
                background-color: {StyleColors.GROUPBOX_BG};
                margin-top: 4px;
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
                margin-bottom: 4px;
                padding-top: 30px;
                padding-left: {StyleDimensions.PADDING};
                padding-right: {StyleDimensions.PADDING};
                padding-bottom: {StyleDimensions.PADDING};
                /*font-weight: bold;*/
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                color: {StyleColors.TEXT_PRIMARY};
            }}
            QGroupBox::title {{
                subcontrol-origin: padding;
                subcontrol-position: top left;
                left: 6px;
                margin-top: 4px;
                padding: 0 10px;
                background-color: {StyleColors.GROUPBOX_BG};
            }}
        """
    
    @staticmethod
    def with_title_flush() -> str:
        """Titled groupbox for use inside a splitter.

        The right margin and right-side border radii are reduced so
        the groupbox sits close to the splitter handle.  The left
        side retains the normal margin and radius.  Both values are
        controlled by ``SPLITTER_ADJACENT_MARGIN`` and
        ``SPLITTER_ADJACENT_BORDER_RADIUS``."""
        return f"""
            QGroupBox {{
                /* border: 1px solid {StyleColors.INPUT_BORDER}; */
                border-top-left-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
                border-bottom-left-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
                border-top-right-radius: {StyleDimensions.SPLITTER_ADJACENT_BORDER_RADIUS};
                border-bottom-right-radius: {StyleDimensions.SPLITTER_ADJACENT_BORDER_RADIUS};
                background-color: {StyleColors.GROUPBOX_BG};
                margin-top: 4px;
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.SPLITTER_ADJACENT_MARGIN};
                margin-bottom: 4px;
                padding-top: 30px;
                padding-left: {StyleDimensions.PADDING};
                padding-right: {StyleDimensions.PADDING};
                padding-bottom: {StyleDimensions.PADDING};
                /*font-weight: bold;*/
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                color: {StyleColors.TEXT_PRIMARY};
            }}
            QGroupBox::title {{
                subcontrol-origin: padding;
                subcontrol-position: top left;
                left: 6px;
                margin-top: 4px;
                padding: 0 10px;
                background-color: {StyleColors.GROUPBOX_BG};
            }}
        """

    @staticmethod
    def with_title_flush_right() -> str:
        """Titled groupbox for the RIGHT side of a splitter.

        Mirror of :meth:`with_title_flush`: the LEFT margin and
        left-side border radii are reduced so the groupbox sits flush
        against a splitter handle on its left, while the right side
        retains the normal margin and radius.  Both reduced values are
        controlled by ``SPLITTER_ADJACENT_MARGIN`` and
        ``SPLITTER_ADJACENT_BORDER_RADIUS``.  Used by the histogram
        panel in the full-resolution dialog so its handle and window
        margins mirror the left panel's."""
        return f"""
            QGroupBox {{
                /* border: 1px solid {StyleColors.INPUT_BORDER}; */
                border-top-left-radius: {StyleDimensions.SPLITTER_ADJACENT_BORDER_RADIUS};
                border-bottom-left-radius: {StyleDimensions.SPLITTER_ADJACENT_BORDER_RADIUS};
                border-top-right-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
                border-bottom-right-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
                background-color: {StyleColors.GROUPBOX_BG};
                margin-top: 4px;
                margin-left: {StyleDimensions.SPLITTER_ADJACENT_MARGIN};
                margin-right: {StyleDimensions.MARGIN};
                margin-bottom: 4px;
                padding-top: 30px;
                padding-left: {StyleDimensions.PADDING};
                padding-right: {StyleDimensions.PADDING};
                padding-bottom: {StyleDimensions.PADDING};
                /*font-weight: bold;*/
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                color: {StyleColors.TEXT_PRIMARY};
            }}
            QGroupBox::title {{
                subcontrol-origin: padding;
                subcontrol-position: top left;
                left: 6px;
                margin-top: 4px;
                padding: 0 10px;
                background-color: {StyleColors.GROUPBOX_BG};
            }}
        """

    @staticmethod
    def plot_area() -> str:
        return f"""
            QGroupBox {{
                border: 2px solid transparent;
                border-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
                background-color: {StyleColors.MAIN_BG};
                margin-top: 4px;
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
                margin-bottom: 4px;
                padding-top: {StyleDimensions.PADDING};
                padding-left: {StyleDimensions.PADDING};
                padding-right: {StyleDimensions.PADDING};
                padding-bottom: {StyleDimensions.PADDING};
            }}
        """
    
    @staticmethod
    def plot_area_flush() -> str:
        """Plot area groupbox for the right side of a splitter.

        The left margin and left-side border radii are reduced so
        the groupbox sits close to the splitter handle.  The right
        side retains the normal margin and radius.  See
        :meth:`with_title_flush`."""
        return f"""
            QGroupBox {{
                border: 2px solid transparent;
                border-top-left-radius: {StyleDimensions.SPLITTER_ADJACENT_BORDER_RADIUS};
                border-bottom-left-radius: {StyleDimensions.SPLITTER_ADJACENT_BORDER_RADIUS};
                border-top-right-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
                border-bottom-right-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
                background-color: {StyleColors.MAIN_BG};
                margin-top: 4px;
                margin-left: {StyleDimensions.SPLITTER_ADJACENT_MARGIN};
                margin-right: {StyleDimensions.MARGIN};
                margin-bottom: 4px;
                padding-top: {StyleDimensions.PADDING};
                padding-left: {StyleDimensions.PADDING};
                padding-right: {StyleDimensions.PADDING};
                padding-bottom: {StyleDimensions.PADDING};
            }}
        """

    @staticmethod
    def plot() -> str:
        return f"""
            QGroupBox {{
                border: 2px solid {StyleColors.GROUPBOX_BG};
                border-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
                background-color: {StyleColors.MAIN_BG};
                margin-top: {StyleDimensions.MARGIN};
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
                margin-bottom: {StyleDimensions.MARGIN};
                padding-top: {StyleDimensions.PADDING};
                padding-left: {StyleDimensions.PADDING};
                padding-right: {StyleDimensions.PADDING};
                padding-bottom: {StyleDimensions.PADDING};
            }}
        """

    @staticmethod
    def plot_active() -> str:
        """Plot-card style for the active/driving plot.

        Identical to plot() but with the border recoloured to the active
        accent. Derived from plot() by swapping only the border colour so
        the two cannot drift: any future change to the card's background,
        radius, margins, or padding is inherited automatically. The border
        width is unchanged, so toggling between plot() and plot_active()
        causes no layout shift.
        """
        return GroupBoxStyles.plot().replace(
            f"border: 2px solid {StyleColors.GROUPBOX_BG}",
            f"border: 2px solid {StyleColors.ACTIVE_PLOT_BORDER}",
        )

    @staticmethod
    def plot_hover() -> str:
        return f"""
            QGroupBox {{
                border: 2px solid {StyleColors.TEXT_DISABLED};
                border-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
                background-color: {StyleColors.MAIN_BG};
                margin-top: {StyleDimensions.MARGIN};
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
                margin-bottom: {StyleDimensions.MARGIN};
                padding-top: {StyleDimensions.PADDING};
                padding-left: {StyleDimensions.PADDING};
                padding-right: {StyleDimensions.PADDING};
                padding-bottom: {StyleDimensions.PADDING};
            }}
        """

    @staticmethod
    def embedded() -> str:
        """Borderless groupbox with a visible title used as a section
        header inside a parent container (e.g. SliceDataGroupBox)."""
        return f"""
            QGroupBox {{
                border: none;
                border-radius: 0px;
                background-color: transparent;
                margin: 0px;
                padding-top: 22px;
                padding-left: 0px;
                padding-right: 0px;
                padding-bottom: 0px;
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                color: {StyleColors.TEXT_PRIMARY};
            }}
            QGroupBox::title {{
                subcontrol-origin: padding;
                subcontrol-position: top left;
                left: 0px;
                margin-top: 2px;
                padding: 0 4px;
                color: {StyleColors.TEXT_PRIMARY};
            }}
        """

    @staticmethod
    def embedded_untitled() -> str:
        """Borderless groupbox without a title, used for self-describing
        content (e.g. ImageViewerGroupBox) inside a parent container."""
        return f"""
            QGroupBox {{
                border: none;
                border-radius: 0px;
                background-color: transparent;
                margin: 0px;
                padding: 0px;
            }}
        """
    
    @staticmethod
    def site_params_with_title() -> str:
        return f"""
            QGroupBox {{
                border: 1px solid {StyleColors.INPUT_BORDER};
                border-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
                background-color: {StyleColors.GROUPBOX_BG};
                margin-top: 4px;
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
                margin-bottom: 4px;
                padding-top: 30px;
                padding-left: {StyleDimensions.PADDING};
                padding-right: {StyleDimensions.PADDING};
                padding-bottom: {StyleDimensions.PADDING};
                /*font-weight: bold;*/
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                color: {StyleColors.TEXT_PRIMARY};
            }}
            QGroupBox::title {{
                subcontrol-origin: padding;
                subcontrol-position: top left;
                left: 6px;
                margin-top: 4px;
                padding: 0 10px;
                background-color: {StyleColors.GROUPBOX_BG};
            }}
        """


class ButtonStyles:

    @staticmethod
    def default() -> str:
        return f"""
            QPushButton {{
                background-color: {StyleColors.BUTTON_BG};
                color: {StyleColors.TEXT_PRIMARY};
                border: 1px solid {StyleColors.BUTTON_BG};
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                margin-top: 4px;
                margin-bottom: 4px;
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
                padding: {StyleDimensions.PADDING};
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
            }}
            QPushButton:hover {{
                background-color: {StyleColors.BUTTON_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {StyleColors.BUTTON_PRESSED};
            }}
            QPushButton:disabled {{
                background-color: {StyleColors.BUTTON_DISABLED};
                color: {StyleColors.TEXT_DISABLED};
            }}
            QToolTip {{
                background-color: {StyleColors.BUTTON_BG};
                color: {StyleColors.TEXT_PRIMARY};
                /*border: 1px solid #ffffff;*/
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                padding: {StyleDimensions.PADDING};
                font-size: {StyleDimensions.FONT_SIZE_LARGE};
            }}
        """
    
    @staticmethod
    def toggle() -> str:
        """Checkable button: the checked state carries the active-plot
        accent border so a toggled-on panel button reads as engaged."""
        return ButtonStyles.default() + f"""
            QPushButton:checked {{
                background-color: {StyleColors.BUTTON_HOVER};
                border: 1px solid {StyleColors.ACTIVE_PLOT_BORDER};
            }}
        """

    @staticmethod
    def update_highlight() -> str:
        return f"""
            QPushButton {{
                background-color: {StyleColors.BUTTON_BG};
                color: {StyleColors.TEXT_PRIMARY};
                border: 1px solid {StyleColors.UPDATE_PLOT_BUTTON_NEW_DATA};
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                margin-top: 4px;
                margin-bottom: 4px;
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
                padding: {StyleDimensions.PADDING};
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
            }}
            QPushButton:hover {{
                background-color: {StyleColors.BUTTON_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {StyleColors.BUTTON_PRESSED};
            }}
            QPushButton:disabled {{
                background-color: {StyleColors.BUTTON_DISABLED};
                color: {StyleColors.TEXT_DISABLED};
            }}
            QToolTip {{
                background-color: {StyleColors.BUTTON_BG};
                color: {StyleColors.TEXT_PRIMARY};
                /*border: 1px solid #ffffff;*/
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                padding: {StyleDimensions.PADDING};
                font-size: {StyleDimensions.FONT_SIZE_LARGE};
            }}
        """

    @staticmethod
    def plot_close() -> str:
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {StyleColors.TEXT_DISABLED};
                border: none;
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                font-size: 14px;
                font-weight: bold;
                padding: 0px;
                margin: 0px;
            }}
            QPushButton:hover {{
                background-color: {StyleColors.BUTTON_BG};
                color: {StyleColors.TEXT_PRIMARY};
            }}
            QPushButton:pressed {{
                background-color: {StyleColors.BUTTON_PRESSED};
                color: {StyleColors.TEXT_PRIMARY};
            }}
        """

    @staticmethod
    def link_title() -> str:
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {StyleColors.TEXT_PRIMARY};
                border: none;
                /* tab-bar corner spacing */
                margin: 0px 12px 4px 0px;
                padding: 0px;
                font-size: {StyleDimensions.FONT_SIZE_LARGE};
            }}
            QPushButton:hover {{
                color: {StyleColors.BUTTON_HOVER};
            }}
            QPushButton:pressed {{
                color: {StyleColors.BUTTON_PRESSED};
            }}
            QToolTip {{
                background-color: {StyleColors.BUTTON_BG};
                color: {StyleColors.TEXT_PRIMARY};
                /*border: 1px solid #ffffff;*/
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                padding: {StyleDimensions.PADDING};
                font-size: {StyleDimensions.FONT_SIZE_LARGE};
            }}
        """


class SpinBoxStyles:

    @staticmethod
    def default() -> str:
        return f"""
            QSpinBox {{
                background-color: {StyleColors.INPUT_BG};
                color: {StyleColors.TEXT_PRIMARY};
                border: 1px solid {StyleColors.INPUT_BORDER};
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                padding: {StyleDimensions.PADDING};
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
            }}
            QSpinBox:focus {{
                border: 1px solid {StyleColors.BUTTON_HOVER};
            }}
            QSpinBox:hover {{
                border: 1px solid {StyleColors.BUTTON_HOVER};
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                width: 0px;
                height: 0px;
            }}
        """


class CheckBoxStyles:

    @staticmethod
    def default() -> str:
        return f"""
            QCheckBox {{
                color: {StyleColors.TEXT_PRIMARY};
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                spacing: {StyleDimensions.CHECKBOX_SPACING};
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
                padding: {StyleDimensions.PADDING};
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                border: 1px solid {StyleColors.INPUT_BORDER};
                background-color: {StyleColors.INPUT_BG};
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid {StyleColors.BUTTON_HOVER};
            }}
            QCheckBox::indicator:checked {{
                background-color: {StyleColors.BUTTON_HOVER};
                border: 1px solid {StyleColors.BUTTON_HOVER};
            }}
            QCheckBox:disabled {{
                color: {StyleColors.TEXT_DISABLED};
            }}
            QCheckBox::indicator:disabled {{
                background-color: {StyleColors.BUTTON_DISABLED};
            }}
            QToolTip {{
                background-color: {StyleColors.BUTTON_BG};
                color: {StyleColors.TEXT_PRIMARY};
                /*border: 1px solid #ffffff;*/
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                padding: {StyleDimensions.PADDING};
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
            }}
        """


class ComboBoxStyles:

    # Arrow icon path
    _arrow_path = str(ASSETS_DIR / "down_arrow_white.svg").replace("\\", "/")

    @staticmethod
    def default() -> str:
        return f"""
            QComboBox {{
                background-color: {StyleColors.INPUT_BG};
                color: {StyleColors.TEXT_PRIMARY};
                border: 1px solid {StyleColors.INPUT_BORDER};
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                padding: {StyleDimensions.PADDING};
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
            }}
            QComboBox:hover {{
                border: 1px solid {StyleColors.BUTTON_HOVER};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 40px;
            }}
            QComboBox::down-arrow {{
                image: url({ComboBoxStyles._arrow_path});
                width: 16px;
                height: 16px;
                border-left: 8px solid transparent;
                border-right: 8px solid transparent;
            }}
            QComboBox QAbstractItemView {{
                background-color: {StyleColors.INPUT_BG};
                color: {StyleColors.TEXT_PRIMARY};
                border: 1px solid {StyleColors.INPUT_BORDER};
                /* border-radius: {StyleDimensions.BORDER_RADIUS_SMALL}; */
                outline: none;
                /* The highlight is painted by ::item:selected below; the
                   palette-level value would be covered by it anyway. */
                selection-background-color: transparent;
                selection-color: {StyleColors.TEXT_PRIMARY};
            }}
            QComboBox QAbstractItemView::item {{
                padding: 8px 8px;
                border: {StyleDimensions.COMBOBOX_ITEM_BORDER}px solid {StyleColors.INPUT_BORDER};
                outline: none;
            }}
            QComboBox QAbstractItemView::item:hover {{
                padding: 8px 8px;
                background-color: {StyleColors.BUTTON_BG};
                border: {StyleDimensions.COMBOBOX_ITEM_BORDER}px solid {StyleColors.INPUT_BORDER};
                /* border-radius: {StyleDimensions.BORDER_RADIUS_SMALL}; */
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {StyleColors.COMBO_CURRENT_ITEM_BG};
                border: {StyleDimensions.COMBOBOX_ITEM_BORDER}px solid {StyleColors.INPUT_BORDER};
                /* border-radius: {StyleDimensions.BORDER_RADIUS_SMALL}; */
            }}
            /* Dropdown Scrollbar */
            {_vertical_scrollbar(StyleColors.INPUT_BG, "QComboBox QAbstractItemView ")}
        """

    @staticmethod
    def checkable() -> str:
        return f"""
            QComboBox {{
                background-color: {StyleColors.INPUT_BG};
                color: {StyleColors.TEXT_PRIMARY};
                border: 1px solid {StyleColors.INPUT_BORDER};
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                padding: {StyleDimensions.PADDING};
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
            }}
            QComboBox:hover {{
                border: 1px solid {StyleColors.BUTTON_HOVER};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 40px;
            }}
            QComboBox::down-arrow {{
                image: url({ComboBoxStyles._arrow_path});
                width: 16px;
                height: 16px;
                border-left: 8px solid transparent;
                border-right: 8px solid transparent;
            }}
            QComboBox QAbstractItemView {{
                background-color: {StyleColors.INPUT_BG};
                color: {StyleColors.TEXT_PRIMARY};
                border: 1px solid {StyleColors.INPUT_BORDER};
                /* border-radius: {StyleDimensions.BORDER_RADIUS_SMALL}; */
                outline: none;
                selection-background-color: transparent;
                selection-color: {StyleColors.TEXT_PRIMARY};
            }}
            QComboBox QAbstractItemView::item {{
                padding: 8px 8px;
                border: 1px solid {StyleColors.INPUT_BORDER};
                outline: none;
            }}
            QComboBox QAbstractItemView::item:hover {{
                padding: 8px 8px;
                background-color: {StyleColors.BUTTON_BG};
                border: 1px solid {StyleColors.INPUT_BORDER};
                /* border-radius: {StyleDimensions.BORDER_RADIUS_SMALL}; */
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: transparent;
                border: 1px solid {StyleColors.INPUT_BORDER};
            }}
            QComboBox QAbstractItemView::indicator {{
                width: 18px;
                height: 18px;
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                border: 1px solid {StyleColors.BUTTON_HOVER};
                background-color: {StyleColors.INPUT_BG};
                margin-right: 10px;
            }}
            QComboBox QAbstractItemView::indicator:hover {{
                border: 1px solid {StyleColors.BUTTON_HOVER};
            }}
            QComboBox QAbstractItemView::indicator:checked {{
                background-color: {StyleColors.BUTTON_HOVER};
                border: 1px solid {StyleColors.BUTTON_HOVER};
            }}
            /* Dropdown Scrollbar */
            {_vertical_scrollbar(StyleColors.INPUT_BG, "QComboBox QAbstractItemView ")}
        """
    
    @staticmethod
    def context_menu() -> str:
        return f"""
            QMenu {{
                background-color: {StyleColors.INPUT_BG};
                color: {StyleColors.TEXT_PRIMARY};
                border: 1px solid {StyleColors.INPUT_BORDER};
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                padding: 4px 0px;
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
            }}
            QMenu::item {{
                padding: 6px 20px;
            }}
            QMenu::item:selected {{
                background-color: {StyleColors.BUTTON_BG};
            }}
            QMenu::item:pressed {{
                background-color: {StyleColors.BUTTON_PRESSED};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {StyleColors.INPUT_BORDER};
                margin: 4px 8px;
            }}
        """


class ScrollAreaStyles:

    @staticmethod
    def default() -> str:
        return f"""
            QScrollArea {{
                background-color: {StyleColors.MAIN_BG};
                border: none;
                border-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {StyleColors.MAIN_BG};
            }}
            {_vertical_scrollbar(StyleColors.MAIN_BG)}
            {_horizontal_scrollbar(StyleColors.GROUPBOX_BG)}
        """

    @staticmethod
    def plot_button_scroll_area() -> str:
        return f"""
            QScrollArea {{
                background-color: {StyleColors.MAIN_BG};
                border: none;
                border-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {StyleColors.GROUPBOX_BG};
            }}
            {_vertical_scrollbar(StyleColors.GROUPBOX_BG)}
            {_horizontal_scrollbar(StyleColors.GROUPBOX_BG)}
        """

    @staticmethod
    def embedded() -> str:
        """Scroll area styled for embedding inside a QGroupBox
        (GROUPBOX_BG background throughout)."""
        return f"""
            QScrollArea {{
                background-color: {StyleColors.GROUPBOX_BG};
                border: none;
                border-radius: 0px;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {StyleColors.GROUPBOX_BG};
            }}
            {_vertical_scrollbar(StyleColors.GROUPBOX_BG)}
        """

    @staticmethod
    def horizontal_only() -> str:
        """Style for horizontal-only scroll areas (e.g., for long file paths)."""
        return f"""
                QScrollArea {{
                    background-color: transparent;
                    border: none;
                }}
                QScrollArea > QWidget > QWidget {{
                    background-color: transparent;
                }}
                {_horizontal_scrollbar(StyleColors.MAIN_BG)}
            """


class ProgressBarStyles:

    @staticmethod
    def default() -> str:
        return f"""
            QProgressBar {{
                border: 1px solid {StyleColors.INPUT_BORDER};
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                background-color: {StyleColors.INPUT_BG};
                text-align: center;
                color: {StyleColors.TEXT_PRIMARY};
                height: 20px;
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
            }}
            QProgressBar::chunk {{
                background-color: {StyleColors.BUTTON_HOVER};
                border-radius: 2px;
                margin: 1px;
            }}
        """


class LineEditStyles:

    @staticmethod
    def line_edit() -> str:
        return f"""
            QLineEdit {{
                background-color: transparent;
                border: 1px solid {StyleColors.BUTTON_BG};
                border-radius: {StyleDimensions.BORDER_RADIUS_LARGE};
                color: {StyleColors.TEXT_PRIMARY};
                padding: {StyleDimensions.PADDING};
                font-family: {StyleFonts.FONT_COURIER};
                font-size: {StyleDimensions.FONT_SIZE_LARGE};
                selection-background-color: {StyleColors.BUTTON_HOVER};
            }}
        """

    @staticmethod
    def search() -> str:
        return f"""
            QLineEdit {{
                background-color: {StyleColors.INPUT_BG};
                color: {StyleColors.TEXT_PRIMARY};
                border: 1px solid {StyleColors.INPUT_BORDER};
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                padding: {StyleDimensions.PADDING};
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                margin-left: {StyleDimensions.MARGIN};
                margin-right: {StyleDimensions.MARGIN};
            }}
            QLineEdit:hover {{
                border: 1px solid {StyleColors.BUTTON_HOVER};
            }}
            QLineEdit:focus {{
                border: 1px solid {StyleColors.BUTTON_HOVER};
            }}
        """


class StatusBarStyles:

    @staticmethod
    def default() -> str:
        return f"""
            QStatusBar {{
                background-color: {StyleColors.MAIN_BG};
                border: none;
                margin: {StyleDimensions.MARGIN};
            }}
            QStatusBar::item {{
                background-color: transparent;
                border: none;
            }}
        """


class TreeWidgetStyles:

    # Down arrow icon path
    _down_arrow_path = str(ASSETS_DIR / "filled_down_arrow_white.svg").replace("\\", "/")
    # Right arrow icon path
    _right_arrow_path = str(ASSETS_DIR / "filled_right_arrow_white.svg").replace("\\", "/")

    @staticmethod
    def metadata() -> str:
        return f"""
            QTreeWidget {{
                background-color: {StyleColors.INPUT_BG};
                color: {StyleColors.TEXT_PRIMARY};
                border: none;
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                font-size: {StyleDimensions.FONT_SIZE_NORMAL};
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 2px 0px;
            }}
            QTreeWidget::item:selected {{
                background-color: {StyleColors.BUTTON_BG};
            }}
            QTreeWidget::item:hover {{
                background-color: {StyleColors.BUTTON_BG};
            }}
            QHeaderView {{
                background-color: {StyleColors.INPUT_BG};
            }}
            QHeaderView::section {{
                background-color: {StyleColors.INPUT_BG};
                color: {StyleColors.TEXT_PRIMARY};
                border: none;
                border-right: 2px solid {StyleColors.BUTTON_BG};
                padding: 0px;
                margin: 0px;
                min-height: 16px;
                max-height: 16px;
            }}
            QHeaderView::section:last {{
                border-right: none;
            }}
            QTreeWidget::branch {{
                background-color: {StyleColors.INPUT_BG};
            }}
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {{
                border-image: none;
                image: url({TreeWidgetStyles._right_arrow_path});
                width: 16px;
                height: 16px;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
            }}
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {{
                border-image: none;
                image: url({TreeWidgetStyles._down_arrow_path});
                width: 16px;
                height: 16px;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
            }}
            {_vertical_scrollbar(StyleColors.INPUT_BG)}
            {_horizontal_scrollbar(StyleColors.INPUT_BG)}
        """


class TextEditStyles:
    """Styles for QTextEdit widgets."""

    @staticmethod
    def metadata() -> str:
        """Read-only text display for raw image metadata."""
        return f"""
            QTextEdit {{
                background-color: {StyleColors.INPUT_BG};
                border: none;
                border-radius: {StyleDimensions.BORDER_RADIUS_SMALL};
                color: {StyleColors.TEXT_PRIMARY};
                padding: {StyleDimensions.PADDING};
                font-family: {StyleFonts.FONT_COURIER};
                font-size: {StyleDimensions.FONT_SIZE_EXTRA_LARGE};
                selection-background-color: {StyleColors.BUTTON_HOVER};
            }}
            {_vertical_scrollbar(StyleColors.INPUT_BG, "QTextEdit ")}
            {_horizontal_scrollbar(StyleColors.INPUT_BG, "QTextEdit ")}
        """


class SplitterStyles:
    """Styles for QSplitter widgets.

    Note: the CollapsibleSplitter handle uses custom painting rather
    than CSS, so these colours are consumed directly by the handle's
    ``paintEvent``.  They are centralised here so that every visual
    property lives in ``app_styles``.
    """

    # Handle colours (read by CollapsibleSplitterHandle.paintEvent)
    HANDLE_COLOR = StyleColors.BUTTON_BG
    HANDLE_HOVER_COLOR = StyleColors.BUTTON_HOVER
    HANDLE_PRESSED_COLOR = StyleColors.BUTTON_PRESSED
    ARROW_COLOR = StyleColors.TEXT_PRIMARY


class ToolBarStyles:
    """Styles for the matplotlib ``NavigationToolbar2QT``.

    Centralised here so the dark-theme toolbar appearance lives in one
    place instead of being duplicated as an inline stylesheet in every
    module that embeds a navigation toolbar.  Pair with
    ``AppStyles.apply_toolbar_icon_color`` to recolour the toolbar icons.
    """

    @staticmethod
    def navigation(hover_color: str = StyleColors.BUTTON_HOVER) -> str:
        """Return the stylesheet for a navigation toolbar.

        Every visible sub-element (the bar, the tool buttons, the group
        separators, and the coordinate-readout label) is pinned to the app
        palette, so the toolbar keeps its dark-theme appearance even when
        the host OS is in light mode and would otherwise tint un-styled
        child widgets.  Pair with ``AppStyles.apply_toolbar_icon_color`` to
        pin the icon colour the same way.

        :param hover_color: Background colour for hovered and active
            (checked) tool buttons.  Defaults to the accent hover colour.
        """
        return f"""
            QToolBar {{
                background-color: {StyleColors.GROUPBOX_BG};
                border: none;
                spacing: 4px;
            }}
            QToolBar::separator {{
                background-color: {StyleColors.BUTTON_BG};
                width: 1px;
                margin: 4px 3px;
            }}
            QToolButton {{
                color: {StyleColors.TEXT_PRIMARY};
                background-color: transparent;
                border: none;
                padding: 4px;
            }}
            QToolButton:hover {{
                background-color: {hover_color};
                border-radius: 4px;
            }}
            QToolButton:pressed {{
                background-color: {StyleColors.BUTTON_PRESSED};
                border-radius: 4px;
            }}
            QToolButton:checked {{
                background-color: {hover_color};
                border-radius: 4px;
            }}
            QLabel {{
                color: {StyleColors.TEXT_PRIMARY};
                background-color: transparent;
            }}
        """


class AppStyles:

    Colors = StyleColors
    Dimensions = StyleDimensions
    Window = WindowStyles
    GroupBox = GroupBoxStyles
    Label = LabelStyles
    Button = ButtonStyles
    SpinBox = SpinBoxStyles
    AppText = ApplicationText
    AppToolTips = ToolTips
    CheckBox = CheckBoxStyles
    ComboBox = ComboBoxStyles
    ScrollArea = ScrollAreaStyles
    ProgressBar = ProgressBarStyles
    StatusBar = StatusBarStyles
    LineEdit = LineEditStyles
    TextEdit = TextEditStyles
    TreeWidget = TreeWidgetStyles
    Splitter = SplitterStyles
    ToolBar = ToolBarStyles

    @staticmethod
    def apply_toolbar_icon_color(toolbar, color: str = StyleColors.TEXT_PRIMARY) -> None:
        """Force all NavigationToolbar2QT icons to a specific color.

        Matplotlib toolbar icons are dark-on-transparent PNGs. On Windows with
        a light system theme Qt may also apply palette tinting, leaving icons
        dark against the app's dark toolbar background. This method repaints
        every action icon using SourceIn composition: the icon silhouette
        (alpha channel) is preserved while all opaque pixels are filled with
        `color`, making the result theme-independent.

        Call this once immediately after ``NavigationToolbar2QT(canvas, parent)``
        is constructed.

        Args:
            toolbar: A ``NavigationToolbar2QT`` instance.
            color:   Any Qt-parseable color string (default: ``TEXT_PRIMARY``
                     white, ``"#ffffff"``).
        """
        from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
        from PySide6.QtCore import Qt

        target_color = QColor(color)
        icon_size = toolbar.iconSize()

        for action in toolbar.actions():
            icon = action.icon()
            if icon.isNull():
                continue

            # Prefer the exact icon size used by the toolbar; fall back to the
            # first available size if the toolbar size is not listed.
            sizes = icon.availableSizes()
            size = icon_size if icon_size in sizes or not sizes else sizes[0]

            source_pm = icon.pixmap(size)
            if source_pm.isNull():
                continue

            # Paint a new pixmap: draw the original (preserving shape), then
            # flood-fill the opaque region with the target colour.
            colored_pm = QPixmap(source_pm.size())
            colored_pm.fill(Qt.GlobalColor.transparent)
            painter = QPainter(colored_pm)
            painter.drawPixmap(0, 0, source_pm)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceIn
            )
            painter.fillRect(colored_pm.rect(), target_color)
            painter.end()

            action.setIcon(QIcon(colored_pm))