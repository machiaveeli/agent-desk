import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer

from agent_desk.cli.formatting import (
    format_projects_table,
    format_sessions_table,
    format_trash_table,
)
from agent_desk.config import Config, default_config_path, default_trash_root, load_config
from agent_desk.display import format_cwd
from agent_desk.domain.errors import (
    ConfigError,
    ProjectNotFound,
    ResumeError,
    TrashError,
    UnknownProvider,
)
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.codex import CodexProvider
from agent_desk.services.catalog import CatalogService
from agent_desk.services.resume import (
    ExecutableFinder,
    Launcher,
    ResumeService,
    run_in_foreground,
)
from agent_desk.services.trash import TrashService
from agent_desk.tui.app import AgentDeskApp

PACKAGE_NAME = "agent-desk"
EXIT_FAILURE = 1

type CatalogLoader = Callable[[], CatalogService | ConfigError]
type TrashLoader = Callable[[CatalogService], TrashService | ConfigError]
type TuiRunner = Callable[[CatalogService, ResumeService, TrashService], None]
type ProviderOption = Annotated[
    str | None, typer.Option("--provider", help="Show only this AI CLI, e.g. 'codex'.")
]

app = typer.Typer(add_completion=False)
trash_app = typer.Typer(help="List, restore and empty the agent-desk trash.")
app.add_typer(trash_app, name="trash")


