"""Builds a synthetic ~/.codex tree inside tmp_path. Every value here is made up.

The shapes are not made up. No real Codex data was available, so each shape below comes from
the source code of the Codex CLI (https://github.com/openai/codex, Apache-2.0, commit
e1b755849216aacd40574b5ccf9ee18d18b1a867, read on 2026-11-18), as cited per builder. `SRC`
below stands for https://github.com/openai/codex/blob/e1b755849216aacd40574b5ccf9ee18d18b1a867.
The layout follows Codex's own test helpers in SRC/codex-rs/app-server/tests/common/rollout.rs.
A builder only writes fields found there, trimmed to the ones agent-desk reads plus the
required ones.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

# A dict becomes one JSON line; a str is written verbatim, which is how tests add broken lines.
type JsonLine = dict[str, object] | str
type HistoryMode = Literal["legacy", "paginated"]

BASE_TIME = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
FAKE_CLI_VERSION = "0.0.0"
CORRUPTED_LINE = '{"timestamp": "2026-01-01T10:00:00.000Z", "type": "event_msg", "payl'
UNKNOWN_TYPE_LINE: JsonLine = {"type": "some_future_type", "payload": {"anything": True}}
SESSIONS_DIR_NAME = "sessions"
SESSION_INDEX_FILE_NAME = "session_index.jsonl"


def timestamp_at(minute: int) -> str:
    """SRC/codex-rs/rollout/src/recorder.rs#L2114-L2118: UTC, milliseconds, "Z"."""
    moment = BASE_TIME + timedelta(minutes=minute)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def envelope(item_type: str, payload: Mapping[str, object], minute: int) -> JsonLine:
    """SRC/codex-rs/history/src/lib.rs#L628-L635: every line is {timestamp, type, payload}."""
    return {"timestamp": timestamp_at(minute), "type": item_type, "payload": payload}


# Legacy history mode. SRC/codex-rs/rollout/src/policy.rs#L142-L156 persists these event_msg
# lines only in legacy rollouts; structs at SRC/codex-rs/protocol/src/protocol.rs#L2876-L2914.
def user_message(text: str, *, minute: int = 0) -> JsonLine:
    return envelope("event_msg", {"type": "user_message", "message": text}, minute)


def agent_message(text: str, *, minute: int = 0) -> JsonLine:
    return envelope("event_msg", {"type": "agent_message", "message": text}, minute)


# Paginated history mode: item_completed events. Shapes from
# SRC/codex-rs/protocol/src/items.rs#L95-L101 and #L141-L184, as written in Codex's tests
# (SRC/codex-rs/tui/src/lib_tests.rs#L1466-L1475,
# SRC/codex-rs/tui/src/dynamic_tools_tests.rs#L44-L53).
def user_message_item(text: str, *, session_id: str, minute: int = 0) -> JsonLine:
    item = {"type": "UserMessage", "id": f"user-{minute}", "content": [text_input(text)]}
    return item_completed(item, session_id, minute)


def agent_message_item(text: str, *, session_id: str, minute: int = 0) -> JsonLine:
    content = [{"type": "Text", "text": text}]
    item = {"type": "AgentMessage", "id": f"agent-{minute}", "content": content}
    return item_completed(item, session_id, minute)


def item_completed(item: Mapping[str, object], session_id: str, minute: int) -> JsonLine:
    payload = {"type": "item_completed", "thread_id": session_id, "turn_id": "turn-1", "item": item}
    return envelope("event_msg", payload, minute)


def text_input(text: str) -> dict[str, object]:
    """SRC/codex-rs/protocol/src/user_input.rs#L16-L20."""
    return {"type": "text", "text": text}


# response_item lines are written in both history modes
# (SRC/codex-rs/rollout/src/policy.rs#L81-L99).
# Shapes from SRC/codex-rs/protocol/src/models.rs#L1151-L1298 and #L2181-L2194.
def response_user_message(text: str, *, minute: int = 0) -> JsonLine:
    """A model-input user message; Codex also injects context (e.g. <environment_context>)
    this way (SRC/codex-rs/protocol/src/protocol.rs#L127-L151)."""
    payload = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}
    return envelope("response_item", payload, minute)


