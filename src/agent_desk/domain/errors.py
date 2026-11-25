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


@dataclass(frozen=True)
class UnknownProvider:
    """No registered provider has this id. `known_ids` lists the ones that exist."""

    provider_id: str
    known_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProjectNotFound:
    """No provider has a project whose cwd is this path."""

    cwd: Path


type ResumeErrorReason = Literal["session_not_found", "cwd_unknown", "cwd_missing", "cli_not_found"]


@dataclass(frozen=True)
class ResumeError:
    """Why a session cannot be resumed. `detail` is a message for the user."""

    reason: ResumeErrorReason
    detail: str


type TrashErrorReason = Literal["not_found", "session_active", "already_trashed"]


@dataclass(frozen=True)
class TrashError:
    """Why the trash refused an operation; nothing changed on disk. `detail` is for the user."""

    reason: TrashErrorReason
    detail: str
