"""Terminal presentation: colour, prompts and the console observer.

Colour is handled with raw ANSI escapes rather than a third-party package. The
project needs eight sequences, and depending on ``colorama`` for that would add
an install-time requirement to a tool whose selling point is that it runs on a
bare Python. Windows 10 and later understand the same escapes once virtual
terminal processing is switched on, which :func:`_enable_windows_ansi` does.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Final, TextIO

from models import CardResult, Flashcard
from observers import BaseSessionObserver

#: Answers that mean "stop the quiz" rather than "this is my answer".
QUIT_WORDS: Final[frozenset[str]] = frozenset({"exit", "quit", ":q"})

#: Answers that mean "I do not know", scored as wrong but without a typo.
SKIP_WORDS: Final[frozenset[str]] = frozenset({"skip", "pass", "?"})

_RESET: Final[str] = "\033[0m"
_CODES: Final[dict[str, str]] = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "bold": "\033[1m",
    "dim": "\033[2m",
}


def _enable_windows_ansi() -> bool:
    """Switch on ANSI escape handling for the Windows console.

    Returns:
        ``True`` if escapes can be used, ``False`` if the console refused.
        Any failure is treated as "no colour" rather than an error, because a
        quiz that runs without colour is still a working quiz.
    """
    if os.name != "nt":  # pragma: no cover - platform-specific
        return True
    try:  # pragma: no cover - requires a real Windows console handle
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        enable_virtual_terminal = 0x0004
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(
            kernel32.SetConsoleMode(handle, mode.value | enable_virtual_terminal)
        )
    except Exception:  # pragma: no cover - any failure means "no colour"
        return False


def supports_color(stream: TextIO, requested: bool = True) -> bool:
    """Return whether coloured output should be written to ``stream``.

    Colour is suppressed when the user turned it off, when the ``NO_COLOR``
    convention is set, when the stream is not a terminal (so that redirecting
    output to a file gives clean text), or when a dumb terminal is in use.

    Args:
        stream: The destination stream.
        requested: Whether colour was requested at all.

    Returns:
        ``True`` if escape sequences may be written.
    """
    if not requested:
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    return _enable_windows_ansi()


class Console:
    """Writes to a stream, adding colour only when the stream can take it."""

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        color: bool = True,
        input_fn: Callable[[], str] | None = None,
    ) -> None:
        """Create a console.

        Args:
            stream: Destination for output. Defaults to :data:`sys.stdout`.
            color: Whether colour is wanted. It is still suppressed if the
                stream cannot display it.
            input_fn: Callable used to read a line. Defaults to :func:`input`,
                and is injected by the tests.
        """
        self.stream: TextIO = stream if stream is not None else sys.stdout
        self.color_enabled: bool = supports_color(self.stream, color)
        self._input: Callable[[], str] = input_fn if input_fn is not None else input

    def paint(self, text: str, *styles: str) -> str:
        """Return ``text`` wrapped in the given styles, or unchanged.

        Args:
            text: The text to style.
            *styles: Style names from :data:`_CODES`. Unknown names are
                ignored so a typo degrades to plain text instead of printing
                a stray escape sequence.

        Returns:
            The styled, or unstyled, text.
        """
        if not self.color_enabled or not styles:
            return text
        prefix = "".join(_CODES[style] for style in styles if style in _CODES)
        return f"{prefix}{text}{_RESET}" if prefix else text

    def write(self, text: str = "", *styles: str) -> None:
        """Write one line of ``text`` in the given styles."""
        print(self.paint(text, *styles), file=self.stream)

    def rule(self, width: int = 56) -> None:
        """Write a horizontal divider."""
        self.write("-" * width, "dim")

    def prompt(self, label: str) -> str:
        """Read one line from the user.

        Args:
            label: The prompt text, written without a trailing newline.

        Returns:
            The raw line the user typed.

        Raises:
            EOFError: If the input stream closed.
        """
        print(self.paint(label, "cyan"), end="", file=self.stream, flush=True)
        return str(self._input())


class ConsolePresenter:
    """Asks questions at the terminal; the engine's :class:`AnswerProvider`."""

    def __init__(self, console: Console) -> None:
        """Create a presenter writing to ``console``."""
        self.console = console

    def ask(self, card: Flashcard, number: int, total: int | None) -> str | None:
        """Show ``card`` and return the user's answer.

        Args:
            card: The card to show.
            number: The 1-based question number.
            total: Expected question count, or ``None`` when it is open-ended.

        Returns:
            The answer text, or ``None`` if the user asked to stop by typing a
            quit word, or by closing the input stream with Ctrl+D or Ctrl+Z.
            A skip word returns an empty string, which the grader counts as an
            incorrect answer without pretending the user typed that word.
        """
        counter = f"Question {number}" + (f" of {total}" if total else "")
        self.console.write()
        self.console.write(counter, "dim")
        self.console.write(card.front, "bold")
        try:
            answer = self.console.prompt("Your answer: ")
        except EOFError:
            self.console.write()
            return None
        normalized = answer.strip().lower()
        if normalized in QUIT_WORDS:
            return None
        if normalized in SKIP_WORDS:
            return ""
        return answer


class ConsoleObserver(BaseSessionObserver):
    """Prints the session banner and per-answer feedback."""

    def __init__(self, console: Console, *, show_answer: bool = True) -> None:
        """Create the observer.

        Args:
            console: Where to write.
            show_answer: Whether to reveal the expected answer after a miss.
        """
        self.console = console
        self.show_answer = show_answer

    def on_session_start(self, deck_name: str, mode_name: str, total: int) -> None:
        """Print which deck and mode the session is running."""
        self.console.write()
        self.console.write(f"Flashcard Quizzer - {deck_name}", "bold", "cyan")
        self.console.write(f"Mode: {mode_name}   Cards: {total}", "dim")
        self.console.write(
            'Type your answer, "skip" to pass, or "exit" to stop early.', "dim"
        )
        self.console.rule()

    def on_answer(self, result: CardResult) -> None:
        """Print whether the answer was accepted, and the answer if not."""
        if result.correct:
            self.console.write("Correct", "green", "bold")
            return
        self.console.write("Incorrect", "red", "bold")
        if self.show_answer:
            self.console.write(f"  Answer: {result.card.back}", "yellow")
