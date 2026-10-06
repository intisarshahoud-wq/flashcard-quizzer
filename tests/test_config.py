"""Tests for configuration resolution and precedence (:mod:`config`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import AppConfig, ConfigError, find_config_file, load_config


def write_config(
    directory: Path, payload: object, name: str = ".flashcardrc.json"
) -> Path:
    """Write ``payload`` as a config file and return its path."""
    path = directory / name
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_are_usable_without_any_configuration() -> None:
    """A user with no config file and no flags still gets a working setup."""
    config = AppConfig()

    assert config.mode == "sequential"
    assert config.deck == Path("data/glossary.json")
    assert config.limit is None
    assert config.color is True
    assert config.log_level == "WARNING"


def test_merge_cli_ignores_unspecified_flags() -> None:
    """argparse leaves unused flags as None, which must not overwrite anything."""
    config = AppConfig(mode="adaptive", limit=5)

    merged = config.merge_cli(mode=None, limit=None, seed=7)

    assert merged.mode == "adaptive"
    assert merged.limit == 5
    assert merged.seed == 7


def test_merge_cli_rejects_unknown_fields() -> None:
    """A typo in a field name is an error, not a silently dropped setting."""
    with pytest.raises(ConfigError, match="Unknown configuration field"):
        AppConfig().merge_cli(moed="adaptive")


def test_config_file_is_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings in .flashcardrc.json replace the defaults."""
    write_config(tmp_path, {"mode": "random", "limit": 4, "color": False})
    monkeypatch.chdir(tmp_path)

    config = load_config()

    assert config.mode == "random"
    assert config.limit == 4
    assert config.color is False


def test_explicit_config_path_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--config reads the named file rather than searching."""
    write_config(tmp_path, {"mode": "random"})
    chosen = write_config(tmp_path, {"mode": "adaptive"}, "other.json")
    monkeypatch.chdir(tmp_path)

    assert load_config(chosen).mode == "adaptive"


def test_missing_explicit_config_is_an_error(tmp_path: Path) -> None:
    """A --config path that does not exist is reported, not ignored."""
    with pytest.raises(ConfigError, match="Config file not found"):
        load_config(tmp_path / "absent.json")


def test_find_config_file_returns_none_when_there_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no config anywhere, the search simply finds nothing."""
    monkeypatch.chdir(tmp_path)

    assert find_config_file() is None


def test_environment_overrides_the_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FLASHCARD_* variables take precedence over the file."""
    write_config(tmp_path, {"mode": "random", "limit": 4})
    monkeypatch.chdir(tmp_path)

    config = load_config(environ={"FLASHCARD_MODE": "adaptive", "FLASHCARD_LIMIT": "9"})

    assert config.mode == "adaptive"
    assert config.limit == 9


def test_unrelated_environment_variables_are_ignored() -> None:
    """The environment is shared, so unknown FLASHCARD_* names are skipped."""
    config = load_config(environ={"FLASHCARD_NOT_A_SETTING": "x", "PATH": "/usr/bin"})

    assert config.mode == "sequential"


@pytest.mark.parametrize("raw", ["true", "yes", "1", "on", "TRUE"])
def test_boolean_settings_accept_common_spellings(raw: str) -> None:
    """Humans write booleans several ways; all the usual ones are accepted."""
    assert load_config(environ={"FLASHCARD_COLOR": raw}).color is True


@pytest.mark.parametrize("raw", ["false", "no", "0", "off"])
def test_boolean_settings_accept_falsey_spellings(raw: str) -> None:
    """The negative spellings are accepted too."""
    assert load_config(environ={"FLASHCARD_COLOR": raw}).color is False


def test_invalid_boolean_is_rejected() -> None:
    """A value that is neither true nor false is an error."""
    with pytest.raises(ConfigError, match="must be true or false"):
        load_config(environ={"FLASHCARD_COLOR": "maybe"})


def test_invalid_integer_is_rejected() -> None:
    """A non-numeric limit names the offending setting."""
    with pytest.raises(ConfigError, match="limit must be a whole number"):
        load_config(environ={"FLASHCARD_LIMIT": "lots"})


def test_blank_integer_means_unset() -> None:
    """An empty value clears the setting instead of failing."""
    assert load_config(environ={"FLASHCARD_LIMIT": ""}).limit is None


def test_invalid_log_level_lists_the_valid_ones() -> None:
    """An unknown log level tells the user what is allowed."""
    with pytest.raises(ConfigError, match="log_level must be one of"):
        load_config(environ={"FLASHCARD_LOG_LEVEL": "CHATTY"})


def test_log_file_can_be_switched_off() -> None:
    """ "none" disables file logging rather than creating a file called none."""
    assert load_config(environ={"FLASHCARD_LOG_FILE": "none"}).log_file is None


def test_paths_are_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A ~ in a path is expanded to the user's home directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    config = load_config(environ={"FLASHCARD_DECK": "~/decks/mine.json"})

    assert "~" not in str(config.deck)


def test_unknown_key_in_config_file_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A misspelled setting in the file is named, with the valid ones listed."""
    write_config(tmp_path, {"moed": "random"})
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigError, match="unknown setting"):
        load_config()


def test_config_file_must_hold_an_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A JSON list is not a settings mapping."""
    write_config(tmp_path, [1, 2, 3])
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigError, match="must contain a JSON object"):
        load_config()


def test_broken_config_file_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid JSON in the config file produces a readable error."""
    write_config(tmp_path, "{not json")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config()


def test_config_file_keys_are_case_insensitive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A capitalised key still maps to the right setting."""
    write_config(tmp_path, {"MODE": "Adaptive"})
    monkeypatch.chdir(tmp_path)

    assert load_config().mode == "adaptive"
