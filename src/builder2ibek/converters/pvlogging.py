import re
from pathlib import Path

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

default_acf = re.compile(r"/dls_sw/.*/.*/support/pvlogging/1-4/data/access.acf")

xml_component = "pvlogging"

# the blacklist accumulates over all of an IOC's BlacklistPv entities - it is
# keyed on the output file so that converting more than one IOC in a single
# process starts a fresh list for each of them
blacklist: list[str] = []
filename: Path | None = None


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the pvlogging support module
    """
    if entity_type == "PvLogging":
        if "access_file" not in entity or default_acf.match(entity.access_file):
            # use the default access file from the module
            entity.access_file = "/epics/support/pvlogging/src/access.acf"
        else:
            raise ValueError(
                "non default access.acf must be specified in the IOC and"
                " provided in the config folder"
            )
        entity.remove("name")

    if entity_type == "BlacklistPv":
        entity.type = "pvlogging.BlacklistPvs"
        # write the blacklist alongside the converted YAML, not into the cwd
        out_file = ioc.out_dir / (ioc.source_file.stem.lower() + "_blacklist.txt")
        global filename
        if out_file != filename:
            # first BlacklistPv of this IOC: start a new list
            blacklist.clear()
            filename = out_file
            blacklist.append(
                "# Rename to 'pvlogging_excl.txt' and move to IOC config directory.\n"
            )
            blacklist.append("# The following PVs will be excluded from pvlogging")
            print(f"writing pvlogging blacklist {out_file}")
        else:
            # remove previous blacklist entity, we only need one with all PVs
            for ent in ioc.entities:
                if ent["type"] == "pvlogging.BlacklistPvs":
                    ioc.entities.remove(ent)
                    break

        # add new BlacklistPv entity to the list and write the list to file
        blacklist.append(entity.name)
        entity.blacklist = "\n".join(blacklist) + "\n"
        with open(out_file, "w") as blacklist_file:
            blacklist_file.write(entity.blacklist)

        # the BlacklistPv entity declaration only require a pointer to the file
        entity.remove("name")
        entity.remove("blacklist")
        entity.blacklist_file = "/epics/ioc/config/pvlogging_excl.txt"
