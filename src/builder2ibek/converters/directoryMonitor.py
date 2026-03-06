from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "directoryMonitor"

# Track per-manager directory counts for computing N
_manager_dir_counts: dict[str, int] = {}


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML converter for the directoryMonitor support module.
    """

    if entity_type == "Manager":
        # Count how many Directory entities reference this manager
        manager_name = entity.name
        num_dirs = sum(
            1
            for raw in ioc.raw_entities
            if raw.get("type") == "directoryMonitor.Directory"
            and raw.get("manager") == manager_name
        )
        entity["num_dirs"] = num_dirs
        # Reset counter for this manager
        _manager_dir_counts[manager_name] = 0

    elif entity_type == "Directory":
        entity.remove("name")

        manager_name = entity.manager

        # Compute sequential directory number N
        _manager_dir_counts.setdefault(manager_name, 0)
        _manager_dir_counts[manager_name] += 1
        entity["N"] = _manager_dir_counts[manager_name]

        # Look up the manager entity in raw_entities to get P, R, ADDR
        for raw in ioc.raw_entities:
            if (
                raw.get("type") == "directoryMonitor.Manager"
                and raw.get("name") == manager_name
            ):
                entity["P"] = raw.get("P")
                entity["R"] = raw.get("R")
                entity["PORT"] = manager_name
                entity["ADDR"] = raw.get("ADDR", 0)
                break
