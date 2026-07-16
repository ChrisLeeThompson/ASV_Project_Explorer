"""
Project File Parser

Module handles parsing the Project.AsvProject file from ASV projects.
It extracts user-facing project parameters organised by site, recipe,
and activity, using configuration rules to determine which fields to
extract at each level.

The Project.AsvProject hierarchy::

    Root
    ├── Name                         (project name)
    ├── Properties                   (project-level warning flags)
    └── Sites[]
        ├── Properties.Name          (site name)
        ├── IsEnabledForExecution
        ├── Context                  (site-level setup parameters)
        │   ├── Slicing
        │   ├── Specimen
        │   ├── Milling
        │   ├── FiducialDefinition
        │   ├── FiducialConditions
        │   ├── RoughFiducialConditions
        │   └── RockingMillContext
        └── Recipes[]
            ├── Name                 (recipe name)
            ├── Schedule             (recipe-level schedule)
            ├── Context              (recipe-level context, e.g. ImagingContext)
            └── ActivityParameters[]
                ├── Name             (activity name)
                ├── Schedule         (activity schedule)
                └── <parameters>     (activity-specific settings)

Output structure::

    {
        "ProjectName": "ASV Project ...",
        "Sites": [
            {
                "SiteName": "Life Science - Cryo",
                "IsEnabledForExecution": true,
                "SiteContext": {
                    "Slicing": {"SliceThickness": 2e-08, ...},
                    "Milling": {...},
                    ...
                },
                "Recipes": [
                    {
                        "RecipeName": "Area Preparation",
                        "RecipeType": "AreaPreparationRecipe",
                        "Schedule": {"IsEnabled": true},
                        "RecipeContext": {},
                        "Activities": [
                            {
                                "ActivityName": "Eucentric Finder",
                                "ActivityType": "EucentricFinderActivityParameters",
                                "Schedule": {"IsEnabled": true, ...},
                                "Parameters": {"TargetTilt": 0.9075...}
                            },
                            ...
                        ]
                    },
                    ...
                ]
            }
        ]
    }

"""
import json
import logging
import math
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


# =========================================================================
# Public API
# =========================================================================

def parse_project_file(
    file_path: Path,
    config: dict,
) -> dict:
    """
    Parse an ASV Project.AsvProject file and extract project parameters.

    Reads the .NET-serialised JSON project file and extracts user-facing
    parameters at the project, site, recipe, and activity levels using
    the rules defined in the configuration.

    :param file_path: Path to the Project.AsvProject file.
    :param config: The ``ProjectFileConfig`` section from the
        application configuration file.
    :return: Nested dictionary containing extracted project parameters.
        Returns an empty dict if the file is absent.
    :raises json.JSONDecodeError: If the file contains malformed JSON.
    :raises OSError: If the file cannot be read.
    """
    raw_data = _load_json_file(file_path)
    if raw_data is None:
        return {}

    # Unpack config sections
    site_context_config = config.get("SiteContext", {})
    recipe_context_config = config.get("RecipeContext", {})
    activity_config = config.get("ActivityLevel", {})

    # Project-level fields
    project_name = raw_data.get("Name", "Unknown Project")

    # Process each site
    sites_output = []
    raw_sites = raw_data.get("Sites", [])

    for raw_site in raw_sites:
        site_data = _process_site(
            raw_site=raw_site,
            site_context_config=site_context_config,
            recipe_context_config=recipe_context_config,
            activity_config=activity_config,
        )
        if site_data:
            sites_output.append(site_data)

    result = {
        "ProjectName": project_name,
        "Sites": sites_output,
    }

    # Log summary
    total_recipes = sum(
        len(s.get("Recipes", [])) for s in sites_output
    )
    total_activities = sum(
        len(r.get("Activities", []))
        for s in sites_output
        for r in s.get("Recipes", [])
    )
    logger.info(
        f"Parsed project file: {len(sites_output)} site(s), "
        f"{total_recipes} recipe(s), {total_activities} activity(ies)."
    )

    return result


# =========================================================================
# Site Processing
# =========================================================================

