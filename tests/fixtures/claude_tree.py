"""Builds a synthetic ~/.claude tree inside tmp_path. Every value here is made up.

The shapes are not made up. Claude Code's on-disk format has no public documentation, so each
shape below was checked against real local files written by Claude Code 2.1.3xx (structure
and field types only, no content), as noted per builder. A builder only writes fields seen
there, trimmed to the ones agent-desk reads. A shape that was not observed is marked
"Not observed" and no behavior may rely on it.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

# A dict becomes one JSON line; a str is written verbatim, which is how tests add broken lines.
type JsonLine = dict[str, object] | str
type ContentBlock = dict[str, object]

BASE_TIME = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
FAKE_MODEL = "fake-model"
FAKE_PROC_START = "424242"
FAKE_STARTED_AT_MS = 1_767_261_600_000
LARGE_SESSION_FILLER_REPEAT = 80
CORRUPTED_LINE = '{"type": "user", "message": {"role": "us'
UNKNOWN_TYPE_LINE: JsonLine = {"type": "some-future-type", "payload": {"anything": True}}


def timestamp_at(minute: int) -> str:
    moment = BASE_TIME + timedelta(minutes=minute)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def encode_cwd(cwd: str) -> str:
    """Mimics Claude Code's folder naming. Observed: '/' becomes '-' and letters and digits
    stay. Not observed: other characters (assumed to become '-' too) and Windows paths. Only
    the fixture layout uses this; agent-desk reads the cwd from the session, never the name."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


# Observed: message.content is a string or a list of blocks typed "text", "thinking",
# "tool_use" or "tool_result". A tool_result's content is a string or a list of blocks.
def text_block(text: str) -> ContentBlock:
    return {"type": "text", "text": text}


def thinking_block(text: str) -> ContentBlock:
    return {"type": "thinking", "thinking": text, "signature": "fake-signature"}


def tool_use_block(tool_use_id: str, name: str, tool_input: dict[str, object]) -> ContentBlock:
    return {"type": "tool_use", "id": tool_use_id, "name": name, "input": tool_input}


def tool_result_block(tool_use_id: str, text: str) -> ContentBlock:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": text}


# Observed: "user" and "assistant" lines carry sessionId, cwd, an ISO UTC timestamp with
# milliseconds and "Z", and message. Injected lines add isMeta or isCompactSummary.
def user_line(
    content: str | list[ContentBlock], *, cwd: str, minute: int = 0, is_meta: bool = False
) -> JsonLine:
    line: dict[str, object] = {
        "type": "user",
        "cwd": cwd,
        "timestamp": timestamp_at(minute),
        "message": {"role": "user", "content": content},
    }
    if is_meta:
        line["isMeta"] = True
    return line


def assistant_line(content: list[ContentBlock], *, cwd: str, minute: int = 0) -> JsonLine:
    return {
        "type": "assistant",
        "cwd": cwd,
        "timestamp": timestamp_at(minute),
        "message": {
            "type": "message",
            "role": "assistant",
            "model": FAKE_MODEL,
            "content": content,
        },
    }


# Observed: {"type": "custom-title", "customTitle", "sessionId"} and
# {"type": "ai-title", "aiTitle", "sessionId"}. A session may hold several custom-title lines.
def custom_title_line(title: str) -> JsonLine:
    return {"type": "custom-title", "customTitle": title}


def ai_title_line(title: str) -> JsonLine:
    return {"type": "ai-title", "aiTitle": title}


@dataclass(frozen=True)
class ClaudeTree:
    root: Path

    def add_project(self, cwd: str) -> Path:
        project_dir = self.root / "projects" / encode_cwd(cwd)
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir

    def add_session(self, project_dir: Path, session_id: str, lines: list[JsonLine]) -> Path:
        """Writes `<session_id>.jsonl`. Dict lines get the `sessionId` every real line carries."""
        path = project_dir / f"{session_id}.jsonl"
        text = "".join(f"{serialize_line(line, session_id)}\n" for line in lines)
        # Bytes, not text mode: on Windows text mode would turn "\n" into "\r\n".
        path.write_bytes(text.encode("utf-8"))
        return path

    def add_large_session(
        self, project_dir: Path, session_id: str, *, cwd: str, min_size_bytes: int
    ) -> Path:
        """A long user/assistant exchange of at least `min_size_bytes`, for streaming tests."""
        filler = "lorem ipsum " * LARGE_SESSION_FILLER_REPEAT
        pair: list[JsonLine] = [
            user_line(filler, cwd=cwd),
            assistant_line([text_block(filler)], cwd=cwd),
        ]
        pair_size = sum(len(serialize_line(line, session_id)) + 1 for line in pair)
        pair_count = min_size_bytes // pair_size + 1
        return self.add_session(project_dir, session_id, pair * pair_count)

    def add_sibling_file(
        self, project_dir: Path, session_id: str, relative_path: str, text: str
    ) -> Path:
        path = project_dir / session_id / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def add_sibling_custom_title(self, project_dir: Path, session_id: str, title: str) -> Path:
        """Observed: `<session_id>/custom-title.json` holds {"customTitle"}. In every real case
        it also had custom-title lines, with the same value as the last one."""
        content = json.dumps({"customTitle": title})
        return self.add_sibling_file(project_dir, session_id, "custom-title.json", content)

    def add_memory(self, project_dir: Path, file_name: str, text: str) -> Path:
        path = project_dir / "memory" / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def add_active_session_file(
        self, *, pid: int, session_id: str, cwd: str, proc_start: str = FAKE_PROC_START
    ) -> Path:
        """Writes `sessions/<pid>.json` plus the `<pid>.<hash>.key` file Claude keeps beside it.

        Observed fields and types: pid int, sessionId str, cwd str, startedAt int (ms),
        procStart str, status str. On Linux, procStart equals field 22 of /proc/<pid>/stat
        (checked against a running session)."""
        record = {
            "pid": pid,
            "sessionId": session_id,
            "cwd": cwd,
            "startedAt": FAKE_STARTED_AT_MS,
            "procStart": proc_start,
            "status": "busy",
        }
        path = self.add_raw_session_file(f"{pid}.json", json.dumps(record))
        self.add_raw_session_file(f"{pid}.fixture.key", "fake-key")
        return path

    def add_raw_session_file(self, file_name: str, text: str) -> Path:
        path = self.root / "sessions" / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path


def serialize_line(line: JsonLine, session_id: str) -> str:
    if isinstance(line, str):
        return line
    return json.dumps({"sessionId": session_id, **line}, ensure_ascii=False)
