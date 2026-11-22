import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer

from agent_desk.cli.formatting import format_projects_table, format_sessions_table
from agent_desk.config import Config, default_config_path, load_config
from agent_desk.domain.errors import ConfigError, ProjectNotFound, ResumeError, UnknownProvider
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.codex import CodexProvider
from agent_desk.services.catalog import CatalogService
from agent_desk.services.resume import (
    ExecutableFinder,
    Launcher,
    ResumeService,
    run_in_foreground,
)
from agent_desk.tui.app import AgentDeskApp

PACKAGE_NAME = "agent-desk"
EXIT_FAILURE = 1

type CatalogLoader = Callable[[], CatalogService | ConfigError]
type TuiRunner = Callable[[CatalogService, ResumeService], None]
type ProviderOption = Annotated[
    str | None, typer.Option("--provider", help="Show only this AI CLI, e.g. 'codex'.")
]

app = typer.Typer(add_completion=False)


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
    dependencies.run_tui(catalog, resume_service)


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


@dataclass(frozen=True)
class Dependencies:
    """What the commands use from the outside world. Tests pass their own through Typer's
    `obj`, so they never read the real home folder or config, nor start a real AI CLI."""

    load_catalog: CatalogLoader = field(default_factory=lambda: load_default_catalog)
    find_executable: ExecutableFinder = shutil.which
    launch: Launcher = run_in_foreground
    run_tui: TuiRunner = field(default_factory=lambda: run_tui)


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


def run_tui(catalog: CatalogService, resume: ResumeService) -> None:
    AgentDeskApp(catalog, resume).run()


def load_default_catalog() -> CatalogService | ConfigError:
    config = load_config(default_config_path(), os.environ, Path.home())
    if isinstance(config, ConfigError):
        return config
    return build_catalog(config)


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
