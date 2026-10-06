"""End-of-session reporting: the terminal summary and file exports.

Everything here reads from :class:`~models.SessionStats` and returns text. No
function in this module touches the console or decides where a file goes, which
keeps the numbers testable without capturing output and guarantees the exported
figures are the same ones the user saw on screen.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from models import SessionStats
from utils.file_handler import write_text

#: Export formats accepted by :func:`export_session`.
EXPORT_FORMATS: Final[tuple[str, ...]] = ("json", "csv", "md")


@dataclass(frozen=True, slots=True)
class SessionMeta:
    """Context about a finished session, used to label reports.

    Attributes:
        deck_name: Display name of the deck.
        deck_path: Where the deck was loaded from.
        mode_name: The quiz mode that was used.
        aborted: Whether the user stopped before the deck was finished.
    """

    deck_name: str
    deck_path: str
    mode_name: str
    aborted: bool = False


def _format_duration(seconds: float) -> str:
    """Return ``seconds`` as a compact human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(int(round(seconds)), 60)
    return f"{minutes}m {remainder:02d}s"


def _summary_rows(stats: SessionStats, *, timer: bool) -> list[tuple[str, str]]:
    """Return the label/value pairs shown in the summary table."""
    rows: list[tuple[str, str]] = [
        ("Total questions", str(stats.total_questions)),
        ("Correct", str(stats.correct_count)),
        ("Incorrect", str(stats.incorrect_count)),
        ("Accuracy", f"{stats.accuracy:.1f}%"),
        ("Longest streak", str(stats.longest_streak)),
    ]
    if timer and stats.total_questions:
        rows.append(("Time taken", _format_duration(stats.total_seconds)))
        rows.append(("Average per card", _format_duration(stats.average_seconds)))
        fastest = stats.fastest_result
        if fastest is not None:
            rows.append(
                (
                    "Fastest correct",
                    f"{_format_duration(fastest.elapsed_seconds)} "
                    f"({fastest.card.front})",
                )
            )
    return rows


def render_summary(
    stats: SessionStats,
    meta: SessionMeta,
    *,
    timer: bool = True,
    width: int = 56,
) -> str:
    """Return the end-of-session summary as printable text.

    Args:
        stats: The collected session results.
        meta: Context used in the heading.
        timer: Whether to include timing rows.
        width: Width of the divider rules.

    Returns:
        The full summary, newline-separated and without a trailing newline.
    """
    lines: list[str] = ["", "-" * width, "Session summary", "-" * width]
    if stats.total_questions == 0:
        lines.append("No questions were answered.")
        lines.append("-" * width)
        return "\n".join(lines)

    label_width = max(len(label) for label, _ in _summary_rows(stats, timer=timer))
    for label, value in _summary_rows(stats, timer=timer):
        lines.append(f"{label:<{label_width}}  {value}")

    missed = stats.missed_cards
    lines.append("")
    if missed:
        lines.append(f"Review these {len(missed)} card(s):")
        for card in missed:
            lines.append(f"  - {card.front}  ->  {card.back}")
    else:
        lines.append("Nothing missed. Every card answered correctly.")

    if meta.aborted:
        lines.append("")
        lines.append("Session ended early; the deck was not finished.")
    lines.append("-" * width)
    return "\n".join(lines)


