"""
Metadata Reader Worker

Background worker that reads raw metadata from a single SEM/FIB
image file (.tif, .tiff, .png).  Runs in a QThread to keep the
UI responsive for large files or network drives.

Parsing strategies
------------------
- **TIFF** — reads the tail of the file backwards in chunks until
  the ``Date=`` marker is found, then returns every line from the
  marker to the end of the file.
- **PNG** — reads bytes forward, collecting lines until the
  ``</Metadata>`` closing tag is reached.

Both scans are capped at 4 MiB, so files without a metadata block
raise an error instead of being read whole into memory.
"""
import logging
import os
from pathlib import Path
from PySide6.QtCore import QObject, Signal


logger = logging.getLogger(__name__)


# Extraction limits — metadata blocks live within a few hundred KiB
# of the marker, so unsupported or mid-write files fail fast instead
# of pulling the whole binary into memory.
_TAIL_CHUNK_SIZE = 64 * 1024         # backward read granularity
_MAX_SCAN_BYTES = 4 * 1024 * 1024    # scan cap in either direction


class MetadataReaderWorker(QObject):
    """
    Worker that parses raw metadata from a single image file.

    Signals
    -------
    file_path : str
        The validated file path (emitted before parsing begins).
    metadata : list[str]
        The parsed metadata lines.
    error : str
        Human-readable error message on failure.
    finished : (no payload)
        Emitted when the worker is done (success *or* failure).
    """

    file_path = Signal(str)
    metadata = Signal(list)
    error = Signal(str)
    finished = Signal()

    # Maps file extension → stop marker used during extraction
    _SUPPORTED_FORMATS: dict[str, str] = {
        ".tif": "Date=",
        ".tiff": "Date=",
        ".png": "</Metadata>",
    }

    def __init__(self, file_paths: list[str]):
        super().__init__()
        self._file_paths = file_paths

    # -----------------------------------------------------------------
    # Entry point (called from QThread.started)
    # -----------------------------------------------------------------

    def run(self):
        """Parse the first file in the path list and emit results."""
        try:
            if not self._file_paths:
                raise ValueError("No file paths provided.")

            path = self._file_paths[0]
            ext = Path(path).suffix.lower()

            if ext not in self._SUPPORTED_FORMATS:
                supported = ", ".join(self._SUPPORTED_FORMATS)
                raise ValueError(
                    f"Unsupported format: {ext}. "
                    f"Supported: {supported}"
                )

            self.file_path.emit(path)

            stop_marker = self._SUPPORTED_FORMATS[ext]
            if ext == ".png":
                lines = self._extract_forward(path, stop_marker)
            else:
                lines = self._extract_reverse(path, stop_marker)

            self.metadata.emit(lines)
            logger.info(
                f"Parsed {len(lines)} metadata lines from "
                f"{Path(path).name}"
            )

        except Exception as exc:
            logger.error(f"Metadata parsing failed: {exc}", exc_info=True)
            self.error.emit(str(exc))

        finally:
            self.finished.emit()

    # -----------------------------------------------------------------
    # Extraction strategies
    # -----------------------------------------------------------------

    @staticmethod
    def _extract_reverse(
        file_path: str, stop_marker: str
    ) -> list[str]:
        """
        Read the tail of a file backwards in chunks until
        *stop_marker* is found, then return every line from the
        marker's line to the end of the file in forward order.

        At most ``_MAX_SCAN_BYTES`` are read, so a file without a
        metadata block fails fast instead of being loaded whole.

        :param file_path: Path to the image file.
        :param stop_marker: Marker that signals the start of the
            metadata block.
        :return: List of decoded metadata lines.
        :raises ValueError: If *stop_marker* is not found in the
            scanned tail.
        """
        marker = stop_marker.encode("utf-8")
        buffer = b""
        marker_pos = -1
        with open(file_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            file_size = fh.tell()
            pos = file_size
            while pos > 0 and file_size - pos < _MAX_SCAN_BYTES:
                read_size = min(_TAIL_CHUNK_SIZE, pos)
                pos -= read_size
                fh.seek(pos)
                buffer = fh.read(read_size) + buffer
                marker_pos = buffer.rfind(marker)
                if marker_pos != -1:
                    break
        if marker_pos == -1:
            raise ValueError(
                f"No metadata block found in {Path(file_path).name} "
                f"- not a supported SEM/FIB image?"
            )
        # Keep only the marker's line and everything after it.
        line_start = buffer.rfind(b"\n", 0, marker_pos) + 1
        tail = buffer[line_start:]
        if tail.endswith(b"\n"):
            tail = tail[:-1]
        return [
            raw.decode("utf-8", errors="replace").rstrip("\r\n")
            for raw in tail.split(b"\n")
        ]

    @staticmethod
    def _extract_forward(
        file_path: str, stop_marker: str
    ) -> list[str]:
        """
        Read a file forward collecting metadata lines until
        *stop_marker* is found.

        At most ``_MAX_SCAN_BYTES`` are read, so a file without a
        metadata block fails fast instead of being loaded whole.

        :param file_path: Path to the image file.
        :param stop_marker: Marker that signals the end of the
            metadata block.
        :return: List of decoded metadata lines.
        :raises ValueError: If *stop_marker* is not found in the
            scanned head.
        """
        lines: list[str] = []
        scanned = 0
        with open(file_path, "rb") as fh:
            for line in fh:
                decoded = line.decode("utf-8", errors="replace").rstrip(
                    "\r\n"
                )
                lines.append(decoded)
                if stop_marker in decoded:
                    return lines
                scanned += len(line)
                if scanned >= _MAX_SCAN_BYTES:
                    break
        raise ValueError(
            f"No metadata block found in {Path(file_path).name} "
            f"- not a supported SEM/FIB image?"
        )