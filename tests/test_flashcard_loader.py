"""Tests for deck loading and validation (:mod:`data_loader`)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from data_loader import Deck, FlashcardLoadError, load_deck, load_flashcards
from models import Flashcard

DeckWriter = Callable[[Any, str], Path]


def test_load_valid_flashcards_array(array_deck: Path) -> None:
    """A bare JSON array loads into Flashcards in file order."""
    cards = load_flashcards(array_deck)

    assert cards == [
        Flashcard("API", "Application Programming Interface"),
        Flashcard("CPU", "Central Processing Unit"),
    ]


def test_load_valid_flashcards_object_wrapper(object_deck: Path) -> None:
    """The {"cards": [...]} shape loads, and its name is used for the deck."""
    deck = load_deck(object_deck)

    assert isinstance(deck, Deck)
    assert deck.name == "Wrapped Deck"
    assert len(deck) == 2
    assert deck.cards[0].front == "DNS"


def test_deck_name_falls_back_to_file_stem(write_deck: DeckWriter) -> None:
    """A deck with no name is titled after its file."""
    path = write_deck({"cards": [{"front": "a", "back": "b"}]}, "python_basics.json")

    assert load_deck(path).name == "Python Basics"


def test_load_invalid_json(write_deck: DeckWriter) -> None:
    """Malformed JSON raises a friendly error naming the position."""
    path = write_deck('[{"front": "API", "back": }]', "broken.json")

    with pytest.raises(FlashcardLoadError) as excinfo:
        load_flashcards(path)

    message = str(excinfo.value)
    assert "not valid JSON" in message
    assert "line 1" in message
    assert "Traceback" not in message


def test_load_missing_required_field(write_deck: DeckWriter) -> None:
    """A card without a back is rejected and the error names the card."""
    path = write_deck([{"front": "API"}], "no_back.json")

    with pytest.raises(FlashcardLoadError, match="card #1 is missing its back side"):
        load_flashcards(path)


def test_load_missing_front_field(write_deck: DeckWriter) -> None:
    """A card without a front is rejected too, naming its position."""
    path = write_deck(
        [{"front": "ok", "back": "ok"}, {"back": "orphan"}], "no_front.json"
    )

    with pytest.raises(FlashcardLoadError, match="card #2 is missing its front side"):
        load_flashcards(path)


def test_load_missing_file(tmp_path: Path) -> None:
    """A path that does not exist produces a readable message, not a traceback."""
    with pytest.raises(FlashcardLoadError, match="File not found"):
        load_flashcards(tmp_path / "absent.json")


def test_load_directory_instead_of_file(tmp_path: Path) -> None:
    """Pointing at a directory is reported as such."""
    with pytest.raises(FlashcardLoadError, match="found a directory"):
        load_flashcards(tmp_path)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("[]", "contains no cards"),
        ("42", "Deck must be a list of cards"),
        ('"just a string"', "Deck must be a list of cards"),
        ('{"name": "x"}', 'has no "cards" field'),
        ('{"cards": 7}', '"cards" must be a list'),
        ('{"cards": []}', "contains no cards"),
        ('["not an object"]', "card #1 is str"),
        ('[{"front": "a", "back": 5}]', "non-text back side"),
        ('[{"front": "   ", "back": "b"}]', "empty front side"),
        ('[{"front": "a", "back": "\\t "}]', "empty back side"),
    ],
)
def test_rejects_malformed_decks(
    write_deck: DeckWriter, payload: str, expected: str
) -> None:
    """Every structurally invalid deck is rejected with a specific message."""
    path = write_deck(payload, "bad.json")

    with pytest.raises(FlashcardLoadError, match=expected):
        load_flashcards(path)


@pytest.mark.parametrize(
    "payload",
    [
        '[{"Front": "API", "Back": "Application Programming Interface"}]',
        '[{"question": "API", "answer": "Application Programming Interface"}]',
        '[{"term": "API", "definition": "Application Programming Interface"}]',
    ],
)
def test_accepts_alternative_field_names(write_deck: DeckWriter, payload: str) -> None:
    """Capitalised and synonymous field names load the same card."""
    path = write_deck(payload, "aliases.json")

    cards = load_flashcards(path)

    assert cards == [Flashcard("API", "Application Programming Interface")]


def test_values_are_stripped(write_deck: DeckWriter) -> None:
    """Surrounding whitespace is removed from both sides of a card."""
    path = write_deck([{"front": "  API  ", "back": "\tInterface\n"}], "ws.json")

    assert load_flashcards(path) == [Flashcard("API", "Interface")]


def test_duplicate_questions_warn_but_load(write_deck: DeckWriter) -> None:
    """Duplicates are a warning, not an error, and both cards still load."""
    path = write_deck(
        [
            {"front": "API", "back": "one"},
            {"front": "api", "back": "two"},
        ],
        "dupes.json",
    )

    deck = load_deck(path)

    assert len(deck) == 2
    assert len(deck.warnings) == 1
    assert "Duplicate question at card #2" in deck.warnings[0]


def test_valid_deck_has_no_warnings(array_deck: Path) -> None:
    """A clean deck reports nothing to worry about."""
    assert load_deck(array_deck).warnings == ()


def test_shipped_sample_decks_load() -> None:
    """Both decks that ship with the project are valid.

    This guards the repository itself: an edit that breaks data/glossary.json
    should fail the suite rather than only showing up at runtime.
    """
    repo_root = Path(__file__).resolve().parent.parent
    for name, expected_cards in (("glossary.json", 10), ("python_basics.json", 8)):
        deck = load_deck(repo_root / "data" / name)
        assert len(deck) == expected_cards
        assert deck.warnings == ()
