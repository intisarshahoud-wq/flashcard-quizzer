"""Tests for the core data structures and the grading rule (:mod:`models`)."""

from __future__ import annotations

import pytest

from models import CardResult, Flashcard, SessionStats, normalize_answer


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Secure   Shell ", "secure shell"),
        ("SECURE SHELL", "secure shell"),
        ("secure\tshell", "secure shell"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_answer(raw: str, expected: str) -> None:
    """Case, padding and runs of whitespace are all levelled out."""
    assert normalize_answer(raw) == expected


def test_normalize_answer_unifies_unicode_forms() -> None:
    """Visually identical strings in different Unicode forms compare equal."""
    precomposed = "café"
    decomposed = "café"

    assert precomposed != decomposed
    assert normalize_answer(precomposed) == normalize_answer(decomposed)


@pytest.mark.parametrize(
    "answer",
    ["Secure Shell", "secure shell", "  SECURE   shell  "],
)
def test_matches_is_forgiving_about_formatting(answer: str) -> None:
    """A right answer is accepted regardless of case or spacing."""
    assert Flashcard("SSH", "Secure Shell").matches(answer) is True


@pytest.mark.parametrize("answer", ["", "   ", "wrong", "Secure"])
def test_matches_rejects_wrong_answers(answer: str) -> None:
    """Blank and incorrect answers are both rejected."""
    assert Flashcard("SSH", "Secure Shell").matches(answer) is False


def test_matches_accepts_any_pipe_separated_alternative() -> None:
    """A card may list several acceptable answers separated by a pipe."""
    card = Flashcard("Which keyword defines a function?", "def|def keyword")

    assert card.matches("def") is True
    assert card.matches("DEF KEYWORD") is True
    assert card.matches("function") is False


def test_matches_ignores_empty_alternatives() -> None:
    """A stray pipe does not make the blank answer correct."""
    assert Flashcard("x", "yes|").matches("") is False


def test_key_is_normalized_front_text() -> None:
    """Two cards whose questions differ only in formatting share a key."""
    assert Flashcard("  API ", "x").key == Flashcard("api", "y").key == "api"


def test_flashcard_is_immutable() -> None:
    """Cards are frozen, so no layer can edit the deck it was handed."""
    card = Flashcard("API", "Interface")

    with pytest.raises(AttributeError):
        card.front = "changed"  # type: ignore[misc]


def build_stats(outcomes: list[bool], seconds: float = 1.0) -> SessionStats:
    """Return stats populated from ``outcomes``, one card per entry."""
    stats = SessionStats()
    for index, correct in enumerate(outcomes):
        card = Flashcard(f"q{index}", f"a{index}")
        stats.record(
            CardResult(
                card=card,
                given_answer=f"a{index}" if correct else "wrong",
                correct=correct,
                elapsed_seconds=seconds,
            )
        )
    return stats


def test_empty_session_reports_zeroes_rather_than_raising() -> None:
    """Quitting before answering anything is normal, not an error."""
    stats = SessionStats()

    assert stats.total_questions == 0
    assert stats.accuracy == 0.0
    assert stats.average_seconds == 0.0
    assert stats.missed_cards == []
    assert stats.longest_streak == 0
    assert stats.fastest_result is None


def test_counts_and_accuracy() -> None:
    """Correct, incorrect and accuracy agree with each other."""
    stats = build_stats([True, False, True, True])

    assert stats.total_questions == 4
    assert stats.correct_count == 3
    assert stats.incorrect_count == 1
    assert stats.accuracy == pytest.approx(75.0)


def test_accuracy_of_an_all_wrong_session_is_zero() -> None:
    """Getting everything wrong scores 0%, not a division error."""
    assert build_stats([False, False]).accuracy == 0.0


def test_longest_streak_spans_the_best_run() -> None:
    """The streak is the longest run of correct answers, not the last one."""
    assert build_stats([True, True, True, False, True]).longest_streak == 3


def test_missed_cards_are_unique_and_in_first_miss_order() -> None:
    """A card missed twice appears once, where it was first missed."""
    stats = SessionStats()
    first = Flashcard("A", "1")
    second = Flashcard("B", "2")
    for card in (first, second, first):
        stats.record(CardResult(card=card, given_answer="x", correct=False))

    assert [card.front for card in stats.missed_cards] == ["A", "B"]


def test_a_card_missed_then_answered_still_counts_as_missed() -> None:
    """Getting a repeat right does not erase the earlier miss from the review list.

    Adaptive mode re-asks missed cards, so without this the review list would
    quietly empty itself exactly when the user needed it most.
    """
    stats = SessionStats()
    card = Flashcard("A", "1")
    stats.record(CardResult(card=card, given_answer="x", correct=False))
    stats.record(CardResult(card=card, given_answer="1", correct=True))

    assert [missed.front for missed in stats.missed_cards] == ["A"]


def test_timing_aggregates() -> None:
    """Total and average seconds follow from the recorded results."""
    stats = build_stats([True, True], seconds=3.0)

    assert stats.total_seconds == pytest.approx(6.0)
    assert stats.average_seconds == pytest.approx(3.0)


def test_fastest_result_ignores_incorrect_answers() -> None:
    """A quick wrong answer is not the fastest correct one."""
    stats = SessionStats()
    stats.record(
        CardResult(
            Flashcard("A", "1"), given_answer="x", correct=False, elapsed_seconds=0.1
        )
    )
    stats.record(
        CardResult(
            Flashcard("B", "2"), given_answer="2", correct=True, elapsed_seconds=4.0
        )
    )

    fastest = stats.fastest_result
    assert fastest is not None
    assert fastest.card.front == "B"
