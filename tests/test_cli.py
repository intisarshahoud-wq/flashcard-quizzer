"""Tests for the command-line surface itself (:mod:`main`)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import main
from main import CliError, build_parser, configure_logging
from models import Flashcard
from progress_store import ProgressStore
from ui import Console

DeckWriter = Callable[[Any, str], Path]


@pytest.fixture
def deck_file(write_deck: DeckWriter) -> Path:
    """Return a small valid deck on disk."""
    return write_deck(
        [
            {"front": "API", "back": "Application Programming Interface"},
            {"front": "CPU", "back": "Central Processing Unit"},
        ],
        "cli_deck.json",
    )


def test_help_lists_every_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """``--help`` documents the flags the project specification requires."""
    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["--help"])

    output = capsys.readouterr().out
    assert excinfo.value.code == 0
    for flag in ("-f", "--file", "-m", "--mode", "--stats", "--export", "--validate"):
        assert flag in output


def test_help_lists_every_registered_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """A newly registered quiz mode appears in --help without extra wiring."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--help"])

    output = capsys.readouterr().out
    for mode in ("sequential", "random", "adaptive", "spaced"):
        assert mode in output


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """``--version`` prints the version and exits cleanly."""
    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["--version"])

    assert excinfo.value.code == 0
    assert main.VERSION in capsys.readouterr().out


def test_unknown_mode_is_rejected_by_argparse() -> None:
    """A bad --mode fails at parse time with argparse's exit code 2."""
    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["--mode", "telepathy"])

    assert excinfo.value.code == 2


