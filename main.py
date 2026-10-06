"""Command-line entry point for the Flashcard Quizzer.

This module owns argument parsing, wiring and exit codes, and nothing else.
Every decision it makes is delegated: configuration to :mod:`config`, loading
to :mod:`data_loader`, card order to :mod:`quiz_engine`, presentation to
:mod:`ui`, and reporting to :mod:`stats_reporter`.

Exit codes:
    ``0``  The run completed, including when the user quit early.
    ``1``  A problem the user can fix: a bad deck, a bad flag, a bad config.
    ``2``  Argparse rejected the command line.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from pathlib import Path
from typing import Final, Sequence

from config import AppConfig, ConfigError, load_config
from data_loader import Deck, FlashcardLoadError, load_deck
from models import SessionStats
from observers import LoggingObserver, ProgressObserver, SessionSubject
from progress_store import ProgressStore
from quiz_engine import DifficultyOracle, NullOracle, QuizModeFactory, QuizSession
from stats_reporter import (
    EXPORT_FORMATS,
    SessionMeta,
    default_export_path,
    export_session,
    render_summary,
)
from ui import Console, ConsoleObserver, ConsolePresenter
from utils.file_handler import FileHandlerError

#: Application version, reported by ``--version``.
VERSION: Final[str] = "1.0.0"

#: Exit code used for every error the user can act on.
EXIT_USER_ERROR: Final[int] = 1


class CliError(Exception):
    """Raised for any condition that should end the run with a clear message."""


def build_parser() -> argparse.ArgumentParser:
    """Return the fully configured argument parser.

    The mode choices and their descriptions are pulled from the factory, so a
    newly registered quiz mode appears in ``--help`` without this function
    being touched.

    Returns:
        The parser.
    """
    modes = QuizModeFactory.describe()
    mode_help = "  ".join(f"{name}: {text}" for name, text in modes.items())
    parser = argparse.ArgumentParser(
        prog="flashcard-quizzer",
        description=(
            "Practise flashcards from a JSON deck in the terminal. "
            "Supports sequential, random, adaptive and spaced-repetition modes."
        ),
        epilog=(
            f"Modes -- {mode_help}\n\n"
            "Examples:\n"
            "  python main.py -f data/glossary.json -m sequential\n"
            "  python main.py -f data/python_basics.json -m adaptive --limit 5\n"
            "  python main.py -f data/glossary.json -m random --seed 42 "
            "--export md\n"
            "  python main.py -f data/glossary.json --stats\n"
            "  python main.py -f data/glossary.json --validate\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument(
        "-f",
        "--file",
        dest="deck",
        type=Path,
        help="Path to the JSON deck to quiz on.",
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=QuizModeFactory.available(),
        help="How the next card is chosen.",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        metavar="N",
        help="Stop after N questions instead of running the whole deck.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Seed the shuffle so a run can be reproduced exactly.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show your saved progress for this deck and exit.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Check the deck file and exit without starting a quiz.",
    )
    parser.add_argument(
        "--list-modes",
        action="store_true",
        help="List the available quiz modes and exit.",
    )
    parser.add_argument(
        "--export",
        choices=EXPORT_FORMATS,
        dest="export_format",
        help="Write a session report in this format when the quiz ends.",
    )
    parser.add_argument(
        "--export-path",
        type=Path,
        help="Exact file to export to, instead of a timestamped default.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Config file to read instead of searching for .flashcardrc.json.",
    )
    parser.add_argument(
        "--no-color",
        dest="color",
        action="store_false",
        default=None,
        help="Disable coloured output.",
    )
    parser.add_argument(
        "--no-timer",
        dest="timer",
        action="store_false",
        default=None,
        help="Do not time answers or report timing statistics.",
    )
    parser.add_argument(
        "--hide-answers",
        dest="show_answer",
        action="store_false",
        default=None,
        help="Do not reveal the expected answer after a wrong response.",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Do not read or write the saved progress file.",
    )
    parser.add_argument(
        "--progress-file",
        type=Path,
        help="Where cross-session progress is stored.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Verbosity of the log.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Write the log to this file instead of standard error.",
    )
    return parser


def configure_logging(level: str, log_file: Path | None) -> None:
    """Configure the root logger for this run.

    Args:
        level: A level name such as ``"INFO"``.
        log_file: Destination file, or ``None`` to log to standard error.

    Raises:
        CliError: If the log file cannot be opened.
    """
    handler: logging.Handler
    if log_file is None:
        handler = logging.StreamHandler(sys.stderr)
    else:
        try:
            log_file.expanduser().parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(log_file.expanduser(), encoding="utf-8")
        except OSError as exc:
            raise CliError(f"Could not open log file {log_file}: {exc}") from exc
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.WARNING))


def resolve_config(args: argparse.Namespace) -> AppConfig:
    """Return the configuration for this run, with CLI flags applied last.

    Args:
        args: The parsed command line.

    Returns:
        The resolved configuration.

    Raises:
        CliError: If any configuration source is invalid.
    """
    try:
        base = load_config(args.config)
        return base.merge_cli(
            deck=args.deck,
            mode=args.mode,
            limit=args.limit,
            seed=args.seed,
            color=args.color,
            timer=args.timer,
            show_answer=args.show_answer,
            log_level=args.log_level,
            log_file=args.log_file,
            progress_file=args.progress_file,
        )
    except ConfigError as exc:
        raise CliError(str(exc)) from exc


def load_requested_deck(config: AppConfig) -> Deck:
    """Load the deck named by ``config``.

    Args:
        config: The resolved configuration.

    Returns:
        The loaded deck.

    Raises:
        CliError: If the deck cannot be loaded, carrying the loader's own
            user-facing message.
    """
    try:
        return load_deck(config.deck)
    except FlashcardLoadError as exc:
        raise CliError(str(exc)) from exc


def show_modes(console: Console) -> int:
    """Print the available quiz modes and return the exit code."""
    console.write("Available quiz modes:", "bold")
    for name, description in QuizModeFactory.describe().items():
        console.write(f"  {name:<10} {description}")
    return 0


def show_validation(console: Console, deck: Deck) -> int:
    """Print the result of validating ``deck`` and return the exit code."""
    console.write(f"{deck.source} is a valid deck.", "green", "bold")
    console.write(f"  Name:  {deck.name}")
    console.write(f"  Cards: {len(deck)}")
    for warning in deck.warnings:
        console.write(f"  Warning: {warning}", "yellow")
    return 0


def show_stats(console: Console, deck: Deck, store: ProgressStore) -> int:
    """Print the saved progress for ``deck`` and return the exit code."""
    console.write(f"Saved progress for {deck.name}", "bold", "cyan")
    console.write(f"Progress file: {store.path}", "dim")
    if store.load_warning:
        console.write(store.load_warning, "yellow")
    console.rule()

    tracked = [(card, store.records.get(card.key)) for card in deck.cards]
    answered = [(card, record) for card, record in tracked if record and record.seen]
    if not answered:
        console.write("No cards from this deck have been answered yet.")
        return 0

    width = min(44, max(len(card.front) for card, _ in answered))
    console.write(f"{'Card':<{width}}  {'Seen':>4}  {'Right':>5}  {'Accuracy':>8}")
    for card, record in answered:
        assert record is not None  # narrowed by the filter above
        front = card.front
        if len(front) > width:
            front = front[: width - 1] + "…"
        console.write(
            f"{front:<{width}}  {record.seen:>4}  {record.correct:>5}  "
            f"{record.accuracy * 100:>7.1f}%"
        )
    console.rule()
    summary = store.summary()
    console.write(
        f"Lifetime: {summary['answers_recorded']} answers across "
        f"{summary['cards_tracked']} cards, "
        f"{summary['lifetime_accuracy']}% correct."
    )
    return 0


def _export_if_requested(
    console: Console,
    config: AppConfig,
    args: argparse.Namespace,
    stats: SessionStats,
    meta: SessionMeta,
) -> None:
    """Write a session export when ``--export`` was given.

    A failed export is reported as a warning rather than raised: the quiz has
    already happened, and the summary on screen is the primary result.
    """
    if not args.export_format or stats.total_questions == 0:
        return
    destination = args.export_path or default_export_path(
        config.export_dir, meta, args.export_format
    )
    try:
        written = export_session(stats, meta, args.export_format, destination)
    except (FileHandlerError, ValueError) as exc:
        console.write(f"Could not write the export: {exc}", "yellow")
        return
    console.write(f"Session exported to {written}", "dim")


def run_quiz(
    console: Console,
    config: AppConfig,
    args: argparse.Namespace,
    deck: Deck,
    store: ProgressStore | None,
) -> int:
    """Run one full quiz session and return the process exit code.

    Args:
        console: The output console.
        config: The resolved configuration.
        args: The parsed command line, used for export options.
        deck: The deck to quiz on.
        store: Progress store, or ``None`` when tracking is disabled.

    Returns:
        ``0``; a completed or abandoned quiz is not an error.

    Raises:
        CliError: If the mode or limit is rejected by the engine.
    """
    oracle: DifficultyOracle = store if store is not None else NullOracle()
    rng = random.Random(config.seed)
    try:
        mode = QuizModeFactory.create(
            config.mode, deck.cards, rng=rng, oracle=oracle, limit=config.limit
        )
    except ValueError as exc:
        raise CliError(str(exc)) from exc

    subject = SessionSubject()
    subject.attach(ConsoleObserver(console, show_answer=config.show_answer))
    subject.attach(LoggingObserver())
    progress_observer = ProgressObserver(store) if store is not None else None
    if progress_observer is not None:
        subject.attach(progress_observer)

    for warning in deck.warnings:
        console.write(f"Warning: {warning}", "yellow")
    if store is not None and store.load_warning:
        console.write(store.load_warning, "yellow")

    session = QuizSession(
        mode,
        ConsolePresenter(console),
        deck_name=deck.name,
        subject=subject,
        timer=config.timer,
    )
    stats = session.run()

    meta = SessionMeta(
        deck_name=deck.name,
        deck_path=str(deck.source),
        mode_name=mode.name,
        aborted=session.aborted,
    )
    console.write(render_summary(stats, meta, timer=config.timer))
    if progress_observer is not None and progress_observer.save_error:
        console.write(
            f"Progress was not saved: {progress_observer.save_error}", "yellow"
        )
    _export_if_requested(console, config, args, stats, meta)
    return 0


def run(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv``, run the requested action and return an exit code.

    Args:
        argv: Command-line arguments, defaulting to :data:`sys.argv`.

    Returns:
        The process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console(color=args.color is not False)

    try:
        if args.list_modes:
            return show_modes(console)

        config = resolve_config(args)
        configure_logging(config.log_level, config.log_file)
        console = Console(color=config.color)

        deck = load_requested_deck(config)
        store = None if args.no_progress else ProgressStore.load(config.progress_file)

        if args.validate:
            return show_validation(console, deck)
        if args.stats:
            if store is None:
                raise CliError("--stats cannot be combined with --no-progress.")
            return show_stats(console, deck, store)
        return run_quiz(console, config, args, deck, store)
    except CliError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USER_ERROR
    except KeyboardInterrupt:
        console.write()
        console.write("Interrupted. Goodbye.", "dim")
        return 0


def main() -> None:
    """Console entry point: run the application and exit with its code."""
    sys.exit(run())


if __name__ == "__main__":
    main()
