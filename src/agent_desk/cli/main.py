import os
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer

from agent_desk.cli.formatting import format_projects_table, format_sessions_table
from agent_desk.config import default_config_path, load_config
from agent_desk.domain.errors import ConfigError, ProjectNotFound
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.services.catalog import CatalogService

PACKAGE_NAME = "agent-desk"
EXIT_FAILURE = 1

# Tests hand the CLI their own loader through Typer's `obj`, so they never read the real
# home folder or config file.
type CatalogLoader = Callable[[], CatalogService | ConfigError]

app = typer.Typer(add_completion=False)


def print_version_and_exit(is_requested: bool) -> None:
    if not is_requested:
        return
    typer.echo(f"{PACKAGE_NAME} {version(PACKAGE_NAME)}")
    raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
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
    """Browse and manage the local data of AI coding CLIs."""


@app.command()
def projects(ctx: typer.Context) -> None:
    """List the projects of every AI CLI, most recent activity first."""
    catalog = get_catalog(ctx).list_projects()
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
) -> None:
    """List the sessions of one project, most recent first."""
    # absolute(), not resolve(): resolve() follows symlinks and expands Windows short names,
    # and the result would no longer match the cwd the AI CLI recorded.
    result = get_catalog(ctx).list_sessions(project.absolute())
    if isinstance(result, ProjectNotFound):
        typer.echo(f"Error: no project found for {result.cwd}.", err=True)
        raise typer.Exit(EXIT_FAILURE)
    typer.echo(format_sessions_table(result))
    invalid_line_count = sum(summary.invalid_line_count for summary in result)
    if invalid_line_count:
        typer.echo(f"Note: {invalid_line_count} unreadable lines were skipped.", err=True)


def get_catalog(ctx: typer.Context) -> CatalogService:
    load_catalog: CatalogLoader = ctx.obj or load_default_catalog
    catalog = load_catalog()
    if isinstance(catalog, ConfigError):
        typer.echo(f"Error: config: {catalog.detail}", err=True)
        raise typer.Exit(EXIT_FAILURE)
    return catalog


def load_default_catalog() -> CatalogService | ConfigError:
    config = load_config(default_config_path(), os.environ, Path.home())
    if isinstance(config, ConfigError):
        return config
    return CatalogService([ClaudeCodeProvider(root=config.claude_root)])
