"""Platform config and data locations. Env vars override for tests and portable installs."""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_config_path, user_data_path, user_log_path

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


def log_dir() -> Path:
    override = os.environ.get("CUECAL_LOG_DIR")
    if override:
        return Path(override)
    return user_log_path(APP_NAME)


def launchd_plist_path() -> Path:
    override = os.environ.get("CUECAL_LAUNCHD_PLIST")
    if override:
        return Path(override)
    return Path.home() / "Library" / "LaunchAgents" / "com.cuecal.agent.plist"


def lock_path() -> Path:
    override = os.environ.get("CUECAL_LOCK_PATH")
    if override:
        return Path(override)
    return user_data_path(APP_NAME) / "cuecal.lock"
