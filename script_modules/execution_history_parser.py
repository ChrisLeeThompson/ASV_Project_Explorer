"""
Execution History Parser

Module handles parsing the ExecutionHistory.json file from ASV projects.
It traverses the deeply nested .NET-serialized JSON hierarchy to extract
activity-level execution data for each slice, using the configuration
to determine which fields to extract per activity type.

The ExecutionHistory.json hierarchy:
    Root
    └── Executions.$values[]
        ├── CustomExecutionHistory      <- setup runs (skipped)
        └── RunExecutionHistory         <- actual S&V run
            └── SiteExecutionHistory    (SiteName)
                └── SliceExecutionHistory (SliceIndex)
                    └── RecipeExecutionHistory (RecipeName)
                        └── RepeatedActivityExecutionHistory
                            └── ActivityIterationExecutionHistory
                                └── ActivityExecutionHistory  <- target

The parser returns structured data keyed by site name and slice index,
allowing the consolidation logic to merge execution history into each
image based on its FileNameSliceIndex.

Output structure::

    {
        "Life Science - Cryo": {
            0: {
                "Milling": {
                    "Slicing": {
                        "ExecutionOrder": 1,
                        "StartedAt": "...",
                        "FinishedAt": "...",
                        "CalculatedDuration": "11.5s",
                        "Status": "Finished",
                        "Message": "",
                        "Data": { "FiducialMatch": { "Score": 0.93, ... } }
                    }
                },
                "SEM Imaging": {
                    "Auto Focus": { ... },
                    ...
                }
            },
            1: { ... }
        }
    }

"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


# =========================================================================
# Public API
# =========================================================================

def parse_execution_history(
    file_path: Path,
    config: dict,
) -> dict:
    """
    Parse an ASV ExecutionHistory.json file and extract activity data.

    Navigates the .NET-serialized JSON hierarchy using the traversal
    types defined in the configuration, extracts common and
    activity-specific fields, and computes execution order and
    duration for each activity.

    :param file_path: Path to the ExecutionHistory.json file.
    :param config: The ``ExecutionHistoryConfig`` section from the
        application configuration file.
    :return: Nested dictionary keyed by site name, then slice index
        (int), then recipe name, then activity name. Returns an
        empty dict if the file is absent or contains no runs.
    :raises json.JSONDecodeError: If the file contains malformed JSON.
    :raises OSError: If the file cannot be read.
    """
    # Load JSON file
    raw_data = _load_json_file(file_path)
    if raw_data is None:
        return {}

    # Unpack config sections
    traversal_types = config.get("TraversalTypes", {})
    common_fields_config = config.get("CommonFields", {})
    common_fields = common_fields_config.get("Fields", [])
    activity_types = config.get("ActivityTypes", {})

    # Find all RunExecutionHistory nodes (the actual ASV runs)
    run_type = traversal_types.get("RunLevel", "RunExecutionHistory")
    run_nodes = _find_nodes_by_type(raw_data, run_type)

    if not run_nodes:
        logger.warning(
            "No RunExecutionHistory nodes found in "
            f"{file_path.name}. The file may only contain setup runs."
        )
        return {}

    logger.info(
        f"Found {len(run_nodes)} run(s) in {file_path.name}."
    )

    # Process each run and merge results
    result = {}
    for run_node in run_nodes:
        run_data = _process_run(
            run_node=run_node,
            traversal_types=traversal_types,
            common_fields=common_fields,
            activity_types=activity_types,
        )
        # Merge run data into result (later runs overwrite earlier ones
        # for the same site/slice, which is the expected behavior for
        # resumed runs)
        for site_name, slices in run_data.items():
            if site_name not in result:
                result[site_name] = {}
            for slice_index, recipes in slices.items():
                if slice_index not in result[site_name]:
                    result[site_name][slice_index] = {}
                for recipe_name, activities in recipes.items():
                    if recipe_name not in result[site_name][slice_index]:
                        result[site_name][slice_index][recipe_name] = {}
                    result[site_name][slice_index][recipe_name].update(
                        activities
                    )

    # Compute execution order and duration for each slice
    for site_name, slices in result.items():
        for slice_index, recipes in slices.items():
            _assign_execution_order_and_duration(recipes)

    # Log summary
    total_slices = sum(
        len(slices) for slices in result.values()
    )
    total_activities = sum(
        len(activities)
        for slices in result.values()
        for recipes in slices.values()
        for activities in recipes.values()
    )
    logger.info(
        f"Parsed execution history: {len(result)} site(s), "
        f"{total_slices} slice(s), {total_activities} activity entries."
    )

    return result


# =========================================================================
# Run / Site / Slice / Recipe Processing
# =========================================================================

def _process_run(
    run_node: dict,
    traversal_types: dict,
    common_fields: list[str],
    activity_types: dict,
) -> dict:
    """
    Process a single RunExecutionHistory node.

    :param run_node: The RunExecutionHistory dict.
    :param traversal_types: TraversalTypes config section.
    :param common_fields: List of common field paths to extract.
    :param activity_types: ActivityTypes config section.
    :return: Dict keyed by site name -> slice index -> recipe -> activity.
    """
    site_type = traversal_types.get("SiteLevel", "SiteExecutionHistory")
    site_nodes = _find_nodes_by_type(run_node, site_type)

    result = {}
    for site_node in site_nodes:
        site_name = site_node.get("SiteName", "Unknown Site")
        site_data = _process_site(
            site_node=site_node,
            traversal_types=traversal_types,
            common_fields=common_fields,
            activity_types=activity_types,
        )
        if site_data:
            result[site_name] = site_data

    return result


def _process_site(
    site_node: dict,
    traversal_types: dict,
    common_fields: list[str],
    activity_types: dict,
) -> dict:
    """
    Process a single SiteExecutionHistory node.

    :param site_node: The SiteExecutionHistory dict.
    :param traversal_types: TraversalTypes config section.
    :param common_fields: List of common field paths to extract.
    :param activity_types: ActivityTypes config section.
    :return: Dict keyed by slice index (int) -> recipe -> activity.
    """
    slice_type = traversal_types.get(
        "SliceLevel", "SliceExecutionHistory"
    )
    slice_nodes = _find_nodes_by_type(site_node, slice_type)

    result = {}
    for slice_node in slice_nodes:
        slice_index = slice_node.get("SliceIndex")
        if slice_index is None:
            logger.warning("SliceExecutionHistory missing SliceIndex.")
            continue

        # The JSON stores SliceIndex as 0-based, but ASV image
        # filenames use 1-based numbering (_s0001.tif is the first
        # slice).  Convert here at the parsing boundary so every
        # downstream consumer sees indices that match the filenames.
        slice_index += 1

        slice_data = _process_slice(
            slice_node=slice_node,
            traversal_types=traversal_types,
            common_fields=common_fields,
            activity_types=activity_types,
        )
        if slice_data:
            result[slice_index] = slice_data

    return result


def _process_slice(
    slice_node: dict,
    traversal_types: dict,
    common_fields: list[str],
    activity_types: dict,
) -> dict:
    """
    Process a single SliceExecutionHistory node.

    :param slice_node: The SliceExecutionHistory dict.
    :param traversal_types: TraversalTypes config section.
    :param common_fields: List of common field paths to extract.
    :param activity_types: ActivityTypes config section.
    :return: Dict keyed by recipe name -> activity name -> activity data.
    """
    recipe_type = traversal_types.get(
        "RecipeLevel", "RecipeExecutionHistory"
    )
    recipe_nodes = _find_nodes_by_type(slice_node, recipe_type)

    result = {}
    for recipe_node in recipe_nodes:
        recipe_name = recipe_node.get("RecipeName", "Unknown Recipe")
        activities = _process_recipe(
            recipe_node=recipe_node,
            traversal_types=traversal_types,
            common_fields=common_fields,
            activity_types=activity_types,
        )
        if activities:
            result[recipe_name] = activities

    return result


def _process_recipe(
    recipe_node: dict,
    traversal_types: dict,
    common_fields: list[str],
    activity_types: dict,
) -> dict:
    """
    Process a single RecipeExecutionHistory node.

    Navigates through RepeatedActivity -> Iteration -> Activity
    to reach the ActivityExecutionHistory nodes containing result data.

    :param recipe_node: The RecipeExecutionHistory dict.
    :param traversal_types: TraversalTypes config section.
    :param common_fields: List of common field paths to extract.
    :param activity_types: ActivityTypes config section.
    :return: Dict keyed by activity name -> activity data.
    """
    repeated_type = traversal_types.get(
        "RepeatedActivityLevel", "RepeatedActivityExecutionHistory"
    )
    iteration_type = traversal_types.get(
        "IterationLevel", "ActivityIterationExecutionHistory"
    )
    activity_type = traversal_types.get(
        "ActivityLevel", "ActivityExecutionHistory"
    )

    # Navigate: RepeatedActivity -> Iteration (highest index) -> Activity
    repeated_nodes = _find_nodes_by_type(recipe_node, repeated_type)

    result = {}
    for repeated_node in repeated_nodes:
        # Find all iterations and pick the highest index
        iteration_nodes = _find_nodes_by_type(
            repeated_node, iteration_type
        )
        if not iteration_nodes:
            continue

        # Sort by IterationIndex descending, take the latest
        iteration_nodes.sort(
            key=lambda n: n.get("IterationIndex", 0),
            reverse=True,
        )
        latest_iteration = iteration_nodes[0]

        # Find the ActivityExecutionHistory within this iteration
        activity_nodes = _find_nodes_by_type(
            latest_iteration, activity_type
        )

        for activity_node in activity_nodes:
            activity_data = _extract_activity_data(
                activity_node=activity_node,
                common_fields=common_fields,
                activity_types=activity_types,
            )
            if activity_data:
                activity_name = activity_data.get(
                    "ActivityName", "Unknown"
                )
                result[activity_name] = activity_data

    return result


# =========================================================================
# Activity Data Extraction
# =========================================================================

def _extract_activity_data(
    activity_node: dict,
    common_fields: list[str],
    activity_types: dict,
) -> dict:
    """
    Extract common and activity-specific data from an
    ActivityExecutionHistory node.

    :param activity_node: The ActivityExecutionHistory dict.
    :param common_fields: List of dot-notation field paths to extract
        from every activity (e.g. ``"Result.Status"``).
    :param activity_types: ActivityTypes config section with per-activity
        extraction rules.
    :return: Flat dict with extracted fields plus a ``Data`` dict
        for activity-specific results.
    """
    # Extract common fields
    extracted = {}
    for field_path in common_fields:
        key = field_path.split(".")[-1]
        value = _resolve_dot_path(activity_node, field_path)
        extracted[key] = value

    activity_name = extracted.get("ActivityName", "Unknown")

    # Look up activity-specific config
    activity_config = activity_types.get(activity_name)
    if activity_config is None:
        logger.warning(
            f"Unknown activity type encountered: '{activity_name}'. "
            "Only common fields will be extracted. Consider adding "
            "this activity to ExecutionHistoryConfig.ActivityTypes."
        )
        extracted["Data"] = {}
        return extracted

    # Validate FunctionType if configured and present
    expected_function_type = activity_config.get("FunctionType")
    if expected_function_type:
        actual_function_type = _resolve_dot_path(
            activity_node, "Result.FunctionType"
        )
        if (
            actual_function_type
            and actual_function_type != expected_function_type
        ):
            logger.warning(
                f"FunctionType mismatch for '{activity_name}': "
                f"expected '{expected_function_type}', "
                f"got '{actual_function_type}'."
            )

    # Extract activity-specific data paths from Result.Data
    data_paths = activity_config.get("DataPaths", [])
    result_data = _resolve_dot_path(activity_node, "Result.Data")

    activity_data = {}
    if result_data and isinstance(result_data, dict) and data_paths:
        for data_path in data_paths:
            value = _resolve_dot_path(result_data, data_path)
            if value is not None:
                _set_nested_value(activity_data, data_path, value)

    # Handle IncludeSharpnessData flag
    if (
        activity_config.get("IncludeSharpnessData", False)
        and isinstance(result_data, dict)
    ):
        sharpness_data = result_data.get("SharpnessData")
        if sharpness_data is not None:
            activity_data["SharpnessData"] = sharpness_data

    extracted["Data"] = activity_data
    return extracted


# =========================================================================
# Execution Order and Duration
# =========================================================================

def _assign_execution_order_and_duration(recipes: dict):
    """
    Assign ExecutionOrder and CalculatedDuration to all activities
    within a single slice.

    Collects all activities across recipes, sorts by StartedAt
    chronologically, and assigns 1-based execution order. Duration
    is calculated from each activity's StartedAt and FinishedAt.

    Modifies activity dicts in place.

    :param recipes: Dict of recipe_name -> activity_name -> activity_data
        for a single slice.
    """
    # Collect all activity references with their StartedAt for sorting
    all_activities = []
    for recipe_activities in recipes.values():
        for activity_data in recipe_activities.values():
            if isinstance(activity_data, dict):
                all_activities.append(activity_data)

    # Sort by StartedAt chronologically. StartedAt can be JSON null
    # for aborted runs, so fall back to "" to keep the sort str-only.
    all_activities.sort(key=lambda a: a.get("StartedAt") or "")

    # Assign execution order and calculate duration
    for order, activity in enumerate(all_activities, start=1):
        activity["ExecutionOrder"] = order
        activity["CalculatedDuration"] = _calculate_duration(
            activity.get("StartedAt", ""),
            activity.get("FinishedAt", ""),
        )


def _calculate_duration(started_at: str, finished_at: str) -> str:
    """
    Calculate a human-readable duration string between two ISO timestamps.

    Returns formatted strings like ``"11.5s"``, ``"2m 30.1s"``,
    or ``"1h 5m 12.0s"``. Returns an empty string if either
    timestamp is missing or cannot be parsed.

    :param started_at: ISO format start timestamp.
    :param finished_at: ISO format end timestamp.
    :return: Formatted duration string, or empty string.
    """
    if not started_at or not finished_at:
        return ""
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(finished_at)
        delta = (end - start).total_seconds()
        if delta < 0:
            return ""
        if delta < 60:
            return f"{delta:.1f}s"
        elif delta < 3600:
            minutes = int(delta // 60)
            seconds = delta % 60
            return f"{minutes}m {seconds:.1f}s"
        else:
            hours = int(delta // 3600)
            remainder = delta % 3600
            minutes = int(remainder // 60)
            seconds = remainder % 60
            return f"{hours}h {minutes}m {seconds:.1f}s"
    except (ValueError, TypeError) as e:
        logger.debug(f"Could not parse timestamps for duration: {e}")
        return ""


# =========================================================================
# JSON Navigation Helpers
# =========================================================================

def _load_json_file(file_path: Path) -> dict | None:
    """
    Load a JSON file with BOM handling.

    :param file_path: Path to the JSON file.
    :return: Parsed dict, or None if the file does not exist.
    :raises json.JSONDecodeError: If the file contains malformed JSON.
    :raises OSError: If the file cannot be read.
    """
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return None

    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        logger.info(f"Loaded {file_path.name} successfully.")
        return data
    except json.JSONDecodeError:
        logger.error(
            f"Failed to parse JSON: {file_path}", exc_info=True
        )
        raise
    except OSError:
        logger.error(
            f"Failed to read file: {file_path}", exc_info=True
        )
        raise


def _get_short_type(node: dict) -> str:
    """
    Extract the short type name from a .NET ``$type`` annotation.

    Example input::

        "AutoSliceAndView.DataModel.Projects.Execution."
        "Progress.RunExecutionHistory, AutoSliceAndView.DataModel"

    Example output: ``"RunExecutionHistory"``

    :param node: Dictionary that may contain a ``$type`` key.
    :return: Short type name, or empty string if not present.
    """
    type_str = node.get("$type", "")
    if not type_str:
        return ""
    # Format: "Namespace.TypeName, AssemblyName"
    full_type = type_str.split(",")[0]
    return full_type.split(".")[-1]


def _get_child_nodes(node: dict) -> list[dict]:
    """
    Get the child execution nodes from ``Executions.$values``.

    :param node: Parent node containing an ``Executions`` key.
    :return: List of child node dicts, or empty list.
    """
    executions = node.get("Executions", {})
    if isinstance(executions, dict):
        return executions.get("$values", [])
    return []


def _find_nodes_by_type(parent: dict, type_name: str) -> list[dict]:
    """
    Find all immediate child nodes matching a given short type name.

    Searches within ``Executions.$values`` of the parent node.

    :param parent: Parent node to search within.
    :param type_name: Short type name to match
        (e.g. ``"SiteExecutionHistory"``).
    :return: List of matching child node dicts.
    """
    children = _get_child_nodes(parent)
    return [
        child for child in children
        if isinstance(child, dict) and _get_short_type(child) == type_name
    ]


def _resolve_dot_path(data: dict, path: str) -> Any:
    """
    Resolve a dot-notation path within a nested dictionary.

    Example: ``_resolve_dot_path(node, "Result.Status")`` returns
    ``node["Result"]["Status"]`` if it exists, otherwise ``None``.

    :param data: The dictionary to traverse.
    :param path: Dot-separated key path.
    :return: The resolved value, or None if any key is missing.
    """
    current = data
    for key in path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


def _set_nested_value(target: dict, path: str, value: Any):
    """
    Set a value in a nested dictionary using a dot-notation path.

    Creates intermediate dicts as needed. For example,
    ``_set_nested_value(d, "FiducialMatch.Score", 0.93)`` produces
    ``{"FiducialMatch": {"Score": 0.93}}``.

    Single-segment paths set directly on the target:
    ``_set_nested_value(d, "Result", "Succeeded")`` produces
    ``{"Result": "Succeeded"}``.

    :param target: The dictionary to set values in.
    :param path: Dot-separated key path.
    :param value: The value to set.
    """
    keys = path.split(".")
    current = target
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value