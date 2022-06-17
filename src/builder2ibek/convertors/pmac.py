from typing import Any, Dict

from builder2ibek.ioc import Generic_IOC

pmac_defaults = {
    "pmac.GeoBrick": {
        "numAxes": 8,
        "idlePoll": 100,
        "movingPoll": 500,
    }
}


def pmac_handler(entity: Dict[str, Any], entity_type: str, ioc: Generic_IOC):

    pass
