"""
Plot Exporter

Exports all currently displayed ASV plots to a user-selected directory.
Each plot is exported as:
- PNG (high-resolution raster)
- SVG (vector graphic)
- CSV (tabular data: Slice Index, value column, Image Name)

When an ``execution_history_lookup`` is provided, one execution-history
CSV per unique site/step among the exported plots is written at the
export root (every plot of the same step shares identical execution
history, so the file is step-level rather than per-plot).

Directory structure::

    <user-chosen-directory>/
    └── Exported_Plots_YYYYMMDD_HHMMSS/
        ├── SiteName_StepName_ExecutionHistory.csv
        ├── SiteName_StepName_Detector_FieldLabel/
        │   ├── FieldLabel.png
        │   ├── FieldLabel.svg
        │   └── FieldLabel.csv
        ├── SiteName_StepName_Detector_FieldLabel/
        │   ├── ...
        └── ...
"""
import csv
import logging
import re
from collections import namedtuple
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import QFileDialog, QWidget
from script_modules.app_styles import AppStyles
from script_modules.metadata_query import build_execution_history_rows


logger = logging.getLogger(__name__)

# DPI for raster (PNG) exports
EXPORT_PNG_DPI = AppStyles.Dimensions.EXPORT_PNG_DPI

# Result of export_all_plots: the created export directory (or None),
# the number of plots fully exported, and a short error message (or None).
ExportResult = namedtuple("ExportResult", ["export_dir", "ok_count", "error"])


def sanitize_filename(name: str, max_length: int = 80) -> str:
    """
    Replace filesystem-unsafe characters with underscores and collapse
    runs of underscores/whitespace.

    :param name: Raw string to sanitize.
    :param max_length: Maximum character length for the result.
    :return: Filesystem-safe string.
    """
    # Replace common unsafe characters and whitespace
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]+', "_", name)
    # Collapse multiple underscores
    safe = re.sub(r"_+", "_", safe)
    # Strip leading/trailing underscores and dots
    safe = safe.strip("_.")
    # Truncate
    return safe[:max_length] if safe else "plot"


def _build_folder_name(plot_widget) -> str:
    """
    Build a descriptive, filesystem-safe folder name from the plot's
    context metadata.

    Uses the composite key segments: site | step | detector | field_path.
    The field_path is simplified to its final segment (the field label
    equivalent).

    :param plot_widget: ASVPlotWidget instance.
    :return: Sanitized folder name string.
    """
    site = plot_widget._site_name or "UnknownSite"
    step = plot_widget._step_name or "UnknownStep"
    detector = plot_widget._detector or "UnknownDetector"

    # Extract the last segment of the field path from the composite key
    # Composite key format: "site|step|detector|Dot.Separated.Field.Path"
    field_segment = "Plot"
    if plot_widget._composite_key:
        parts = plot_widget._composite_key.split("|")
        if len(parts) >= 4:
            # Use the last dotted segment as the field name
            field_path = parts[3]
            field_segment = field_path.rsplit(".", 1)[-1]

    raw_name = f"{site}_{step}_{detector}_{field_segment}"
    return sanitize_filename(raw_name)


def _build_file_stem(plot_widget) -> str:
    """
    Build a concise file stem (no extension) from the plot's field label.

    :param plot_widget: ASVPlotWidget instance.
    :return: Sanitized file stem string.
    """
    # The y_label typically looks like "Landing Energy (V)" — strip the
    # unit portion for a cleaner filename.
    label = plot_widget._y_label or "Plot"
    # Remove trailing parenthesized unit if present
    label = re.sub(r"\s*\(.*?\)\s*$", "", label)
    return sanitize_filename(label)


