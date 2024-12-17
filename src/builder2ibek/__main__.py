from pathlib import Path
from typing import Optional

import typer

from builder2ibek import __version__
from builder2ibek.convert import convert_file
from builder2ibek.db2autosave import parse_templates
from builder2ibek.dbcompare import compare_dbs

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
    """Convert xmlbuilder assets to epics-containers assets"""


@cli.command()
def xml2yaml(
    xml: Path = typer.Argument(..., help="Filename of the builder XML file"),
    yaml: Optional[Path] = typer.Option(..., help="Output file"),
    schema: str = typer.Option(
        "/epics/ibek-defs/ioc.schema.json",
        help="Generic IOC schema (added to top of the yaml output)",
    ),
):
    if not yaml:
        yaml = xml.absolute().with_suffix("yaml")

    convert_file(xml, yaml, schema)


@cli.command()
def beamline2yaml(
    input: Path = typer.Argument(..., help="Path to root folder BLXX-BUILDER"),
    output: Path = typer.Argument(..., help="Output root folder"),
):
    """
    <<<<<<< HEAD
        Convert whole beamline's IOCs from builder to ibek (TODO)
    =======
        Convert all IOCs in a BLXXI-SUPPORT project into a set of ibek services
        folders (TODO)
    >>>>>>> 4af36b9 (add db compare)
    """
    typer.echo("Not implemented yet")
    raise typer.Exit(code=1)


@cli.command()
def autosave(
    out_folder: Path = typer.Option(
        ".", help="Output folder to write autosave request files"
    ),
    db_list: list[Path] = typer.Argument(
        ..., help="List of DB templates with autosave comments"
    ),
):
    """
    Convert DLS autosave DB template comments into autosave req files
    """
    parse_templates(out_folder, db_list)


@cli.command()
def db_compare(
    original: Path,
    new: Path,
    ignore: list[str] = typer.Option(
        [], help="List of record name sub strings to ignore"
    ),
    output: Optional[Path] = typer.Option(None, help="Output file"),
):
    """
    Compare two DB files and output the differences
    """

    compare_dbs(original, new, ignore, output)


if __name__ == "__main__":
    cli()
