"""
ASV Project Directory Parser

Module handles discovery and traversal of ASV project directory structures.
It walks the project hierarchy (Sites -> Steps -> Subdirectories -> Images)
applying include/exclude filters from the configuration, and calls the
tif_metadata_parser to extract metadata from each discovered .tif image.

ASV project directory structure:
    ProjectRoot/
    ├── Site_1/
    │   ├── Step_1/
    │   │   ├── Acquired/           <- images (config: SubDirectoriesToInclude)
    │   │   └── SetupImages/        <- excluded (config: SubDirectoriesToExclude)
    │   └── Step_2/
    │       └── Acquired/
    ├── Site_2/
    │   └── ...
    ├── ProjectLogs/                <- excluded (config: RootDirectoriesToExclude)
    ├── ImageLogs/                  <- excluded (config: RootDirectoriesToExclude)
    ├── ExecutionHistory.json
    ├── Metadata.json
    └── Project.AsvProject

"""
import logging
from collections.abc import Callable
from pathlib import Path

from script_modules.tif_metadata_parser import extract_tif_metadata

logger = logging.getLogger(__name__)


def parse_project_directory(
    project_path: Path,
    root_dirs_to_exclude: list[str],
    sub_dirs_to_include: list[str],
    sub_dirs_to_exclude: list[str],
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    total_images: int | None = None
) -> list[dict]:
    """
    Parse an ASV project directory and extract metadata from all .tif images.

    Discovers sites, steps, and image subdirectories within the project,
    applies directory filters from the configuration, and extracts metadata
    from each .tif image found.

    :param project_path: Path to the ASV project root directory.
    :param root_dirs_to_exclude: Directory names to skip at the site level.
    :param sub_dirs_to_include: Subdirectory names to include within steps
                                 (e.g., ["Acquired"]). If empty, all
                                 subdirectories are included.
    :param sub_dirs_to_exclude: Subdirectory names to skip within steps
                                 (e.g., ["SetupImages"]).
    :param progress_callback: Optional callback invoked after each image
                               is parsed with (current_count, total_count).
    :param cancel_check: Optional callable that returns True if the
                          operation should be cancelled.
    :param total_images: Optional pre-computed total image count (e.g.
                          from a prior discover_tif_files call). If None,
                          the count is computed here for progress tracking.
    :return: List of site dictionaries, each containing steps and image metadata.
    """
    logger.info(f"Parsing project directory: {project_path}")

    # Pre-count total images for progress tracking (unless the caller
    # already counted them via discover_tif_files)
    if total_images is None:
        total_images = 0
        if progress_callback:
            tif_files = discover_tif_files(
                project_path, root_dirs_to_exclude,
                sub_dirs_to_include, sub_dirs_to_exclude
            )
            total_images = len(tif_files)

    # Mutable counter shared across all sites and steps
    counter = [0]

    # Discover site directories
    site_dirs = _get_filtered_directories(
        parent_path=project_path,
        dirs_to_exclude=root_dirs_to_exclude
    )
    logger.info(f"Discovered {len(site_dirs)} site directories.")

    # Process each site
    sites = []
    for site_dir in site_dirs:
        if cancel_check and cancel_check():
            break

        site_data = _process_site(
            site_dir=site_dir,
            project_path=project_path,
            root_dirs_to_exclude=root_dirs_to_exclude,
            sub_dirs_to_include=sub_dirs_to_include,
            sub_dirs_to_exclude=sub_dirs_to_exclude,
            counter=counter,
            total_images=total_images,
            progress_callback=progress_callback,
            cancel_check=cancel_check
        )
        if site_data:
            sites.append(site_data)

    logger.info(
        f"Parsing complete. Found {len(sites)} sites with images."
    )
    return sites


def discover_tif_files(
    project_path: Path,
    root_dirs_to_exclude: list[str],
    sub_dirs_to_include: list[str],
    sub_dirs_to_exclude: list[str]
) -> list[Path]:
    """
    Discover all .tif file paths in the project without extracting metadata.

    Useful for counting images or building progress indicators before
    starting the full parse.

    :param project_path: Path to the ASV project root directory.
    :param root_dirs_to_exclude: Directory names to skip at the site level.
    :param sub_dirs_to_include: Subdirectory names to include within steps.
    :param sub_dirs_to_exclude: Subdirectory names to skip within steps.
    :return: Sorted list of .tif file paths.
    """
    tif_files = []

    site_dirs = _get_filtered_directories(project_path, root_dirs_to_exclude)
    for site_dir in site_dirs:
        step_dirs = _get_filtered_directories(site_dir, root_dirs_to_exclude)
        for step_dir in step_dirs:
            image_dirs = _get_filtered_subdirectories(
                step_dir, sub_dirs_to_include, sub_dirs_to_exclude
            )
            for image_dir in image_dirs:
                tif_files.extend(_collect_tif_files(image_dir))

    tif_files.sort()
    logger.info(f"Discovered {len(tif_files)} .tif files in project.")
    return tif_files


# --- Private Helper Functions ---

