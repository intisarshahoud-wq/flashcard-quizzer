"""Tests for the quiz strategies and their factory (:mod:`quiz_engine`)."""

from __future__ import annotations

import random

import pytest

from conftest import FakeOracle
from models import Flashcard
from quiz_engine import (
    MAX_REPEATS,
    AdaptiveMode,
    NullOracle,
    QuizMode,
    QuizModeFactory,
    RandomMode,
    SequentialMode,
    SpacedRepetitionMode,
)


def drain(mode: QuizMode) -> list[str]:
    """Return the fronts of every card ``mode`` serves, answering nothing."""
    served: list[str] = []
    while True:
        card = mode.next_card()
        if card is None:
            return served
        served.append(card.front)


def test_quiz_mode_factory(cards: list[Flashcard]) -> None:
    """The factory maps each registered name to the right class."""
    expected: dict[str, type[QuizMode]] = {
        "sequential": SequentialMode,
        "random": RandomMode,
        "adaptive": AdaptiveMode,
        "spaced": SpacedRepetitionMode,
    }

    for name, mode_cls in expected.items():
        assert QuizModeFactory.get(name) is mode_cls
        assert isinstance(QuizModeFactory.create(name, cards), mode_cls)

    assert QuizModeFactory.available() == ("adaptive", "random", "sequential", "spaced")


def test_factory_is_case_and_whitespace_insensitive(cards: list[Flashcard]) -> None:
    """A user typing "  Adaptive " still gets the adaptive mode."""
    assert isinstance(QuizModeFactory.create("  Adaptive ", cards), AdaptiveMode)


def test_factory_rejects_unknown_mode_and_lists_valid_ones(
    cards: list[Flashcard],
) -> None:
    """An unknown mode names the valid choices instead of failing silently."""
    with pytest.raises(ValueError) as excinfo:
        QuizModeFactory.create("telepathy", cards)

    message = str(excinfo.value)
    assert "telepathy" in message
    assert "sequential" in message


def test_factory_describe_covers_every_mode() -> None:
    """Every registered mode carries help text for --help and --list-modes."""
    described = QuizModeFactory.describe()

    assert set(described) == set(QuizModeFactory.available())
    assert all(text.strip() for text in described.values())


def test_factory_rejects_unnamed_mode() -> None:
    """A strategy class without a name cannot be registered."""

    class Nameless(QuizMode):
        """A deliberately misconfigured strategy."""

        def build_queue(self) -> list[Flashcard]:
            """Return nothing of interest."""
            return list(self._cards)

    with pytest.raises(ValueError, match="non-empty name"):
        QuizModeFactory.register(Nameless)


def test_factory_rejects_duplicate_registration() -> None:
    """Two strategies cannot claim the same --mode value."""

    class Clashing(QuizMode):
        """A strategy reusing an existing name."""

        name = "sequential"

        def build_queue(self) -> list[Flashcard]:
            """Return the deck unchanged."""
            return list(self._cards)

    with pytest.raises(ValueError, match="already registered"):
        QuizModeFactory.register(Clashing)


def test_sequential_mode_preserves_deck_order(cards: list[Flashcard]) -> None:
    """Sequential mode asks card 1 to N exactly once each."""
    mode = SequentialMode(cards)

    assert drain(mode) == ["API", "CPU", "DNS"]


def test_random_mode_asks_every_card_once(cards: list[Flashcard]) -> None:
    """Shuffling changes the order but never the membership."""
    mode = RandomMode(cards, rng=random.Random(1))

    served = drain(mode)

    assert sorted(served) == ["API", "CPU", "DNS"]


def test_random_mode_is_reproducible_from_a_seed(cards: list[Flashcard]) -> None:
    """The same seed produces the same order, which is what --seed promises."""
    first = drain(RandomMode(cards, rng=random.Random(99)))
    second = drain(RandomMode(cards, rng=random.Random(99)))

    assert first == second


def test_random_mode_does_not_mutate_the_caller_deck(cards: list[Flashcard]) -> None:
    """Shuffling must not reorder the deck the caller still holds."""
    original = list(cards)

    drain(RandomMode(cards, rng=random.Random(7)))

    assert cards == original


def test_adaptive_mode_orders_hardest_cards_first(cards: list[Flashcard]) -> None:
    """Cards with a worse history are asked before easier ones."""
    oracle = FakeOracle({"api": 0.1, "cpu": 0.9, "dns": 0.5})
    mode = AdaptiveMode(cards, rng=random.Random(0), oracle=oracle)

    assert drain(mode) == ["CPU", "DNS", "API"]


