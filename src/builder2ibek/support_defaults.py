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
# {entity_type: {param_name, ...}}
_params: dict[str, set[str]] = {}
# {entity_type: {param_name: param_spec}}
_param_specs: dict[str, dict[str, dict[str, Any]]] = {}


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
                _params[entity_type] = set(params)
                _param_specs[entity_type] = {
                    k: v for k, v in params.items() if isinstance(v, dict)
                }
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


def entity_params(entity_type: str) -> set[str] | None:
    """The parameter names of an entity model, or None if no model is found."""
    return _params.get(entity_type)


def entity_defaults(entity_type: str) -> dict[str, Any]:
    """The defaults of an entity model's parameters, by name; {} if none."""
    return _defaults.get(entity_type, {})


def empty_attribute(entity_type: str, param: str) -> Any:
    """
    The value for a parameter whose XML attribute is empty, as the builder
    treated it (iocbuilder includeXml.constructArgDict): a str argument is
    passed on as "", a bool one is False, and int and float ones fail to
    convert, so no working IOC passes them empty. None (use the model's
    default) for a parameter the model does not take as "", or does not have,
    or when there is no model to say.
    """
    spec = _param_specs.get(entity_type, {}).get(param)
    if spec is None:
        return None
    typ = spec.get("type")
    if typ == "str":
        return ""
    if typ == "bool":
        return False
    if typ == "enum" and "" in (spec.get("values") or {}):
        return ""
    return None


def fill_empty_attributes(entity: dict[str, Any]):
    """Give each empty XML attribute of entity the value the builder used"""
    entity_type = str(entity.get("type", ""))
    for key, value in list(entity.items()):
        if value == "" and key != "type":
            entity[key] = empty_attribute(entity_type, key)


def values_match(entity_val: Any, default_val: Any) -> bool:
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
        if param_name in entity and values_match(entity[param_name], default_val):
            del entity[param_name]


# Load at import time
_load_all_support_yamls()
