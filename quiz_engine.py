"""The quiz engine: card-selection strategies, their factory, and the loop.

Design patterns in this module
------------------------------

**Strategy** -- :class:`QuizMode` defines one operation, "give me the next card
to ask". Sequential, random, adaptive and spaced-repetition selection are four
interchangeable implementations of it. :class:`QuizSession` drives the loop and
never asks which one it is holding.

**Factory** -- :class:`QuizModeFactory` turns the ``--mode`` string from the
command line into a configured strategy object. Registration is a decorator, so
adding a mode means writing one class; nothing else in the codebase changes,
and ``--help`` picks the new name up automatically.
"""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable, Sequence
from typing import ClassVar, Protocol

from models import CardResult, Flashcard, SessionStats
from observers import SessionSubject

#: How many other cards are asked before a missed card comes round again.
#: One intervening card would make the repeat a giveaway; too many and a short
#: deck would end before the repeat ever happened.
REQUEUE_GAP: int = 2

#: How many extra times a single card may be re-asked within one session.
MAX_REPEATS: int = 2


class QuizAborted(Exception):
    """Raised internally when the user asks to quit mid-session."""


class DifficultyOracle(Protocol):
    """Read-only view of a card's history, as the adaptive modes need it.

    Declaring this as a protocol keeps the engine independent of
    :mod:`progress_store`: anything exposing these two methods will do, which
    is what lets the tests drive the modes with a hand-built stub.
    """

    def difficulty(self, key: str) -> float:
        """Return a 0.0-1.0 score, higher meaning the card is harder."""
        ...

    def due_score(self, key: str) -> float:
        """Return how overdue the card is; higher means more urgent."""
        ...


class NullOracle:
    """An oracle with no history, used when progress tracking is disabled."""

    def difficulty(self, key: str) -> float:
        """Return a neutral difficulty for every card."""
        return 0.5

    def due_score(self, key: str) -> float:
        """Return a neutral urgency for every card."""
        return 1.0


class AnswerProvider(Protocol):
    """Supplies the user's answer for a card.

    Implemented by the console UI in production and by a scripted stub in the
    integration tests, which is the whole reason the engine depends on this
    protocol rather than calling :func:`input` itself.
    """

    def ask(self, card: Flashcard, number: int, total: int | None) -> str | None:
        """Return the user's answer, or ``None`` if they want to stop."""
        ...


class QuizMode(ABC):
    """Base strategy for choosing which card to ask next.

    Subclasses supply an initial ordering via :meth:`build_queue` and may
    override :meth:`record_result` to react to an answer, as the adaptive modes
    do when they put a missed card back into the queue.

    Attributes:
        name: The value accepted by ``--mode``.
        description: One-line help text shown by ``--help`` and ``--list-modes``.
    """

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""

    def __init__(
        self,
        cards: Sequence[Flashcard],
        *,
        rng: random.Random | None = None,
        oracle: DifficultyOracle | None = None,
        limit: int | None = None,
    ) -> None:
        """Create a strategy over ``cards``.

        Args:
            cards: The deck to quiz on. Must not be empty.
            rng: Random source, injectable so tests are deterministic.
            oracle: History provider for the history-aware modes.
            limit: Maximum questions to ask, or ``None`` for no cap.

        Raises:
            ValueError: If ``cards`` is empty or ``limit`` is not positive.
        """
        if not cards:
            raise ValueError("Cannot start a quiz with an empty deck.")
        if limit is not None and limit <= 0:
            raise ValueError("Question limit must be a positive whole number.")
        self._cards: tuple[Flashcard, ...] = tuple(cards)
        self._rng = rng or random.Random()
        self._oracle: DifficultyOracle = oracle or NullOracle()
        self._limit = limit
        self._asked = 0
        self._repeats: dict[str, int] = {}
        self._queue: deque[Flashcard] = deque(self.build_queue())

    @abstractmethod
    def build_queue(self) -> list[Flashcard]:
        """Return the cards in the order this strategy wants to ask them."""

    @property
    def cards(self) -> tuple[Flashcard, ...]:
        """Return the deck this strategy was built over."""
        return self._cards

    @property
    def asked(self) -> int:
        """Return how many questions have been handed out so far."""
        return self._asked

    @property
    def remaining(self) -> int:
        """Return how many more questions this strategy will serve."""
        pending = len(self._queue)
        if self._limit is None:
            return pending
        return max(0, min(pending, self._limit - self._asked))

    @property
    def planned_total(self) -> int | None:
        """Return the expected question count, or ``None`` if it can grow.

        The adaptive modes re-queue missed cards, so their final count is not
        knowable up front and the UI shows an open-ended counter instead.
        """
        if self._limit is not None:
            return min(self._limit, len(self._cards))
        return len(self._cards)

    def next_card(self) -> Flashcard | None:
        """Return the next card to ask, or ``None`` when the quiz is over."""
        if self._limit is not None and self._asked >= self._limit:
            return None
        if not self._queue:
            return None
        card = self._queue.popleft()
        self._asked += 1
        return card

    def record_result(self, card: Flashcard, correct: bool) -> None:
        """React to an answer. The base strategy ignores it."""

    def _requeue(self, card: Flashcard, gap: int = REQUEUE_GAP) -> bool:
        """Put ``card`` back into the queue a few positions ahead.

        Args:
            card: The card to ask again.
            gap: How many queued cards to let through first.

        Returns:
            ``True`` if the card was re-queued, ``False`` if it had already
            been repeated :data:`MAX_REPEATS` times. The cap is what guarantees
            the loop terminates even if the user never answers correctly.
        """
        seen = self._repeats.get(card.key, 0)
        if seen >= MAX_REPEATS:
            return False
        self._repeats[card.key] = seen + 1
        position = min(gap, len(self._queue))
        self._queue.insert(position, card)
        return True


