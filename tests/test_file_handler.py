"""Tests for the filesystem helpers (:mod:`utils.file_handler`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils import file_handler
from utils.file_handler import (
    FileHandlerError,
    read_json,
    read_text,
    resolve_readable_path,
    write_json,
    write_text,
)


def test_read_json_round_trips(tmp_path: Path) -> None:
    """What write_json writes, read_json reads back unchanged."""
    path = tmp_path / "data.json"
    payload = {"cards": [{"front": "A", "back": "1"}], "count": 1}

    write_json(path, payload)

    assert read_json(path) == payload


def test_write_json_creates_missing_directories(tmp_path: Path) -> None:
    """Exporting into a directory that does not exist yet just works."""
    destination = tmp_path / "deep" / "nested" / "out.json"

    written = write_json(destination, [1, 2, 3])

    assert written.exists()
    assert json.loads(written.read_text(encoding="utf-8")) == [1, 2, 3]


def test_write_json_leaves_no_temporary_files_behind(tmp_path: Path) -> None:
    """The atomic write cleans up after itself."""
    write_json(tmp_path / "out.json", {"a": 1})

    assert [item.name for item in tmp_path.iterdir()] == ["out.json"]


def test_write_json_preserves_the_old_file_when_serialisation_fails(
    tmp_path: Path,
) -> None:
    """A failed write must not destroy the previous contents.

    The progress file is rewritten after every session, so a truncating write
    would turn one bad value into total data loss.
    """
    path = tmp_path / "progress.json"
    write_json(path, {"good": True})

    with pytest.raises(FileHandlerError, match="not JSON-serialisable"):
        write_json(path, {"bad": object()})

    assert read_json(path) == {"good": True}
    assert [item.name for item in tmp_path.iterdir()] == ["progress.json"]


def test_read_json_reports_the_position_of_a_syntax_error(tmp_path: Path) -> None:
    """A JSON syntax error names the line and column, not a traceback."""
    path = tmp_path / "broken.json"
    path.write_text('{\n  "front": "A",\n  "back":\n}', encoding="utf-8")

    with pytest.raises(FileHandlerError) as excinfo:
        read_json(path)

    message = str(excinfo.value)
    assert "broken.json" in message
    assert "line 4" in message


def test_read_missing_file(tmp_path: Path) -> None:
    """A missing file is reported by name."""
    with pytest.raises(FileHandlerError, match="File not found"):
        read_json(tmp_path / "nothing.json")


def test_read_directory(tmp_path: Path) -> None:
    """A directory is not a deck."""
    with pytest.raises(FileHandlerError, match="found a directory"):
        read_text(tmp_path)


def test_read_rejects_non_utf8_content(tmp_path: Path) -> None:
    """Binary content produces a clear message rather than a decode traceback."""
    path = tmp_path / "binary.json"
    path.write_bytes(b"\xff\xfe\x00\x01not text")

    with pytest.raises(FileHandlerError, match="not valid UTF-8 text"):
        read_text(path)


def test_read_rejects_oversized_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file past the size cap is refused before it is loaded into memory."""
    monkeypatch.setattr(file_handler, "MAX_FILE_BYTES", 16)
    path = tmp_path / "big.json"
    path.write_text("x" * 64, encoding="utf-8")

    with pytest.raises(FileHandlerError, match="too large to load"):
        resolve_readable_path(path)


def test_resolve_returns_an_absolute_path(tmp_path: Path) -> None:
    """Relative input is resolved so later messages name a full path."""
    path = tmp_path / "deck.json"
    path.write_text("[]", encoding="utf-8")

    assert resolve_readable_path(path).is_absolute()


def test_write_text_creates_parents_and_writes_utf8(tmp_path: Path) -> None:
    """Markdown and CSV exports are written as UTF-8 under new directories."""
    destination = tmp_path / "exports" / "report.md"

    write_text(destination, "# Caf\u00e9 report\n")

    assert destination.read_text(encoding="utf-8") == "# Caf\u00e9 report\n"


def test_write_text_reports_an_unwritable_destination(tmp_path: Path) -> None:
    """Writing where a file already blocks the directory path is reported."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(FileHandlerError, match="Could not write"):
        write_text(blocker / "inner.md", "content")


def test_write_json_reports_an_unwritable_destination(tmp_path: Path) -> None:
    """The same failure is reported for JSON writes."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(FileHandlerError, match="Could not create directory"):
        write_json(blocker / "inner" / "out.json", {"a": 1})
