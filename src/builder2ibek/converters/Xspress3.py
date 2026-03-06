from math import floor

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "Xspress3"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "Xspress3":
        port = entity.get("PORT", "")
        p = entity.get("P", "")
        r = entity.get("R", "")
        timeout = entity.get("TIMEOUT", 1)
        num_channels = int(entity.get("num_channels", 1))
        num_cards = int(entity.get("num_cards", 1))

        # Convert bool-like string params to str for consistency
        for param in ("use_resgrades", "readout_MCA", "use_odin"):
            val = entity.get(param)
            if val is not None:
                entity[param] = str(val)

        prev_chan_grp = None
        for chan in range(num_channels):
            chan_grp = f".{8 * floor(chan / 8) + 1}-{8 * (floor(chan / 8) + 1)}"
            if num_channels <= 8:
                chan_grp = ""
            if prev_chan_grp != chan_grp:
                prev_chan_grp = chan_grp
                entity.add_entity(
                    {
                        "type": "Xspress3.auto_xspress3DTCGuiHeader",
                        "PORT": port,
                        "CHAN_GRP": chan_grp,
                    }
                )
            entity.add_entity(
                {
                    "type": "Xspress3.auto_xspress3Channel",
                    "CHAN_NUM": chan + 1,
                    "CHAN_IND": chan,
                    "PORT": port,
                    "P": p,
                    "R": r,
                    "TIMEOUT": timeout,
                    "CHAN_GRP": chan_grp,
                }
            )
        for card in range(num_cards):
            entity.add_entity(
                {
                    "type": "Xspress3.auto_xspress3Card",
                    "PORT": port,
                    "P": p,
                    "R": r,
                    "TIMEOUT": timeout,
                    "CARD_NUM": card,
                }
            )

    elif entity_type == "Xspress3DTCPlugin":
        port = entity.get("PORT", "")
        p = entity.get("P", "")
        r = entity.get("R", "")
        timeout = entity.get("TIMEOUT", 1)
        num_channels = int(entity.get("num_channels", 1))

        entity.add_entity(
            {
                "type": "Xspress3.auto_xspress3DTCFactors",
                "NUM_CHANNELS": num_channels,
                "PORT": port,
                "P": p,
                "R": r,
                "TIMEOUT": timeout,
            }
        )
        for chan in range(num_channels):
            entity.add_entity(
                {
                    "type": "Xspress3.auto_xspress3DTCChannel",
                    "PORT": port,
                    "CHAN_IND": chan,
                    "CHAN_NUM": chan + 1,
                    "P": p,
                    "R": r,
                    "TIMEOUT": timeout,
                }
            )

    elif entity_type == "Xspress3Plugins":
        entity.remove("name")

        det = entity.get("DET", "")
        port_prefix = entity.get("PORTPREFIX", "")
        p = entity.get("P", "")
        num_channels = int(entity.get("num_channels", 1))
        max_buffers = int(entity.get("max_buffers", 4096))

        # Create NDProcess plugin
        entity.add_entity(
            {
                "type": "ADCore.NDProcess",
                "PORT": port_prefix + ".PROC",
                "NDARRAY_PORT": det,
                "R": ":PROC:",
                "P": p,
                "QUEUE": max_buffers,
                "ADDR": 0,
                "TIMEOUT": 5,
            }
        )

        for chan in range(num_channels):
            chan_grp = f".{8 * floor(chan / 8) + 1}-{8 * (floor(chan / 8) + 1)}"
            if num_channels <= 8:
                chan_grp = ""
            roi_port = f"{port_prefix}.ROIS{chan_grp}.ROI{chan + 1}"

            # NDROI per channel
            entity.add_entity(
                {
                    "type": "ADCore.NDROI",
                    "PORT": roi_port,
                    "NDARRAY_PORT": det,
                    "P": p,
                    "R": f":ROI{chan + 1}:",
                    "QUEUE": max_buffers,
                    "ADDR": 0,
                    "TIMEOUT": 5,
                }
            )
            # NDStdArrays per channel
            entity.add_entity(
                {
                    "type": "ADCore.NDStdArrays",
                    "PORT": f"{port_prefix}.ARRS{chan_grp}.ARR{chan + 1}",
                    "NDARRAY_PORT": roi_port,
                    "NELEMENTS": max_buffers,
                    "FTVL": "DOUBLE",
                    "TYPE": "Float64",
                    "R": f":ARR{chan + 1}:",
                    "QUEUE": max_buffers,
                    "ADDR": 0,
                    "TIMEOUT": 5,
                    "P": p,
                }
            )

            roisum_port = f"{port_prefix}.ROIS{chan_grp}.SUM.ROISUM{chan + 1}"

            # NDROI sum per channel
            entity.add_entity(
                {
                    "type": "ADCore.NDROI",
                    "PORT": roisum_port,
                    "NDARRAY_PORT": port_prefix + ".PROC",
                    "P": p,
                    "R": f":ROISUM{chan + 1}:",
                    "QUEUE": max_buffers,
                    "ADDR": 0,
                    "TIMEOUT": 5,
                }
            )
            # NDStdArrays sum per channel
            entity.add_entity(
                {
                    "type": "ADCore.NDStdArrays",
                    "PORT": f"{port_prefix}.ARRS{chan_grp}.SUM.ARRSUM{chan + 1}",
                    "NDARRAY_PORT": roisum_port,
                    "NELEMENTS": max_buffers,
                    "FTVL": "DOUBLE",
                    "TYPE": "Float64",
                    "P": p,
                    "R": f":ARRSUM{chan + 1}:",
                    "QUEUE": max_buffers,
                    "ADDR": 0,
                    "TIMEOUT": 5,
                }
            )

            # NDAttribute per channel
            entity.add_entity(
                {
                    "type": "ADCore.NDAttribute",
                    "PORT": f"{port_prefix}.SCAS{chan_grp}.C{chan + 1}_SCAS",
                    "NDARRAY_PORT": det,
                    "NDARRAY_ADDR": 0,
                    "MAX_ATTRIBUTES": 9,
                    "QUEUE": max_buffers,
                    "ADDR": 0,
                    "TIMEOUT": 5,
                    "NCHANS": max_buffers,
                    "P": p,
                    "R": f":C{chan + 1}_SCAS:",
                }
            )

            # Plugins channel template
            entity.add_entity(
                {
                    "type": "Xspress3.auto_xspress3PluginsChannel",
                    "P": p,
                    "CHAN": chan + 1,
                }
            )
