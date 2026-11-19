"""Builds a SessionSummary from a Codex rollout in a single streaming pass."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_desk.domain.models import Session, SessionSummary
from agent_desk.domain.text import truncate
from agent_desk.providers.codex_rollout import (
    RolloutMeta,
    read_file_name_session_id,
    read_message,
    read_session_meta,
)
from agent_desk.providers.jsonl import JsonObject, parse_timestamp, read_json_lines, read_text

FIRST_PROMPT_MAX_LENGTH = 120
SESSION_INDEX_FILE_NAME = "session_index.jsonl"


@dataclass
class RolloutFacts:
    """What one pass over the lines collects. Mutable on purpose: it fills up while streaming."""

    meta: RolloutMeta | None = None
    first_prompt: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    invalid_line_count: int = 0

    def add_line(self, line: JsonObject | None) -> None:
        if line is None:
            self.invalid_line_count += 1
            return
        self.add_timestamp(parse_timestamp(line.get("timestamp")))
        if self.meta is None:
            self.meta = read_session_meta(line)
        if self.first_prompt is None:
            self.first_prompt = read_first_prompt(line)

    def add_timestamp(self, moment: datetime | None) -> None:
        if moment is None:
            return
        if self.started_at is None or moment < self.started_at:
            self.started_at = moment
        if self.ended_at is None or moment > self.ended_at:
            self.ended_at = moment


def summarize_rollout(path: Path, provider_id: str, thread_names: dict[str, str]) -> SessionSummary:
    facts = RolloutFacts()
    for line in read_json_lines(path):
        facts.add_line(line)
    session = Session(
        provider_id=provider_id,
        session_id=choose_session_id(facts.meta, path),
        path=path,
        sibling_dir=None,
        cwd=facts.meta.cwd if facts.meta is not None else None,
    )
    return SessionSummary(
        session=session,
        title=thread_names.get(session.session_id) or facts.first_prompt or session.session_id,
        started_at=facts.started_at,
        ended_at=facts.ended_at,
        first_prompt=facts.first_prompt,
        size_bytes=path.stat().st_size,
        invalid_line_count=facts.invalid_line_count,
    )


def choose_session_id(meta: RolloutMeta | None, path: Path) -> str:
    meta_id = meta.session_id if meta is not None else None
    return meta_id or read_file_name_session_id(path) or path.stem


def read_first_prompt(line: JsonObject) -> str | None:
    message = read_message(line)
    if message is None or message[0] != "user":
        return None
    return truncate(" ".join(message[1].split()), FIRST_PROMPT_MAX_LENGTH)


def read_thread_names(root: Path) -> dict[str, str]:
    """Session names from `session_index.jsonl`. Entries are only appended, so the last one
    for an id wins. A missing or unreadable index means no names."""
    names: dict[str, str] = {}
    try:
        for line in read_json_lines(root / SESSION_INDEX_FILE_NAME):
            session_id = read_text(line.get("id")) if line is not None else None
            name = read_text(line.get("thread_name")) if line is not None else None
            if session_id is not None and name is not None:
                names[session_id] = name
    except OSError:
        return {}
    return names
