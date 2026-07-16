"""
Consolidated Metadata Writer

Module handles building and writing the consolidated metadata JSON file
from parsed ASV project data. The output file combines all image metadata
from the project directory parser into a single JSON file for use by the
UI plotting and display components.

The output structure follows the ConsolidatedMetadataConfig template
defined in the application configuration file.

"""
import json
import logging
import os
from pathlib import Path


logger = logging.getLogger(__name__)


# Format identifier written to consolidated metadata files for validation.
FORMAT_ID = "ASVProjectExplorerMetadata"


def write_consolidated_metadata(
    output_directory: Path,
    output_filename: str,
    project_name: str,
    project_root: str,
    sites: list[dict],
    project_parameters: dict | None = None,
    minify: bool = True
) -> Path | None:
    """
    Write the consolidated metadata JSON file.

    Assembles the parsed site/step/image data into the consolidated
    output structure and writes it to the specified output directory.

    :param output_directory: Directory to write the output file to.
    :param output_filename: Name of the output JSON file.
    :param project_name: Name of the ASV project (derived from root directory name).
    :param project_root: Absolute path to the project root directory.
    :param sites: List of site dictionaries from the directory parser.
    :param project_parameters: Dictionary of project parameters from the project file.
    :param minify: If True, write compact JSON. If False, write indented JSON.
    :return: Path to the written file, or None on failure.
    """
    consolidated_data = {
        "_format": FORMAT_ID,
        "ProjectName": project_name,
        "ProjectRoot": project_root,
        "Sites": sites,
        "ProjectParameters": project_parameters or {}
    }

    # Ensure output directory exists
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.error(
            f"Failed to create output directory: {output_directory}",
            exc_info=True
        )
        return None

    output_path = output_directory / output_filename
    # Write to a sibling temp file and rename so the file at output_path
    # is always a complete JSON, even if it is read (e.g. by Save) or the
    # app crashes mid-write.
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    try:
        dump_kwargs = {"ensure_ascii": False}
        if minify:
            dump_kwargs["separators"] = (",", ":")
        else:
            dump_kwargs["indent"] = 2
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(consolidated_data, f, **dump_kwargs)
        os.replace(tmp_path, output_path)
        logger.info(f"Consolidated metadata written to: {output_path}")
        return output_path

    except OSError:
        logger.error(
            f"Failed to write consolidated metadata: {output_path}",
            exc_info=True
        )
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def load_consolidated_metadata(file_path: Path) -> dict | None:
    """
    Load a previously written consolidated metadata JSON file.

    Useful for reloading parsed data without re-parsing the project
    directory (e.g., when reopening the application).

    :param file_path: Path to the consolidated metadata JSON file.
    :return: Parsed metadata dictionary, or None on failure.
    """
    if not file_path.exists():
        logger.warning(f"Consolidated metadata file not found: {file_path}")
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Loaded consolidated metadata from: {file_path}")
        return data

    except (json.JSONDecodeError, OSError):
        logger.error(
            f"Failed to load consolidated metadata: {file_path}",
            exc_info=True
        )
        return None


def validate_consolidated_json(file_path: Path) -> bool:
    """
    Validate that a JSON file is an ASV Project Explorer consolidated
    metadata file by checking for the _format identifier.

    Performs a lightweight read of the file to check the format field
    without loading the entire structure into memory.

    :param file_path: Path to the JSON file to validate.
    :return: True if the file contains the correct format identifier.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("_format") == FORMAT_ID
    except (json.JSONDecodeError, OSError, AttributeError):
        return False