def _process_site(
    raw_site: dict,
    site_context_config: dict,
    recipe_context_config: dict,
    activity_config: dict,
) -> dict:
    """
    Process a single site node from the project file.

    Extracts the site name, enabled status, site-level context
    (slicing, milling, specimen, fiducial settings), and all recipes
    with their activities.

    :param raw_site: The site dictionary from ``Sites[]``.
    :param site_context_config: SiteContext config section.
    :param recipe_context_config: RecipeContext config section.
    :param activity_config: ActivityLevel config section.
    :return: Processed site dictionary.
    """
    properties = raw_site.get("Properties", {})
    site_name = properties.get("Name", "Unknown Site")

    site_data = {
        "SiteName": site_name,
        "IsEnabledForExecution": raw_site.get("IsEnabledForExecution", False),
    }

    # Extract site-level context
    raw_context = raw_site.get("Context", {})
    if raw_context and site_context_config:
        site_data["SiteContext"] = _extract_site_context(
            raw_context, site_context_config
        )
    else:
        site_data["SiteContext"] = {}

    # Process recipes
    raw_recipes = raw_site.get("Recipes", [])
    recipes_output = []
    for raw_recipe in raw_recipes:
        recipe_data = _process_recipe(
            raw_recipe=raw_recipe,
            recipe_context_config=recipe_context_config,
            activity_config=activity_config,
        )
        if recipe_data:
            recipes_output.append(recipe_data)

    site_data["Recipes"] = recipes_output

    logger.info(
        f"Site '{site_name}': {len(recipes_output)} recipe(s) processed."
    )
    return site_data


def _extract_site_context(
    raw_context: dict,
    site_context_config: dict,
) -> dict:
    """
    Extract user-facing parameters from the site-level Context.

    Iterates over the configured context sections (e.g. Slicing,
    Milling, Specimen) and extracts the specified fields from each.

    :param raw_context: The ``Context`` dict from a site node.
    :param site_context_config: Config defining which sections and
        fields to extract.
    :return: Dict keyed by section name with extracted fields.
    """
    sections_config = site_context_config.get("Sections", {})
    result = {}

    for section_name, section_rules in sections_config.items():
        raw_section = raw_context.get(section_name)
        if raw_section is None:
            continue

        extract_fields = section_rules.get("ExtractFields", [])
        if not extract_fields:
            continue

        section_data = {}
        for field_path in extract_fields:
            value = _resolve_dot_path(raw_section, field_path)
            if value is not None:
                value = _simplify_value(value)
                _set_nested_value(section_data, field_path, value)

        if section_data:
            result[section_name] = section_data

    return result


# =========================================================================
# Recipe Processing
# =========================================================================

def _process_recipe(
    raw_recipe: dict,
    recipe_context_config: dict,
    activity_config: dict,
) -> dict:
    """
    Process a single recipe node from a site.

    Extracts recipe name, type, schedule, recipe-level context
    (e.g. ImagingContext), and all activity parameters.

    :param raw_recipe: The recipe dictionary from ``Recipes[]``.
    :param recipe_context_config: RecipeContext config section.
    :param activity_config: ActivityLevel config section.
    :return: Processed recipe dictionary.
    """
    recipe_name = raw_recipe.get("Name", "Unknown Recipe")
    recipe_type = _get_short_type(raw_recipe)

    # Recipe schedule
    raw_schedule = raw_recipe.get("Schedule", {})
    schedule = _extract_schedule(raw_schedule)

    # Recipe-level context (e.g. ImagingContext for SDB recipes)
    recipe_context = {}
    raw_context = raw_recipe.get("Context", {})
    if raw_context and recipe_context_config:
        recipe_context = _extract_recipe_context(
            raw_context, recipe_context_config
        )

    # Extra recipe-level fields (BeamType, QuadMultiplicity for imaging)
    recipe_extra = {}
    for key in ("BeamType", "QuadMultiplicity"):
        value = raw_recipe.get(key)
        if value is not None:
            recipe_extra[key] = value

    # Process activities
    raw_activities = raw_recipe.get("ActivityParameters", [])
    activities_output = _process_activities(
        raw_activities=raw_activities,
        activity_config=activity_config,
    )

    recipe_data = {
        "RecipeName": recipe_name,
        "RecipeType": recipe_type,
        "Schedule": schedule,
    }
    if recipe_extra:
        recipe_data["RecipeProperties"] = recipe_extra
    if recipe_context:
        recipe_data["RecipeContext"] = recipe_context

    recipe_data["Activities"] = activities_output

    return recipe_data


