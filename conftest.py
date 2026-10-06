"""Shared pytest fixtures and test doubles.

Living at the project root, this file also puts the root on ``sys.path`` for
pytest, which is what lets the tests import ``models``, ``quiz_engine`` and the
rest the same way :mod:`main` does.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from models import Flashcard


class ScriptedProvider:
    """An :class:`~quiz_engine.AnswerProvider` that replays a fixed script.

    Each call to :meth:`ask` returns the next scripted answer. ``None`` in the
    script means "the user quit"; running off the end of the script also
    returns ``None`` so a test can never hang on an unexpected extra question.
    """

    def __init__(self, answers: Sequence[str | None]) -> None:
        """Create a provider that will return ``answers`` in order."""
        self.answers: list[str | None] = list(answers)
        self.asked: list[Flashcard] = []
        self.totals: list[int | None] = []

    def ask(self, card: Flashcard, number: int, total: int | None) -> str | None:
        """Return the next scripted answer and record what was asked."""
        self.asked.append(card)
        self.totals.append(total)
        if not self.answers:
            return None
        return self.answers.pop(0)


class EchoProvider:
    """A provider that always answers correctly, for termination tests."""

    def ask(self, card: Flashcard, number: int, total: int | None) -> str | None:
        """Return the card's own answer."""
        return card.back


class FakeOracle:
    """A :class:`~quiz_engine.DifficultyOracle` driven by literal values."""

    def __init__(
        self,
        difficulties: dict[str, float] | None = None,
        due: dict[str, float] | None = None,
    ) -> None:
        """Create an oracle returning the given scores, defaulting to neutral."""
        self.difficulties = difficulties or {}
        self.due = due or {}

    def difficulty(self, key: str) -> float:
        """Return the configured difficulty for ``key``, else ``0.5``."""
        return self.difficulties.get(key, 0.5)

    def due_score(self, key: str) -> float:
        """Return the configured urgency for ``key``, else ``1.0``."""
        return self.due.get(key, 1.0)


class FakeClock:
    """A monotonic clock that advances by a fixed step on every read."""

    def __init__(self, step: float = 1.0) -> None:
        """Create a clock advancing ``step`` seconds per call."""
        self.step = step
        self.now = 0.0

    def __call__(self) -> float:
        """Return the current time, then advance it."""
        current = self.now
        self.now += self.step
        return current


@pytest.fixture
def cards() -> list[Flashcard]:
    """Return a small, stable deck used across the engine tests."""
    return [
        Flashcard("API", "Application Programming Interface"),
        Flashcard("CPU", "Central Processing Unit"),
        Flashcard("DNS", "Domain Name System"),
    ]


@pytest.fixture
def write_deck(tmp_path: Path) -> Callable[[Any, str], Path]:
    """Return a helper that writes ``payload`` to a temporary deck file.

    The payload is written verbatim when it is a string, so a test can supply
    deliberately broken JSON, and serialised otherwise.
    """

    def _write(payload: Any, name: str = "deck.json") -> Path:
        """Write ``payload`` to ``name`` under tmp_path and return the path."""
        path = tmp_path / name
        text = payload if isinstance(payload, str) else json.dumps(payload)
        path.write_text(text, encoding="utf-8")
        return path

    return _write


@pytest.fixture
def array_deck(write_deck: Callable[[Any, str], Path]) -> Path:
    """Return a valid deck file in the bare-array format."""
    return write_deck(
        [
            {"front": "API", "back": "Application Programming Interface"},
            {"front": "CPU", "back": "Central Processing Unit"},
        ],
        "array.json",
    )


@pytest.fixture
def object_deck(write_deck: Callable[[Any, str], Path]) -> Path:
    """Return a valid deck file in the ``{"cards": [...]}`` format."""
    return write_deck(
        {
            "name": "Wrapped Deck",
            "cards": [
                {"front": "DNS", "back": "Domain Name System"},
                {"front": "TLS", "back": "Transport Layer Security"},
            ],
        },
        "object.json",
    )


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep tests away from the developer's real config and colour settings.

    Without this, a ``FLASHCARD_*`` variable or a ``.flashcardrc.json`` in the
    working directory would silently change what the configuration tests see.
    """
    for name in list(os_environ_keys()):
        if name.startswith("FLASHCARD_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def os_environ_keys() -> list[str]:
    """Return the current environment variable names.

    Wrapped in a function so the autouse fixture can iterate over a snapshot
    while deleting entries from the live mapping.
    """
    import os

    return list(os.environ)
