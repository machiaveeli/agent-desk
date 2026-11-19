# agent-desk

A terminal dashboard to browse and manage the data that AI coding CLIs keep on disk: sessions, memory files, and projects.

Tools like the Claude Code CLI and the Codex CLI store every session as plain files in your home directory (`~/.claude`, `~/.codex`). Over time these folders grow, projects get renamed or deleted, and there is no built-in way to see what is there. agent-desk reads those folders and gives you one place to list, read, resume, and clean them up.

## Status

**Early development. Not usable yet.**

What works today (Claude Code and Codex, read-only except for resume):
- `agent-desk projects`: every project with its session count, last activity, and size.
- `agent-desk sessions --project <path>`: the sessions of one project (`.` for the current folder).
- `--provider claude-code` or `--provider codex` on both commands shows only that CLI.
- `agent-desk resume <session-id>`: reopen a session in `claude` or `codex`, inside its project folder.
- `agent-desk --version`

Codex sessions are read from `~/.codex/sessions` (or `$CODEX_HOME`). Compressed (`.jsonl.zst`) and archived sessions are not shown yet.

Planned for the first release:
- A terminal dashboard, including a condensed transcript of each session.
- Move sessions to an app trash and restore them.
- Manage memory files.
- Find orphan projects and large folders, and clean them up with a preview.

Supported platforms: Linux and Windows, Python 3.12+.

## Your data stays local

agent-desk only reads and writes files on your machine. It makes no network calls and collects no telemetry.

It never edits the contents of a session. When it removes something, the files go to the app's own trash first, so you can restore them. It also refuses to touch a session that is still running.

## Run from source

You need [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/machiaveeli/agent-desk.git
cd agent-desk
uv sync
uv run agent-desk --version
```

Run the checks:

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
