import io
import re
from pathlib import Path

import ruamel.yaml as yaml

from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "adUtil"

schema = ""

GDA_PLUGINS = Path(__file__).parent / "gdaPlugins.yaml"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    if entity_type == "gdaPlugins":
        ioc.entities.remove(entity)
        yaml_text = GDA_PLUGINS.read_text()
        for macro, value in entity.items():
            yaml_text = re.sub(rf"(\$\({macro}(?:=[^\)]*)?\))", str(value), yaml_text)

        # substitute remaining macros with their in-place defaults
        yaml_text = re.sub(r"\$\(.*?=([^\)]*)\)", r"\1", yaml_text)

        with io.StringIO(yaml_text) as f:
            yml = yaml.YAML(typ="safe", pure=True)
            entities = yml.load(f)

        print(f"adding gdaPlugins items to entities for {entity.CAM}")
        ioc.entities.extend(entities)
