"""End-to-end tests: the session loop, the observers and the CLI together."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import main
from conftest import EchoProvider, FakeClock, ScriptedProvider
from models import Flashcard
from observers import (
    BaseSessionObserver,
    LoggingObserver,
    ProgressObserver,
    SessionSubject,
)
from progress_store import ProgressStore
from quiz_engine import AdaptiveMode, QuizModeFactory, QuizSession, SequentialMode

DeckWriter = Callable[[Any, str], Path]


def test_full_session(cards: list[Flashcard]) -> None:
    """Answer three questions and check every derived statistic.

    Two correct and one incorrect answer must give 2/3 correct, 66.7%
    accuracy, and exactly the missed card listed for review.
    """
    provider = ScriptedProvider(
        [
            "Application Programming Interface",
            "wrong on purpose",
            "  domain   NAME system  ",
        ]
    )
    session = QuizSession(SequentialMode(cards), provider, deck_name="Acronyms")

    stats = session.run()

    assert stats.total_questions == 3
    assert stats.correct_count == 2
    assert stats.incorrect_count == 1
    assert stats.accuracy == pytest.approx(66.666, abs=0.01)
    assert [card.front for card in stats.missed_cards] == ["CPU"]
    assert stats.longest_streak == 1
    assert session.aborted is False
    assert [card.front for card in provider.asked] == ["API", "CPU", "DNS"]


def test_full_session_records_timings(cards: list[Flashcard]) -> None:
    """With the timer on, each answer carries the elapsed seconds."""
    session = QuizSession(
        SequentialMode(cards),
        EchoProvider(),
        timer=True,
        clock=FakeClock(step=2.0),
    )

    stats = session.run()

    assert stats.total_questions == 3
    assert all(result.elapsed_seconds == 2.0 for result in stats.results)
    assert stats.total_seconds == pytest.approx(6.0)
    assert stats.average_seconds == pytest.approx(2.0)


def test_timer_can_be_switched_off(cards: list[Flashcard]) -> None:
    """With the timer off, no time is attributed to any answer."""
    session = QuizSession(
        SequentialMode(cards), EchoProvider(), timer=False, clock=FakeClock(step=5.0)
    )

    stats = session.run()

    assert stats.total_seconds == 0.0


def test_session_stops_when_the_user_quits(cards: list[Flashcard]) -> None:
    """Returning None from the provider ends the session cleanly."""
    session = QuizSession(SequentialMode(cards), ScriptedProvider(["API", None]))

    stats = session.run()

    assert stats.total_questions == 1
    assert session.aborted is True


def test_session_survives_a_keyboard_interrupt(cards: list[Flashcard]) -> None:
    """Ctrl+C ends the quiz and still produces a summary."""

    class Interrupting:
        """A provider that answers once, then raises KeyboardInterrupt."""

        def __init__(self) -> None:
            """Start with no questions answered."""
            self.calls = 0

        def ask(self, card: Flashcard, number: int, total: int | None) -> str | None:
            """Answer the first question, then interrupt."""
            self.calls += 1
            if self.calls == 1:
                return card.back
            raise KeyboardInterrupt

    session = QuizSession(SequentialMode(cards), Interrupting())

    stats = session.run()

    assert stats.total_questions == 1
    assert session.aborted is True


def test_observers_receive_the_whole_session(cards: list[Flashcard]) -> None:
    """Every lifecycle event reaches an attached observer, in order."""
    events: list[str] = []

    class Recorder:
        """An observer that notes the name of each event it receives."""

        def on_session_start(self, deck_name: str, mode: str, total: int) -> None:
            """Note the session banner."""
            events.append(f"start:{deck_name}:{mode}:{total}")

        def on_question(self, card: Flashcard, number: int) -> None:
            """Note the question number."""
            events.append(f"question:{number}")

        def on_answer(self, result: Any) -> None:
            """Note whether the answer was accepted."""
            events.append(f"answer:{result.correct}")

        def on_session_end(self, stats: Any) -> None:
            """Note how many questions were answered."""
            events.append(f"end:{stats.total_questions}")

    subject = SessionSubject([Recorder()])
    QuizSession(
        SequentialMode(cards, limit=1),
        EchoProvider(),
        deck_name="Acronyms",
        subject=subject,
    ).run()

    assert events == [
        "start:Acronyms:sequential:3",
        "question:1",
        "answer:True",
        "end:1",
    ]


def test_one_broken_observer_does_not_stop_the_quiz(
    cards: list[Flashcard], caplog: pytest.LogCaptureFixture
) -> None:
    """An observer that raises is logged and the other observers still run."""

    class Exploding(BaseSessionObserver):
        """An observer that fails on every answer."""

        def on_answer(self, result: Any) -> None:
            """Fail, to prove one bad observer cannot end the quiz."""
            raise RuntimeError("observer is broken")

    seen: list[bool] = []

    class Healthy(BaseSessionObserver):
        """An observer that records answers normally."""

        def on_answer(self, result: Any) -> None:
            """Record the outcome so the test can assert it arrived."""
            seen.append(result.correct)

    subject = SessionSubject([Exploding(), Healthy()])
    session = QuizSession(SequentialMode(cards), EchoProvider(), subject=subject)

    stats = session.run()

    assert stats.total_questions == 3
    assert seen == [True, True, True]
    assert "Exploding" in caplog.text


def test_progress_observer_persists_across_sessions(
    tmp_path: Path, cards: list[Flashcard]
) -> None:
    """A miss recorded in one session is visible to the next one."""
    progress_file = tmp_path / "progress.json"
    store = ProgressStore.load(progress_file)
    subject = SessionSubject([ProgressObserver(store), LoggingObserver()])

    QuizSession(
        SequentialMode(cards),
        ScriptedProvider(["wrong", "Central Processing Unit", "wrong"]),
        subject=subject,
    ).run()

    assert progress_file.exists()
    reloaded = ProgressStore.load(progress_file)
    assert reloaded.records["api"].incorrect == 1
    assert reloaded.records["cpu"].correct == 1
    assert reloaded.difficulty("api") > reloaded.difficulty("cpu")


def test_second_session_prioritises_the_previously_missed_card(
    tmp_path: Path, cards: list[Flashcard]
) -> None:
    """Adaptive mode reads the saved history and asks the weak card first.

    This is the feature the progress file exists for, so it is verified across
    two real sessions rather than against a stub oracle.
    """
    progress_file = tmp_path / "progress.json"
    store = ProgressStore.load(progress_file)
    QuizSession(
        SequentialMode(cards),
        ScriptedProvider(
            ["Application Programming Interface", "Central Processing Unit", "wrong"]
        ),
        subject=SessionSubject([ProgressObserver(store)]),
    ).run()

    second_store = ProgressStore.load(progress_file)
    mode = QuizModeFactory.create("adaptive", cards, oracle=second_store)
    first_card = mode.next_card()

    assert isinstance(mode, AdaptiveMode)
    assert first_card is not None
    assert first_card.front == "DNS"


def test_cli_runs_a_full_quiz(
    write_deck: DeckWriter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main.run`` plays a scripted quiz and prints the summary."""
    deck = write_deck(
        [
            {"front": "API", "back": "Application Programming Interface"},
            {"front": "CPU", "back": "Central Processing Unit"},
        ],
        "cli.json",
    )
    answers = iter(["Application Programming Interface", "nope"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))

    exit_code = main.run(
        [
            "--file",
            str(deck),
            "--mode",
            "sequential",
            "--no-progress",
            "--no-color",
            "--no-timer",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Total questions  2" in output
    assert "Accuracy         50.0%" in output
    assert "CPU  ->  Central Processing Unit" in output


def test_cli_exports_the_session(
    write_deck: DeckWriter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--export json`` writes a report whose numbers match the summary."""
    deck = write_deck([{"front": "API", "back": "Interface"}], "export.json")
    monkeypatch.setattr("builtins.input", lambda: "Interface")
    destination = tmp_path / "report.json"

    exit_code = main.run(
        [
            "-f",
            str(deck),
            "--no-progress",
            "--no-color",
            "--export",
            "json",
            "--export-path",
            str(destination),
        ]
    )

    assert exit_code == 0
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["totals"] == {
        "questions": 1,
        "correct": 1,
        "incorrect": 0,
        "accuracy_percent": 100.0,
        "longest_streak": 1,
        "seconds": payload["totals"]["seconds"],
    }
    assert "Session exported to" in capsys.readouterr().out


def test_cli_reports_a_bad_deck_without_a_traceback(
    write_deck: DeckWriter, capsys: pytest.CaptureFixture[str]
) -> None:
    """A malformed deck exits 1 with one readable line on stderr."""
    deck = write_deck("{not json", "broken.json")

    exit_code = main.run(["-f", str(deck), "--no-progress"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("Error: ")
    assert "Traceback" not in captured.err


def test_cli_exits_cleanly_on_ctrl_c(
    write_deck: DeckWriter,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ctrl+C at the prompt ends the run with exit code 0, not a traceback."""
    deck = write_deck([{"front": "API", "back": "Interface"}], "interrupt.json")

    def interrupt() -> str:
        """Stand in for the user pressing Ctrl+C at the prompt."""
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)

    exit_code = main.run(["-f", str(deck), "--no-progress", "--no-color"])

    assert exit_code == 0
    assert "Traceback" not in capsys.readouterr().out


def test_cli_quit_word_stops_the_quiz(
    write_deck: DeckWriter,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Typing "exit" ends the session and the summary says so."""
    deck = write_deck(
        [{"front": "A", "back": "1"}, {"front": "B", "back": "2"}], "quit.json"
    )
    answers = iter(["1", "exit"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))

    exit_code = main.run(["-f", str(deck), "--no-progress", "--no-color"])

    # The summary pads its label column to the widest label, which depends on
    # whether timing rows are shown, so compare on collapsed whitespace.
    output = " ".join(capsys.readouterr().out.split())
    assert exit_code == 0
    assert "Total questions 1" in output
    assert "Session ended early" in output
