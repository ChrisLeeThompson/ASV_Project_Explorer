"""
Autofocus Sharpness Dialog

Modal dialog that displays a sharpness histogram plot from an Auto Focus
execution result. Shows the three sharpness curves (G1, G2, G3) against
working distance, with vertical marker lines for the Found WD and the
Optimized WD.

When Found WD and Optimized WD are identical, only the Optimized WD line
is drawn to avoid visual overlap.  When they differ, both are shown with
distinct colors and dashed lines.

"""
import logging
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSizePolicy,
)
from PySide6.QtCore import Qt
from script_modules.app_styles import AppStyles


logger = logging.getLogger(__name__)


# ── Sharpness curve colors ──────────────────────────────────────────────────
# G-number convention (confirmed by the user, July 2026):
# G1 = Fine, G2 = Medium, G3 = Coarse.
_COLOR_COARSE   = AppStyles.Colors.COLOR_COARSE   # G3 (Coarse) curve
_COLOR_MEDIUM   = AppStyles.Colors.COLOR_MEDIUM   # G2 (Medium) curve
_COLOR_FINE     = AppStyles.Colors.COLOR_FINE     # G1 (Fine) curve
_COLOR_FOUND_WD = AppStyles.Colors.COLOR_FOUND_WD # Found WD marker
_COLOR_OPT_WD   = AppStyles.Colors.COLOR_OPT_WD   # Optimized / corrected WD marker

# Tolerance for treating FoundWd == OptimizedWd (metres)
_WD_EQUALITY_TOL = 1e-9