def function_call(name: str, arguments: dict[str, object], *, minute: int = 0) -> JsonLine:
    # `arguments` is a JSON string, not an object (comment at models.rs#L1224-L1226).
    payload = {
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(arguments),
        "call_id": f"call-{minute}",
    }
    return envelope("response_item", payload, minute)


def custom_tool_call(name: str, tool_input: str, *, minute: int = 0) -> JsonLine:
    payload = {
        "type": "custom_tool_call",
        "name": name,
        "input": tool_input,
        "call_id": f"call-{minute}",
    }
    return envelope("response_item", payload, minute)


def local_shell_call(command: list[str], *, minute: int = 0) -> JsonLine:
    payload = {
        "type": "local_shell_call",
        "call_id": f"call-{minute}",
        "status": "completed",
        "action": {"type": "exec", "command": command},
    }
    return envelope("response_item", payload, minute)


def session_meta(
    session_id: str, *, cwd: str, history_mode: HistoryMode, source: object, minute: int
) -> JsonLine:
    """SRC/codex-rs/protocol/src/protocol.rs#L3543-L3640, filled like the Codex test helper
    (SRC/codex-rs/app-server/tests/common/rollout.rs#L256-L297). `history_mode` has no
    skip_serializing_if, so it is always written."""
    payload: dict[str, object] = {
        "session_id": session_id,
        "id": session_id,
        "timestamp": timestamp_at(minute),
        "cwd": cwd,
        "originator": "codex",
        "cli_version": FAKE_CLI_VERSION,
        "source": source,
        "model_provider": None,
        "base_instructions": None,
        "history_mode": history_mode,
    }
    return envelope("session_meta", payload, minute)


@dataclass(frozen=True)
class CodexTree:
    root: Path

    def add_session(
        self,
        session_id: str,
        *,
        cwd: str,
        created: datetime,
        lines: list[JsonLine],
        history_mode: HistoryMode = "legacy",
        source: object = "cli",
    ) -> Path:
        """Writes the session_meta line, then `lines`. Paginated rollouts number every JSON
        line with `ordinal`, like create_fake_paginated_rollout (rollout.rs#L62-L93)."""
        meta = session_meta(session_id, cwd=cwd, history_mode=history_mode, source=source, minute=0)
        all_lines = [meta, *lines]
        if history_mode == "paginated":
            all_lines = add_ordinals(all_lines)
        return self.add_raw_rollout(rollout_path(created, session_id), serialize_lines(all_lines))

    def add_raw_rollout(self, relative_path: Path, text: str) -> Path:
        path = self.root / SESSIONS_DIR_NAME / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        # Bytes, not text mode: on Windows text mode would turn "\n" into "\r\n".
        path.write_bytes(text.encode("utf-8"))
        return path

    def add_thread_name(self, session_id: str, name: str, *, minute: int) -> Path:
        """SRC/codex-rs/rollout/src/session_index.rs#L23-L60: append-only, the last entry for an
        id wins."""
        path = self.root / SESSION_INDEX_FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        entry: JsonLine = {
            "id": session_id,
            "thread_name": name,
            "updated_at": timestamp_at(minute),
        }
        with path.open("ab") as file:
            file.write(serialize_lines([entry]).encode("utf-8"))
        return path


def rollout_path(created: datetime, session_id: str) -> Path:
    """Relative to `sessions/`: YYYY/MM/DD/rollout-<YYYY-MM-DDThh-mm-ss>-<id>.jsonl
    (SRC/codex-rs/rollout/src/rollout_file_name.rs#L62-L74, recorder.rs#L1701-L1713)."""
    file_name = f"rollout-{created.strftime('%Y-%m-%dT%H-%M-%S')}-{session_id}.jsonl"
    return Path(created.strftime("%Y"), created.strftime("%m"), created.strftime("%d"), file_name)


def add_ordinals(lines: list[JsonLine]) -> list[JsonLine]:
    return [
        line if isinstance(line, str) else {**line, "ordinal": ordinal}
        for ordinal, line in enumerate(lines)
    ]


def serialize_lines(lines: list[JsonLine]) -> str:
    return "".join(f"{serialize_line(line)}\n" for line in lines)


def serialize_line(line: JsonLine) -> str:
    return line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)
