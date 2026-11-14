from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type ConfigErrorReason = Literal[
    "unreadable", "invalid_toml", "unknown_key", "wrong_type", "out_of_range", "not_absolute"
]


@dataclass(frozen=True)
class ConfigError:
    """A config file problem, returned instead of raised. `field` is None for whole-file errors."""

    field: str | None
    reason: ConfigErrorReason
    detail: str


@dataclass(frozen=True)
class ProviderNotFound:
    """The provider's root folder does not exist: the CLI is not installed or never ran."""

    provider_id: str
    root: Path
