"""Application configuration, resolved from defaults, a file and the environment.

Precedence, lowest to highest:

1. The defaults baked into :class:`AppConfig`.
2. A JSON config file (``--config PATH``, else ``.flashcardrc.json`` in the
   current directory, else the same name in the user's home directory).
3. ``FLASHCARD_*`` environment variables.
4. Command-line flags, applied by :mod:`main` via :meth:`AppConfig.merge_cli`.

Keeping the precedence rules in one place means the CLI never has to reason
about where a value came from; it only overrides what the user actually typed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from utils.file_handler import FileHandlerError, read_json

#: Config file names searched when ``--config`` is not given.
CONFIG_FILENAME: Final[str] = ".flashcardrc.json"

#: Prefix for environment variable overrides, e.g. ``FLASHCARD_MODE``.
ENV_PREFIX: Final[str] = "FLASHCARD_"

#: Valid values for ``log_level``.
LOG_LEVELS: Final[tuple[str, ...]] = (
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
)


class ConfigError(Exception):
    """Raised when configuration values are present but unusable."""


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Resolved settings for one run of the application.

    Attributes:
        deck: Path to the deck file to quiz on.
        mode: Name of the quiz mode to use.
        limit: Maximum questions to ask, or ``None`` for the whole deck.
        seed: Seed for the random number generator, or ``None`` for entropy.
        color: Whether coloured output is permitted at all.
        show_answer: Whether to reveal the answer after a wrong response.
        timer: Whether to time each question and report timing stats.
        log_level: Logging threshold name.
        log_file: Destination for the log file, or ``None`` to disable it.
        progress_file: Where cross-session progress is stored.
        export_dir: Default directory for exported session reports.
    """

    deck: Path = Path("data/glossary.json")
    mode: str = "sequential"
    limit: int | None = None
    seed: int | None = None
    color: bool = True
    show_answer: bool = True
    timer: bool = True
    log_level: str = "WARNING"
    log_file: Path | None = None
    progress_file: Path = Path(".flashcard_progress.json")
    export_dir: Path = Path("exports")

    def merge_cli(self, **overrides: Any) -> AppConfig:
        """Return a copy with every non-``None`` override applied.

        ``argparse`` leaves unspecified flags as ``None``, so this lets the CLI
        hand over its whole namespace without deciding which values the user
        actually typed.

        Args:
            **overrides: Field names mapped to values, where ``None`` means
                "not specified".

        Returns:
            A new :class:`AppConfig`.

        Raises:
            ConfigError: If an unknown field name is supplied.
        """
        known = {field.name for field in self.__dataclass_fields__.values()}
        applied: dict[str, Any] = {}
        for key, value in overrides.items():
            if key not in known:
                raise ConfigError(f"Unknown configuration field: {key}")
            if value is not None:
                applied[key] = value
        return replace(self, **applied)


def _as_bool(value: Any, field_name: str) -> bool:
    """Return ``value`` interpreted as a boolean.

    Args:
        value: A bool, or a string such as ``"true"``/``"0"``/``"yes"``.
        field_name: Used in the error message.

    Returns:
        The boolean value.

    Raises:
        ConfigError: If the value is not recognisable as a boolean.
    """
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{field_name} must be true or false, got {value!r}.")


def _as_optional_int(value: Any, field_name: str) -> int | None:
    """Return ``value`` as an ``int``, or ``None`` for an empty value."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"{field_name} must be a whole number, got {value!r}."
        ) from exc


def _as_optional_path(value: Any) -> Path | None:
    """Return ``value`` as a :class:`~pathlib.Path`, or ``None`` if empty."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "off"}:
        return None
    return Path(text).expanduser()


