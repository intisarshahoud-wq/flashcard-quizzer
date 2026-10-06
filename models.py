"""Core immutable data structures shared by every layer of the quizzer.

This module deliberately holds no I/O and no presentation logic so that it can
be imported by the loader, the quiz engine, the reporter and the tests without
creating a dependency cycle.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field


def normalize_answer(text: str) -> str:
    """Return a comparison-ready form of ``text``.

    Normalization makes answer checking forgiving of the differences a human
    typist should not be punished for: surrounding whitespace, runs of internal
    whitespace, letter case, and Unicode forms that look identical but encode
    differently (for example a pre-composed ``e`` with an accent versus the
    same glyph built from a base letter plus a combining mark).

    Args:
        text: Raw text typed by the user, or the ``back`` of a card.

    Returns:
        The normalized string used for equality comparison.

    Examples:
        >>> normalize_answer("  Secure   SHELL ")
        'secure shell'
    """
    collapsed = " ".join(text.split())
    return unicodedata.normalize("NFKC", collapsed).casefold()


@dataclass(frozen=True, slots=True)
class Flashcard:
    """A single question/answer pair.

    Attributes:
        front: The prompt shown to the user.
        back: The expected answer.
    """

    front: str
    back: str

    @property
    def key(self) -> str:
        """Return a stable identifier for this card.

        The normalized ``front`` is used rather than the list index so that
        progress recorded in one session still matches the card after the deck
        has been reordered or extended.
        """
        return normalize_answer(self.front)

    def matches(self, answer: str) -> bool:
        """Return ``True`` if ``answer`` is an acceptable response.

        Comparison is case-insensitive and whitespace-insensitive. A card whose
        ``back`` contains ``|`` accepts any of the pipe-separated alternatives,
        which lets a deck author write ``"def|def keyword"`` without needing a
        richer file format.

        Args:
            answer: The text the user typed.

        Returns:
            ``True`` when the answer matches the card, ``False`` otherwise.
        """
        given = normalize_answer(answer)
        if not given:
            return False
        accepted = (normalize_answer(part) for part in self.back.split("|"))
        return any(given == option for option in accepted if option)


@dataclass(frozen=True, slots=True)
class CardResult:
    """The outcome of a single answered question.

    Attributes:
        card: The card that was asked.
        given_answer: Exactly what the user typed, preserved for the report.
        correct: Whether the answer was accepted.
        elapsed_seconds: Wall-clock seconds spent on this question.
    """

    card: Flashcard
    given_answer: str
    correct: bool
    elapsed_seconds: float = 0.0


@dataclass
class SessionStats:
    """Accumulates results and derives the end-of-session summary.

    The engine appends to this object; the reporter only reads from it. Keeping
    the arithmetic here means the percentages in the terminal summary and in an
    exported file can never disagree.
    """

    results: list[CardResult] = field(default_factory=list)

    def record(self, result: CardResult) -> None:
        """Append ``result`` to the session history."""
        self.results.append(result)

    @property
    def total_questions(self) -> int:
        """Return how many questions were answered."""
        return len(self.results)

    @property
    def correct_count(self) -> int:
        """Return how many answers were correct."""
        return sum(1 for result in self.results if result.correct)

    @property
    def incorrect_count(self) -> int:
        """Return how many answers were incorrect."""
        return self.total_questions - self.correct_count

    @property
    def accuracy(self) -> float:
        """Return accuracy as a percentage in the range 0.0-100.0.

        An empty session scores ``0.0`` rather than raising, because quitting
        before the first answer is a normal way to end a quiz.
        """
        if not self.results:
            return 0.0
        return self.correct_count / self.total_questions * 100.0

    @property
    def missed_cards(self) -> list[Flashcard]:
        """Return the distinct cards answered incorrectly, in first-miss order."""
        seen: set[str] = set()
        missed: list[Flashcard] = []
        for result in self.results:
            if result.correct or result.card.key in seen:
                continue
            seen.add(result.card.key)
            missed.append(result.card)
        return missed

    @property
    def total_seconds(self) -> float:
        """Return the total time spent answering."""
        return sum(result.elapsed_seconds for result in self.results)

    @property
    def average_seconds(self) -> float:
        """Return the mean seconds per question, or ``0.0`` for an empty session."""
        if not self.results:
            return 0.0
        return self.total_seconds / self.total_questions

    @property
    def fastest_result(self) -> CardResult | None:
        """Return the quickest correct answer, or ``None`` if there was none."""
        correct = [result for result in self.results if result.correct]
        if not correct:
            return None
        return min(correct, key=lambda result: result.elapsed_seconds)

    @property
    def longest_streak(self) -> int:
        """Return the length of the longest run of consecutive correct answers."""
        best = 0
        current = 0
        for result in self.results:
            current = current + 1 if result.correct else 0
            best = max(best, current)
        return best