def _extract_recipe_context(
    raw_context: dict,
    recipe_context_config: dict,
) -> dict:
    """
    Extract user-facing parameters from recipe-level Context.

    Handles special context sections like ImagingContext which
    contain resolved imaging conditions for SDB recipes.

    :param raw_context: The ``Context`` dict from a recipe node.
    :param recipe_context_config: Config defining which context
        sections and fields to extract.
    :return: Dict with extracted recipe context data.
    """
    sections_config = recipe_context_config.get("Sections", {})
    result = {}

    for section_name, section_rules in sections_config.items():
        raw_section = raw_context.get(section_name)
        if raw_section is None:
            continue

        extract_fields = section_rules.get("ExtractFields", [])
        if not extract_fields:
            continue

        section_data = {}
        for field_path in extract_fields:
            value = _resolve_dot_path(raw_section, field_path)
            if value is not None:
                value = _simplify_value(value)
                _set_nested_value(section_data, field_path, value)

        if section_data:
            result[section_name] = section_data

    return result


# =========================================================================
# Activity Processing
# =========================================================================

def _process_activities(
    raw_activities: list[dict],
    activity_config: dict,
) -> list[dict]:
    """
    Process all activity parameters within a recipe.

    For each activity, extracts common fields (name, schedule) and
    activity-specific parameters based on config rules. Activities
    not listed in the config use the ``_DEFAULT_`` fallback which
    extracts all non-internal fields.

    :param raw_activities: List of activity parameter dicts.
    :param activity_config: ActivityLevel config section containing
        CommonFields and Activities rules.
    :return: List of processed activity dictionaries.
    """
    common_schedule_fields = activity_config.get("CommonScheduleFields", [])
    activities_rules = activity_config.get("Activities", {})
    internal_fields = set(activity_config.get("InternalFields", []))
    default_rule = activities_rules.get("_DEFAULT_", {})

    results = []
    for raw_activity in raw_activities:
        activity_data = _extract_activity(
            raw_activity=raw_activity,
            common_schedule_fields=common_schedule_fields,
            activities_rules=activities_rules,
            default_rule=default_rule,
            internal_fields=internal_fields,
        )
        if activity_data:
            results.append(activity_data)

    return results


def _extract_activity(
    raw_activity: dict,
    common_schedule_fields: list[str],
    activities_rules: dict,
    default_rule: dict,
    internal_fields: set[str],
) -> dict:
    """
    Extract data from a single activity parameter node.

    :param raw_activity: The activity parameter dict.
    :param common_schedule_fields: Schedule fields to extract for
        every activity.
    :param activities_rules: Per-activity extraction rules keyed by
        activity name.
    :param default_rule: Fallback rule for unlisted activities.
    :param internal_fields: Set of field names to exclude in
        default/ALL extraction mode.
    :return: Dict with ActivityName, ActivityType, Schedule, and
        Parameters.
    """
    activity_name = raw_activity.get("Name", "Unknown")
    activity_type = _get_short_type(raw_activity)

    # Extract schedule
    raw_schedule = raw_activity.get("Schedule", {})
    schedule = _extract_schedule_fields(raw_schedule, common_schedule_fields)

    # Look up activity-specific config
    activity_rule = activities_rules.get(activity_name)

    if activity_rule is None:
        # Unknown activity — use _DEFAULT_ rule
        logger.info(
            f"Activity '{activity_name}' not in config, "
            f"using _DEFAULT_ extraction."
        )
        activity_rule = default_rule

    # Determine which parameters to extract
    extract_params = activity_rule.get("ExtractParameters", [])

    parameters = {}
    if extract_params == "ALL":
        # Extract all fields except internal ones
        parameters = _extract_all_parameters(
            raw_activity, internal_fields
        )
    elif isinstance(extract_params, list) and extract_params:
        parameters = _extract_listed_parameters(
            raw_activity, extract_params
        )

    return {
        "ActivityName": activity_name,
        "ActivityType": activity_type,
        "Schedule": schedule,
        "Parameters": parameters,
    }


def _extract_listed_parameters(
    raw_activity: dict,
    param_names: list[str],
) -> dict:
    """
    Extract specific named parameters from an activity node.

    :param raw_activity: The activity parameter dict.
    :param param_names: List of parameter names to extract.
    :return: Dict of extracted parameters.
    """
    parameters = {}
    for param_name in param_names:
        value = raw_activity.get(param_name)
        if value is not None:
            parameters[param_name] = _simplify_value(value)
    return parameters


