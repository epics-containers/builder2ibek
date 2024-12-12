import re
from pathlib import Path
from typing import Optional

import typer
from ruamel.yaml import YAML, CommentedMap

from builder2ibek import __version__
from builder2ibek.builder import Builder
from builder2ibek.convert import dispatch

cli = typer.Typer()
yaml = YAML()


def version_callback(value: bool):
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@cli.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Print the version of builder2ibek and exit",
    ),
):
    """Convert build XML to ibek YAML"""


@cli.command()
def module(
    input: Path = typer.Argument(..., help="Path to support module root"),
    output: Path = typer.Argument(..., help="Output folder"),
):
    """
    Convert a beamline's IOCs from builder to ibek
    """
    typer.echo("Not implemented yet")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    cli()
