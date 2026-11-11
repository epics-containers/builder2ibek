from pathlib import Path

import typer

from builder2ibek import __version__
from builder2ibek.convert import convert_file
from builder2ibek.db2autosave import parse_templates
from builder2ibek.dbcompare import compare_dbs
from builder2ibek.devc7 import DLS_SW, devc7_cli
from builder2ibek.migrate_autosave import migrate_folder
from builder2ibek.reconvert import reconvert_cli
from builder2ibek.vendor_patterns import VendorError

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
    yaml: Path = typer.Option(..., help="Output file"),
    schema: str = typer.Option(
        "/epics/ibek-defs/ioc.schema.json",
        help="Generic IOC schema (added to top of the yaml output)",
    ),
    description: str = typer.Option(
        "",
        help="Short description of the IOC's device (e.g. 'Geobrick 06')",
    ),
    blgui: bool = typer.Option(
        False,
        "--blgui/--no-blgui",
        help="Emit BLGui.status / BLGui.device entities (DEVSTA and INFO PVs). "
        "Only for generic IOCs whose binary includes the BLGui module; "
        "otherwise BLGui entities are dropped.",
    ),
    vendor: bool = typer.Option(
        True,
        "--vendor/--no-vendor",
        help="Vendor the runtime patterns of a pattern-only IOC into its instance "
        "folder with `ibek pattern add`. --no-vendor writes the ioc.yaml and only "
        "lists the patterns.",
    ),
    patterns_out: Path | None = typer.Option(
        None,
        "--patterns-out",
        help="Write the IOC's `ibek pattern add` references to this file, one per "
        "line (empty when the IOC uses none)",
    ),
):
    """
    Convert a builder XML IOC to an ibek ioc.yaml.

    An IOC whose devices all come from runtime patterns and the runtime image
    (ioc-streamdevice-runtime) is pattern-only. Given
    services/<ioc>/config/ioc.yaml, xml2yaml runs `ibek pattern add` for each
    pattern into services/<ioc>/, which writes the pattern files under config/,
    runtime-lock.yaml, ioc.schema.json and the ioc.yaml schema header. A
    values.yaml that still holds the template's REPLACE_WITH_IMAGE_URI gets the
    runtime image; an image someone set is never changed. Patterns already in
    runtime-lock.yaml are checked and kept at their locked version.

    ADPandABlocks PandAs become fastcs-pandablocks instances instead. An IOC
    that holds only PandAs and boilerplate becomes one fastcs instance in place
    of the ioc.yaml: given services/<ioc>/config/ioc.yaml, it writes
    services/<ioc>/values.yaml and config/controller.yaml. Otherwise each PandA
    gets its own instance, named from its PV prefix, as a sibling of the IOC's
    folder (services/<prefix>/), and the ioc.yaml keeps the other devices.
    A PandA another instance already serves (same prefix or box) is refused
    with a warning, and an existing instance is never overwritten.
    """
    try:
        result = convert_file(
            xml, yaml, schema, description=description, blgui=blgui, vendor=vendor
        )
    except (FileExistsError, VendorError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e
    if patterns_out is not None:
        patterns_out.write_text("".join(f"{ref}\n" for ref in result.patterns))
    for note in result.notes:
        typer.echo(note)
    for warning in result.warnings:
        typer.echo(f"warning: {warning}", err=True)


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
def migrate_autosave(
    input_folder: Path = typer.Argument(
        Path("."),
        help="Folder holding the legacy <IOC>_N.sav set (default: cwd)",
    ),
    output_folder: Path = typer.Argument(
        Path("."),
        help="Folder to write autosave_{positions,settings}.sav into (default: cwd)",
    ),
    from_stem: str = typer.Option(
        None,
        "--from",
        "-f",
        help="IOC stem (e.g. BL19I-VA-IOC-01) selecting which <stem>_N.sav set "
        "to use. Only needed when the input folder holds more than one stem.",
    ),
    backup: bool = typer.Option(
        True,
        "--backup/--no-backup",
        help="Copy an existing destination to <file>.bak before overwriting",
    ),
    clean: bool = typer.Option(
        True,
        "--clean/--no-clean",
        help="Remove round-robin sibling files (.sav0/.savB/...) of each target "
        "so the IOC cannot restore a stale one (dated archives are kept)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report changes without writing any files"
    ),
):
    """
    Convert the legacy DLS autosave save set into the ibek
    autosave_positions.sav / autosave_settings.sav files.

    The legacy set (<stem>_0.sav, _1.sav, _2.sav -- most recent save of each) is
    found automatically in the input folder and reformatted (a trailing .VAL is
    dropped) following the DLS pass convention: set 0 -> positions, sets 1+ ->
    settings. At restore the IOC applies the values it recognises and ignores
    the rest, so the new IOC's PV set is not needed.
    """
    try:
        migrate_folder(
            input_folder,
            output_folder,
            stem=from_stem,
            backup=backup,
            clean=clean,
            dry_run=dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc


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
    inside one EPICS_ROOT tempdir. An IOC whose existing ioc.yaml has
    BLGui.* entities is reconverted with --blgui, which
    regenerates them from the XML. ADPandABlocks PandAs are written as
    fastcs-pandablocks instances, as xml2yaml does; those are not validated.
    """
    reconvert_cli(
        beamline,
        services_repo,
        validate=validate,
        descriptions_json=descriptions_json,
        only=list(only) or None,
        json_out=json_out,
    )


@cli.command("dev-c7")
def dev_c7(
    beamline: str = typer.Argument(
        ..., help="Beamline prefix of the IOCs to add (e.g. 'BL08J' or 'i08')"
    ),
    services_repo: Path = typer.Option(
        ..., "--services-repo", help="Path to the beamline services repo"
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write the planned folders (default: print the plan only). "
        "An existing folder is never overwritten.",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit the plan as JSON on stdout"
    ),
    init_dir: Path | None = typer.Option(
        None,
        help="DLS init configuration: <server>/soft-iocs and real-iocs "
        "[default: <dls-sw>/prod/etc/init]",
    ),
    redirect_table: Path | None = typer.Option(
        None,
        help="DLS IOC redirector table: IOC name -> boot script "
        "[default: <dls-sw>/prod/etc/redirector/redirect_table]",
    ),
    dls_sw: Path = typer.Option(
        DLS_SW, help="Root that /dls_sw paths resolve under (for tests)"
    ),
):
    """
    Add every live Linux IOC with a beamline prefix to a services repo as a
    dev-c7 legacy IOC, running the build it boots from today.

    Live IOCs are those in the init launch lists; each one's version comes
    from the redirect table. Live IOCs with no redirect entry, Windows,
    vxWorks and RTEMS IOCs, IOCs that already have a services folder, and
    retired IOCs are reported and left out. The IOCs keep running on their
    servers: never deploy a folder while its IOC runs there.
    """
    code = devc7_cli(
        beamline,
        services_repo,
        apply=apply,
        json_out=json_out,
        init_dir=init_dir,
        redirect_table=redirect_table,
        dls_sw=dls_sw,
    )
    if code:
        raise typer.Exit(code)


if __name__ == "__main__":
    cli()
