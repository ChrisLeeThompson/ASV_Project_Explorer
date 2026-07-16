"""
Configuration Manager

Module handles loading and accessing the ASV Project Explorer
configuration file. The configuration file is a JSON file that
contains settings for directory parsing, metadata plotting, 
execution history parsing, and consolidated metadata output.

The ConfigManager class loads the JSON file once at startup and 
provides accessors for each configuration section.
"""
import json
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


class ConfigManager:

    def __init__(self, config_path: str | Path):
        """
        Initialize the ConfigManager and load the configuration file.

        :param config_path: Path to the JSON configuration file.
        :raises FileNotFoundError: If the configuration file does not exist.
        :raises json.JSONDecodeError: If the configuration file is not valid JSON.
        """
        self.config_path = Path(config_path)
        self._config: dict = {}
        self._load_config()
    
    def _load_config(self):
        """Load and parse the JSON configuration file.

        utf-8-sig tolerates the BOM that Windows editors commonly add
        when users hand-edit the config (the parsers read their JSON
        the same way).
        """
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_path}"
            )
        with open(self.config_path, "r", encoding="utf-8-sig") as f:
            self._config = json.load(f)
        logger.info(f"Configuration loaded successfully from: {self.config_path}")

# --- Top-Level Directory / File Names ---

    @property
    def temp_json_directory_name(self) -> str:
        """Name of the temporary JSON output directory."""
        return self._config.get("TemporaryJSONFileDirectoryName", "")

    @property
    def temp_consolidated_json_filename(self) -> str:
        """Filename for the temporary consolidated metadata JSON file."""
        return self._config.get(
            "TemporaryConsolidatedJSONFileName",
            "_temp_consolidated_metadata.json"
        )

    @property
    def export_plot_directory_name(self) -> str:
        """Name of the exported plots directory."""
        return self._config.get("ExportPlotDirectoryName", "")

    @property
    def default_saved_json_filename(self) -> str:
        """Default filename for saving metadata JSON files."""
        return self._config.get(
            "DefaultSavedJSONFileName", "consolidated_asv_metadata.json"
        )

    @property
    def minify_exported_json(self) -> bool:
        """If True, write the consolidated JSON file in compact (minified) form."""
        return self._config.get("MinifyExportedJSON", True)

    @property
    def show_trend_line_by_default(self) -> bool:
        """If True, new plots show the linear trend line + slope/R² by default."""
        return self._config.get("ShowTrendLineByDefault", True)

    # --- ASV Project Directory Config ---

    @property
    def _directory_config(self) -> dict:
        """Access the ASVProjectDirectoryConfig section."""
        return self._config.get("ASVProjectDirectoryConfig", {})

    @property
    def validation_files(self) -> list[str]:
        """List of files required in the ASV project root directory."""
        return self._directory_config.get("ValidationFiles", [])

    @property
    def root_directories_to_exclude(self) -> list[str]:
        """Directories to exclude when parsing the ASV project root."""
        root_dirs = self._directory_config.get("ProjectRootDirectories", {})
        return root_dirs.get("DirectoriesToExclude", [])

    @property
    def sub_directories_to_include(self) -> list[str]:
        """Subdirectories to include when parsing ASV site steps."""
        sub_dirs = self._directory_config.get("SiteSubDirectories", {})
        return sub_dirs.get("DirectoriesToInclude", [])

    @property
    def sub_directories_to_exclude(self) -> list[str]:
        """Subdirectories to exclude when parsing ASV site steps."""
        sub_dirs = self._directory_config.get("SiteSubDirectories", {})
        return sub_dirs.get("DirectoriesToExclude", [])

    @property
    def image_logs_directories_to_include(self) -> list[str]:
        """Subdirectories to include when parsing the ImageLogs directory."""
        image_logs = self._directory_config.get("ImageLogsDirectories", {})
        return image_logs.get("DirectoriesToInclude", [])

    @property
    def image_logs_directories_to_exclude(self) -> list[str]:
        """Subdirectories to exclude when parsing the ImageLogs directory."""
        image_logs = self._directory_config.get("ImageLogsDirectories", {})
        return image_logs.get("DirectoriesToExclude", [])

    @property
    def parse_project_root_files(self) -> list[dict]:
        """List of root file parsing rules (Name and Parse flag)."""
        return self._directory_config.get("ParseProjectRootFiles", [])

    # --- Metadata to Plot Config ---

    @property
    def _metadata_to_plot_config(self) -> dict:
        """Access the MetadataToPlotConfig section."""
        return self._config.get("MetadataToPlotConfig", {})

    @property
    def plot_fields(self) -> list[dict]:
        """List of metadata field definitions for plotting."""
        return self._metadata_to_plot_config.get("Fields", [])

    @property
    def plot_field_labels(self) -> list[str]:
        """Alphabetically sorted list of plot field labels (display names)."""
        return sorted(
            (field.get("Label", "") for field in self.plot_fields),
            key=str.casefold
        )

    @property
    def plot_field_groups(self) -> list[str]:
        """Unique list of plot field groups, preserving config order."""
        seen = set()
        groups = []
        for field in self.plot_fields:
            group = field.get("Group", "")
            if group and group not in seen:
                seen.add(group)
                groups.append(group)
        return groups

    # --- Execution History Config ---

    @property
    def execution_history_config(self) -> dict:
        """Access the ExecutionHistoryConfig section.

        Returns the full ExecutionHistoryConfig dict containing
        TraversalTypes, CommonFields, and ActivityTypes used by
        the execution history parser.
        """
        return self._config.get("ExecutionHistoryConfig", {})

    # --- Project File Config ---

    @property
    def project_file_config(self) -> dict:
        """Access the ProjectFileConfig section.

        Returns the full ProjectFileConfig dict containing
        SiteContext, RecipeContext, and ActivityLevel rules
        used by the project file parser.
        """
        return self._config.get("ProjectFileConfig", {})

    # --- Consolidated Metadata Config ---

    @property
    def _consolidated_metadata_config(self) -> dict:
        """Access the ConsolidatedMetadataConfig section."""
        return self._config.get("ConsolidatedMetadataConfig", {})

    @property
    def consolidated_metadata_template(self) -> dict:
        """Full template dictionary for building consolidated metadata."""
        return self._consolidated_metadata_config

    # --- Version ---

    @property
    def version(self) -> str:
        """Configuration file version."""
        return self._config.get("_version", "unknown")