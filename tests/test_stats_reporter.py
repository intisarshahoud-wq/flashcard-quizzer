"""Tests for the session summary and exports (:mod:`stats_reporter`)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from models import CardResult, Flashcard, SessionStats
from stats_reporter import (
    EXPORT_FORMATS,
    SessionMeta,
    default_export_path,
    export_session,
    render,
    render_summary,
    to_csv,
    to_json,
    to_markdown,
)

META = SessionMeta(
    deck_name="Acronyms",
    deck_path="data/glossary.json",
    mode_name="sequential",
)


@pytest.fixture
def stats() -> SessionStats:
    """Return a session with two correct answers and one miss."""
    session = SessionStats()
    session.record(CardResult(Flashcard("API", "Interface"), "Interface", True, 1.5))
    session.record(CardResult(Flashcard("CPU", "Processor"), "wrong", False, 2.5))
    session.record(CardResult(Flashcard("DNS", "Names"), "Names", True, 1.0))
    return session


def test_summary_reports_every_headline_number(stats: SessionStats) -> None:
    """The summary carries the totals, the accuracy and the review list."""
    text = render_summary(stats, META)

    assert "Total questions" in text
    assert "66.7%" in text
    assert "Review these 1 card(s):" in text
    assert "CPU  ->  Processor" in text


def test_summary_congratulates_a_perfect_run() -> None:
    """With nothing missed the summary says so instead of an empty list."""
    session = SessionStats()
    session.record(CardResult(Flashcard("API", "Interface"), "Interface", True, 0.5))

    assert "Nothing missed" in render_summary(session, META)


def test_summary_of_an_empty_session() -> None:
    """Quitting before answering produces a short, honest summary."""
    text = render_summary(SessionStats(), META)

    assert "No questions were answered." in text
    assert "Accuracy" not in text


def test_summary_notes_an_early_exit(stats: SessionStats) -> None:
    """An abandoned session is labelled as such."""
    meta = SessionMeta("Acronyms", "data/glossary.json", "sequential", aborted=True)

    assert "Session ended early" in render_summary(stats, meta)


def test_summary_includes_timing_when_the_timer_is_on(stats: SessionStats) -> None:
    """Timing rows appear only when the timer was running."""
    with_timer = render_summary(stats, META, timer=True)
    without_timer = render_summary(stats, META, timer=False)

    assert "Time taken" in with_timer
    assert "Fastest correct" in with_timer
    assert "Time taken" not in without_timer


def test_summary_omits_fastest_when_nothing_was_correct() -> None:
    """With no correct answer there is no fastest correct answer to report."""
    session = SessionStats()
    session.record(CardResult(Flashcard("API", "Interface"), "no", False, 1.0))

    assert "Fastest correct" not in render_summary(session, META)


def test_duration_is_formatted_in_minutes_past_a_minute() -> None:
    """Long sessions read as minutes and seconds, not 125.0s."""
    session = SessionStats()
    session.record(CardResult(Flashcard("A", "1"), "1", True, 125.0))

    assert "2m 05s" in render_summary(session, META)


def test_json_export_matches_the_summary_numbers(stats: SessionStats) -> None:
    """The exported totals are the same figures shown on screen."""
    payload = json.loads(to_json(stats, META))

    assert payload["totals"]["questions"] == 3
    assert payload["totals"]["correct"] == 2
    assert payload["totals"]["accuracy_percent"] == 66.7
    assert payload["missed"] == ["CPU"]
    assert len(payload["answers"]) == 3
    assert payload["answers"][1]["given"] == "wrong"


def test_csv_export_has_one_row_per_answer(stats: SessionStats) -> None:
    """The CSV holds a header plus one row for each question asked."""
    rows = list(csv.reader(io.StringIO(to_csv(stats, META))))

    assert rows[0] == [
        "deck",
        "mode",
        "question",
        "expected",
        "given",
        "correct",
        "seconds",
    ]
    assert len(rows) == 4
    assert rows[2][5] == "no"


def test_csv_export_has_no_blank_lines_between_rows(stats: SessionStats) -> None:
    """The line terminator is set explicitly so Windows does not double it up."""
    text = to_csv(stats, META)

    assert "\r" not in text
    assert "\n\n" not in text


def test_markdown_export_renders_a_table(stats: SessionStats) -> None:
    """The Markdown report contains the metadata, a table and a review list."""
    text = to_markdown(stats, META)

    assert text.startswith("# Flashcard session - Acronyms")
    assert "| # | Question | Expected | Your answer | Result |" in text
    assert "| 2 | CPU | Processor | wrong | incorrect |" in text
    assert "- **CPU** - Processor" in text


def test_markdown_marks_a_skipped_answer() -> None:
    """An empty answer is labelled rather than left as an empty cell."""
    session = SessionStats()
    session.record(CardResult(Flashcard("API", "Interface"), "", False, 0.0))

    assert "_(skipped)_" in to_markdown(session, META)


def test_markdown_says_so_when_nothing_was_missed() -> None:
    """A perfect run gets a one-line review section."""
    session = SessionStats()
    session.record(CardResult(Flashcard("API", "Interface"), "Interface", True, 0.1))

    assert "Nothing missed." in to_markdown(session, META)


@pytest.mark.parametrize("export_format", EXPORT_FORMATS)
def test_render_dispatches_every_supported_format(
    stats: SessionStats, export_format: str
) -> None:
    """Each advertised format produces non-empty output."""
    assert render(stats, META, export_format).strip()


def test_render_is_case_insensitive(stats: SessionStats) -> None:
    """--export JSON works as well as --export json."""
    assert render(stats, META, " JSON ") == render(stats, META, "json")


def test_render_rejects_an_unknown_format(stats: SessionStats) -> None:
    """An unsupported format lists the ones that are supported."""
    with pytest.raises(ValueError, match="Unknown export format"):
        render(stats, META, "pdf")


def test_default_export_path_is_timestamped_and_slugged(tmp_path: Path) -> None:
    """Exports land in the export directory under a filesystem-safe name."""
    meta = SessionMeta("Python Basics!", "data/x.json", "random")

    path = default_export_path(tmp_path, meta, "md")

    assert path.parent == tmp_path
    assert path.suffix == ".md"
    assert path.name.startswith("python-basics")


def test_default_export_path_handles_a_nameless_deck(tmp_path: Path) -> None:
    """A deck whose name is all punctuation still gets a usable file name."""
    meta = SessionMeta("!!!", "data/x.json", "random")

    assert default_export_path(tmp_path, meta, "json").name.startswith("session-")


def test_export_session_writes_the_file(stats: SessionStats, tmp_path: Path) -> None:
    """Exporting writes the rendered document to disk."""
    destination = tmp_path / "nested" / "report.md"

    written = export_session(stats, META, "md", destination)

    assert written == destination
    assert "Flashcard session" in destination.read_text(encoding="utf-8")
