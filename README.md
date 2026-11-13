# agent-desk

A terminal dashboard to browse and manage the data that AI coding CLIs keep on disk: sessions, memory files, and projects.

Tools like the Claude Code CLI and the Codex CLI store every session as plain files in your home directory (`~/.claude`, `~/.codex`). Over time these folders grow, projects get renamed or deleted, and there is no built-in way to see what is there. agent-desk reads those folders and gives you one place to list, read, resume, and clean them up.

## Status

**Early development. Not usable yet.**

What works today:
- `agent-desk --version`

Planned for the first release:
- List projects and sessions across Claude Code and Codex.
- Read a condensed transcript of a session.
- Resume a session in its own CLI.
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
uv run mypy src
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