def _write_csv(
    filepath: Path,
    y_label: str,
    slice_numbers: list,
    values: list,
    image_names: list
):
    """
    Write plot data to a CSV file.

    Datetime values are formatted as ISO 8601 strings. All other values
    are written as-is.

    :param filepath: Destination CSV path.
    :param y_label: Column header for the value column.
    :param slice_numbers: List of slice index integers.
    :param values: List of y-axis values (numeric or datetime).
    :param image_names: List of image filename strings.
    """
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Slice Index", y_label, "Image Name"])
        for idx, val, name in zip(slice_numbers, values, image_names):
            # Format datetime objects as ISO strings
            if isinstance(val, datetime):
                val = val.isoformat()
            writer.writerow([idx, val, name])


def _write_execution_history_csv(
    filepath: Path, headers: list, rows: list
):
    """
    Write flattened execution-history rows to a CSV file.

    :param filepath: Destination CSV path.
    :param headers: Column header strings.
    :param rows: Row value lists aligned with the headers.
    """
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def _export_execution_histories(
    plot_widgets: dict, export_dir: Path, execution_history_lookup
):
    """
    Write one execution-history CSV per unique site/step among the
    plots, at the export root.

    Failures are isolated per site/step: a CSV that cannot be built
    or written is logged and skipped without affecting the plot
    export.

    :param plot_widgets: Dict of {composite_key: ASVPlotWidget}.
    :param export_dir: The timestamped export directory.
    :param execution_history_lookup: Callable(site_name, step_name)
        returning a {slice_index: execution_history} dict.
    """
    contexts = []
    for plot_widget in plot_widgets.values():
        context = (plot_widget._site_name, plot_widget._step_name)
        if context not in contexts:
            contexts.append(context)

    seen_names: dict[str, int] = {}
    for site_name, step_name in contexts:
        try:
            eh_by_slice = execution_history_lookup(site_name, step_name)
            if not eh_by_slice:
                logger.warning(
                    "No execution history for: %s | %s",
                    site_name, step_name
                )
                continue
            headers, rows = build_execution_history_rows(eh_by_slice)
            if not rows:
                continue
            file_name = sanitize_filename(f"{site_name}_{step_name}")
            if file_name in seen_names:
                seen_names[file_name] += 1
                file_name = f"{file_name}_{seen_names[file_name]}"
            else:
                seen_names[file_name] = 0
            csv_path = export_dir / f"{file_name}_ExecutionHistory.csv"
            _write_execution_history_csv(csv_path, headers, rows)
            logger.debug("Saved: %s", csv_path.name)
        except Exception:
            logger.warning(
                "Failed to export execution history for: %s | %s",
                site_name, step_name, exc_info=True
            )


def _save_figure(plot_widget, directory: Path, file_stem: str):
    """
    Save the plot figure as PNG and SVG files.

    Temporarily hides interactive overlay artists (hover marker, select
    marker, annotation) so the exported image is clean.

    :param plot_widget: ASVPlotWidget instance.
    :param directory: Target directory for the files.
    :param file_stem: Base filename without extension.
    """
    figure = plot_widget.figure

    # --- Temporarily hide interactive overlays ---
    hidden_artists = []
    for artist in (
        plot_widget._hover_scatter,
        plot_widget._select_scatter,
        plot_widget._annotation
    ):
        if artist is not None and artist.get_visible():
            artist.set_visible(False)
            hidden_artists.append(artist)

    try:
        png_path = directory / f"{file_stem}.png"
        svg_path = directory / f"{file_stem}.svg"

        figure.savefig(
            str(png_path),
            dpi=EXPORT_PNG_DPI,
            bbox_inches="tight",
            facecolor=figure.get_facecolor(),
            edgecolor="none"
        )
        figure.savefig(
            str(svg_path),
            format="svg",
            bbox_inches="tight",
            facecolor=figure.get_facecolor(),
            edgecolor="none"
        )
        logger.debug("Saved: %s, %s", png_path.name, svg_path.name)
    finally:
        # Restore visibility of hidden artists
        for artist in hidden_artists:
            artist.set_visible(True)


