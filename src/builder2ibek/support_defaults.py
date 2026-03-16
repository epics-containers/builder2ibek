"""
Load defaults from ibek support YAML files so we can omit parameters
whose values match the defaults during conversion.
"""

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

_project_root = Path(__file__).parent.parent.parent

# {entity_type: {param_name: default_value}}
_defaults: dict[str, dict[str, Any]] = {}


def _load_all_support_yamls():
    """Load all support YAML files from ibek-support/ and ibek-support-dls/."""
    yml = YAML(typ="safe", pure=True)

    for base_dir in _project_root.glob("ibek-support*"):
        for yaml_file in base_dir.glob("*/*.ibek.support.yaml"):
            try:
                data = yml.load(yaml_file.read_text())
            except Exception:
                continue
            if not data:
                continue

            module_name = data.get("module", "")
            for model in data.get("entity_models", []):
                entity_name = model.get("name", "")
                if not entity_name:
                    continue
                entity_type = f"{module_name}.{entity_name}"
                params = model.get("parameters", {})
                defaults = {}
                for param_name, param_spec in params.items():
                    if isinstance(param_spec, dict) and "default" in param_spec:
                        default_val = param_spec["default"]
                        # Skip Jinja2 template defaults — they're dynamic
                        if isinstance(default_val, str) and "{{" in default_val:
                            continue
                        defaults[param_name] = default_val
                if defaults:
                    _defaults[entity_type] = defaults


def _values_match(entity_val: Any, default_val: Any) -> bool:
    """Compare entity value to default, with numeric type tolerance."""
    if entity_val == default_val:
        return True
    # Numeric comparison: 0 == 0.0, 1 == 1.0, etc.
    if isinstance(entity_val, (int, float)) and isinstance(default_val, (int, float)):
        return float(entity_val) == float(default_val)
    return False


def strip_defaults(entity: dict[str, Any]):
    """Remove parameters from entity whose values match the support YAML defaults."""
    entity_type = entity.get("type", "")
    defaults = _defaults.get(entity_type)
    if not defaults:
        return

    for param_name, default_val in defaults.items():
        if param_name in entity and _values_match(entity[param_name], default_val):
            del entity[param_name]


# Load at import time
_load_all_support_yamls()
