"""Tests for terminal presentation and prompting (:mod:`ui`)."""

from __future__ import annotations

import io
from typing import cast

import pytest

import ui
from models import CardResult, Flashcard
from ui import Console, ConsoleObserver, ConsolePresenter, supports_color

CARD = Flashcard("SSH", "Secure Shell")


class FakeTTY(io.StringIO):
    """A text stream that claims to be a terminal."""

    def isatty(self) -> bool:
        """Report that this stream can display escape sequences."""
        return True


@pytest.fixture
def plain_console() -> Console:
    """Return a console writing uncoloured text to a buffer."""
    return Console(io.StringIO(), color=False)


def read(console: Console) -> str:
    """Return everything written to ``console`` so far."""
    buffer = cast(io.StringIO, console.stream)
    return buffer.getvalue()


def test_color_is_suppressed_when_not_a_terminal() -> None:
    """Redirecting output to a file must not fill it with escape codes."""
    assert supports_color(io.StringIO(), requested=True) is False


def test_color_is_suppressed_when_not_requested() -> None:
    """--no-color wins even on a real terminal."""
    assert supports_color(FakeTTY(), requested=False) is False


def test_no_color_environment_variable_is_respected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The NO_COLOR convention disables colour regardless of the flag."""
    monkeypatch.setenv("NO_COLOR", "1")

    assert supports_color(FakeTTY(), requested=True) is False


def test_dumb_terminals_get_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """A TERM of "dumb" means escape sequences are not understood."""
    monkeypatch.setenv("TERM", "dumb")

    assert supports_color(FakeTTY(), requested=True) is False


def test_color_is_used_on_a_capable_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """On a real terminal with colour requested, escapes are emitted."""
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.setattr(ui, "_enable_windows_ansi", lambda: True)
    console = Console(FakeTTY(), color=True)

    console.write("hello", "green")

    assert "\033[32m" in read(console)


def test_paint_returns_plain_text_without_color(plain_console: Console) -> None:
    """With colour off, painting is a no-op."""
    assert plain_console.paint("hello", "red") == "hello"


def test_paint_ignores_unknown_styles(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo in a style name degrades to plain text, not a stray escape."""
    monkeypatch.setattr(ui, "_enable_windows_ansi", lambda: True)
    monkeypatch.delenv("TERM", raising=False)
    console = Console(FakeTTY(), color=True)

    assert console.paint("hello", "chartreuse") == "hello"


def test_write_and_rule(plain_console: Console) -> None:
    """Lines and dividers reach the stream."""
    plain_console.write("line one")
    plain_console.rule(width=5)

    assert read(plain_console) == "line one\n-----\n"


def test_prompt_returns_the_typed_line() -> None:
    """The prompt label is written and the typed line comes back."""
    console = Console(io.StringIO(), color=False, input_fn=lambda: "my answer")

    answer = console.prompt("Your answer: ")

    assert answer == "my answer"
    assert "Your answer: " in read(console)


def test_presenter_shows_the_question_and_counter() -> None:
    """Each question is shown with its number and the deck total."""
    console = Console(io.StringIO(), color=False, input_fn=lambda: "Secure Shell")
    presenter = ConsolePresenter(console)

    answer = presenter.ask(CARD, number=2, total=10)

    output = read(console)
    assert answer == "Secure Shell"
    assert "Question 2 of 10" in output
    assert "SSH" in output


def test_presenter_hides_the_total_when_it_is_open_ended() -> None:
    """Adaptive mode has no fixed total, so the counter does not invent one."""
    console = Console(io.StringIO(), color=False, input_fn=lambda: "x")

    ConsolePresenter(console).ask(CARD, number=1, total=None)

    assert "Question 1\n" in read(console)


@pytest.mark.parametrize("word", ["exit", "quit", "EXIT", "  Quit  ", ":q"])
def test_quit_words_end_the_session(word: str) -> None:
    """Any quit word returns None, which the engine reads as "stop"."""
    console = Console(io.StringIO(), color=False, input_fn=lambda: word)

    assert ConsolePresenter(console).ask(CARD, 1, 1) is None


@pytest.mark.parametrize("word", ["skip", "pass", "?", " SKIP "])
def test_skip_words_count_as_a_blank_answer(word: str) -> None:
    """Skipping is scored wrong without pretending the user typed "skip"."""
    console = Console(io.StringIO(), color=False, input_fn=lambda: word)

    assert ConsolePresenter(console).ask(CARD, 1, 1) == ""


def test_end_of_input_ends_the_session() -> None:
    """Ctrl+D or a closed pipe ends the quiz instead of raising."""

    def closed() -> str:
        """Stand in for a closed input stream (Ctrl+D or Ctrl+Z)."""
        raise EOFError

    console = Console(io.StringIO(), color=False, input_fn=closed)

    assert ConsolePresenter(console).ask(CARD, 1, 1) is None


def test_observer_announces_the_session(plain_console: Console) -> None:
    """The banner names the deck, the mode and the card count."""
    ConsoleObserver(plain_console).on_session_start("Acronyms", "adaptive", 12)

    output = read(plain_console)
    assert "Flashcard Quizzer - Acronyms" in output
    assert "Mode: adaptive   Cards: 12" in output


def test_observer_confirms_a_correct_answer(plain_console: Console) -> None:
    """A correct answer says so and reveals nothing further."""
    ConsoleObserver(plain_console).on_answer(
        CardResult(CARD, "Secure Shell", correct=True)
    )

    assert read(plain_console) == "Correct\n"


def test_observer_reveals_the_answer_after_a_miss(plain_console: Console) -> None:
    """A wrong answer is corrected on the spot."""
    ConsoleObserver(plain_console).on_answer(CardResult(CARD, "nope", correct=False))

    output = read(plain_console)
    assert "Incorrect" in output
    assert "Answer: Secure Shell" in output


def test_observer_can_keep_the_answer_hidden(plain_console: Console) -> None:
    """--hide-answers suppresses the reveal for self-testing."""
    observer = ConsoleObserver(plain_console, show_answer=False)

    observer.on_answer(CardResult(CARD, "nope", correct=False))

    output = read(plain_console)
    assert "Incorrect" in output
    assert "Secure Shell" not in output