def test_adaptive_mode_behavior(cards: list[Flashcard]) -> None:
    """Adaptive mode re-asks a card that was answered incorrectly.

    This is the behaviour that separates adaptive mode from a weighted
    shuffle, so it is asserted directly: the missed card must come round
    again within the same session.
    """
    mode = AdaptiveMode(cards, rng=random.Random(0), oracle=NullOracle())

    first = mode.next_card()
    assert first is not None
    mode.record_result(first, correct=False)

    served_later = drain(mode)

    assert first.front in served_later, "a missed card should be asked again"
    assert len(served_later) == len(cards)  # two unseen cards plus the repeat


def test_adaptive_mode_does_not_repeat_correct_answers(
    cards: list[Flashcard],
) -> None:
    """A card answered correctly is not asked a second time."""
    mode = AdaptiveMode(cards, rng=random.Random(0), oracle=NullOracle())

    first = mode.next_card()
    assert first is not None
    mode.record_result(first, correct=True)

    assert first.front not in drain(mode)


def test_adaptive_mode_terminates_when_always_wrong(cards: list[Flashcard]) -> None:
    """Repeating a card is capped, so a user who never gets it right still finishes.

    Without the cap in ``_requeue`` this loop would never end, which is the
    single most dangerous failure mode in the whole engine.
    """
    mode = AdaptiveMode(cards, rng=random.Random(0), oracle=NullOracle())

    asked = 0
    while True:
        card = mode.next_card()
        if card is None:
            break
        asked += 1
        mode.record_result(card, correct=False)
        assert asked <= len(cards) * (MAX_REPEATS + 1), "quiz failed to terminate"

    assert asked == len(cards) * (MAX_REPEATS + 1)


def test_adaptive_mode_total_is_open_ended(cards: list[Flashcard]) -> None:
    """Adaptive mode reports no fixed total, because repeats can extend it."""
    assert AdaptiveMode(cards).planned_total is None
    assert SequentialMode(cards).planned_total == len(cards)


def test_spaced_mode_orders_by_how_overdue_a_card_is(
    cards: list[Flashcard],
) -> None:
    """The most overdue card is asked first."""
    oracle = FakeOracle(due={"api": -2.0, "cpu": 9.0, "dns": 3.0})
    mode = SpacedRepetitionMode(cards, oracle=oracle)

    assert drain(mode) == ["CPU", "DNS", "API"]


def test_spaced_mode_breaks_ties_on_difficulty(cards: list[Flashcard]) -> None:
    """Equally overdue cards are ordered hardest first."""
    oracle = FakeOracle(
        difficulties={"api": 0.2, "cpu": 0.8, "dns": 0.5},
        due={"api": 1.0, "cpu": 1.0, "dns": 1.0},
    )
    mode = SpacedRepetitionMode(cards, oracle=oracle)

    assert drain(mode) == ["CPU", "DNS", "API"]


def test_spaced_mode_requeues_a_miss_at_the_back(cards: list[Flashcard]) -> None:
    """A missed card returns, but only after everything else."""
    mode = SpacedRepetitionMode(cards, oracle=NullOracle())

    first = mode.next_card()
    assert first is not None
    mode.record_result(first, correct=False)

    assert drain(mode)[-1] == first.front


def test_limit_caps_the_number_of_questions(cards: list[Flashcard]) -> None:
    """--limit stops the quiz early without affecting the deck."""
    mode = SequentialMode(cards, limit=2)

    assert drain(mode) == ["API", "CPU"]
    assert mode.asked == 2


def test_limit_larger_than_deck_is_harmless(cards: list[Flashcard]) -> None:
    """Asking for more questions than there are cards just runs the deck."""
    assert len(drain(SequentialMode(cards, limit=99))) == len(cards)


def test_remaining_counts_down(cards: list[Flashcard]) -> None:
    """``remaining`` reflects both the queue and the limit."""
    mode = SequentialMode(cards, limit=2)

    assert mode.remaining == 2
    mode.next_card()
    assert mode.remaining == 1
    mode.next_card()
    assert mode.remaining == 0


def test_empty_deck_is_rejected() -> None:
    """Starting a quiz with no cards is a programming error, caught early."""
    with pytest.raises(ValueError, match="empty deck"):
        SequentialMode([])


@pytest.mark.parametrize("limit", [0, -1])
def test_non_positive_limit_is_rejected(cards: list[Flashcard], limit: int) -> None:
    """A limit of zero or less is rejected rather than silently ignored."""
    with pytest.raises(ValueError, match="positive whole number"):
        SequentialMode(cards, limit=limit)


def test_null_oracle_is_neutral() -> None:
    """With no history available every card scores the same."""
    oracle = NullOracle()

    assert oracle.difficulty("anything") == 0.5
    assert oracle.due_score("anything") == 1.0


def test_base_mode_ignores_results(cards: list[Flashcard]) -> None:
    """The default strategy does not react to answers at all."""
    mode = SequentialMode(cards)

    mode.record_result(cards[0], correct=False)

    assert drain(mode) == ["API", "CPU", "DNS"]
