#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details


"""Utils — thin wrappers that delegate to the service layer.

CLI-specific exception translation (``click.Abort``, ``sys.exit``)
happens here so that the service modules remain free of
``click`` / ``rich_click`` imports.
"""

import os
import sys
from pathlib import Path
from typing import Optional, Tuple, List, IO

import rich_click as click
from click import ClickException

from ewccli.enums import Federee
from ewccli.configuration import config as ewc_hub_config
from ewccli.logger import get_logger
from ewccli.services.config_service import ConfigService
from ewccli.services.keypair_service import KeyPairService
from ewccli.services.exceptions import ConfigServiceError, KeyPairServiceError

_LOGGER = get_logger(__name__)


# ---------------------------------------------------------------------------
# Config / profile wrappers
# ---------------------------------------------------------------------------

def _resolve_profile(
    profile: Optional[str] = None,
    federee: Optional[str] = None,
    region: Optional[str] = None,
    tenant_name: Optional[str] = None,
) -> str:
    """Return explicit profile or auto-generate one using federee-tenant."""
    try:
        return ConfigService.resolve_profile(
            profile=profile,
            federee=federee,
            region=region,
            tenant_name=tenant_name,
        )
    except ConfigServiceError:
        raise click.Abort()


def save_default_login_profile(
    federee: str,
    region: str,
    tenant_name: str,
    ssh_private_key_path_to_save: str,
    ssh_public_key_path_to_save: str,
    application_credential_id: Optional[str] = None,
    application_credential_secret: Optional[str] = None,
    token: Optional[str] = None,
    profiles_file_path: Path = ewc_hub_config.EWC_CLI_PROFILES_PATH,
) -> None:
    """Save the default login profile only if it does not exist."""
    ConfigService.save_default_login_profile(
        federee=federee,
        region=region,
        tenant_name=tenant_name,
        ssh_private_key_path_to_save=ssh_private_key_path_to_save,
        ssh_public_key_path_to_save=ssh_public_key_path_to_save,
        application_credential_id=application_credential_id,
        application_credential_secret=application_credential_secret,
        token=token,
        profiles_file_path=profiles_file_path,
    )


def save_cli_profile(
    federee: str,
    region: str,
    tenant_name: str,
    ssh_private_key_path_to_save: str,
    ssh_public_key_path_to_save: str,
    profile: Optional[str] = None,
    token: Optional[str] = None,
    application_credential_id: Optional[str] = None,
    application_credential_secret: Optional[str] = None,
    profiles_file_path: Path = ewc_hub_config.EWC_CLI_PROFILES_PATH,
) -> None:
    """Save all profile data into a single profiles file."""
    try:
        ConfigService.save_cli_profile(
            federee=federee,
            region=region,
            tenant_name=tenant_name,
            ssh_private_key_path_to_save=ssh_private_key_path_to_save,
            ssh_public_key_path_to_save=ssh_public_key_path_to_save,
            profile=profile,
            token=token,
            application_credential_id=application_credential_id,
            application_credential_secret=application_credential_secret,
            profiles_file_path=profiles_file_path,
        )
    except ConfigServiceError as e:
        click.secho(f"❌ {e}", fg="red", bold=True)
        raise click.Abort()


def load_cli_profile(
    profile: Optional[str] = None,
    federee: Optional[str] = None,
    tenant_name: Optional[str] = None,
    profiles_file_path: Path = ewc_hub_config.EWC_CLI_PROFILES_PATH,
    dry_run: bool = False,
):
    """Load all profile data from the profiles file."""
    try:
        return ConfigService.load_cli_profile(
            profile=profile,
            federee=federee,
            tenant_name=tenant_name,
            profiles_file_path=profiles_file_path,
            dry_run=dry_run,
        )
    except ConfigServiceError as e:
        click.secho(f"❌ {e}", fg="red", bold=True)
        raise click.Abort()


# ---------------------------------------------------------------------------
# Hub catalog / download wrappers
# ---------------------------------------------------------------------------

def download_items(force: bool = False):
    """Download items for the community hub."""
    ConfigService.download_items(force=force)


def generate_random_id(length: int = 10):
    """Generate random ID."""
    return ConfigService.generate_random_id(length=length)


def run_command_from_host(
    description: str,
    command: List[str],
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    dry_run: bool = False,
) -> Tuple[int, str]:
    """Run command with subprocess."""
    return ConfigService.run_command_from_host(
        description=description,
        command=command,
        timeout=timeout,
        cwd=cwd,
        env=env,
        dry_run=dry_run,
    )


def run_command_from_host_live(
    description: str,
    command: str,
    timeout: Optional[str] = None,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    dry_run: bool = False,
):
    """Run a shell command, streaming output live to the terminal."""
    return ConfigService.run_command_from_host_live(
        description=description,
        command=command,
        timeout=timeout,
        cwd=cwd,
        env=env,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# SSH key-pair wrappers
# ---------------------------------------------------------------------------

def load_ssh_private_key(encoded_key: Optional[str] = None):
    """Load SSH private key from a base64-encoded string."""
    try:
        return KeyPairService.load_ssh_private_key(encoded_key=encoded_key)
    except KeyPairServiceError as e:
        _LOGGER.error(str(e))
        sys.exit(1)


def load_ssh_public_key(encoded_key: Optional[str] = None):
    """Load SSH public key from a base64-encoded string."""
    try:
        return KeyPairService.load_ssh_public_key(encoded_key=encoded_key)
    except KeyPairServiceError as e:
        _LOGGER.error(str(e))
        sys.exit(1)


def verify_private_key(private_key: str):
    """Verify SSH private key using cryptography."""
    try:
        KeyPairService.verify_private_key(private_key=private_key)
    except KeyPairServiceError as e:
        _LOGGER.error(str(e))
        sys.exit(1)


def check_ssh_keys_match(ssh_private_key_path: str, ssh_public_key_path: str) -> bool:
    """Check whether a private key corresponds to a given public key."""
    return KeyPairService.check_ssh_keys_match(
        ssh_private_key_path=ssh_private_key_path,
        ssh_public_key_path=ssh_public_key_path,
    )


def save_ssh_key(ssh_key, path_key):
    """Store SSH key to the provided path."""
    KeyPairService.save_ssh_key(ssh_key=ssh_key, path_key=path_key)


def save_encoded_ssh_keys(
    ssh_public_key_path: str,
    ssh_private_key_path: str,
    ssh_public_encoded: Optional[str] = None,
    ssh_private_encoded: Optional[str] = None,
):
    """Store SSH keys provided as encoded strings."""
    return KeyPairService.save_encoded_ssh_keys(
        ssh_public_key_path=ssh_public_key_path,
        ssh_private_key_path=ssh_private_key_path,
        ssh_public_encoded=ssh_public_encoded,
        ssh_private_encoded=ssh_private_encoded,
    )


def generate_ssh_keypair(resolved_profile: str) -> Tuple[str, str]:
    """Generate RSA SSH Key Pair and save to ~/.ssh"""
    return KeyPairService.generate_ssh_keypair(resolved_profile=resolved_profile)
