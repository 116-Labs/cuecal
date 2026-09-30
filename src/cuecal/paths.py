"""Platform config and data locations. Env vars override for tests and portable installs."""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_config_path, user_data_path

APP_NAME = "cuecal"


def config_path() -> Path:
    override = os.environ.get("CUECAL_CONFIG")
    if override:
        return Path(override)
    return user_config_path(APP_NAME) / "config.toml"


def db_path() -> Path:
    override = os.environ.get("CUECAL_DB")
    if override:
        return Path(override)
    return user_data_path(APP_NAME) / "state.db"
