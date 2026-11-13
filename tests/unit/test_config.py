from dataclasses import replace
from pathlib import Path

import pytest

from agent_desk.config import Config, default_config_path, load_config
from agent_desk.domain.errors import ConfigError


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


@pytest.fixture
def custom_root(tmp_path: Path) -> Path:
    return tmp_path / "custom-root"


def make_default_config(home: Path) -> Config:
    return Config(
        claude_root=home / ".claude",
        codex_root=home / ".codex",
        trash_retention_days=30,
        codex_active_threshold_minutes=10,
    )


def test_missing_file_returns_defaults(config_path: Path, home: Path) -> None:
    result = load_config(config_path, env={}, home=home)

    assert result == make_default_config(home)


@pytest.mark.parametrize(
    ("toml_text", "changes"),
    [
        ("[trash]\nretention_days = 7\n", {"trash_retention_days": 7}),
        ("[trash]\nretention_days = 0\n", {"trash_retention_days": 0}),
        (
            "[providers.codex]\nactive_threshold_minutes = 3\n",
            {"codex_active_threshold_minutes": 3},
        ),
    ],
    ids=["retention", "retention-zero", "codex-threshold"],
)
def test_file_overrides_only_the_fields_it_sets(
    config_path: Path, home: Path, toml_text: str, changes: dict[str, int]
) -> None:
    config_path.write_text(toml_text, encoding="utf-8")

    result = load_config(config_path, env={}, home=home)

    assert result == replace(make_default_config(home), **changes)


@pytest.mark.parametrize(
    ("table", "field"),
    [("providers.claude-code", "claude_root"), ("providers.codex", "codex_root")],
)
def test_file_overrides_provider_root(
    config_path: Path, home: Path, custom_root: Path, table: str, field: str
) -> None:
    config_path.write_text(f"[{table}]\nroot = '{custom_root}'\n", encoding="utf-8")

    result = load_config(config_path, env={}, home=home)

    assert getattr(result, field) == custom_root


@pytest.mark.parametrize(
    ("toml_root", "expected_parts"),
    [("~", ()), ("~/custom", ("custom",))],
    ids=["home-itself", "inside-home"],
)
def test_tilde_in_root_expands_to_injected_home(
    config_path: Path, home: Path, toml_root: str, expected_parts: tuple[str, ...]
) -> None:
    config_path.write_text(f"[providers.codex]\nroot = '{toml_root}'\n", encoding="utf-8")

    result = load_config(config_path, env={}, home=home)

    assert isinstance(result, Config)
    assert result.codex_root == home.joinpath(*expected_parts)


@pytest.mark.parametrize(
    ("env_var", "field"),
    [("CLAUDE_CONFIG_DIR", "claude_root"), ("CODEX_HOME", "codex_root")],
)
def test_env_var_overrides_default_root(
    config_path: Path, home: Path, custom_root: Path, env_var: str, field: str
) -> None:
    result = load_config(config_path, env={env_var: str(custom_root)}, home=home)

    assert getattr(result, field) == custom_root


def test_empty_env_var_is_ignored(config_path: Path, home: Path) -> None:
    result = load_config(config_path, env={"CODEX_HOME": ""}, home=home)

    assert result == make_default_config(home)


def test_file_wins_over_env_var(
    config_path: Path, home: Path, custom_root: Path, tmp_path: Path
) -> None:
    config_path.write_text(f"[providers.codex]\nroot = '{custom_root}'\n", encoding="utf-8")
    env_root = tmp_path / "from-env"

    result = load_config(config_path, env={"CODEX_HOME": str(env_root)}, home=home)

    assert isinstance(result, Config)
    assert result.codex_root == custom_root


@pytest.mark.parametrize(
    ("toml_text", "field", "reason"),
    [
        ("[trash\n", None, "invalid_toml"),
        ("trash = 5\n", "trash", "wrong_type"),
        ("[trash]\nretention_days = -1\n", "trash.retention_days", "out_of_range"),
        ("[trash]\nretention_days = '30'\n", "trash.retention_days", "wrong_type"),
        ("[trash]\nretention_days = true\n", "trash.retention_days", "wrong_type"),
        (
            "[providers.codex]\nactive_threshold_minutes = 0\n",
            "providers.codex.active_threshold_minutes",
            "out_of_range",
        ),
        ("[providers.codex]\nroot = 5\n", "providers.codex.root", "wrong_type"),
        ("[providers.codex]\nroot = 'relative/dir'\n", "providers.codex.root", "not_absolute"),
        ("trahs = 1\n", "trahs", "unknown_key"),
        ("[providers.gemini]\nroot = '~'\n", "providers.gemini", "unknown_key"),
        ("[trash]\nretention = 1\n", "trash.retention", "unknown_key"),
    ],
    ids=[
        "invalid-toml",
        "table-not-a-table",
        "negative-retention",
        "retention-as-string",
        "retention-as-bool",
        "zero-threshold",
        "root-not-a-string",
        "relative-root",
        "unknown-top-level-key",
        "unknown-provider",
        "unknown-key-in-table",
    ],
)
def test_invalid_value_returns_config_error(
    config_path: Path, home: Path, toml_text: str, field: str | None, reason: str
) -> None:
    config_path.write_text(toml_text, encoding="utf-8")

    result = load_config(config_path, env={}, home=home)

    assert isinstance(result, ConfigError)
    assert (result.field, result.reason) == (field, reason)


def test_unreadable_file_returns_config_error(config_path: Path, home: Path) -> None:
    config_path.mkdir()

    result = load_config(config_path, env={}, home=home)

    assert isinstance(result, ConfigError)
    assert (result.field, result.reason) == (None, "unreadable")


def test_default_config_path_is_inside_app_config_dir() -> None:
    path = default_config_path()

    assert (path.parent.name, path.name) == ("agent-desk", "config.toml")
