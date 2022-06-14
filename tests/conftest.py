from pathlib import Path

from ibek.support import Support
from pytest import fixture
from ruamel.yaml import YAML


def get_support(samples: Path, yaml_file: str) -> Support:
    """
    Get a support object from the sample YAML directory
    """
    # load from file
    d = YAML(typ="safe").load(samples / "yaml" / f"{yaml_file}")
    # create a support object from that dict
    support = Support.deserialize(d)
    return support


@fixture
def samples():
    return Path(__file__).parent / "samples"
