from pathlib import Path

import typer

from builder2ibek import __version__
from builder2ibek.convert import convert_file
from builder2ibek.db2autosave import parse_templates
from builder2ibek.dbcompare import compare_dbs
from builder2ibek.reconvert import reconvert_cli

cli = typer.Typer()


def version_callback(value: bool):
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@cli.callback()
def main(
    version: bool | None = typer.Option(
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
    yaml: Path | None = typer.Option(..., help="Output file"),
    schema: str = typer.Option(
        "/epics/ibek-defs/ioc.schema.json",
        help="Generic IOC schema (added to top of the yaml output)",
    ),
    description: str = typer.Option(
        "",
        help="Short description of the IOC's device (e.g. 'Geobrick 06')",
    ),
):
    if not yaml:
        yaml = xml.absolute().with_suffix("yaml")

    convert_file(xml, yaml, schema, description=description)


@cli.command()
def beamline2yaml(
    input: Path = typer.Argument(..., help="Path to root folder BLXX-BUILDER"),
    output: Path = typer.Argument(..., help="Output root folder"),
):
    """
    TODO: Convert all IOCs in a BLXXI-SUPPORT project into a set of ibek services
    folders (not yet implemented)
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
    remove_duplicates: bool = typer.Option(
        False, help="Remove duplicate records in the original DB"
    ),
    skip_known: bool = typer.Option(
        True,
        "--skip-known/--no-skip-known",
        help="Ignore record differences known to come from the devIocStats "
        "upgrade (common to all ibek conversions)",
    ),
    output: Path | None = typer.Option(None, help="Output file"),
):
    """
    Compare two DB files and output the differences
    """

    compare_dbs(
        original,
        new,
        ignore=ignore,
        remove_duplicates=remove_duplicates,
        skip_known=skip_known,
        output=output,
    )


@cli.command()
def reconvert(
    beamline: str = typer.Argument(..., help="Beamline prefix (e.g. 'i21' or 'BL21I')"),
    services_repo: Path = typer.Option(
        ..., "--services-repo", help="Path to the beamline services repo"
    ),
    validate: bool = typer.Option(
        True,
        "--validate/--no-validate",
        help="Schema-validate each reconverted ioc.yaml with ibek generate2",
    ),
    descriptions_json: Path | None = typer.Option(
        None,
        "--descriptions-json",
        help="Optional JSON object mapping ioc-name -> one-line description. "
        "Overrides descriptions read from existing ioc.yaml files.",
    ),
    only: list[str] = typer.Option(
        [],
        "--only",
        help="Limit to specific ioc-names (repeatable, case-insensitive)",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON on stdout"
    ),
):
    """
    Re-run xml2yaml on all IOCs for a beamline's services repo and
    optionally schema-validate each result with ibek generate2. Sequential
    inside one EPICS_ROOT tempdir.
    """
    reconvert_cli(
        beamline,
        services_repo,
        validate=validate,
        descriptions_json=descriptions_json,
        only=list(only) or None,
        json_out=json_out,
    )


if __name__ == "__main__":
    cli()