def _coerce(field_name: str, value: Any) -> Any:
    """Return ``value`` converted to the type :class:`AppConfig` expects.

    Args:
        field_name: The config field being set.
        value: The raw value from a file or environment variable.

    Returns:
        The converted value.

    Raises:
        ConfigError: If the field is unknown or the value cannot be converted.
    """
    if field_name in {"deck", "progress_file", "export_dir"}:
        path = _as_optional_path(value)
        if path is None:
            raise ConfigError(f"{field_name} must be a path.")
        return path
    if field_name == "log_file":
        return _as_optional_path(value)
    if field_name in {"limit", "seed"}:
        return _as_optional_int(value, field_name)
    if field_name in {"color", "show_answer", "timer"}:
        return _as_bool(value, field_name)
    if field_name == "mode":
        return str(value).strip().lower()
    if field_name == "log_level":
        level = str(value).strip().upper()
        if level not in LOG_LEVELS:
            raise ConfigError(
                f"log_level must be one of {', '.join(LOG_LEVELS)}, got {value!r}."
            )
        return level
    raise ConfigError(f"Unknown configuration field: {field_name}")


def _known_fields() -> set[str]:
    """Return the set of configurable field names."""
    return set(AppConfig.__dataclass_fields__)


def find_config_file(explicit: str | Path | None = None) -> Path | None:
    """Return the config file to use, or ``None`` if there is none.

    Args:
        explicit: A path given on the command line. It must exist.

    Returns:
        The path to an existing config file, or ``None``.

    Raises:
        ConfigError: If ``explicit`` was given but does not exist.
    """
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigError(f"Config file not found: {path}")
        return path
    for candidate in (Path.cwd() / CONFIG_FILENAME, Path.home() / CONFIG_FILENAME):
        if candidate.is_file():
            return candidate
    return None


def _from_file(path: Path) -> dict[str, Any]:
    """Return the settings held in the JSON config file at ``path``.

    Unknown keys are rejected rather than ignored, because a silently dropped
    setting is far harder to diagnose than a named error.

    Args:
        path: An existing JSON config file.

    Returns:
        Coerced settings ready to apply to :class:`AppConfig`.

    Raises:
        ConfigError: If the file is unreadable, is not a JSON object, or holds
            an unknown key or an uncoercible value.
    """
    try:
        payload = read_json(path)
    except FileHandlerError as exc:
        raise ConfigError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"{path.name} must contain a JSON object of settings.")

    known = _known_fields()
    settings: dict[str, Any] = {}
    for raw_key, raw_value in payload.items():
        key = str(raw_key).strip().lower()
        if key not in known:
            raise ConfigError(
                f"{path.name}: unknown setting {raw_key!r}. "
                f"Valid settings: {', '.join(sorted(known))}."
            )
        settings[key] = _coerce(key, raw_value)
    return settings


def _from_env(environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Return settings read from ``FLASHCARD_*`` environment variables.

    Args:
        environ: Environment mapping to read. Defaults to :data:`os.environ`.

    Returns:
        Coerced settings. Variables that do not name a known field are ignored,
        since the environment is shared with unrelated software.

    Raises:
        ConfigError: If a recognised variable holds an uncoercible value.
    """
    source = os.environ if environ is None else environ
    known = _known_fields()
    settings: dict[str, Any] = {}
    for name, value in source.items():
        if not name.startswith(ENV_PREFIX):
            continue
        key = name[len(ENV_PREFIX) :].lower()
        if key not in known:
            continue
        settings[key] = _coerce(key, value)
    return settings


def load_config(
    explicit_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> AppConfig:
    """Return the configuration before command-line flags are applied.

    Args:
        explicit_path: Value of ``--config``, if given.
        environ: Environment mapping, injectable for tests.

    Returns:
        An :class:`AppConfig` combining defaults, the config file and the
        environment.

    Raises:
        ConfigError: If any source holds invalid settings.
    """
    settings: dict[str, Any] = {}
    config_file = find_config_file(explicit_path)
    if config_file is not None:
        settings.update(_from_file(config_file))
    settings.update(_from_env(environ))
    return AppConfig().merge_cli(**settings)
