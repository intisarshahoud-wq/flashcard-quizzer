"""Filesystem helpers shared by the loader, the progress store and the exporter.

Every disk access in the application goes through this module so that the size
limit, the encoding, the error wrapping and the atomic-write behaviour are
defined exactly once.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Final

#: Refuse to read anything larger than this. A flashcard deck is a few
#: kilobytes; a multi-megabyte file is a mistake or a hostile input, and
#: ``json.load`` would otherwise happily try to hold all of it in memory.
MAX_FILE_BYTES: Final[int] = 5 * 1024 * 1024

#: Text encoding used for every file this application reads or writes.
ENCODING: Final[str] = "utf-8"


class FileHandlerError(Exception):
    """Raised when a file cannot be read or written safely.

    Carries a message that is already fit to show a user, so callers can print
    it directly instead of formatting a traceback.
    """


def resolve_readable_path(path: str | Path) -> Path:
    """Return ``path`` resolved to an existing, readable regular file.

    Args:
        path: A path supplied by the user, possibly relative.

    Returns:
        The absolute, symlink-resolved path.

    Raises:
        FileHandlerError: If the path does not exist, is a directory, is not
            readable, or is larger than :data:`MAX_FILE_BYTES`.
    """
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise FileHandlerError(f"File not found: {candidate}") from exc

    if resolved.is_dir():
        raise FileHandlerError(f"Expected a file but found a directory: {resolved}")
    if not resolved.is_file():
        raise FileHandlerError(f"Not a regular file: {resolved}")
    if not os.access(resolved, os.R_OK):
        raise FileHandlerError(f"No permission to read: {resolved}")

    size = resolved.stat().st_size
    if size > MAX_FILE_BYTES:
        limit_mb = MAX_FILE_BYTES / (1024 * 1024)
        raise FileHandlerError(
            f"File is too large to load ({size / (1024 * 1024):.1f} MB, "
            f"limit {limit_mb:.0f} MB): {resolved}"
        )
    return resolved


def read_text(path: str | Path) -> str:
    """Return the decoded contents of ``path``.

    Args:
        path: The file to read.

    Returns:
        The file contents as text.

    Raises:
        FileHandlerError: If the file is unreadable or is not valid UTF-8.
    """
    resolved = resolve_readable_path(path)
    try:
        return resolved.read_text(encoding=ENCODING)
    except UnicodeDecodeError as exc:
        raise FileHandlerError(
            f"File is not valid {ENCODING.upper()} text: {resolved}"
        ) from exc
    except OSError as exc:
        raise FileHandlerError(f"Could not read {resolved}: {exc}") from exc


def read_json(path: str | Path) -> Any:
    """Return the JSON value stored in ``path``.

    Args:
        path: The JSON file to read.

    Returns:
        The decoded JSON value. The caller is responsible for checking its
        shape; this function only guarantees that the text parsed.

    Raises:
        FileHandlerError: If the file is unreadable or contains invalid JSON.
            The message names the line and column of the syntax error so the
            user can find it.
    """
    resolved = resolve_readable_path(path)
    text = read_text(resolved)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise FileHandlerError(
            f"{resolved.name} is not valid JSON "
            f"(line {exc.lineno}, column {exc.colno}): {exc.msg}"
        ) from exc


def write_json(path: str | Path, payload: object, *, indent: int = 2) -> Path:
    """Write ``payload`` to ``path`` as JSON, atomically.

    The data is written to a temporary file in the destination directory and
    then moved into place. A crash or a full disk therefore leaves the previous
    file intact instead of truncating it to nothing, which matters because the
    progress file is rewritten after every session.

    Args:
        path: Destination file. Parent directories are created if needed.
        payload: Any JSON-serialisable value.
        indent: Indentation passed to :func:`json.dump`.

    Returns:
        The resolved destination path.

    Raises:
        FileHandlerError: If the payload cannot be serialised or the file
            cannot be written.
    """
    destination = Path(path).expanduser()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FileHandlerError(
            f"Could not create directory {destination.parent}: {exc}"
        ) from exc

    handle = None
    temp_name = ""
    try:
        file_descriptor, temp_name = tempfile.mkstemp(
            dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
        )
        handle = os.fdopen(file_descriptor, "w", encoding=ENCODING)
        json.dump(payload, handle, indent=indent, ensure_ascii=False)
        handle.write("\n")
        handle.close()
        handle = None
        os.replace(temp_name, destination)
    except (TypeError, ValueError) as exc:
        raise FileHandlerError(f"Value is not JSON-serialisable: {exc}") from exc
    except OSError as exc:
        raise FileHandlerError(f"Could not write {destination}: {exc}") from exc
    finally:
        if handle is not None:
            handle.close()
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)

    return destination


def write_text(path: str | Path, content: str) -> Path:
    """Write ``content`` to ``path``, creating parent directories as needed.

    Args:
        path: Destination file.
        content: Text to write.

    Returns:
        The destination path.

    Raises:
        FileHandlerError: If the file cannot be written.
    """
    destination = Path(path).expanduser()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding=ENCODING)
    except OSError as exc:
        raise FileHandlerError(f"Could not write {destination}: {exc}") from exc
    return destination
