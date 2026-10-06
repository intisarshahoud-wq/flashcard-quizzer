"""Cross-session progress tracking that powers the adaptive and review modes.

The store keeps one record per card, keyed on the normalized question text
rather than a list index, so a record survives reordering or extending a deck.
Records carry both plain counters (used by adaptive mode) and SM-2 style
scheduling fields (used by spaced-repetition mode).

A corrupt or unreadable progress file is never fatal: the application starts
from an empty history and says so. Losing practice statistics is an
inconvenience, but refusing to run a quiz over it would be worse.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

from models import Flashcard
from utils.file_handler import FileHandlerError, read_json, write_json

#: Schema version written into the file so a future format change can migrate.
SCHEMA_VERSION: Final[int] = 1

#: Starting ease factor for a newly seen card, following SM-2 convention.
DEFAULT_EASE: Final[float] = 2.5

#: Ease never drops below this, or a hard card would be asked forever.
MIN_EASE: Final[float] = 1.3


def _today() -> date:
    """Return today's date in UTC.

    UTC is used rather than local time so that a review interval does not jump
    forward or backward when the user travels or the clock changes.
    """
    return datetime.now(timezone.utc).date()


@dataclass
class CardProgress:
    """The accumulated history for a single card.

    Attributes:
        front: The question text, stored for readable reports.
        seen: How many times the card has been asked.
        correct: How many times it was answered correctly.
        incorrect: How many times it was answered incorrectly.
        streak: Current run of consecutive correct answers.
        last_correct: Outcome of the most recent answer, or ``None`` if unseen.
        last_seen: ISO date of the most recent answer.
        ease: SM-2 ease factor.
        interval_days: Days until the card is next due.
        due: ISO date on which the card becomes due.
    """

    front: str = ""
    seen: int = 0
    correct: int = 0
    incorrect: int = 0
    streak: int = 0
    last_correct: bool | None = None
    last_seen: str | None = None
    ease: float = DEFAULT_EASE
    interval_days: int = 0
    due: str | None = None

    @property
    def accuracy(self) -> float:
        """Return the historical accuracy as a fraction in 0.0-1.0."""
        if self.seen == 0:
            return 0.0
        return self.correct / self.seen

    @property
    def difficulty(self) -> float:
        """Return a 0.0-1.0 difficulty score, higher meaning "ask me sooner".

        The score uses Laplace smoothing so that a card missed once out of one
        attempt does not outrank a card missed nine times out of ten, and an
        unseen card lands mid-scale instead of looking either mastered or
        hopeless. The most recent answer is weighted on top, because a card
        just missed is the one the user most needs to see again.
        """
        smoothed = (self.incorrect + 1.0) / (self.seen + 2.0)
        if self.last_correct is False:
            smoothed = smoothed * 0.6 + 0.4
        elif self.last_correct is True:
            smoothed *= 0.8
        return min(1.0, max(0.0, smoothed))

    def days_overdue(self, today: date | None = None) -> int:
        """Return how many days past due this card is.

        Args:
            today: The reference date, injectable for tests.

        Returns:
            A positive number of days overdue, ``0`` if due today, or a
            negative number if it is not yet due. An unseen card counts as one
            day overdue so that new material is scheduled ahead of cards the
            user has already mastered.
        """
        reference = today or _today()
        if self.due is None:
            return 1
        try:
            due_date = date.fromisoformat(self.due)
        except ValueError:
            return 1
        return (reference - due_date).days

    def register(self, correct: bool, today: date | None = None) -> None:
        """Update this record with the outcome of one answer.

        Args:
            correct: Whether the answer was right.
            today: The reference date, injectable for tests.
        """
        reference = today or _today()
        self.seen += 1
        self.last_correct = correct
        self.last_seen = reference.isoformat()
        if correct:
            self.correct += 1
            self.streak += 1
            self.ease = min(3.0, self.ease + 0.1)
            if self.interval_days <= 0:
                self.interval_days = 1
            elif self.interval_days == 1:
                self.interval_days = 3
            else:
                self.interval_days = max(1, round(self.interval_days * self.ease))
        else:
            self.incorrect += 1
            self.streak = 0
            self.ease = max(MIN_EASE, self.ease - 0.2)
            self.interval_days = 0
        self.due = (reference + timedelta(days=self.interval_days)).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of this record."""
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> CardProgress:
        """Return a record built from ``raw``, ignoring anything unusable.

        The file may have been hand-edited or written by an older version, so
        every field is validated individually and bad values fall back to the
        default rather than aborting the load.

        Args:
            raw: A mapping read from the progress file.

        Returns:
            A :class:`CardProgress` instance.
        """
        record = cls()
        if not isinstance(raw, dict):
            return record
        for name, current in record.to_dict().items():
            if name not in raw:
                continue
            value = raw[name]
            if current is None or isinstance(current, (str, bool)):
                if value is None or isinstance(value, (str, bool)):
                    setattr(record, name, value)
            elif isinstance(current, int) and isinstance(value, int):
                setattr(record, name, max(0, value))
            elif isinstance(current, float) and isinstance(value, (int, float)):
                setattr(record, name, float(value))
        return record