class AutofocusSharpnessDialog(QDialog):
    """
    Modal dialog showing the sharpness histogram from an Auto Focus result.

    :param sharpness_data: List of dicts, each containing ``Wd`` (metres),
        ``SharpnessG1``, ``SharpnessG2``, and ``SharpnessG3``.
    :param found_wd: Working distance (metres) found by the AF algorithm,
        or ``None`` if not available.
    :param optimized_wd: Optimized / corrected working distance (metres)
        that was actually applied, or ``None`` if not available.
    :param activity_context: Optional string appended to the window title
        for context (e.g. ``"Slice 42  •  Site 1"``).
    :param parent: Optional parent widget.
    """

    def __init__(
        self,
        sharpness_data: list[dict],
        found_wd: float | None,
        optimized_wd: float | None,
        activity_context: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._sharpness_data = sharpness_data
        self._found_wd = found_wd
        self._optimized_wd = optimized_wd
        self._activity_context = activity_context

        self._setup_window()
        self._create_widgets()
        self._setup_layout()
        self._plot()

    # -----------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------

    def _setup_window(self):
        """Configure dialog title, initial size, and base stylesheet."""
        title = "Sharpness Histogram"
        if self._activity_context:
            title = f"{title}  —  {self._activity_context}"
        self.setWindowTitle(title)
        self.setMinimumSize(680, 460)
        self.resize(780, 520)
        self.setModal(True)
        self.setStyleSheet(
            f"background-color: {AppStyles.Colors.MAIN_BG};"
            f"color: {AppStyles.Colors.TEXT_PRIMARY};"
        )

    def _create_widgets(self):
        """Create the matplotlib figure, canvas, and navigation toolbar."""
        # ── Figure & canvas ──────────────────────────────────────────
        self.figure = Figure(
            facecolor=AppStyles.Colors.MAIN_BG,
            constrained_layout=True,
        )
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self.ax = self.figure.add_subplot(111)
        self._style_axes(self.ax)

        # ── Navigation toolbar ───────────────────────────────────────
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.toolbar.setStyleSheet(
            f"""
            QToolBar {{
                background-color: {AppStyles.Colors.GROUPBOX_BG};
                border: none;
                spacing: 4px;
            }}
            QToolButton {{
                color: {AppStyles.Colors.TEXT_PRIMARY};
                background-color: transparent;
                border: none;
                padding: 4px;
            }}
            QToolButton:hover {{
                background-color: {AppStyles.Colors.BUTTON_BG};
                border-radius: 3px;
            }}
            """
        )
        AppStyles.apply_toolbar_icon_color(self.toolbar)

    def _setup_layout(self):
        """Arrange toolbar, canvas, and close button vertically."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
            AppStyles.Dimensions.LAYOUT_CONTENTS_MARGIN,
        )
        layout.setSpacing(AppStyles.Dimensions.LAYOUT_VSPACING)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        layout.addLayout(button_row)

    # -----------------------------------------------------------------
    # Plotting
    # -----------------------------------------------------------------

    def _plot(self):
        """Render the sharpness curves and WD marker lines."""
        ax = self.ax
        # Filter to well-formed points — raw JSON entries may be missing
        # keys, which would otherwise raise KeyError during extraction.
        required_keys = ("Wd", "SharpnessG1", "SharpnessG2", "SharpnessG3")
        data = [
            pt for pt in self._sharpness_data
            if all(k in pt for k in required_keys)
        ]

        if not data:
            ax.text(
                0.5, 0.5,
                "No sharpness data available",
                ha="center", va="center",
                transform=ax.transAxes,
                color=AppStyles.Colors.TEXT_PRIMARY,
                fontsize=AppStyles.Dimensions.PLOT_TITLE_FONT_SIZE,
            )
            self.canvas.draw_idle()
            return

        # ── Extract series (WD: metres → mm) ─────────────────────────
        wd_mm = [pt["Wd"] * 1000.0 for pt in data]
        g1    = [pt["SharpnessG1"]  for pt in data]
        g2    = [pt["SharpnessG2"]  for pt in data]
        g3    = [pt["SharpnessG3"]  for pt in data]

        point_style = dict(marker="o", markersize=4, linewidth=AppStyles.Dimensions.PLOT_LINE_WIDTH)

        ax.plot(wd_mm, g3, color=_COLOR_COARSE, label="Coarse (G3)", **point_style)
        ax.plot(wd_mm, g2, color=_COLOR_MEDIUM, label="Medium (G2)", **point_style)
        ax.plot(wd_mm, g1, color=_COLOR_FINE,   label="Fine (G1)", **point_style)

        # ── Vertical WD markers ───────────────────────────────────────
        found_wd     = self._found_wd
        optimized_wd = self._optimized_wd

        # Decide whether Found WD and Optimized WD are distinct
        both_present  = found_wd is not None and optimized_wd is not None
        values_differ = (
            both_present
            and abs(found_wd - optimized_wd) > _WD_EQUALITY_TOL
        )

        if values_differ:
            # Draw both lines with their respective colors
            ax.axvline(
                x=found_wd * 1000.0,
                color=_COLOR_FOUND_WD,
                linewidth=AppStyles.Dimensions.PLOT_LINE_WIDTH,
                linestyle="--",
                label=f"Found WD ({found_wd * 1000.0:.4f} mm)",
            )
            ax.axvline(
                x=optimized_wd * 1000.0,
                color=_COLOR_OPT_WD,
                linewidth=AppStyles.Dimensions.PLOT_LINE_WIDTH,
                linestyle="--",
                label=f"Optimized WD ({optimized_wd * 1000.0:.4f} mm)",
            )
        elif optimized_wd is not None:
            # Identical values (or only OptimizedWd present) — one line suffices
            ax.axvline(
                x=optimized_wd * 1000.0,
                color=_COLOR_OPT_WD,
                linewidth=AppStyles.Dimensions.PLOT_LINE_WIDTH,
                linestyle="--",
                label=f"Optimized WD ({optimized_wd * 1000.0:.4f} mm)",
            )
        elif found_wd is not None:
            # Only FoundWd available
            ax.axvline(
                x=found_wd * 1000.0,
                color=_COLOR_FOUND_WD,
                linewidth=AppStyles.Dimensions.PLOT_LINE_WIDTH,
                linestyle="--",
                label=f"Found WD ({found_wd * 1000.0:.4f} mm)",
            )

        # ── Labels, title, and legend ─────────────────────────────────
        spine_color = AppStyles.Colors.PLOT_SPINE_COLOR

        ax.set_xlabel("Working Distance (mm)", color=spine_color)
        ax.set_ylabel("Sharpness Score",       color=spine_color)
        ax.set_title(
            "Sharpness Histogram",
            color=spine_color,
            fontsize=AppStyles.Dimensions.PLOT_TITLE_FONT_SIZE
        )
        ax.legend(
            facecolor=AppStyles.Colors.GROUPBOX_BG,
            edgecolor=AppStyles.Colors.PLOT_SPINE_COLOR,
            labelcolor=AppStyles.Colors.TEXT_PRIMARY,
            fontsize=9,
        )

        self.canvas.draw_idle()

    # -----------------------------------------------------------------
    # Styling
    # -----------------------------------------------------------------

    @staticmethod
    def _style_axes(ax) -> None:
        """Apply dark theme to axes consistent with the rest of the app."""
        ax.set_facecolor(AppStyles.Colors.MAIN_BG)
        spine_color = AppStyles.Colors.PLOT_SPINE_COLOR
        ax.tick_params(colors=spine_color, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(spine_color)