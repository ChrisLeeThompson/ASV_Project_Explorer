# ASV Project Explorer

> [!NOTE]
> **Full documentation:** https://chrisleethompson.github.io/scripts/asv_project_explorer/

A PySide6 desktop utility for exploring Thermo Scientific Auto Slice and View (ASV) project metadata. Point it at an ASV project directory and it consolidates the per-slice metadata into a single JSON file. From there you can plot any metadata field against slice index, browse the image behind each point, and inspect the execution history and project parameters that produced it. The data helps with tracking a project's progress, analyzing data quality, and troubleshooting ASV issues.

## Documentation

Full documentation: https://chrisleethompson.github.io/scripts/asv_project_explorer/

## Features

- **Metadata plots** of any recognized field against slice index; click a point to select that slice.
- **Slice data** for the selected slice: image preview, searchable image metadata, and slice execution history.
- **Full-resolution window** for viewing the selected image at native size.
- **Auto-update** that watches an active project folder and refreshes as new slices arrive.
- **Exports** of plots as PNG, SVG, and CSV, plus one execution-history CSV per imaging step.
- **Single Image Metadata** tab: drop a single SEM/FIB `.tif` or ASV `.png` image to view and search its raw metadata.

## Requirements

- Python 3.11+
- PySide6 6.7.1+
- Matplotlib 3.8.1+
- NumPy 2.2.5+
- tifffile 2025.3.13+

AutoScript is not required. All packages above ship with the AutoScript 4.14 Python environment, where the script is developed and tested, so no extra installation is needed there.

## Installation

1. Download the latest release ZIP from the [Releases page](https://github.com/ChrisLeeThompson/ASV_Project_Explorer/releases).
2. Extract it and copy the script folder to your desired location. The script does not connect to a microscope, so it can be installed on any PC that meets the requirements.
3. If you run the script with the AutoScript Python environment, no packages need to be installed. Otherwise, install them with:

   ```
   pip install -r requirements.txt
   ```

## Running

Run the main module from the script folder:

```
python asv_project_explorer.py
```

The script also runs from the AutoScript Python interpreter or AutoScript Runner.

## Notes

- Tested with ASV 5.13. Projects from older ASV versions may not parse correctly. Cross-section and spin mill projects are both supported; type-specific parameters are extracted only for the matching project type.
- Load a project by dragging an ASV project directory (or a previously generated metadata JSON file) onto the Catbug image, or with the Load ASV Project and Load Metadata File buttons.
- Parsing a project writes a consolidated metadata JSON file so later loads are fast. Save Metadata File keeps a copy wherever you choose; Delete Temp Metadata File removes the auto-generated one.
- The parsers are data-driven: field paths, plot definitions, and execution-history extraction rules live in `config_files/ASVProjectExplorerConfig.json`, documented inline via `_comment` fields. If a project uses field names this version does not recognize, that file is the place to start.

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 Christopher Thompson.

The Catbug artwork in `script_assets/` is not covered by the MIT license; see [LICENSE](LICENSE). PySide6 (Qt for Python) is licensed under the LGPLv3 and is used as an unmodified runtime dependency installed from PyPI; it is not distributed with this source.

## Contact

Developed by Chris Thompson with assistance from Anthropic's Claude. Questions and suggestions are welcome: [@ChrisLeeThompson](https://github.com/ChrisLeeThompson) on GitHub.