@dataclass
class ProgressStore:
    """Reads, updates and writes the per-card history file.

    Attributes:
        path: The JSON file backing the store.
        records: Card key mapped to its history.
        load_warning: A message describing why an existing file was ignored.
    """

    path: Path
    records: dict[str, CardProgress] = field(default_factory=dict)
    load_warning: str | None = None

    @classmethod
    def load(cls, path: str | Path) -> ProgressStore:
        """Return a store loaded from ``path``, or an empty one.

        Args:
            path: The progress file. It need not exist.

        Returns:
            A populated store, or an empty store whose ``load_warning``
            explains why the file on disk was not usable.
        """
        destination = Path(path).expanduser()
        store = cls(path=destination)
        if not destination.exists():
            return store
        try:
            payload = read_json(destination)
        except FileHandlerError as exc:
            store.load_warning = f"Ignoring unreadable progress file: {exc}"
            return store
        if not isinstance(payload, dict):
            store.load_warning = (
                f"Ignoring progress file {destination.name}: expected a JSON object."
            )
            return store
        raw_cards = payload.get("cards")
        if not isinstance(raw_cards, dict):
            store.load_warning = (
                f'Ignoring progress file {destination.name}: no "cards" object.'
            )
            return store
        store.records = {
            str(key): CardProgress.from_dict(value) for key, value in raw_cards.items()
        }
        return store

    def save(self) -> Path:
        """Write the store to disk and return the path written.

        Raises:
            FileHandlerError: If the file cannot be written.
        """
        payload = {
            "version": SCHEMA_VERSION,
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cards": {key: record.to_dict() for key, record in self.records.items()},
        }
        return write_json(self.path, payload)

    def record_for(self, card: Flashcard) -> CardProgress:
        """Return the stored record for ``card``, creating it if absent."""
        record = self.records.get(card.key)
        if record is None:
            record = CardProgress(front=card.front)
            self.records[card.key] = record
        elif not record.front:
            record.front = card.front
        return record

    def register(
        self, card: Flashcard, correct: bool, today: date | None = None
    ) -> CardProgress:
        """Record one answer for ``card`` and return the updated record.

        Args:
            card: The card that was asked.
            correct: Whether the answer was right.
            today: Reference date, injectable for tests.

        Returns:
            The updated record.
        """
        record = self.record_for(card)
        record.register(correct, today=today)
        return record

    def difficulty(self, key: str) -> float:
        """Return the stored difficulty for ``key``.

        Args:
            key: A card key, as produced by :attr:`models.Flashcard.key`.

        Returns:
            The difficulty in 0.0-1.0. An unknown key returns ``0.5``, which
            places new cards between known-easy and known-hard ones.
        """
        record = self.records.get(key)
        return 0.5 if record is None else record.difficulty

    def due_score(self, key: str, today: date | None = None) -> float:
        """Return how urgently ``key`` should be reviewed.

        Args:
            key: A card key.
            today: Reference date, injectable for tests.

        Returns:
            Days overdue as a float; larger means more urgent. An unknown card
            scores ``1.0``, treating new material as mildly overdue.
        """
        record = self.records.get(key)
        if record is None:
            return 1.0
        return float(record.days_overdue(today))

    def summary(self) -> dict[str, float | int]:
        """Return aggregate counters across every stored card."""
        total_seen = sum(record.seen for record in self.records.values())
        total_correct = sum(record.correct for record in self.records.values())
        accuracy = (total_correct / total_seen * 100.0) if total_seen else 0.0
        return {
            "cards_tracked": len(self.records),
            "answers_recorded": total_seen,
            "lifetime_accuracy": round(accuracy, 1),
        }
