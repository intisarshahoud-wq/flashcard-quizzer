"""Loading and validation of flashcard decks from JSON files.

Two on-disk shapes are supported, because both appear in the sample data:

* **Array format** -- a bare list of card objects::

      [{"front": "API", "back": "Application Programming Interface"}]

* **Object format** -- a wrapper with an optional deck name::

      {"name": "Python Basics", "cards": [{"front": "...", "back": "..."}]}

Every failure raises :class:`FlashcardLoadError` with a message written for a
user rather than a developer, so the CLI can print it and exit without ever
showing a traceback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from models import Flashcard
from utils.file_handler import FileHandlerError, read_json

#: Keys accepted for the question side of a card, lower-cased.
FRONT_KEYS: Final[tuple[str, ...]] = ("front", "question", "term")

#: Keys accepted for the answer side of a card, lower-cased.
BACK_KEYS: Final[tuple[str, ...]] = ("back", "answer", "definition")

#: Keys that may carry the deck name in object format.
NAME_KEYS: Final[tuple[str, ...]] = ("name", "title", "deck")


class FlashcardLoadError(Exception):
    """Raised when a deck file cannot be turned into usable flashcards."""


@dataclass(frozen=True, slots=True)
class Deck:
    """A named collection of flashcards loaded from one file.

    Attributes:
        name: Display name, defaulting to the file stem.
        cards: The validated cards, in file order.
        source: The file the deck was read from.
        warnings: Non-fatal observations, such as duplicate questions.
    """

    name: str
    cards: tuple[Flashcard, ...]
    source: Path
    warnings: tuple[str, ...] = field(default=())

    def __len__(self) -> int:
        """Return the number of cards in the deck."""
        return len(self.cards)


def _ordinal(index: int) -> str:
    """Return a human-friendly position label for card ``index`` (0-based)."""
    return f"card #{index + 1}"


def _lookup(raw: dict[str, Any], candidates: tuple[str, ...]) -> tuple[str, Any] | None:
    """Return the first ``(key, value)`` in ``raw`` matching ``candidates``.

    The comparison ignores case and surrounding whitespace so that a deck
    written with ``"Front"`` or ``"BACK"`` still loads.

    Args:
        raw: The card object straight from JSON.
        candidates: Accepted key spellings, lower-cased.

    Returns:
        The matching key and its value, or ``None`` if no key matched.
    """
    normalized = {str(key).strip().lower(): key for key in raw}
    for candidate in candidates:
        if candidate in normalized:
            original = normalized[candidate]
            return original, raw[original]
    return None


def _require_text(
    raw: dict[str, Any], candidates: tuple[str, ...], index: int, side: str
) -> str:
    """Return the validated text for one side of a card.

    Args:
        raw: The card object.
        candidates: Accepted key spellings for this side.
        index: The card's 0-based position, used in error messages.
        side: Either ``"front"`` or ``"back"``, used in error messages.

    Returns:
        The stripped text value.

    Raises:
        FlashcardLoadError: If the key is absent, is not a string, or is blank.
    """
    found = _lookup(raw, candidates)
    if found is None:
        expected = " or ".join(f'"{name}"' for name in candidates)
        raise FlashcardLoadError(
            f"{_ordinal(index)} is missing its {side} side "
            f"(expected a {expected} field)."
        )
    key, value = found
    if not isinstance(value, str):
        raise FlashcardLoadError(
            f'{_ordinal(index)} has a non-text {side} side: "{key}" is '
            f"{type(value).__name__}, expected text."
        )
    text = value.strip()
    if not text:
        raise FlashcardLoadError(
            f'{_ordinal(index)} has an empty {side} side ("{key}").'
        )
    return text


def _extract_card_list(payload: Any) -> list[Any]:
    """Return the raw card list from either supported top-level shape.

    Args:
        payload: The decoded JSON value.

    Returns:
        The list of raw card entries.

    Raises:
        FlashcardLoadError: If the payload is neither a list nor an object with
            a ``cards`` list.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        found = _lookup(payload, ("cards",))
        if found is None:
            raise FlashcardLoadError(
                'Deck object has no "cards" field. Use either a list of cards '
                'or {"cards": [...]}.'
            )
        _, value = found
        if not isinstance(value, list):
            raise FlashcardLoadError(
                f'"cards" must be a list of card objects, '
                f"got {type(value).__name__}."
            )
        return value
    raise FlashcardLoadError(
        f'Deck must be a list of cards or an object with a "cards" list, '
        f"got {type(payload).__name__}."
    )


def _extract_deck_name(payload: Any, source: Path) -> str:
    """Return the deck's display name, falling back to the file stem."""
    if isinstance(payload, dict):
        found = _lookup(payload, NAME_KEYS)
        if found is not None:
            _, value = found
            if isinstance(value, str) and value.strip():
                return value.strip()
    return source.stem.replace("_", " ").replace("-", " ").title()


def _build_card(raw: Any, index: int) -> Flashcard:
    """Validate one raw entry and return it as a :class:`Flashcard`.

    Args:
        raw: One entry from the card list.
        index: Its 0-based position, used in error messages.

    Returns:
        The validated card.

    Raises:
        FlashcardLoadError: If the entry is not an object or either side fails
            validation.
    """
    if not isinstance(raw, dict):
        raise FlashcardLoadError(
            f"{_ordinal(index)} is {type(raw).__name__}, expected an object "
            'like {"front": "...", "back": "..."}.'
        )
    front = _require_text(raw, FRONT_KEYS, index, "front")
    back = _require_text(raw, BACK_KEYS, index, "back")
    return Flashcard(front=front, back=back)


def _collect_warnings(cards: list[Flashcard]) -> list[str]:
    """Return non-fatal notes about ``cards``.

    A duplicate question is legal JSON and the quiz still runs, so it is
    reported rather than raised. It is worth surfacing because the adaptive
    mode keys its history on the question text and would merge the two.
    """
    warnings: list[str] = []
    seen: dict[str, int] = {}
    for position, card in enumerate(cards, start=1):
        if card.key in seen:
            warnings.append(
                f'Duplicate question at card #{position}: "{card.front}" '
                f"also appears at card #{seen[card.key]}."
            )
        else:
            seen[card.key] = position
    return warnings


def load_deck(path: str | Path) -> Deck:
    """Load, validate and return the deck stored at ``path``.

    Args:
        path: Path to a JSON deck in either supported format.

    Returns:
        The loaded :class:`Deck`.

    Raises:
        FlashcardLoadError: If the file is missing, unreadable, not valid JSON,
            not a recognised deck shape, empty, or contains an invalid card.
            The message is safe to print directly to the user.
    """
    try:
        payload = read_json(path)
    except FileHandlerError as exc:
        raise FlashcardLoadError(str(exc)) from exc

    source = Path(path).expanduser().resolve()
    raw_cards = _extract_card_list(payload)
    if not raw_cards:
        raise FlashcardLoadError(f"{source.name} contains no cards.")

    cards = [_build_card(raw, index) for index, raw in enumerate(raw_cards)]
    return Deck(
        name=_extract_deck_name(payload, source),
        cards=tuple(cards),
        source=source,
        warnings=tuple(_collect_warnings(cards)),
    )


def load_flashcards(path: str | Path) -> list[Flashcard]:
    """Return just the cards from the deck at ``path``.

    A thin convenience wrapper over :func:`load_deck` for callers and tests
    that do not care about the deck name or warnings.

    Args:
        path: Path to a JSON deck file.

    Returns:
        The validated cards in file order.

    Raises:
        FlashcardLoadError: Propagated from :func:`load_deck`.
    """
    return list(load_deck(path).cards)