def print_version_and_exit(is_requested: bool) -> None:
    if not is_requested:
        return
    typer.echo(f"{PACKAGE_NAME} {version(PACKAGE_NAME)}")
    raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    show_version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=print_version_and_exit,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Browse and manage the local data of AI coding CLIs. With no command, opens the TUI."""
    if ctx.invoked_subcommand is not None:
        return
    dependencies = get_dependencies(ctx)
    catalog = get_catalog(ctx)
    resume_service = ResumeService(catalog, dependencies.find_executable, dependencies.launch)
    dependencies.run_tui(catalog, resume_service, get_trash(ctx, catalog))


@app.command()
def projects(ctx: typer.Context, provider: ProviderOption = None) -> None:
    """List the projects of every AI CLI, most recent activity first."""
    catalog = get_catalog(ctx, provider).list_projects()
    for missing in catalog.missing_providers:
        typer.echo(f"Note: no {missing.provider_id} data found at {missing.root}.", err=True)
    if not catalog.projects:
        typer.echo("No projects found.")
        return
    typer.echo(format_projects_table(catalog.projects))


@app.command()
def sessions(
    ctx: typer.Context,
    project: Annotated[
        Path, typer.Option("--project", help="The project folder (its cwd), e.g. '.'.")
    ],
    provider: ProviderOption = None,
) -> None:
    """List the sessions of one project, most recent first."""
    # absolute(), not resolve(): resolve() follows symlinks and expands Windows short names,
    # and the result would no longer match the cwd the AI CLI recorded.
    result = get_catalog(ctx, provider).list_sessions(project.absolute())
    if isinstance(result, ProjectNotFound):
        typer.echo(f"Error: no project found for {result.cwd}.", err=True)
        raise typer.Exit(EXIT_FAILURE)
    typer.echo(format_sessions_table(result))
    invalid_line_count = sum(summary.invalid_line_count for summary in result)
    if invalid_line_count:
        typer.echo(f"Note: {invalid_line_count} unreadable lines were skipped.", err=True)


@app.command()
def resume(
    ctx: typer.Context,
    session_id: Annotated[str, typer.Argument(help="The session id, as `sessions` lists it.")],
) -> None:
    """Resume a session in its own AI CLI, inside the project folder, in this terminal."""
    dependencies = get_dependencies(ctx)
    service = ResumeService(
        catalog=get_catalog(ctx),
        find_executable=dependencies.find_executable,
        launch=dependencies.launch,
    )
    plan = service.prepare(session_id)
    if isinstance(plan, ResumeError):
        typer.echo(f"Error: {plan.detail}", err=True)
        raise typer.Exit(EXIT_FAILURE)
    if plan.is_active:
        typer.echo("This session is open in another terminal. Two copies may overwrite each other.")
        if not typer.confirm("Resume it anyway?", default=False):
            raise typer.Exit(EXIT_FAILURE)
    raise typer.Exit(service.launch_plan(plan))


@trash_app.command("list")
def list_trash(ctx: typer.Context) -> None:
    """List the trash, most recent first; 'expired' entries go on the next `trash empty`."""
    listing = get_trash(ctx, get_catalog(ctx)).list_entries()
    for unreadable in listing.unreadable:
        typer.echo(
            f"Note: entry {unreadable.entry_id} cannot be read: {unreadable.detail}.", err=True
        )
    if not listing.entries:
        typer.echo("The trash is empty.")
        return
    typer.echo(format_trash_table(listing.entries))


@trash_app.command("restore")
def restore_trash(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="The entry id, as `trash list` shows it.")],
) -> None:
    """Move a trashed session back to where it was."""
    entry = get_trash(ctx, get_catalog(ctx)).restore(entry_id)
    if isinstance(entry, TrashError):
        typer.echo(f"Error: {entry.detail}", err=True)
        raise typer.Exit(EXIT_FAILURE)
    typer.echo(f"Restored '{entry.title}' ({entry.provider_id}, {format_cwd(entry.cwd)}).")


@trash_app.command("empty")
def empty_trash(ctx: typer.Context) -> None:
    """Delete the expired entries for good, after confirmation."""
    trash = get_trash(ctx, get_catalog(ctx))
    planned = trash.plan_empty()
    if not planned:
        typer.echo("No expired entries to delete.")
        return
    listing = trash.list_entries().entries
    typer.echo(format_trash_table([listed for listed in listing if listed.entry in planned]))
    if not typer.confirm(f"Delete {len(planned)} expired entries for good?", default=False):
        raise typer.Exit(EXIT_FAILURE)
    deleted = trash.empty(planned)
    typer.echo(f"Deleted {len(deleted)} entries.")
    if len(deleted) < len(planned):
        skipped = len(planned) - len(deleted)
        typer.echo(f"Note: {skipped} entries changed meanwhile and were kept.", err=True)


@dataclass(frozen=True)
class Dependencies:
    """What the commands use from the outside world. Tests pass their own through Typer's
    `obj`, so they never read the real home folder or config, nor start a real AI CLI."""

    load_catalog: CatalogLoader = field(default_factory=lambda: load_default_catalog)
    find_executable: ExecutableFinder = shutil.which
    launch: Launcher = run_in_foreground
    run_tui: TuiRunner = field(default_factory=lambda: run_tui)
    load_trash: TrashLoader = field(default_factory=lambda: load_default_trash)


def get_dependencies(ctx: typer.Context) -> Dependencies:
    dependencies = ctx.obj
    return dependencies if isinstance(dependencies, Dependencies) else Dependencies()


def get_catalog(ctx: typer.Context, provider_id: str | None = None) -> CatalogService:
    catalog = get_dependencies(ctx).load_catalog()
    if isinstance(catalog, ConfigError):
        typer.echo(f"Error: config: {catalog.detail}", err=True)
        raise typer.Exit(EXIT_FAILURE)
    if provider_id is None:
        return catalog
    selected = catalog.only_provider(provider_id)
    if isinstance(selected, UnknownProvider):
        known = ", ".join(selected.known_ids)
        typer.echo(f"Error: unknown provider '{provider_id}' (known: {known}).", err=True)
        raise typer.Exit(EXIT_FAILURE)
    return selected


def get_trash(ctx: typer.Context, catalog: CatalogService) -> TrashService:
    trash = get_dependencies(ctx).load_trash(catalog)
    if isinstance(trash, ConfigError):
        typer.echo(f"Error: config: {trash.detail}", err=True)
        raise typer.Exit(EXIT_FAILURE)
    return trash


def run_tui(catalog: CatalogService, resume: ResumeService, trash: TrashService) -> None:
    AgentDeskApp(catalog, resume, trash).run()


def load_default_catalog() -> CatalogService | ConfigError:
    config = load_config(default_config_path(), os.environ, Path.home())
    if isinstance(config, ConfigError):
        return config
    return build_catalog(config)


def load_default_trash(catalog: CatalogService) -> TrashService | ConfigError:
    config = load_config(default_config_path(), os.environ, Path.home())
    if isinstance(config, ConfigError):
        return config
    return build_trash(config, catalog, default_trash_root())


def build_trash(config: Config, catalog: CatalogService, root: Path) -> TrashService:
    return TrashService(
        root=root,
        is_active=catalog.is_active,
        now=lambda: datetime.now(UTC),
        retention_days=config.trash_retention_days,
    )


def build_catalog(config: Config) -> CatalogService:
    return CatalogService(
        [
            ClaudeCodeProvider(root=config.claude_root),
            CodexProvider(
                root=config.codex_root,
                active_threshold_minutes=config.codex_active_threshold_minutes,
            ),
        ]
    )