def _process_site(
    site_dir: Path,
    project_path: Path,
    root_dirs_to_exclude: list[str],
    sub_dirs_to_include: list[str],
    sub_dirs_to_exclude: list[str],
    counter: list[int],
    total_images: int,
    progress_callback: Callable[[int, int], None] | None,
    cancel_check: Callable[[], bool] | None
) -> dict | None:
    """
    Process a single site directory and return structured site data.

    :param site_dir: Path to the site directory.
    :param project_path: Path to the project root (for relative path calculation).
    :param root_dirs_to_exclude: Directories to exclude at the step level.
    :param sub_dirs_to_include: Subdirectories to include within steps.
    :param sub_dirs_to_exclude: Subdirectories to exclude within steps.
    :param counter: Mutable counter [current_count] shared across all steps.
    :param total_images: Total number of images for progress tracking.
    :param progress_callback: Optional callback invoked after each image.
    :param cancel_check: Optional callable that returns True to cancel.
    :return: Site data dictionary, or None if no images found.
    """
    site_name = site_dir.name
    relative_path = _get_relative_path(site_dir, project_path)

    # Discover step directories within this site
    step_dirs = _get_filtered_directories(site_dir, root_dirs_to_exclude)

    steps = []
    for step_dir in step_dirs:
        if cancel_check and cancel_check():
            break

        step_data = _process_step(
            step_dir=step_dir,
            project_path=project_path,
            sub_dirs_to_include=sub_dirs_to_include,
            sub_dirs_to_exclude=sub_dirs_to_exclude,
            counter=counter,
            total_images=total_images,
            progress_callback=progress_callback,
            cancel_check=cancel_check
        )
        if step_data:
            steps.append(step_data)

    if not steps:
        return None

    return {
        "SiteName": site_name,
        "RelativePath": str(relative_path),
        "Steps": steps
    }


def _process_step(
    step_dir: Path,
    project_path: Path,
    sub_dirs_to_include: list[str],
    sub_dirs_to_exclude: list[str],
    counter: list[int],
    total_images: int,
    progress_callback: Callable[[int, int], None] | None,
    cancel_check: Callable[[], bool] | None
) -> dict | None:
    """
    Process a single step directory and return structured step data.

    :param step_dir: Path to the step directory.
    :param project_path: Path to the project root (for relative path calculation).
    :param sub_dirs_to_include: Subdirectories to include (e.g., ["Acquired"]).
    :param sub_dirs_to_exclude: Subdirectories to exclude (e.g., ["SetupImages"]).
    :param counter: Mutable counter [current_count] shared across all steps.
    :param total_images: Total number of images for progress tracking.
    :param progress_callback: Optional callback invoked after each image.
    :param cancel_check: Optional callable that returns True to cancel.
    :return: Step data dictionary, or None if no images found.
    """
    step_name = step_dir.name
    relative_path = _get_relative_path(step_dir, project_path)

    # Get image subdirectories (e.g., "Acquired")
    image_dirs = _get_filtered_subdirectories(
        step_dir, sub_dirs_to_include, sub_dirs_to_exclude
    )

    # Collect and parse all .tif images from the subdirectories
    images = []
    for image_dir in image_dirs:
        tif_files = _collect_tif_files(image_dir)
        for tif_path in tif_files:
            if cancel_check and cancel_check():
                return None

            image_data = extract_tif_metadata(tif_path)
            # Insert RelativePath after ImageName for cleaner ordering
            relative_image_path = str(
                _get_relative_path(tif_path, project_path)
            )
            ordered_image_data = {"ImageName": image_data.pop("ImageName")}
            ordered_image_data["RelativePath"] = relative_image_path
            ordered_image_data.update(image_data)
            images.append(ordered_image_data)

            # Report progress
            if progress_callback:
                counter[0] += 1
                progress_callback(counter[0], total_images)

    if not images:
        return None

    return {
        "StepName": step_name,
        "RelativePath": str(relative_path),
        "Images": images
    }


def _get_filtered_directories(
    parent_path: Path,
    dirs_to_exclude: list[str]
) -> list[Path]:
    """
    Get sorted child directories, excluding specified directory names.

    :param parent_path: Path to the parent directory.
    :param dirs_to_exclude: List of directory names to exclude.
    :return: Sorted list of directory paths.
    """
    try:
        return sorted(
            d for d in parent_path.iterdir()
            if d.is_dir() and d.name not in dirs_to_exclude
        )
    except OSError:
        logger.error(
            f"Error reading directory: {parent_path}", exc_info=True
        )
        return []


def _get_filtered_subdirectories(
    step_path: Path,
    dirs_to_include: list[str],
    dirs_to_exclude: list[str]
) -> list[Path]:
    """
    Get sorted subdirectories within a step, applying include/exclude filters.

    If dirs_to_include is not empty, only directories in that list are returned.
    Directories in dirs_to_exclude are always removed.

    :param step_path: Path to the step directory.
    :param dirs_to_include: Subdirectory names to include (empty = include all).
    :param dirs_to_exclude: Subdirectory names to exclude.
    :return: Sorted list of subdirectory paths.
    """
    try:
        subdirs = []
        for d in step_path.iterdir():
            if not d.is_dir():
                continue
            if d.name in dirs_to_exclude:
                continue
            if dirs_to_include and d.name not in dirs_to_include:
                continue
            subdirs.append(d)
        return sorted(subdirs)

    except OSError:
        logger.error(
            f"Error reading subdirectories in: {step_path}", exc_info=True
        )
        return []


def _collect_tif_files(directory: Path) -> list[Path]:
    """
    Collect and sort all .tif and .tiff files in a directory.

    :param directory: Path to the directory to search.
    :return: Sorted list of .tif file paths.
    """
    tif_files = list(directory.glob("*.tif")) + list(directory.glob("*.tiff"))
    return sorted(tif_files)


def _get_relative_path(path: Path, root: Path) -> Path:
    """
    Calculate the relative path from a root directory.

    :param path: The full path.
    :param root: The root directory to calculate relative to.
    :return: Relative path, or the original path if not relative to root.
    """
    try:
        return path.relative_to(root)
    except ValueError:
        return path