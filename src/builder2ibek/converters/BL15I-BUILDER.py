from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "BL15I-BUILDER"

# Entity types that have an entity model in
# ibek-support-dls/BL15I-BUILDER/BL15I-BUILDER.ibek.support.yaml.
# Everything else is still dropped - see the docstring below.
converted = ["auto_BL15I_SumTheDiode"]


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for BL15I-BUILDER module.

    BL15I-BUILDER defines beamline-specific AutoSubstitution templates.
    Only the ones listed in `converted` have an entity model so far; the rest
    are skipped until someone needs them.
    """
    if entity_type not in converted:
        entity.delete_me()
        return

    # builder's object name is not passed to the template - the substitutions
    # pattern is P, SHUTTER, DIODE and the two gda_* tags, which the global
    # handler has already stripped.
    entity.remove("name")
