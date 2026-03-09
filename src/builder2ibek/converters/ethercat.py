from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "ethercat"

# Track whether we've already inserted the dummy for this IOC
_dummy_inserted = False


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the ethercat support module.

    Ethercat entities are marked for major rewrite — the new approach uses
    fastcs-catio instead of the legacy ethercat support module.
    """
    global _dummy_inserted

    if entity_type == "EthercatMaster":
        # Replace the first EthercatMaster with a placeholder comment
        _dummy_inserted = True
        entity.clear()
        entity.type = "epics.PostStartupCommand"
        entity["command"] = (
            "# TODO: ethercat support requires major rewrite for "
            "epics-containers — switch to fastcs-catio"
        )
    else:
        # Drop all other ethercat entities
        entity.delete_me()
