from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.converters.pmac import _sort_keys
from builder2ibek.types import Entity, Generic_IOC

xml_component = "BL05I"

# the hexapod mirror switches, which run a PLC on a GeoBrick
HEXAPOD_TYPES = ("BL05I_changeHexapodMirror", "BL05I_changeHexapodMirror_withRef")

# the pmac driver's idle poll period, in ms, for a GeoBrick that runs a hexapod
# mirror switch; the pmac model's default is 500
HEXAPOD_IDLE_POLL = 200


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the BL05I beamline module,
    which comes from its ibek-runtime-support pattern

    The hexapod mirror switches are the one exception to the rule that ibek
    parameter names match the XML's. The builder classes took PORT, the asyn
    port to the GeoBrick, which is a pmac.GeoBrick's Port attribute. The pattern
    models talk to the GeoBrick through the pmac driver instead, so they take
    PmacController, the name of that pmac.GeoBrick entity, and this converter
    looks the brick up among the IOC's entities. finalize also sets IdlePoll on
    such a brick.

    A water chiller's records use Hostlink.proto, which the HostLink pattern of
    ibek-runtime-streamdevice supplies, so the converter adds a HostLink entity
    to an IOC with a water chiller: that pulls the pattern into the IOC.

    IOCs that use BL05I: BL05I-HO-IOC-01 (water chillers), BL05I-MO-IOC-04,
    BL05I-MO-IOC-05 and BL05J-MO-IOC-02 (hexapod mirror switches), see
    /dls_sw/work/R3.14.12.7/support/BL05I-BUILDER/etc/makeIocs
    """

    # no BL05I model declares name, and nothing refers to one
    entity.remove("name")

    if entity_type in HEXAPOD_TYPES:
        # deliberate exception to the round-trip rule: PORT becomes
        # PmacController, the GeoBrick whose asyn port PORT names
        port = entity.PORT
        entity.remove("PORT")
        brick = next(
            (
                raw.get("name")
                for raw in ioc.raw_entities
                if raw.get("type") == "pmac.GeoBrick" and raw.get("Port") == port
            ),
            None,
        )
        if brick is None:
            ioc.extra_warnings.append(
                f"{entity_type} {entity.P}{entity.R}: no pmac.GeoBrick has Port "
                f"{port}, so PmacController is left as {port}"
            )
            brick = port
        entity.PmacController = brick

    elif entity_type == "BL05I_waterchiller":
        if not any(e.get("type") == "HostLink.HostLink" for e in ioc.entities):
            entity.add_entity({"type": "HostLink.HostLink"})


def finalize(ioc: Generic_IOC):
    """
    Set IdlePoll on each GeoBrick that runs a hexapod mirror switch, unless the
    XML sets it.

    The switch's run flag is read on the pmac driver's fast loop, which runs at
    IdlePoll (500 ms by default) while no motor moves. The builder's version
    polled it every 0.2 s through StreamDevice, so the brick polls at 200 ms.
    """
    bricks = {
        e.get("PmacController")
        for e in ioc.entities
        if e.get("type") in [f"BL05I.{t}" for t in HEXAPOD_TYPES]
    }
    for entity in ioc.entities:
        if (
            entity.get("type") == "pmac.GeoBrick"
            and entity.get("name") in bricks
            and isinstance(entity, Entity)
            and "IdlePoll" not in entity.xml_attributes()
        ):
            entity["IdlePoll"] = HEXAPOD_IDLE_POLL
            _sort_keys(entity)