def _extract_all_parameters(
    raw_activity: dict,
    internal_fields: set[str],
) -> dict:
    """
    Extract all non-internal parameters from an activity node.

    Used for custom or unlisted activities where the config specifies
    ``"ExtractParameters": "ALL"``. Skips fields listed in
    ``InternalFields`` and common structural fields.

    :param raw_activity: The activity parameter dict.
    :param internal_fields: Set of field names to exclude.
    :return: Dict of extracted parameters.
    """
    # Always skip these structural fields regardless of config
    always_skip = {"$type", "Name", "Schedule", "InternalId"}
    skip = always_skip | internal_fields

    parameters = {}
    for key, value in raw_activity.items():
        if key in skip:
            continue
        parameters[key] = _simplify_value(value)

    return parameters


# =========================================================================
# Schedule Extraction
# =========================================================================

def _extract_schedule(raw_schedule: dict) -> dict:
    """
    Extract all non-$type fields from a schedule node.

    :param raw_schedule: The Schedule dict from a recipe or activity.
    :return: Cleaned schedule dict.
    """
    if not raw_schedule or not isinstance(raw_schedule, dict):
        return {}
    return {
        k: v for k, v in raw_schedule.items()
        if k != "$type"
    }


def _extract_schedule_fields(
    raw_schedule: dict,
    field_names: list[str],
) -> dict:
    """
    Extract specific fields from a schedule node.

    :param raw_schedule: The Schedule dict from an activity.
    :param field_names: List of field names to extract.
    :return: Dict of extracted schedule fields.
    """
    if not raw_schedule or not isinstance(raw_schedule, dict):
        return {}

    result = {}
    for field in field_names:
        value = raw_schedule.get(field)
        if value is not None:
            result[field] = value
    return result


# =========================================================================
# Value Simplification
# =========================================================================

def _simplify_value(value: Any) -> Any:
    """
    Simplify .NET-serialised values into user-friendly forms.

    Handles several common patterns from the ASV project file:

    - ``{"Linked": bool, "Value": <actual>}`` → extracts Value and
      notes linkage.
    - ``{"$type": "...", "$values": [...]}`` → unwraps to plain list.
    - ``{"$type": "...", <other keys>}`` → strips ``$type``.
    - Nested dicts → recursively simplified.
    - NaN strings → ``None``.
    - Float NaN → ``None``.

    :param value: The raw value to simplify.
    :return: Simplified value.
    """
    if value is None:
        return None

    # Handle NaN string
    if isinstance(value, str) and value == "NaN":
        return None

    # Handle float NaN
    if isinstance(value, float) and math.isnan(value):
        return None

    # Handle Linked/Value pattern
    if isinstance(value, dict):
        if "Linked" in value and "Value" in value and len(value) == 2:
            inner = _simplify_value(value["Value"])
            return {"Linked": value["Linked"], "Value": inner}

        # Handle $values list wrapper
        if "$values" in value:
            raw_list = value["$values"]
            if isinstance(raw_list, list):
                return [_simplify_value(item) for item in raw_list]

        # Recursively simplify dict, stripping $type
        simplified = {}
        for k, v in value.items():
            if k == "$type":
                continue
            simplified[k] = _simplify_value(v)

        # Drop keys with None values from simplified dicts to reduce noise
        # (but keep False, 0, empty string as they're meaningful)
        cleaned = {
            k: v for k, v in simplified.items()
            if v is not None
        }
        return cleaned if cleaned else simplified

    # Handle lists
    if isinstance(value, list):
        return [_simplify_value(item) for item in value]

    return value


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

    Example: ``"...CrossSectionSiteDto, ..."`` → ``"CrossSectionSiteDto"``

    :param node: Dictionary that may contain a ``$type`` key.
    :return: Short type name, or empty string if not present.
    """
    type_str = node.get("$type", "")
    if not type_str:
        return ""
    full_type = type_str.split(",")[0]
    return full_type.split(".")[-1]


def _resolve_dot_path(data: dict, path: str) -> Any:
    """
    Resolve a dot-notation path within a nested dictionary.

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

    Creates intermediate dicts as needed.

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