class QuizModeFactory:
    """Creates quiz strategies by name.

    The registry is populated by the :meth:`register` decorator at import time,
    which keeps the list of modes next to the classes themselves instead of in
    a second place that can drift out of date.
    """

    _registry: ClassVar[dict[str, type[QuizMode]]] = {}

    @classmethod
    def register(cls, mode_cls: type[QuizMode]) -> type[QuizMode]:
        """Register ``mode_cls`` under its :attr:`~QuizMode.name`.

        Args:
            mode_cls: The strategy class to register.

        Returns:
            The same class, so this works as a decorator.

        Raises:
            ValueError: If the class has no name or the name is already taken.
        """
        key = mode_cls.name.strip().lower()
        if not key:
            raise ValueError(f"{mode_cls.__name__} must define a non-empty name.")
        if key in cls._registry and cls._registry[key] is not mode_cls:
            raise ValueError(f"Quiz mode {key!r} is already registered.")
        cls._registry[key] = mode_cls
        return mode_cls

    @classmethod
    def available(cls) -> tuple[str, ...]:
        """Return every registered mode name, sorted."""
        return tuple(sorted(cls._registry))

    @classmethod
    def describe(cls) -> dict[str, str]:
        """Return each mode name mapped to its one-line description."""
        return {name: cls._registry[name].description for name in sorted(cls._registry)}

    @classmethod
    def get(cls, name: str) -> type[QuizMode]:
        """Return the class registered under ``name``.

        Args:
            name: A mode name; case and surrounding whitespace are ignored.

        Returns:
            The registered strategy class.

        Raises:
            ValueError: If no mode is registered under that name. The message
                lists the valid names so the user can correct the typo.
        """
        key = str(name).strip().lower()
        if key not in cls._registry:
            valid = ", ".join(cls.available())
            raise ValueError(f"Unknown quiz mode {name!r}. Choose one of: {valid}.")
        return cls._registry[key]

    @classmethod
    def create(
        cls,
        name: str,
        cards: Sequence[Flashcard],
        *,
        rng: random.Random | None = None,
        oracle: DifficultyOracle | None = None,
        limit: int | None = None,
    ) -> QuizMode:
        """Return a configured strategy instance for ``name``.

        Args:
            name: The mode name from the command line or config.
            cards: The deck to quiz on.
            rng: Random source, injectable for deterministic tests.
            oracle: History provider for history-aware modes.
            limit: Maximum questions to ask.

        Returns:
            A ready-to-use :class:`QuizMode`.

        Raises:
            ValueError: If the name is unknown or the arguments are invalid.
        """
        mode_cls = cls.get(name)
        return mode_cls(cards, rng=rng, oracle=oracle, limit=limit)


@QuizModeFactory.register
class SequentialMode(QuizMode):
    """Asks every card once, in the order the deck file lists them."""

    name = "sequential"
    description = "Ask the cards in deck order, from first to last."

    def build_queue(self) -> list[Flashcard]:
        """Return the deck unchanged."""
        return list(self._cards)


@QuizModeFactory.register
class RandomMode(QuizMode):
    """Asks every card once, in a shuffled order."""

    name = "random"
    description = "Shuffle the deck and ask each card once."

    def build_queue(self) -> list[Flashcard]:
        """Return a shuffled copy of the deck.

        The copy matters: shuffling in place would reorder the caller's deck as
        a side effect, which would silently change what a later sequential run
        does.
        """
        shuffled = list(self._cards)
        self._rng.shuffle(shuffled)
        return shuffled


