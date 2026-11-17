"""Reads a Claude Code transcript as condensed entries, one line at a time."""

from collections.abc import Iterator
from pathlib import Path

from agent_desk.domain.models import TranscriptEntry, TranscriptRole
from agent_desk.providers.claude_summary import (
    LOCAL_COMMAND_TAGS,
    read_block_text,
    read_text,
    truncate,
)
from agent_desk.providers.jsonl import JsonObject, read_json_lines

TOOL_SUMMARY_MAX_LENGTH = 80
# Lines Claude Code adds on the user's behalf: injected context (isMeta) and the summary
# written when a long conversation is compacted.
INJECTED_LINE_FLAGS = ("isMeta", "isCompactSummary")


def read_transcript_entries(path: Path) -> Iterator[TranscriptEntry]:
    """User and assistant text plus one line per tool call. Thinking and tool results are
    left out: they are long and the call line already says what was done."""
    for line in read_json_lines(path):
        if line is not None:
            yield from read_line_entries(line)


def read_line_entries(line: JsonObject) -> Iterator[TranscriptEntry]:
    role: TranscriptRole
    match line.get("type"):
        case "user":
            role = "user"
        case "assistant":
            role = "assistant"
        case _:
            return
    if any(line.get(flag) is True for flag in INJECTED_LINE_FLAGS):
        return
    message = line.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return
    for block in content:
        entry = read_block_entry(role, block)
        if entry is not None:
            yield entry


def read_block_entry(role: TranscriptRole, block: object) -> TranscriptEntry | None:
    text = read_block_text(block)
    if text is not None:
        return read_text_entry(role, text)
    if isinstance(block, dict) and block.get("type") == "tool_use":
        return read_tool_call(block)
    return None


def read_text_entry(role: TranscriptRole, text: str) -> TranscriptEntry | None:
    text = text.strip()
    # Local slash commands (/clear...) and their output are recorded as user lines.
    if not text or (role == "user" and text.startswith(LOCAL_COMMAND_TAGS)):
        return None
    return TranscriptEntry(role, text)


def read_tool_call(block: JsonObject) -> TranscriptEntry | None:
    """Collapsed to the tool name and its first text argument (the command, the file path,
    the search pattern...), which is what tells one call apart from another."""
    name = read_text(block.get("name"))
    if name is None:
        return None
    tool_input = block.get("input")
    arguments = tool_input.values() if isinstance(tool_input, dict) else []
    first_text = next((value for value in arguments if isinstance(value, str)), "")
    summary = truncate(" ".join(first_text.split()), TOOL_SUMMARY_MAX_LENGTH)
    return TranscriptEntry("tool", summary, tool_name=name)
