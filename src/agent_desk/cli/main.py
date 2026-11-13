from importlib.metadata import version
from typing import Annotated

import typer

PACKAGE_NAME = "agent-desk"

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
