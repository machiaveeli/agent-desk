"""Reads a Codex rollout as condensed entries, one line at a time."""

import json
from collections.abc import Iterator
from pathlib import Path

from agent_desk.domain.models import TranscriptEntry
from agent_desk.domain.text import truncate
from agent_desk.providers.codex_rollout import (
    RESPONSE_ITEM_TYPE,
    iter_valid_lines,
    read_message,
    read_payload,
)
from agent_desk.providers.jsonl import JsonObject, read_text

TOOL_SUMMARY_MAX_LENGTH = 80
# A local shell call has no tool name of its own; its item type stands in for it.
LOCAL_SHELL_CALL_TYPE = "local_shell_call"


def read_transcript_entries(path: Path) -> Iterator[TranscriptEntry]:
    """User and assistant text from the message events, plus one line per tool call. The
    model-input copies of messages (response_item "message") are left out: they repeat the
    events and also carry context Codex injects. Reasoning and tool outputs are left out too."""
    for line in iter_valid_lines(path):
        entry = read_line_entry(line)
        if entry is not None:
            yield entry


def read_line_entry(line: JsonObject) -> TranscriptEntry | None:
    message = read_message(line)
    if message is not None:
        return TranscriptEntry(*message)
    payload = read_payload(line, RESPONSE_ITEM_TYPE)
    return read_tool_call(payload) if payload is not None else None


def read_tool_call(payload: JsonObject) -> TranscriptEntry | None:
    """Collapsed to the tool name and its first text argument, which is what tells one call
    apart from another."""
    match payload.get("type"):
        case "function_call":
            return make_tool_entry(payload.get("name"), first_text_argument(payload))
        case "custom_tool_call":
            return make_tool_entry(payload.get("name"), payload.get("input"))
        case "local_shell_call":
            return make_tool_entry(LOCAL_SHELL_CALL_TYPE, read_shell_command(payload))
    return None


def first_text_argument(payload: JsonObject) -> str | None:
    # `arguments` is a JSON object encoded as a string.
    try:
        arguments = json.loads(str(payload.get("arguments")))
    except ValueError:
        return None
    values = arguments.values() if isinstance(arguments, dict) else []
    return next((value for value in values if isinstance(value, str)), None)


def read_shell_command(payload: JsonObject) -> str | None:
    action = payload.get("action")
    command = action.get("command") if isinstance(action, dict) else None
    if not isinstance(command, list):
        return None
    return " ".join(part for part in command if isinstance(part, str))


def make_tool_entry(name: object, argument: object) -> TranscriptEntry | None:
    tool_name = read_text(name)
    if tool_name is None:
        return None
    text = argument if isinstance(argument, str) else ""
    summary = truncate(" ".join(text.split()), TOOL_SUMMARY_MAX_LENGTH)
    return TranscriptEntry("tool", summary, tool_name=tool_name)
