"""
Module handles background folder scanning for the auto-update feature.

FolderScanWorker runs on a dedicated QThread (moved there by the parent
tab) and, on request, walks the loaded ASV project folder to build a
lightweight snapshot of its .tif files: {relative_path: mtime}.

The parent tab compares consecutive snapshots to decide whether the
project folder has changed (files added, removed, or modified in place)
and, if so, triggers a quiet metadata rebuild. The scan itself performs
no metadata extraction, so it stays cheap relative to a full parse.

All filesystem access is wrapped so the worker never raises across the
thread boundary; failures (folder deleted, drive unmounted) are reported
via the scan_failed signal instead.
"""
import logging
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot
from script_modules.asv_project_directory_parser import discover_tif_files


logger = logging.getLogger(__name__)


class FolderScanWorker(QObject):

    # Emitted when a scan completes.
    # Args: snapshot dict of {relative_tif_path: mtime}
    snapshot_ready = Signal(dict)

    # Emitted when the scan fails (folder missing or unreadable).
    # Args: error message
    scan_failed = Signal(str)

    @Slot(str, list, list, list)
    def scan(
        self,
        project_root: str,
        root_dirs_to_exclude: list,
        sub_dirs_to_include: list,
        sub_dirs_to_exclude: list
    ):
        """Scan the project folder and emit a {relative_path: mtime}
        snapshot of its .tif files.

        Reuses the same directory discovery (and include/exclude
        filters) as the full parse, so the snapshot covers exactly the
        files the parser would consume.

        :param project_root: Absolute path to the ASV project root.
        :param root_dirs_to_exclude: Directory names to skip at the
                                     site level.
        :param sub_dirs_to_include: Subdirectory names to include
                                    within steps.
        :param sub_dirs_to_exclude: Subdirectory names to skip within
                                    steps.
        """
        project = Path(project_root)
        if not project.is_dir():
            logger.warning(f"Auto-update scan: folder missing: {project}")
            self.scan_failed.emit(
                f"Project folder not found: {project_root}"
            )
            return

        try:
            tif_files = discover_tif_files(
                project,
                root_dirs_to_exclude,
                sub_dirs_to_include,
                sub_dirs_to_exclude
            )
            snapshot = {}
            for tif_path in tif_files:
                try:
                    key = str(tif_path.relative_to(project))
                except ValueError:
                    key = str(tif_path)
                try:
                    snapshot[key] = tif_path.stat().st_mtime
                except OSError:
                    # File vanished between discovery and stat; treat it
                    # as absent so the next scan detects the change.
                    continue
            self.snapshot_ready.emit(snapshot)
        except OSError as exc:
            logger.error(f"Auto-update scan failed: {exc}", exc_info=True)
            self.scan_failed.emit(f"Folder scan failed: {exc}")