def export_all_plots(
    plot_widgets: dict,
    base_directory_name: str,
    default_browse_dir: str,
    parent_widget: QWidget | None = None,
    progress_callback=None,
    execution_history_lookup=None,
) -> ExportResult:
    """
    Export all displayed plots to a user-selected directory.

    Opens a folder selection dialog, creates a timestamped export
    directory, and writes PNG, SVG, and CSV files for every plot.
    Per-plot failures are logged and skipped; the returned result
    reports how many plots exported fully.

    :param plot_widgets: Dict of {composite_key: ASVPlotWidget} from
        PlotDisplayArea._plot_widgets.
    :param base_directory_name: Config value for the export folder
        prefix (e.g. "Exported_Plots").
    :param default_browse_dir: Starting directory for the file dialog.
    :param parent_widget: Parent widget for the dialog (for modality).
    :param progress_callback: Optional callable(current, total) for
        progress updates.
    :param execution_history_lookup: Optional callable(site_name,
        step_name) returning a {slice_index: execution_history} dict;
        when provided, one execution-history CSV per unique site/step
        is written at the export root. Execution-history failures are
        logged and do not affect the per-plot result.
    :return: ExportResult(export_dir, ok_count, error).
        ExportResult(None, 0, None) if the user cancelled the dialog
        (or there was nothing to export); ExportResult(None, 0, message)
        if the export directory could not be created; otherwise
        ExportResult(export_dir, ok_count, None) where ok_count is the
        number of plots that exported without error.
    """
    if not plot_widgets:
        logger.warning("No plots to export.")
        return ExportResult(None, 0, None)

    # --- Ask user where to save ---
    chosen_dir = QFileDialog.getExistingDirectory(
        parent_widget,
        "Select Export Directory",
        default_browse_dir,
        QFileDialog.Option.ShowDirsOnly
    )
    if not chosen_dir:
        return ExportResult(None, 0, None)  # User cancelled

    # --- Create timestamped export directory ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = base_directory_name or "Exported_Plots"
    export_dir = Path(chosen_dir) / f"{base_name}_{timestamp}"

    try:
        export_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.error(
            "Failed to create export directory: %s", export_dir, exc_info=True
        )
        return ExportResult(
            None, 0, f"Could not create export directory: {export_dir}"
        )

    # --- Execution-history CSVs (one per unique site/step) ---
    if execution_history_lookup is not None:
        _export_execution_histories(
            plot_widgets, export_dir, execution_history_lookup
        )

    # --- Export each plot ---
    total = len(plot_widgets)
    ok_count = 0
    seen_folder_names: dict[str, int] = {}

    for index, (composite_key, plot_widget) in enumerate(plot_widgets.items()):
        # Build unique folder name (handle duplicates from different keys
        # that might sanitize to the same string)
        folder_name = _build_folder_name(plot_widget)
        if folder_name in seen_folder_names:
            seen_folder_names[folder_name] += 1
            folder_name = f"{folder_name}_{seen_folder_names[folder_name]}"
        else:
            seen_folder_names[folder_name] = 0

        plot_dir = export_dir / folder_name
        plot_ok = True
        try:
            plot_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.error(
                "Failed to create plot directory: %s", plot_dir, exc_info=True
            )
            continue

        file_stem = _build_file_stem(plot_widget)

        # Save figure as PNG and SVG
        try:
            _save_figure(plot_widget, plot_dir, file_stem)
        except Exception:
            logger.error(
                "Failed to save figure for: %s", composite_key, exc_info=True
            )
            plot_ok = False

        # Write CSV data
        try:
            csv_path = plot_dir / f"{file_stem}.csv"
            _write_csv(
                filepath=csv_path,
                y_label=plot_widget._y_label,
                slice_numbers=plot_widget._slice_numbers,
                values=plot_widget._values,
                image_names=plot_widget._image_names
            )
            logger.debug("Saved: %s", csv_path.name)
        except Exception:
            logger.error(
                "Failed to write CSV for: %s", composite_key, exc_info=True
            )
            plot_ok = False

        if plot_ok:
            ok_count += 1

        # Report progress
        if progress_callback:
            progress_callback(index + 1, total)

    logger.info(
        "Exported %d of %d plot(s) to: %s", ok_count, total, export_dir
    )
    return ExportResult(export_dir, ok_count, None)