"""Observer pattern plumbing for quiz session events.

The quiz engine announces what happened; it never decides what should be done
about it. Printing feedback, writing a log line and updating the saved progress
file are three unrelated reactions to the same events, and each lives in its
own observer. Adding a fourth reaction -- a sound effect, a web hook, a
leaderboard -- means writing one class and attaching it, with no change to the
engine at all.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from models import CardResult, Flashcard, SessionStats
from progress_store import ProgressStore
from utils.file_handler import FileHandlerError


@runtime_checkable
class SessionObserver(Protocol):
    """Anything that wants to be told what happens during a quiz.

    Every method has a default-free signature but observers are free to
    implement only what they care about by subclassing
    :class:`BaseSessionObserver`.
    """

    def on_session_start(self, deck_name: str, mode_name: str, total: int) -> None:
        """Called once before the first question."""

    def on_question(self, card: Flashcard, number: int) -> None:
        """Called just before ``card`` is put to the user."""

    def on_answer(self, result: CardResult) -> None:
        """Called after each answer is graded."""

    def on_session_end(self, stats: SessionStats) -> None:
        """Called once after the last question, including after an early quit."""


class BaseSessionObserver:
    """A no-op observer, so subclasses override only the events they want."""

    def on_session_start(self, deck_name: str, mode_name: str, total: int) -> None:
        """Ignore the start of the session."""

    def on_question(self, card: Flashcard, number: int) -> None:
        """Ignore the question being asked."""

    def on_answer(self, result: CardResult) -> None:
        """Ignore the graded answer."""

    def on_session_end(self, stats: SessionStats) -> None:
        """Ignore the end of the session."""


class SessionSubject:
    """Holds observers and fans each event out to all of them.

    An exception raised by one observer must not abort the quiz or stop the
    other observers, so each notification is isolated. The failure is logged
    rather than swallowed silently.
    """

    def __init__(self, observers: list[SessionObserver] | None = None) -> None:
        """Create a subject, optionally pre-attached to ``observers``."""
        self._observers: list[SessionObserver] = list(observers or [])
        self._logger = logging.getLogger("flashcard.events")

    @property
    def observers(self) -> tuple[SessionObserver, ...]:
        """Return the currently attached observers."""
        return tuple(self._observers)

    def attach(self, observer: SessionObserver) -> None:
        """Add ``observer`` if it is not attached already."""
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer: SessionObserver) -> None:
        """Remove ``observer`` if present; do nothing otherwise."""
        if observer in self._observers:
            self._observers.remove(observer)

    def _dispatch(self, event: str, *args: object) -> None:
        """Call ``event`` on every observer, isolating failures."""
        for observer in list(self._observers):
            handler = getattr(observer, event, None)
            if handler is None:
                continue
            try:
                handler(*args)
            except Exception:  # noqa: BLE001 - one bad observer must not end the quiz
                self._logger.exception(
                    "Observer %s failed handling %s",
                    type(observer).__name__,
                    event,
                )

    def session_started(self, deck_name: str, mode_name: str, total: int) -> None:
        """Announce the start of a session."""
        self._dispatch("on_session_start", deck_name, mode_name, total)

    def question_asked(self, card: Flashcard, number: int) -> None:
        """Announce that ``card`` is about to be asked."""
        self._dispatch("on_question", card, number)

    def answer_graded(self, result: CardResult) -> None:
        """Announce a graded answer."""
        self._dispatch("on_answer", result)

    def session_ended(self, stats: SessionStats) -> None:
        """Announce the end of a session."""
        self._dispatch("on_session_end", stats)


class LoggingObserver(BaseSessionObserver):
    """Writes a structured trace of the session to the logging framework."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        """Create the observer, defaulting to the ``flashcard.session`` logger."""
        self._logger = logger or logging.getLogger("flashcard.session")

    def on_session_start(self, deck_name: str, mode_name: str, total: int) -> None:
        """Log which deck and mode the session started with."""
        self._logger.info(
            "Session started: deck=%r mode=%s cards=%d", deck_name, mode_name, total
        )

    def on_answer(self, result: CardResult) -> None:
        """Log each graded answer at debug level."""
        self._logger.debug(
            "Answer: front=%r given=%r correct=%s seconds=%.2f",
            result.card.front,
            result.given_answer,
            result.correct,
            result.elapsed_seconds,
        )

    def on_session_end(self, stats: SessionStats) -> None:
        """Log the headline numbers for the finished session."""
        self._logger.info(
            "Session ended: answered=%d correct=%d accuracy=%.1f%%",
            stats.total_questions,
            stats.correct_count,
            stats.accuracy,
        )


class ProgressObserver(BaseSessionObserver):
    """Feeds every answer into the :class:`~progress_store.ProgressStore`.

    The store is written once, at the end of the session, rather than after
    every answer: a quiz is short, and one atomic write is both faster and less
    likely to leave a half-updated file behind.
    """

    def __init__(self, store: ProgressStore, *, autosave: bool = True) -> None:
        """Create the observer.

        Args:
            store: The store to update.
            autosave: Whether to write the store to disk when the session ends.
        """
        self._store = store
        self._autosave = autosave
        self._logger = logging.getLogger("flashcard.progress")
        self.save_error: str | None = None

    @property
    def store(self) -> ProgressStore:
        """Return the store this observer updates."""
        return self._store

    def on_answer(self, result: CardResult) -> None:
        """Record the answer against the card's long-term history."""
        self._store.register(result.card, result.correct)

    def on_session_end(self, stats: SessionStats) -> None:
        """Persist the updated history, recording any failure for the caller.

        A failed save must not crash the application after the user has
        finished a quiz, so the error is captured in :attr:`save_error` for the
        CLI to report as a warning.
        """
        if not self._autosave or stats.total_questions == 0:
            return
        try:
            self._store.save()
        except FileHandlerError as exc:
            self.save_error = str(exc)
            self._logger.warning("Could not save progress: %s", exc)
