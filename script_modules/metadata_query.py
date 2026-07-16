"""
Metadata Query Helpers

Pure data functions for querying and extracting values from the
consolidated ASV metadata structure. These functions have no Qt
dependencies and operate solely on the in-memory metadata dictionary.

Used primarily by ASVProjectMetadataTab to populate combo boxes,
extract plot data, and detect units.
"""
import logging
from datetime import datetime


logger = logging.getLogger(__name__)


def get_unique_detectors(images: list[dict]) -> list[str]:
    """
    Extract unique detector names from a list of images, preserving
    the order of first appearance.

    :param images: List of image dictionaries.
    :return: Ordered list of unique detector name strings.
    """
    seen = set()
    detectors = []
    for image in images:
        detector = image.get("FileNameDetector")
        if detector and detector not in seen:
            seen.add(detector)
            detectors.append(detector)
    return detectors


def filter_images_by_detector(images: list[dict], detector: str) -> list[dict]:
    """
    Return only the images matching the given detector name.

    :param images: List of image dictionaries from a step.
    :param detector: The detector name to filter by.
    :return: Filtered list of image dictionaries.
    """
    return [
        img for img in images
        if img.get("FileNameDetector") == detector
    ]


def get_available_plot_fields(
    images: list[dict],
    plot_fields: list[dict]
) -> list[dict]:
    """
    Filter config plot fields to only those that have data in at least
    one image.

    :param images: List of image dictionaries (pre-filtered by detector).
    :param plot_fields: List of plot field definitions from config.
    :return: Filtered list of plot field dictionaries with available data.
    """
    if not images:
        return []

    available = []
    for field in plot_fields:
        path = field["Path"]
        for image in images:
            value = resolve_metadata_path(image, path)
            if value is not None:
                available.append(field)
                break
    return available


def get_slice_indices(images: list[dict]) -> list[int]:
    """
    Extract all slice indices from a list of images.

    :param images: List of image dictionaries (pre-filtered by detector).
    :return: Sorted list of slice index integers.
    """
    indices = []
    for image in images:
        slice_idx = image.get("FileNameSliceIndex")
        if slice_idx is not None:
            try:
                indices.append(int(slice_idx))
            except (ValueError, TypeError):
                continue
    return sorted(indices)


def extract_plot_data(
    images: list[dict],
    field_path: str,
    start_slice: int,
    end_slice: int,
    plot_as_text: bool = False
) -> tuple[list, list, list[str]]:
    """
    Extract paired (slice_index, value, image_name) data for a single
    metadata field from a list of images, applying the slice range filter.

    Supports numeric, unit-suffixed, and datetime values. Fields flagged
    ``plot_as_text`` keep every resolved value verbatim as a string for a
    categorical y-axis instead of parsing to a numeric type.

    :param images: List of image dicts (pre-filtered by detector).
    :param field_path: Dot-separated path into the Metadata dict.
    :param start_slice: Minimum slice index (inclusive).
    :param end_slice: Maximum slice index (inclusive).
    :param plot_as_text: True when the field's values are categorical text
        (the ``PlotAsText`` config setting).
    :return: Tuple of (slice_indices, values, image_names), sorted by
             slice index.
    """
    triples = []
    for image in images:
        # Get slice index
        slice_idx = image.get("FileNameSliceIndex")
        if slice_idx is None:
            continue
        try:
            slice_int = int(slice_idx)
        except (ValueError, TypeError):
            continue

        # Apply slice range filter
        if slice_int < start_slice or slice_int > end_slice:
            continue

        # Resolve the metadata value
        value = resolve_metadata_path(image, field_path)
        if value is None:
            continue

        # Attempt to parse to a plottable type. Text-flagged fields keep
        # every resolved value verbatim (categorical y-axis); other fields
        # keep only numeric/datetime-parseable values.
        if plot_as_text:
            parsed_value = str(value)
        else:
            parsed_value = try_parse_value(value)
            if parsed_value is None:
                continue

        image_name = image.get("ImageName", "")
        triples.append((slice_int, parsed_value, image_name))

    # Sort by slice index
    triples.sort(key=lambda t: t[0])

    if not triples:
        return [], [], []

    slice_indices = [t[0] for t in triples]
    values = [t[1] for t in triples]
    image_names = [t[2] for t in triples]
    return slice_indices, values, image_names


