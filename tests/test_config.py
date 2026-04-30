"""
Schema-shape tests for config.yaml.

The brief runner reads config.yaml at startup; these checks fail fast if a
hand-edit drops or renames a required key.
"""
from pathlib import Path

import yaml

from src import config as cfg


def test_config_loads():
    c = cfg.load_config()
    assert isinstance(c, dict)


def test_all_default_limits_resolve():
    c = cfg.load_config()
    for key in cfg.DEFAULTS["limits"]:
        val = cfg.get_limit(c, key)
        assert isinstance(val, int)
        assert val > 0


def test_confluence_spaces_is_list_of_strings():
    c = cfg.load_config()
    spaces = c.get("confluence", {}).get("spaces", [])
    assert isinstance(spaces, list)
    assert all(isinstance(s, str) and s for s in spaces)


def test_project_tracker_confluence_spaces_shape():
    c = cfg.load_config()
    space_configs = (
        c.get("google_sheets", {})
         .get("project_tracker", {})
         .get("confluence_spaces", [])
    )
    assert isinstance(space_configs, list)
    for sc in space_configs:
        assert "space" in sc and isinstance(sc["space"], str)
        # nesting_depth optional but must be int if present
        if "nesting_depth" in sc:
            assert isinstance(sc["nesting_depth"], int)
            assert sc["nesting_depth"] >= 0
        if "skip_first_table" in sc:
            assert isinstance(sc["skip_first_table"], bool)


def test_yaml_is_parseable():
    """Belt-and-suspenders: prove the file isn't malformed YAML."""
    path = Path(__file__).resolve().parent.parent / "config.yaml"
    with open(path) as f:
        yaml.safe_load(f)
