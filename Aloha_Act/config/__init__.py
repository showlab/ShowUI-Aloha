import os
import yaml


DEFAULT_CONFIG = {
    "cache_dir": "./.cache",
    "log_dir": "./logs",
    "llm_model": "gpt-5",
    "os_name": "windows",
}

def load_config(config_path: str | None = None) -> dict:
    """Load YAML config with safe loader, defaults, and env overrides.

    Order of precedence (low → high): DEFAULT_CONFIG < YAML file < environment vars.
    """
    cfg = dict(DEFAULT_CONFIG)

    # Load from YAML if available
    with open(config_path, "r") as f:
        file_cfg = yaml.safe_load(f) or {}
    if isinstance(file_cfg, dict):
        cfg.update(file_cfg)

    return cfg


config = load_config("./config/config.yaml")