def detect_unit_suffix(images: list[dict], field_path: str) -> str | None:
    """
    Scan images for the first unit-suffixed string value at the given
    metadata field path and return the unit portion.

    Unit-suffixed values follow the pattern "number unit" separated by
    whitespace, e.g. "125.25928 pA", "29.99 kV", "5 nm".

    :param images: List of image dicts (pre-filtered by detector).
    :param field_path: Dot-separated path into the Metadata dict.
    :return: The unit suffix string, or None if no suffixed value found.
    """
    for image in images:
        value = resolve_metadata_path(image, field_path)
        if not isinstance(value, str):
            continue
        parts = value.split(None, 1)
        if len(parts) == 2:
            try:
                float(parts[0])
                return parts[1]
            except ValueError:
                continue
    return None


def try_parse_value(value):
    """
    Attempt to convert a raw metadata value to a plottable type.

    Returns a float, int, or datetime object, or None if the value
    cannot be converted. Handles plain numbers, unit-suffixed strings
    (e.g. "125.25 pA"), and common datetime formats.

    :param value: Raw value from metadata (could be str, int, float, etc.).
    :return: Parsed value or None.
    """
    # Already numeric
    if isinstance(value, (int, float)):
        return value

    # Already datetime
    if isinstance(value, datetime):
        return value

    # String parsing
    if isinstance(value, str):
        # Try direct numeric conversion
        try:
            return float(value)
        except ValueError:
            pass

        # Try unit-suffixed strings: "125.25928 pA", "29.99 kV", "5 nm"
        parts = value.split(None, 1)
        if len(parts) >= 2:
            try:
                return float(parts[0])
            except ValueError:
                pass

        # Try common datetime formats
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue

    return None


def parse_decimal_places(raw) -> int | None:
    """
    Interpret a plot field's configured ``DecimalPlaces`` setting.

    A blank/empty value means "keep full precision" and returns None.
    A non-negative integer (or integer-like string, e.g. 4 or "4") returns
    that int — the number of decimals a plotted value should be rounded to.
    Invalid non-empty input (negative, non-integer, unparseable) is treated
    as blank (returns None) and logged.

    :param raw: Raw config value (e.g. "", "4", 4, None).
    :return: A non-negative int, or None for full precision.
    """
    # Blank / absent -> full precision.
    if raw is None:
        return None
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            parsed = int(stripped)
        except ValueError:
            logger.warning("Ignoring invalid DecimalPlaces value %r", raw)
            return None
    elif isinstance(raw, bool):
        # bool is an int subclass; reject so True/False don't become 1/0.
        logger.warning("Ignoring invalid DecimalPlaces value %r", raw)
        return None
    elif isinstance(raw, int):
        parsed = raw
    else:
        # Floats (even whole ones) and other types: DecimalPlaces is an int.
        logger.warning("Ignoring invalid DecimalPlaces value %r", raw)
        return None

    if parsed < 0:
        logger.warning("Ignoring negative DecimalPlaces value %r", raw)
        return None
    return parsed


def parse_plot_as_text(raw) -> bool:
    """
    Interpret a plot field's configured ``PlotAsText`` setting.

    Absent/None or false means normal numeric plotting (False). Only a
    JSON true enables the categorical text y-axis. Non-bool values are
    treated as False and logged.

    :param raw: Raw config value (e.g. None, true, false).
    :return: True only for a boolean true.
    """
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    logger.warning("Ignoring invalid PlotAsText value %r", raw)
    return False


# Case-insensitive alias -> canonical temperature unit for ConvertToUnit.
_TEMPERATURE_ALIASES = {
    "k": "K", "kelvin": "K",
    "c": "C", "°c": "C", "celsius": "C",
    "f": "F", "°f": "F", "fahrenheit": "F",
}

# Canonical unit -> (scale, offset) such that kelvin = value * scale + offset.
_TO_KELVIN = {
    "K": (1.0, 0.0),
    "C": (1.0, 273.15),
    "F": (5.0 / 9.0, 459.67 * 5.0 / 9.0),
}


