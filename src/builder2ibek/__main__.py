from pathlib import Path
from typing import Optional

import typer

from builder2ibek import __version__
from builder2ibek.convert import convert_file

cli = typer.Typer()


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
def xml2yaml(
    xml: Path = typer.Argument(..., help="Filename of the builder XML file"),
    yaml: Optional[Path] = typer.Option(..., help="Output file"),
    schema: Optional[str] = typer.Option(
        "/epics/ibek-defs/ioc.schema.json",
        help="Generic IOC schema (added to top of the yaml output)",
    ),
):
    if not yaml:
        yaml = xml.absolute().with_suffix("yaml")

    convert_file(xml, yaml, schema)


@cli.command()
def builder2ibek(
    input: Path = typer.Argument(..., help="Path to root folder BLXX-BUILDER"),
    output: Path = typer.Argument(..., help="Output root folder"),
):
    """
    Convert whole beamline's IOCs from builder to ibek (TODO
    """
    typer.echo("Not implemented yet")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    cli()
