"""Tests for cross-session progress tracking (:mod:`progress_store`)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from models import Flashcard
from progress_store import DEFAULT_EASE, MIN_EASE, CardProgress, ProgressStore

TODAY = date(2026, 1, 15)


@pytest.fixture
def card() -> Flashcard:
    """Return a card used across these tests."""
    return Flashcard("API", "Application Programming Interface")


def test_new_store_is_empty(tmp_path: Path) -> None:
    """A store for a file that does not exist starts clean and silent."""
    store = ProgressStore.load(tmp_path / "absent.json")

    assert store.records == {}
    assert store.load_warning is None


def test_register_counts_answers(tmp_path: Path, card: Flashcard) -> None:
    """Right and wrong answers are counted separately."""
    store = ProgressStore.load(tmp_path / "p.json")

    store.register(card, correct=True, today=TODAY)
    store.register(card, correct=False, today=TODAY)
    record = store.register(card, correct=True, today=TODAY)

    assert record.seen == 3
    assert record.correct == 2
    assert record.incorrect == 1
    assert record.accuracy == pytest.approx(2 / 3)


def test_streak_resets_on_a_miss(tmp_path: Path, card: Flashcard) -> None:
    """A wrong answer clears the run of correct ones."""
    store = ProgressStore.load(tmp_path / "p.json")

    store.register(card, correct=True, today=TODAY)
    store.register(card, correct=True, today=TODAY)
    assert store.record_for(card).streak == 2

    store.register(card, correct=False, today=TODAY)
    assert store.record_for(card).streak == 0


def test_save_and_reload(tmp_path: Path, card: Flashcard) -> None:
    """History survives a round trip through the file."""
    path = tmp_path / "p.json"
    store = ProgressStore.load(path)
    store.register(card, correct=False, today=TODAY)
    store.save()

    reloaded = ProgressStore.load(path)

    assert reloaded.records["api"].incorrect == 1
    assert reloaded.records["api"].front == "API"


def test_saved_file_carries_a_schema_version(tmp_path: Path, card: Flashcard) -> None:
    """The file records its version so a later format change can migrate it."""
    path = tmp_path / "p.json"
    store = ProgressStore.load(path)
    store.register(card, correct=True, today=TODAY)
    store.save()

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["version"] == 1
    assert "updated" in payload
    assert "api" in payload["cards"]


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("{not json", "unreadable progress file"),
        ("[1, 2, 3]", "expected a JSON object"),
        ('{"version": 1}', 'no "cards" object'),
    ],
)
def test_a_damaged_file_is_ignored_with_a_warning(
    tmp_path: Path, content: str, expected: str
) -> None:
    """A corrupt history must not stop the user from practising.

    The quiz is the point; the statistics are a convenience, so the store
    degrades to empty and explains itself rather than raising.
    """
    path = tmp_path / "p.json"
    path.write_text(content, encoding="utf-8")

    store = ProgressStore.load(path)

    assert store.records == {}
    assert store.load_warning is not None
    assert expected in store.load_warning


def test_garbage_fields_fall_back_to_defaults(tmp_path: Path) -> None:
    """A hand-edited record with wrong types loads with sane values."""
    path = tmp_path / "p.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "cards": {
                    "api": {"seen": "lots", "correct": -4, "ease": "fast"},
                    "cpu": "not even an object",
                },
            }
        ),
        encoding="utf-8",
    )

    store = ProgressStore.load(path)

    assert store.records["api"].seen == 0
    assert store.records["api"].correct == 0
    assert store.records["api"].ease == DEFAULT_EASE
    assert store.records["cpu"].seen == 0


def test_difficulty_rises_after_a_miss(tmp_path: Path, card: Flashcard) -> None:
    """A card just missed outranks one just answered correctly."""
    store = ProgressStore.load(tmp_path / "p.json")
    easy = Flashcard("CPU", "Central Processing Unit")

    store.register(card, correct=False, today=TODAY)
    store.register(easy, correct=True, today=TODAY)

    assert store.difficulty("api") > store.difficulty("cpu")


def test_difficulty_of_an_unknown_card_is_neutral(tmp_path: Path) -> None:
    """A card never seen sits between known-easy and known-hard."""
    store = ProgressStore.load(tmp_path / "p.json")

    assert store.difficulty("never-seen") == 0.5


def test_difficulty_stays_within_bounds(tmp_path: Path, card: Flashcard) -> None:
    """The score is a probability-like value, so it never leaves 0.0-1.0."""
    store = ProgressStore.load(tmp_path / "p.json")
    for _ in range(20):
        store.register(card, correct=False, today=TODAY)

    assert 0.0 <= store.difficulty("api") <= 1.0


def test_a_correct_answer_schedules_the_card_further_out(
    tmp_path: Path, card: Flashcard
) -> None:
    """Each success pushes the next review further into the future."""
    store = ProgressStore.load(tmp_path / "p.json")

    first = store.register(card, correct=True, today=TODAY)
    assert first.interval_days == 1

    second = store.register(card, correct=True, today=TODAY)
    assert second.interval_days == 3

    third = store.register(card, correct=True, today=TODAY)
    assert third.interval_days > 3


def test_a_miss_makes_the_card_due_immediately(tmp_path: Path, card: Flashcard) -> None:
    """Getting a card wrong brings it straight back into the review pool."""
    store = ProgressStore.load(tmp_path / "p.json")
    store.register(card, correct=True, today=TODAY)

    record = store.register(card, correct=False, today=TODAY)

    assert record.interval_days == 0
    assert record.due == TODAY.isoformat()


def test_ease_never_falls_below_the_floor(tmp_path: Path, card: Flashcard) -> None:
    """Ease is clamped so a hard card is not scheduled every few minutes."""
    store = ProgressStore.load(tmp_path / "p.json")
    for _ in range(20):
        store.register(card, correct=False, today=TODAY)

    assert store.record_for(card).ease == pytest.approx(MIN_EASE)


def test_due_score_grows_with_how_overdue_a_card_is(
    tmp_path: Path, card: Flashcard
) -> None:
    """A card reviewed long ago scores higher than one reviewed today."""
    store = ProgressStore.load(tmp_path / "p.json")
    store.register(card, correct=True, today=TODAY - timedelta(days=30))

    assert store.due_score("api", today=TODAY) > 0


def test_due_score_of_an_unknown_card(tmp_path: Path) -> None:
    """New material counts as mildly overdue so it gets scheduled."""
    assert ProgressStore.load(tmp_path / "p.json").due_score("new") == 1.0


def test_days_overdue_handles_a_corrupt_date() -> None:
    """A nonsense due date is treated as due rather than crashing the sort."""
    record = CardProgress(due="not-a-date")

    assert record.days_overdue(TODAY) == 1


def test_days_overdue_is_negative_before_the_due_date() -> None:
    """A card scheduled for the future is not yet overdue."""
    record = CardProgress(due=(TODAY + timedelta(days=5)).isoformat())

    assert record.days_overdue(TODAY) == -5


def test_record_for_backfills_a_missing_question(
    tmp_path: Path, card: Flashcard
) -> None:
    """A record saved without its question text picks it up on next use."""
    store = ProgressStore.load(tmp_path / "p.json")
    store.records["api"] = CardProgress()

    assert store.record_for(card).front == "API"


def test_summary_aggregates_every_card(tmp_path: Path, card: Flashcard) -> None:
    """The lifetime summary counts across all tracked cards."""
    store = ProgressStore.load(tmp_path / "p.json")
    other = Flashcard("CPU", "Central Processing Unit")
    store.register(card, correct=True, today=TODAY)
    store.register(card, correct=False, today=TODAY)
    store.register(other, correct=True, today=TODAY)

    summary = store.summary()

    assert summary["cards_tracked"] == 2
    assert summary["answers_recorded"] == 3
    assert summary["lifetime_accuracy"] == pytest.approx(66.7)


def test_summary_of_an_empty_store(tmp_path: Path) -> None:
    """An untouched store reports zeroes rather than dividing by zero."""
    summary = ProgressStore.load(tmp_path / "p.json").summary()

    assert summary == {
        "cards_tracked": 0,
        "answers_recorded": 0,
        "lifetime_accuracy": 0.0,
    }


def test_accuracy_of_an_unseen_record() -> None:
    """A record with no answers reports 0% rather than raising."""
    assert CardProgress().accuracy == 0.0