@QuizModeFactory.register
class AdaptiveMode(QuizMode):
    """Front-loads the cards the user has struggled with, and repeats misses.

    Ordering combines two signals: the long-term difficulty from the progress
    store, and a small random jitter so that a run is not identical every time
    the same deck is opened. Within the session, a missed card is pushed back
    into the queue a couple of positions later, which is the behaviour that
    distinguishes this mode from a plain weighted shuffle.
    """

    name = "adaptive"
    description = "Prioritise cards you have missed before, and repeat misses."

    #: How much random jitter to add to each difficulty score when ordering.
    JITTER: ClassVar[float] = 0.05

    def build_queue(self) -> list[Flashcard]:
        """Return the deck ordered hardest-first."""

        def sort_key(indexed: tuple[int, Flashcard]) -> tuple[float, int]:
            index, card = indexed
            score = self._oracle.difficulty(card.key)
            score += self._rng.uniform(-self.JITTER, self.JITTER)
            return (-score, index)

        ordered = sorted(enumerate(self._cards), key=sort_key)
        return [card for _, card in ordered]

    def record_result(self, card: Flashcard, correct: bool) -> None:
        """Re-queue ``card`` when the answer was wrong.

        Args:
            card: The card just asked.
            correct: Whether the user answered it correctly.
        """
        if not correct:
            self._requeue(card)

    @property
    def planned_total(self) -> int | None:
        """Return ``None``: re-queued misses make the total open-ended."""
        return None


@QuizModeFactory.register
class SpacedRepetitionMode(QuizMode):
    """Asks whatever is most overdue, using the stored SM-2 schedule.

    This mode exists to demonstrate that the Strategy pattern paid for itself:
    it was added after the engine, the CLI and the tests were complete, and it
    required no change to any of them beyond this class.
    """

    name = "spaced"
    description = "Review by schedule: most overdue cards first (SM-2 style)."

    def build_queue(self) -> list[Flashcard]:
        """Return the deck ordered most-overdue first, hardest breaking ties."""

        def sort_key(indexed: tuple[int, Flashcard]) -> tuple[float, float, int]:
            index, card = indexed
            return (
                -self._oracle.due_score(card.key),
                -self._oracle.difficulty(card.key),
                index,
            )

        ordered = sorted(enumerate(self._cards), key=sort_key)
        return [card for _, card in ordered]

    def record_result(self, card: Flashcard, correct: bool) -> None:
        """Re-queue a missed card at the back of the queue."""
        if not correct:
            self._requeue(card, gap=len(self._queue))


class QuizSession:
    """Runs the question/answer loop and collects the results.

    The session owns no I/O of its own: it pulls answers from an
    :class:`AnswerProvider` and announces what happened through a
    :class:`~observers.SessionSubject`.
    """

    def __init__(
        self,
        mode: QuizMode,
        provider: AnswerProvider,
        *,
        deck_name: str = "deck",
        subject: SessionSubject | None = None,
        timer: bool = True,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        """Create a session.

        Args:
            mode: The card-selection strategy to use.
            provider: Where answers come from.
            deck_name: Display name, passed through to observers.
            subject: Event dispatcher. A fresh empty one is created if omitted.
            timer: Whether to measure how long each answer takes.
            clock: Monotonic clock, injectable so tests can control timings.
        """
        self._mode = mode
        self._provider = provider
        self._deck_name = deck_name
        self._subject = subject or SessionSubject()
        self._timer = timer
        self._clock = clock
        self.stats = SessionStats()
        self.aborted = False

    @property
    def subject(self) -> SessionSubject:
        """Return the event dispatcher used by this session."""
        return self._subject

    def run(self) -> SessionStats:
        """Run the quiz to completion and return the collected statistics.

        The loop ends when the strategy runs out of cards, when the user asks
        to quit, or when they interrupt with Ctrl+C. All three are normal
        endings: the session summary is still produced and observers still
        receive :meth:`~observers.SessionObserver.on_session_end`.

        Returns:
            The statistics for the session.
        """
        self._subject.session_started(
            self._deck_name, self._mode.name, len(self._mode.cards)
        )
        number = 0
        try:
            while True:
                card = self._mode.next_card()
                if card is None:
                    break
                number += 1
                self._subject.question_asked(card, number)
                started = self._clock()
                answer = self._provider.ask(card, number, self._mode.planned_total)
                if answer is None:
                    self.aborted = True
                    break
                elapsed = self._clock() - started if self._timer else 0.0
                result = CardResult(
                    card=card,
                    given_answer=answer,
                    correct=card.matches(answer),
                    elapsed_seconds=max(0.0, elapsed),
                )
                self.stats.record(result)
                self._mode.record_result(card, result.correct)
                self._subject.answer_graded(result)
        except KeyboardInterrupt:
            self.aborted = True
        finally:
            self._subject.session_ended(self.stats)
        return self.stats
