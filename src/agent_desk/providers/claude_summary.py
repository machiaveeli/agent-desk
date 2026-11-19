"""Builds a SessionSummary from a Claude Code transcript in a single streaming pass."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_desk.domain.models import Session, SessionSummary
from agent_desk.domain.text import truncate
from agent_desk.providers.jsonl import JsonObject, parse_timestamp, read_json_lines, read_text

FIRST_PROMPT_MAX_LENGTH = 120
SIBLING_TITLE_FILE_NAME = "custom-title.json"
# Claude Code records local slash commands (/clear, /rename...) and their output as user
# lines wrapped in these tags. They are not something the user asked the AI.
LOCAL_COMMAND_TAGS = (
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-stdout>",
    "<local-command-caveat>",
)


@dataclass
class TranscriptFacts:
    """What one pass over the lines collects. Mutable on purpose: it fills up while streaming."""

    cwd: Path | None = None
    custom_title: str | None = None
    ai_title: str | None = None
    first_prompt: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    invalid_line_count: int = 0

    def add_line(self, line: JsonObject | None) -> None:
        if line is None:
            self.invalid_line_count += 1
            return
        self.add_timestamp(parse_timestamp(line.get("timestamp")))
        if self.cwd is None:
            self.cwd = read_cwd(line)
        match line.get("type"):
            case "custom-title":
                self.custom_title = read_text(line.get("customTitle")) or self.custom_title
            case "ai-title":
                self.ai_title = read_text(line.get("aiTitle")) or self.ai_title
            case "user" if self.first_prompt is None:
                self.first_prompt = read_prompt(line)

    def add_timestamp(self, moment: datetime | None) -> None:
        if moment is None:
            return
        if self.started_at is None or moment < self.started_at:
            self.started_at = moment
        if self.ended_at is None or moment > self.ended_at:
            self.ended_at = moment


def summarize_session(path: Path, provider_id: str) -> SessionSummary:
    facts = TranscriptFacts()
    for line in read_json_lines(path):
        facts.add_line(line)
    sibling_dir = path.parent / path.stem
    session = Session(
        provider_id=provider_id,
        session_id=path.stem,
        path=path,
        sibling_dir=sibling_dir if sibling_dir.is_dir() else None,
        cwd=facts.cwd,
    )
    return SessionSummary(
        session=session,
        title=choose_title(facts, session),
        started_at=facts.started_at,
        ended_at=facts.ended_at,
        first_prompt=facts.first_prompt,
        size_bytes=measure_size(session),
        invalid_line_count=facts.invalid_line_count,
    )


def choose_title(facts: TranscriptFacts, session: Session) -> str:
    return (
        facts.custom_title
        or read_sibling_title(session.sibling_dir)
        or facts.ai_title
        or facts.first_prompt
        or session.session_id
    )


def read_sibling_title(sibling_dir: Path | None) -> str | None:
    if sibling_dir is None:
        return None
    try:
        content = json.loads((sibling_dir / SIBLING_TITLE_FILE_NAME).read_bytes())
    except (OSError, ValueError):
        return None
    return read_text(content.get("customTitle")) if isinstance(content, dict) else None


def read_cwd(line: JsonObject) -> Path | None:
    cwd = line.get("cwd")
    return Path(cwd) if isinstance(cwd, str) and cwd else None


def read_prompt(line: JsonObject) -> str | None:
    """The text of a user line, or None when it is not a prompt the user typed."""
    if line.get("isMeta") is True:
        return None
    message = line.get("message")
    text = extract_text(message.get("content")) if isinstance(message, dict) else None
    if text is None or text.lstrip().startswith(LOCAL_COMMAND_TAGS):
        return None
    return truncate(" ".join(text.split()), FIRST_PROMPT_MAX_LENGTH) or None


def extract_text(content: object) -> str | None:
    """Content is a string or a list of blocks. A list with no text block (only tool results,
    images...) gives an empty string, which the caller treats as no prompt."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    texts = (read_block_text(block) for block in content)
    return " ".join(text for text in texts if text is not None)


def read_block_text(block: object) -> str | None:
    """The text of a `{"type": "text", "text": ...}` block; None for any other block."""
    if not isinstance(block, dict) or block.get("type") != "text":
        return None
    text = block.get("text")
    return text if isinstance(text, str) else None


def measure_size(session: Session) -> int:
    total = session.path.stat().st_size
    if session.sibling_dir is not None:
        total += sum(
            path.stat().st_size for path in session.sibling_dir.rglob("*") if path.is_file()
        )
    return total