def test_list_modes(capsys: pytest.CaptureFixture[str]) -> None:
    """``--list-modes`` prints each mode with its description."""
    exit_code = main.run(["--list-modes"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "adaptive" in output
    assert "Shuffle the deck" in output


def test_validate_accepts_a_good_deck(
    deck_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--validate`` confirms a deck and reports its size, without quizzing."""
    exit_code = main.run(["-f", str(deck_file), "--validate", "--no-color"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "is a valid deck" in output
    assert "Cards: 2" in output
    assert "Question 1" not in output


def test_validate_reports_warnings(
    write_deck: DeckWriter, capsys: pytest.CaptureFixture[str]
) -> None:
    """Duplicate questions are surfaced by --validate as warnings."""
    deck = write_deck(
        [{"front": "API", "back": "one"}, {"front": "api", "back": "two"}],
        "dupes.json",
    )

    exit_code = main.run(["-f", str(deck), "--validate", "--no-color"])

    assert exit_code == 0
    assert "Warning: Duplicate question" in capsys.readouterr().out


def test_validate_rejects_a_bad_deck(
    write_deck: DeckWriter, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--validate`` on a broken deck exits 1 with a readable message."""
    deck = write_deck("[{", "broken.json")

    exit_code = main.run(["-f", str(deck), "--validate"])

    assert exit_code == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_stats_without_history(
    deck_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--stats`` on a fresh deck says there is nothing recorded yet."""
    exit_code = main.run(
        [
            "-f",
            str(deck_file),
            "--stats",
            "--no-color",
            "--progress-file",
            str(tmp_path / "p.json"),
        ]
    )

    assert exit_code == 0
    assert "No cards from this deck have been answered yet" in capsys.readouterr().out


def test_stats_reports_saved_history(
    deck_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--stats`` prints per-card counts and the lifetime accuracy."""
    progress_file = tmp_path / "p.json"
    store = ProgressStore.load(progress_file)
    store.register(Flashcard("API", "Application Programming Interface"), correct=True)
    store.register(Flashcard("API", "Application Programming Interface"), correct=False)
    store.save()

    exit_code = main.run(
        [
            "-f",
            str(deck_file),
            "--stats",
            "--no-color",
            "--progress-file",
            str(progress_file),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "API" in output
    assert "50.0%" in output
    assert "Lifetime: 2 answers" in output


def test_stats_truncates_a_long_question(
    write_deck: DeckWriter, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A long question is shortened so the table stays aligned."""
    question = "Which keyword " + "very " * 20 + "long?"
    deck = write_deck([{"front": question, "back": "def"}], "long.json")
    progress_file = tmp_path / "p.json"
    store = ProgressStore.load(progress_file)
    store.register(Flashcard(question, "def"), correct=True)
    store.save()

    exit_code = main.run(
        [
            "-f",
            str(deck),
            "--stats",
            "--no-color",
            "--progress-file",
            str(progress_file),
        ]
    )

    assert exit_code == 0
    assert "…" in capsys.readouterr().out


def test_stats_conflicts_with_no_progress(
    deck_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Asking for saved stats with progress disabled is a clear error."""
    exit_code = main.run(["-f", str(deck_file), "--stats", "--no-progress"])

    assert exit_code == 1
    assert "--stats cannot be combined with --no-progress" in capsys.readouterr().err


def test_a_damaged_progress_file_warns_but_the_quiz_runs(
    deck_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Corrupt history is reported as a warning; the quiz still goes ahead."""
    progress_file = tmp_path / "p.json"
    progress_file.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda: "exit")

    exit_code = main.run(
        ["-f", str(deck_file), "--no-color", "--progress-file", str(progress_file)]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Ignoring unreadable progress file" in output


def test_limit_is_honoured_end_to_end(
    write_deck: DeckWriter,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--limit 1`` asks exactly one question."""
    deck = write_deck(
        [{"front": "A", "back": "1"}, {"front": "B", "back": "2"}], "limited.json"
    )
    monkeypatch.setattr("builtins.input", lambda: "1")

    exit_code = main.run(["-f", str(deck), "-n", "1", "--no-progress", "--no-color"])

    output = " ".join(capsys.readouterr().out.split())
    assert exit_code == 0
    assert "Total questions 1" in output


def test_a_non_positive_limit_is_reported(
    deck_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--limit 0`` is rejected with the engine's message, not a traceback."""
    exit_code = main.run(["-f", str(deck_file), "-n", "0", "--no-progress"])

    assert exit_code == 1
    assert "positive whole number" in capsys.readouterr().err


def test_seed_makes_a_random_run_reproducible(
    write_deck: DeckWriter,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two runs with the same seed ask the questions in the same order."""
    deck = write_deck(
        [{"front": f"Q{index}", "back": str(index)} for index in range(6)],
        "seeded.json",
    )

    def ask_order() -> list[str]:
        monkeypatch.setattr("builtins.input", lambda: "x")
        main.run(
            [
                "-f",
                str(deck),
                "-m",
                "random",
                "--seed",
                "123",
                "--no-progress",
                "--no-color",
                "--hide-answers",
            ]
        )
        return [
            line
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("Q")
        ]

    assert ask_order() == ask_order()


def test_config_file_supplies_the_deck(
    write_deck: DeckWriter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Settings can come from a config file instead of flags."""
    deck = write_deck([{"front": "A", "back": "1"}], "configured.json")
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps({"deck": str(deck), "mode": "random"}), encoding="utf-8"
    )
    monkeypatch.setattr("builtins.input", lambda: "1")

    exit_code = main.run(["--config", str(config), "--no-progress", "--no-color"])

    assert exit_code == 0
    assert "Mode: random" in capsys.readouterr().out


def test_a_missing_config_file_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    """``--config`` pointing nowhere exits 1 with a clear message."""
    exit_code = main.run(["--config", "no_such_config.json"])

    assert exit_code == 1
    assert "Config file not found" in capsys.readouterr().err


def test_export_failure_is_a_warning_not_a_crash(
    write_deck: DeckWriter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed export must not discard a quiz the user has already finished."""
    deck = write_deck([{"front": "A", "back": "1"}], "export_fail.json")
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda: "1")

    exit_code = main.run(
        [
            "-f",
            str(deck),
            "--no-progress",
            "--no-color",
            "--export",
            "md",
            "--export-path",
            str(blocker / "nested" / "report.md"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Could not write the export" in output
    assert "Total questions" in output


def test_export_uses_a_timestamped_default_path(
    write_deck: DeckWriter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without --export-path the report lands in the configured export folder."""
    deck = write_deck([{"front": "A", "back": "1"}], "auto_export.json")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda: "1")

    exit_code = main.run(
        ["-f", str(deck), "--no-progress", "--no-color", "--export", "csv"]
    )

    assert exit_code == 0
    assert "Session exported to" in capsys.readouterr().out
    assert list((tmp_path / "exports").glob("*.csv"))


def test_nothing_is_exported_for_an_empty_session(
    write_deck: DeckWriter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quitting before answering produces no export file to clutter the folder."""
    deck = write_deck([{"front": "A", "back": "1"}], "empty_export.json")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda: "exit")

    main.run(["-f", str(deck), "--no-progress", "--no-color", "--export", "json"])

    assert not (tmp_path / "exports").exists()


def test_progress_save_failure_is_reported_as_a_warning(
    write_deck: DeckWriter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If progress cannot be saved the user is told, but still sees the summary."""
    deck = write_deck([{"front": "A", "back": "1"}], "save_fail.json")
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda: "1")

    exit_code = main.run(
        [
            "-f",
            str(deck),
            "--no-color",
            "--progress-file",
            str(blocker / "nested" / "p.json"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Progress was not saved" in output
    assert "Total questions" in output


def test_configure_logging_writes_to_a_file(tmp_path: Path) -> None:
    """``--log-file`` sends the log somewhere other than standard error."""
    log_file = tmp_path / "logs" / "run.log"

    configure_logging("INFO", log_file)
    try:
        logging.getLogger("flashcard.test").info("hello from the test")
        for handler in logging.getLogger().handlers:
            handler.flush()
        assert "hello from the test" in log_file.read_text(encoding="utf-8")
    finally:
        # configure_logging closes whatever it replaces, so point the root
        # logger back at stderr rather than leaving the file handle open.
        configure_logging("WARNING", None)


def test_configure_logging_reports_an_unusable_log_file(tmp_path: Path) -> None:
    """A log path that cannot be opened is a clear CliError."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(CliError, match="Could not open log file"):
        configure_logging("INFO", blocker / "nested" / "run.log")


def test_show_validation_returns_zero(deck_file: Path) -> None:
    """The validate helper reports success with exit code 0."""
    from data_loader import load_deck

    console = Console(color=False)

    assert main.show_validation(console, load_deck(deck_file)) == 0


def test_main_entry_point_exits_with_the_run_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``main()`` turns the return value of ``run()`` into a process exit code."""
    monkeypatch.setattr(main, "run", lambda: 3)

    with pytest.raises(SystemExit) as excinfo:
        main.main()

    assert excinfo.value.code == 3
