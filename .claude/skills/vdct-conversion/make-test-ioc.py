"""Emit an ioc.yaml instantiating every entity model in a pattern's support yaml.

make-test-ioc.py <pattern-dir> > <config-dir>/ioc.yaml
"""

import sys
from pathlib import Path

import yaml

pattern = Path(sys.argv[1])
support = next(pattern.glob("*.ibek.support.yaml"))
defs = yaml.safe_load(support.read_text())
module = defs["module"]

DUMMY = {"str": "TEST", "int": 1, "float": 1.0, "bool": True, "id": None}

entities = []
for n, model in enumerate(defs["entity_models"]):
    e = {"type": f"{module}.{model['name']}"}
    for pname, p in (model.get("parameters") or {}).items():
        if "default" in p:
            continue
        t = p.get("type", "str")
        # ids must be unique across the IOC
        e[pname] = f"{model['name']}{n}" if t == "id" else DUMMY.get(t, "TEST")
    entities.append(e)

print(
    yaml.safe_dump(
        {
            "ioc_name": f"test-{module}",
            "description": "schema check",
            "entities": entities,
        },
        sort_keys=False,
    )
)
