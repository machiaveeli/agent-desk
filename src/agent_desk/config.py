import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import platformdirs

from agent_desk.domain.errors import ConfigError

APP_NAME = "agent-desk"
CONFIG_FILE_NAME = "config.toml"

CLAUDE_PROVIDER_ID = "claude-code"
CLAUDE_DEFAULT_DIR_NAME = ".claude"
CLAUDE_ROOT_ENV_VAR = "CLAUDE_CONFIG_DIR"

CODEX_PROVIDER_ID = "codex"
CODEX_DEFAULT_DIR_NAME = ".codex"
CODEX_ROOT_ENV_VAR = "CODEX_HOME"

DEFAULT_TRASH_RETENTION_DAYS = 30
MIN_TRASH_RETENTION_DAYS = 0
DEFAULT_CODEX_ACTIVE_THRESHOLD_MINUTES = 10
MIN_CODEX_ACTIVE_THRESHOLD_MINUTES = 1

type Table = Mapping[str, object]

ROOT_TABLE = ""
# Every table the config file may contain, mapped to the keys allowed inside it.
ALLOWED_KEYS: dict[str, frozenset[str]] = {
    ROOT_TABLE: frozenset({"providers", "trash"}),
    "providers": frozenset({CLAUDE_PROVIDER_ID, CODEX_PROVIDER_ID}),
    f"providers.{CLAUDE_PROVIDER_ID}": frozenset({"root"}),
    f"providers.{CODEX_PROVIDER_ID}": frozenset({"root", "active_threshold_minutes"}),
    "trash": frozenset({"retention_days"}),
}


@dataclass(frozen=True)
class Config:
    claude_root: Path
    codex_root: Path
    trash_retention_days: int
    codex_active_threshold_minutes: int


def default_config_path() -> Path:
    return platformdirs.user_config_path(APP_NAME, appauthor=False) / CONFIG_FILE_NAME


def load_config(path: Path, env: Mapping[str, str], home: Path) -> Config | ConfigError:
    """Load the config file; a missing file means all defaults. Precedence: file > env > default."""
    raw = read_toml(path)
    if isinstance(raw, ConfigError):
        return raw
    key_error = find_unknown_key(raw, ROOT_TABLE)
    if key_error is not None:
        return key_error
    return build_config(raw, env, home)


def read_toml(path: Path) -> Table | ConfigError:
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except FileNotFoundError:
        return {}
    except OSError as error:
        return ConfigError(None, "unreadable", f"cannot read {path}: {error.strerror}")
    except tomllib.TOMLDecodeError as error:
        return ConfigError(None, "invalid_toml", f"{path}: {error}")


def find_unknown_key(table: Table, table_name: str) -> ConfigError | None:
    """Reject typos and misplaced values early, so a wrong key is never silently ignored."""
    for key, value in table.items():
        field = join_field(table_name, key)
        if key not in ALLOWED_KEYS[table_name]:
            return ConfigError(field, "unknown_key", f"'{field}' is not a known setting")
        if field not in ALLOWED_KEYS:
            continue
        if not isinstance(value, dict):
            return ConfigError(field, "wrong_type", f"'{field}' must be a table")
        nested_error = find_unknown_key(value, field)
        if nested_error is not None:
            return nested_error
    return None


def build_config(raw: Table, env: Mapping[str, str], home: Path) -> Config | ConfigError:
    claude = get_table(raw, f"providers.{CLAUDE_PROVIDER_ID}")
    codex = get_table(raw, f"providers.{CODEX_PROVIDER_ID}")
    trash = get_table(raw, "trash")

    claude_root = read_root(
        claude,
        CLAUDE_PROVIDER_ID,
        env.get(CLAUDE_ROOT_ENV_VAR),
        home / CLAUDE_DEFAULT_DIR_NAME,
        home,
    )
    if isinstance(claude_root, ConfigError):
        return claude_root
    codex_root = read_root(
        codex, CODEX_PROVIDER_ID, env.get(CODEX_ROOT_ENV_VAR), home / CODEX_DEFAULT_DIR_NAME, home
    )
    if isinstance(codex_root, ConfigError):
        return codex_root
    retention_days = read_int(
        trash, "trash", "retention_days", DEFAULT_TRASH_RETENTION_DAYS, MIN_TRASH_RETENTION_DAYS
    )
    if isinstance(retention_days, ConfigError):
        return retention_days
    threshold_minutes = read_int(
        codex,
        f"providers.{CODEX_PROVIDER_ID}",
        "active_threshold_minutes",
        DEFAULT_CODEX_ACTIVE_THRESHOLD_MINUTES,
        MIN_CODEX_ACTIVE_THRESHOLD_MINUTES,
    )
    if isinstance(threshold_minutes, ConfigError):
        return threshold_minutes
    return Config(claude_root, codex_root, retention_days, threshold_minutes)


def get_table(raw: Table, dotted_name: str) -> Table:
    table: object = raw
    for key in dotted_name.split("."):
        if not isinstance(table, dict):
            return {}
        table = table.get(key, {})
    return table if isinstance(table, dict) else {}


def read_root(
    table: Table, provider_id: str, env_value: str | None, default_root: Path, home: Path
) -> Path | ConfigError:
    field = f"providers.{provider_id}.root"
    value = table.get("root")
    if value is None:
        return Path(env_value) if env_value else default_root
    if not isinstance(value, str):
        return ConfigError(field, "wrong_type", f"'{field}' must be a path string")
    root = expand_home(Path(value), home)
    if not root.is_absolute():
        return ConfigError(
            field, "not_absolute", f"'{field}' must be an absolute path or start with ~"
        )
    return root


def read_int(
    table: Table, table_name: str, key: str, default: int, minimum: int
) -> int | ConfigError:
    field = join_field(table_name, key)
    value = table.get(key, default)
    # bool is a subclass of int in Python, so `true` would otherwise pass as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        return ConfigError(field, "wrong_type", f"'{field}' must be a whole number")
    if value < minimum:
        return ConfigError(field, "out_of_range", f"'{field}' must be at least {minimum}")
    return value


def expand_home(path: Path, home: Path) -> Path:
    # Not Path.expanduser(): that reads the real home, and tests must inject theirs.
    if not path.parts or path.parts[0] != "~":
        return path
    return home.joinpath(*path.parts[1:])


def join_field(table_name: str, key: str) -> str:
    return f"{table_name}.{key}" if table_name else key
