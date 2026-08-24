# ASV Project Explorer

A PySide6 desktop application for exploring Thermo Scientific Auto Slice And
View (ASV) project metadata.

Point it at an ASV project directory and it consolidates the per-slice
metadata into a single JSON file. From there you can plot any metadata field
against slice index, browse the image behind each point, and inspect the
execution history and project parameters that produced it.

## Requirements

Python 3.11 and the packages in [requirements.txt](requirements.txt)
(PySide6, matplotlib, numpy, tifffile). All four ship with AutoScript 4.13, so
no extra installation is normally needed on a microscope support PC.
Elsewhere:

```
pip install -r requirements.txt
```

## Running

```
python asv_project_explorer.py
```

The application also runs from AutoScript Runner.

## The two tabs

**ASV Project Metadata** — load a project directory (or a previously
generated metadata JSON file), then plot metadata fields against slice index.
Clicking a plot point selects that slice and shows its image, image metadata,
and slice execution history. Plots can be exported as PNG, SVG, and CSV.
Auto-update watches the project folder and refreshes as new slices arrive.

**Single Image Metadata** — drop a single SEM/FIB `.tif` or ASV `.png` image
to view and search its raw metadata.

## Loading a project

Drag an ASV project directory or a previously generated JSON metadata file
onto the Catbug image, or use the **Load ASV Project** / **Load Metadata
File** buttons.

Parsing a project writes a consolidated metadata JSON file so subsequent loads
are fast. **Save Metadata File** keeps a copy wherever you choose; **Delete
Temp Metadata File** removes the auto-generated one.

## Compatibility

ASV version 5.11 was used as the basis for the parsing algorithms. Projects
from older ASV versions may not parse correctly.

Much of what the parsers look for is data-driven rather than hard-coded — the
field paths, plot definitions, and execution-history extraction rules all live
in [config_files/ASVProjectExplorerConfig.json](config_files/ASVProjectExplorerConfig.json),
which is documented inline via `_comment` fields. If a project uses field
names this version does not recognise, that file is the place to start.

## Notes

- The Catbug artwork in `script_assets/` is not covered by the MIT license.
  See [LICENSE](LICENSE).
- The code was written with assistance from Claude AI.

## Contact

Questions or suggestions: Chris Thompson
([ChrisLeeThompson](https://github.com/ChrisLeeThompson) on GitHub).