def to_json(stats: SessionStats, meta: SessionMeta) -> str:
    """Return the session as a JSON document."""
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "deck": {"name": meta.deck_name, "path": meta.deck_path},
        "mode": meta.mode_name,
        "aborted": meta.aborted,
        "totals": {
            "questions": stats.total_questions,
            "correct": stats.correct_count,
            "incorrect": stats.incorrect_count,
            "accuracy_percent": round(stats.accuracy, 1),
            "longest_streak": stats.longest_streak,
            "seconds": round(stats.total_seconds, 2),
        },
        "answers": [
            {
                "front": result.card.front,
                "expected": result.card.back,
                "given": result.given_answer,
                "correct": result.correct,
                "seconds": round(result.elapsed_seconds, 2),
            }
            for result in stats.results
        ],
        "missed": [card.front for card in stats.missed_cards],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def to_csv(stats: SessionStats, meta: SessionMeta) -> str:
    """Return the per-answer detail as CSV text.

    ``lineterminator`` is set explicitly because :mod:`csv` defaults to
    ``\\r\\n``; combined with a text-mode write that would produce ``\\r\\r\\n``
    on Windows and a blank line between every row.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        ["deck", "mode", "question", "expected", "given", "correct", "seconds"]
    )
    for result in stats.results:
        writer.writerow(
            [
                meta.deck_name,
                meta.mode_name,
                result.card.front,
                result.card.back,
                result.given_answer,
                "yes" if result.correct else "no",
                f"{result.elapsed_seconds:.2f}",
            ]
        )
    return buffer.getvalue()


def to_markdown(stats: SessionStats, meta: SessionMeta) -> str:
    """Return the session as a Markdown report."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Flashcard session - {meta.deck_name}",
        "",
        f"- **Generated:** {stamp}",
        f"- **Deck file:** `{meta.deck_path}`",
        f"- **Mode:** {meta.mode_name}",
        f"- **Questions:** {stats.total_questions}",
        f"- **Accuracy:** {stats.accuracy:.1f}%",
        f"- **Longest streak:** {stats.longest_streak}",
        f"- **Time taken:** {_format_duration(stats.total_seconds)}",
        "",
        "## Answers",
        "",
        "| # | Question | Expected | Your answer | Result |",
        "| - | -------- | -------- | ----------- | ------ |",
    ]
    for position, result in enumerate(stats.results, start=1):
        given = result.given_answer.strip() or "_(skipped)_"
        lines.append(
            f"| {position} | {result.card.front} | {result.card.back} | "
            f"{given} | {'correct' if result.correct else 'incorrect'} |"
        )
    missed = stats.missed_cards
    lines.extend(["", "## To review", ""])
    if missed:
        lines.extend(f"- **{card.front}** - {card.back}" for card in missed)
    else:
        lines.append("Nothing missed.")
    return "\n".join(lines) + "\n"


def render(stats: SessionStats, meta: SessionMeta, export_format: str) -> str:
    """Return the session rendered in ``export_format``.

    Args:
        stats: The session results.
        meta: Session context.
        export_format: One of :data:`EXPORT_FORMATS`.

    Returns:
        The rendered document.

    Raises:
        ValueError: If the format is not supported.
    """
    renderers = {"json": to_json, "csv": to_csv, "md": to_markdown}
    key = export_format.strip().lower()
    if key not in renderers:
        valid = ", ".join(EXPORT_FORMATS)
        raise ValueError(f"Unknown export format {export_format!r}. Choose: {valid}.")
    return renderers[key](stats, meta)


def default_export_path(directory: Path, meta: SessionMeta, export_format: str) -> Path:
    """Return a timestamped file path for an export.

    Args:
        directory: Where exports are written.
        meta: Session context, used in the file name.
        export_format: The file extension to use.

    Returns:
        A path such as ``exports/glossary-20260101-134500.json``.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = "".join(
        char if char.isalnum() else "-" for char in meta.deck_name.lower()
    ).strip("-")
    return directory / f"{slug or 'session'}-{stamp}.{export_format}"


def export_session(
    stats: SessionStats,
    meta: SessionMeta,
    export_format: str,
    destination: Path,
) -> Path:
    """Render the session and write it to ``destination``.

    Args:
        stats: The session results.
        meta: Session context.
        export_format: One of :data:`EXPORT_FORMATS`.
        destination: The file to write. Parent directories are created.

    Returns:
        The path written.

    Raises:
        ValueError: If the format is unsupported.
        utils.file_handler.FileHandlerError: If the file cannot be written.
    """
    return write_text(destination, render(stats, meta, export_format))
