"""
Centralized configuration loader for Intel Brief.
Loads config.yaml once, provides defaults for all tunable values,
and helper functions for common paths.
"""

import logging
import sys
from pathlib import Path

import yaml

_config_cache: dict | None = None

# ── Defaults for all tunable limits ──────────────────────────────────────────
DEFAULTS = {
    "lookback_hours": 24,
    "obsidian_vault_path": "~/Documents/chief_of_staff",
    "obsidian_output_folder": "Intel Briefs",
    "limits": {
        "jira_comment_depth": 3,
        "gmail_snippet_chars": 300,
        "confluence_body_chars": 1500,
        "confluence_project_chars": 8000,
        "raw_data_max_bytes": 150_000,
        "project_update_max_bytes": 100_000,
        "history_window_days": 3,
        "recurring_window_days": 5,
        "github_pr_body_chars": 500,
    },
}


def load_config(path: Path | None = None) -> dict:
    """Load and cache config.yaml. Subsequent calls return the cached copy."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    if path is None:
        path = Path(__file__).parent.parent / "config.yaml"
    with open(path) as f:
        _config_cache = yaml.safe_load(f)
    return _config_cache


def get_vault_path(config: dict) -> Path:
    """Resolve the Obsidian vault path from config, expanding ~."""
    return Path(config.get("obsidian_vault_path", DEFAULTS["obsidian_vault_path"])).expanduser()


def get_output_dir(config: dict) -> Path:
    """Resolve the brief output directory."""
    return get_vault_path(config) / config.get("obsidian_output_folder", DEFAULTS["obsidian_output_folder"])


def get_limit(config: dict, key: str) -> int:
    """Get a limit value from config, falling back to DEFAULTS."""
    return config.get("limits", {}).get(key, DEFAULTS["limits"][key])


# ── Logging setup ────────────────────────────────────────────────────────────

def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure and return the project-wide logger."""
    logger = logging.getLogger("intel_brief")
    if logger.handlers:
        return logger

    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("  %(message)s"))
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger


log = setup_logging()
