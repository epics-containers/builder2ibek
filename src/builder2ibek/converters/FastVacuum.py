from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "FastVacuum"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the FastVacuum support
    module. Preserves the `name` attribute on Channel entities (used as the
    PV name for IMG/FP records) and coerces `img` to a zero-padded string.
    """

    if entity_type == "Master16":
        # Master16 has no name attribute in the XML, drop any default
        entity.remove("name")

    elif entity_type in ("auto_Channel16", "auto_ChannelUn"):
        # Ensure img is emitted as a string (support YAML expects str).
        img = entity.get("img")
        if img is not None and not isinstance(img, str):
            entity["img"] = f"{int(img):02d}"
