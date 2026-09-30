"""Secret storage in the OS keyring (Keychain / Credential Manager / Secret Service)."""

from __future__ import annotations

import keyring

SERVICE = "cuecal"


def get_secret(ref: str) -> str | None:
    return keyring.get_password(SERVICE, ref)


def set_secret(ref: str, value: str) -> None:
    keyring.set_password(SERVICE, ref, value)


def delete_secret(ref: str) -> None:
    try:
        keyring.delete_password(SERVICE, ref)
    except keyring.errors.PasswordDeleteError:
        pass


def backend_name() -> str:
    backend = keyring.get_keyring()
    return f"{type(backend).__module__}.{type(backend).__name__}"