def parse_convert_to_unit(raw) -> str | None:
    """
    Interpret a plot field's configured ``ConvertToUnit`` setting.

    Absent/None or a blank string means no conversion (None). Any other
    string is returned stripped but otherwise verbatim — it is both the
    conversion target and the text shown in the y-axis label; whether it
    names a supported unit is decided later by resolve_unit_conversion.
    Non-string values are treated as absent and logged.

    :param raw: Raw config value (e.g. None, "C", "°C", "kelvin").
    :return: The stripped target-unit string, or None for no conversion.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        stripped = raw.strip()
        return stripped if stripped else None
    logger.warning("Ignoring invalid ConvertToUnit value %r", raw)
    return None


def resolve_unit_conversion(
    source_unit, target_unit
) -> tuple[float, float] | None:
    """
    Build the affine map converting values between two temperature units.

    Both units are matched case-insensitively against the supported
    aliases (K/kelvin, C/°C/celsius, F/°F/fahrenheit). When either side
    is unknown — user error, or a non-temperature unit — the mismatch is
    logged and None is returned so the caller plots the original values.

    :param source_unit: Unit the raw metadata values are in (e.g. "K").
    :param target_unit: Requested display unit (e.g. "C").
    :return: (scale, offset) with converted = value * scale + offset,
        or None when the conversion cannot be resolved.
    """
    source_key = (
        _TEMPERATURE_ALIASES.get(source_unit.strip().lower())
        if isinstance(source_unit, str) else None
    )
    target_key = (
        _TEMPERATURE_ALIASES.get(target_unit.strip().lower())
        if isinstance(target_unit, str) else None
    )
    if source_key is None or target_key is None:
        logger.warning(
            "Cannot convert unit %r to %r; plotting original values",
            source_unit, target_unit
        )
        return None
    source_scale, source_offset = _TO_KELVIN[source_key]
    target_scale, target_offset = _TO_KELVIN[target_key]
    return (
        source_scale / target_scale,
        (source_offset - target_offset) / target_scale,
    )


def convert_plot_values(
    values: list, conversion: tuple[float, float] | None
) -> list:
    """
    Apply a unit conversion to the numeric entries of a plotted-values
    list.

    Non-numeric entries (datetime, None, strings) pass through untouched.
    When ``conversion`` is None — or the identity map, e.g. converting a
    unit to one of its own aliases — the original list is returned
    unchanged so integer values keep their integer display.

    :param values: List of plotted y-values (may be mixed types).
    :param conversion: (scale, offset) from resolve_unit_conversion, or
        None for no conversion.
    :return: A new list with numeric entries converted, or the original
        list when there is nothing to convert.
    """
    if conversion is None or conversion == (1.0, 0.0):
        return values
    scale, offset = conversion
    converted = []
    for value in values:
        if isinstance(value, bool):
            converted.append(value)
        elif isinstance(value, (int, float)):
            converted.append(value * scale + offset)
        else:
            converted.append(value)
    return converted


def resolve_plot_unit_and_conversion(
    field_unit: str, detected_unit: str | None, convert_to_unit_raw
) -> tuple[str, tuple[float, float] | None]:
    """
    Decide a plot's display unit and value conversion together.

    The source unit follows the y-axis label rule: a unit detected in the
    actual metadata values wins over the config ``Unit``. When the field
    requests a ``ConvertToUnit`` and it resolves, the display unit is the
    requested string verbatim; otherwise (no request, or an unresolvable
    conversion, which is logged) the source unit and unconverted values
    are kept — label and data always fall back together.

    :param field_unit: The field's config ``Unit`` value.
    :param detected_unit: Unit sniffed from the data by
        detect_unit_suffix, or None.
    :param convert_to_unit_raw: The field's raw ``ConvertToUnit`` config
        value.
    :return: (display_unit, conversion) where conversion is a
        (scale, offset) tuple or None.
    """
    source_unit = detected_unit if detected_unit else field_unit
    target_unit = parse_convert_to_unit(convert_to_unit_raw)
    if target_unit is None:
        return source_unit, None
    conversion = resolve_unit_conversion(source_unit, target_unit)
    if conversion is None:
        return source_unit, None
    return target_unit, conversion


def round_plot_values(values: list, decimals: int | None) -> list:
    """
    Round the numeric entries of a plotted-values list to a fixed number
    of decimal places.

    Non-numeric entries (datetime, None, strings) pass through untouched.
    When ``decimals`` is None the original list is returned unchanged (full
    precision). When ``decimals`` is 0 the numeric entries become ints for
    a clean integer display.

    :param values: List of plotted y-values (may be mixed types).
    :param decimals: Number of decimal places, or None for no rounding.
    :return: A new list with numeric entries rounded, or the original list
        when ``decimals`` is None.
    """
    if decimals is None:
        return values
    rounded = []
    for value in values:
        if isinstance(value, bool):
            rounded.append(value)
        elif isinstance(value, (int, float)):
            rounded.append(
                int(round(value)) if decimals == 0
                else round(value, decimals)
            )
        else:
            rounded.append(value)
    return rounded


def resolve_metadata_path(image: dict, path: str):
    """
    Navigate a dot-separated path into an image's Metadata dictionary.

    For example, path "MicroscopeMetadata.EBeamDeceleration.LandingEnergy"
    resolves to image["Metadata"]["MicroscopeMetadata"]["EBeamDeceleration"]["LandingEnergy"].

    :param image: Image dictionary containing a "Metadata" key.
    :param path: Dot-separated path string.
    :return: The resolved value, or None if any key is missing.
    """
    current = image.get("Metadata", {})
    for key in path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current