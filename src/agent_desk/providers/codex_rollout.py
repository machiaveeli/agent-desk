"""Reads the parts of a Codex rollout line that agent-desk needs.

Codex has no public format document; every shape here follows the Codex CLI source
(openai/codex), as listed in the Codex fact table of the project planning notes.
"""

from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from agent_desk.domain.models import TranscriptRole
from agent_desk.providers.jsonl import JsonObject, read_json_lines, read_text

SESSION_META_TYPE = "session_meta"
EVENT_MSG_TYPE = "event_msg"
RESPONSE_ITEM_TYPE = "response_item"
# Sessions Codex starts on its own (review, compaction, memory...), not ones the user opened.
NON_ROOT_SOURCE_KEYS = frozenset({"subagent", "internal"})
ROLLOUT_PREFIX = "rollout-"
ROLLOUT_SUFFIX = ".jsonl"
# rollout-<YYYY-MM-DDThh-mm-ss>-<thread id>[_<rollout id>].jsonl
FILE_NAME_TIMESTAMP_LENGTH = 19
REVERTED_ROLLOUT_SEPARATOR = "_"


@dataclass(frozen=True)
class RolloutMeta:
    """What the first `session_meta` line says about a rollout."""

    session_id: str | None
    cwd: Path | None
    is_non_root: bool


def read_payload(line: JsonObject, line_type: str) -> JsonObject | None:
    if line.get("type") != line_type:
        return None
    payload = line.get("payload")
    return payload if isinstance(payload, dict) else None


def read_session_meta(line: JsonObject) -> RolloutMeta | None:
    payload = read_payload(line, SESSION_META_TYPE)
    if payload is None:
        return None
    cwd = read_text(payload.get("cwd"))
    source = payload.get("source")
    is_non_root = isinstance(source, dict) and not NON_ROOT_SOURCE_KEYS.isdisjoint(source)
    return RolloutMeta(read_text(payload.get("id")), Path(cwd) if cwd else None, is_non_root)


def read_rollout_meta(path: Path) -> RolloutMeta | None:
    """The first session_meta of the file. Later ones are copied from a fork's parent."""
    # closing() shuts the file as soon as the meta is found; an open handle blocks moves on
    # Windows.
    with closing(read_json_lines(path)) as lines:
        for line in lines:
            meta = read_session_meta(line) if line is not None else None
            if meta is not None:
                return meta
    return None


def read_message(line: JsonObject) -> tuple[TranscriptRole, str] | None:
    """A message the user typed or the assistant wrote, from its event line.

    Legacy rollouts write `user_message` / `agent_message` events; paginated rollouts write
    `item_completed` events holding a `UserMessage` / `AgentMessage` item.
    """
    payload = read_payload(line, EVENT_MSG_TYPE)
    if payload is None:
        return None
    match payload.get("type"):
        case "user_message":
            return with_role("user", read_text(payload.get("message")))
        case "agent_message":
            return with_role("assistant", read_text(payload.get("message")))
        case "item_completed":
            return read_message_item(payload.get("item"))
    return None


def read_message_item(item: object) -> tuple[TranscriptRole, str] | None:
    if not isinstance(item, dict):
        return None
    match item.get("type"):
        case "UserMessage":
            return with_role("user", join_texts(item.get("content"), "text"))
        case "AgentMessage":
            return with_role("assistant", join_texts(item.get("content"), "Text"))
    return None


def join_texts(content: object, text_type: str) -> str | None:
    if not isinstance(content, list):
        return None
    texts = (
        part.get("text")
        for part in content
        if isinstance(part, dict) and part.get("type") == text_type
    )
    return read_text(" ".join(text for text in texts if isinstance(text, str)))


def with_role(role: TranscriptRole, text: str | None) -> tuple[TranscriptRole, str] | None:
    return (role, text) if text is not None else None


def list_rollout_files(sessions_dir: Path) -> list[Path]:
    """Plain rollouts under sessions/YYYY/MM/DD/. Compressed `.jsonl.zst` ones are skipped:
    reading them needs zstd, which Python 3.12 lacks."""
    pattern = f"*/*/*/{ROLLOUT_PREFIX}*{ROLLOUT_SUFFIX}"
    # glob() on a missing folder yields nothing, so no existence check is needed.
    return sorted(path for path in sessions_dir.glob(pattern) if path.is_file())


def read_file_name_session_id(path: Path) -> str | None:
    core = path.name.removeprefix(ROLLOUT_PREFIX).removesuffix(ROLLOUT_SUFFIX)
    ids = core[FILE_NAME_TIMESTAMP_LENGTH + 1 :]
    return ids.split(REVERTED_ROLLOUT_SEPARATOR)[0] or None


def iter_valid_lines(path: Path) -> Iterator[JsonObject]:
    return (line for line in read_json_lines(path) if line is not None)
