#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details


"""Utils."""

import os
import base64
import sys
import subprocess
from pathlib import Path
import secrets
import string
from datetime import datetime, timezone
from typing import Optional, Tuple, IO, List, Dict

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from configparser import ConfigParser

import rich_click as click
from click import ClickException

from ewccli.enums import Federee
from ewccli.configuration import config as ewc_hub_config
from ewccli.logger import get_logger
from ewccli.services.config_service import ConfigService
from ewccli.services.keypair_service import KeyPairService
from ewccli.services.exceptions import ConfigError, KeyPairError

_LOGGER = get_logger(__name__)

_config_service = ConfigService()
_keypair_service = KeyPairService()


def _resolve_profile(
    profile: Optional[str] = None,
    federee: Optional[str] = None,
    region: Optional[str] = None,
    tenant_name: Optional[str] = None,
) -> str:
    """Return explicit profile or auto-generate one using federee-tenant."""
    try:
        return _config_service.resolve_profile(
            profile=profile,
            federee=federee,
            region=region,
            tenant_name=tenant_name,
        )
    except ConfigError as e:
        click.secho(f"❌ {e}", fg="red", bold=True)
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
    """Save the default login profile if it does not already exist."""
    _config_service.save_default_login_profile(
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
    """
    Save all profile data (config + credentials) into a single profiles file.

    Parameters
    ----------
    federee : str
        Federee name.
    region : str
        Region in the specific federee.
    tenant_name : str
        Tenant name.
    ssh_private_key_path_to_save: str
        SSH private key path
    ssh_public_key_path_to_save: str
        SSH public key path
    profile : str, optional
        Explicit profile name. If None, auto-generated using federee-tenant.
    token : str, optional
        Authentication token.
    application_credential_id : str, optional
        Application credential ID.
    application_credential_secret : str, optional
        Application credential secret.
    """
    resolved_profile = _resolve_profile(profile, federee, region, tenant_name)
    cfg = ConfigParser()
    cfg.read(profiles_file_path)

    # Fail if profile exists
    if resolved_profile in cfg:
        click.secho(
            f"❌ Profile '{resolved_profile}' already exists in {profiles_file_path}",
            fg="red",
            bold=True,
        )
        click.secho(
            "Use a different profile name or delete the existing profile first.",
            fg="yellow",
        )
        raise click.Abort()

    # --- Save profile data
    cfg[resolved_profile] = {}

    # Non-sensitive
    cfg[resolved_profile]["federee"] = federee
    cfg[resolved_profile]["region"] = region
    cfg[resolved_profile]["tenant_name"] = tenant_name
    cfg[resolved_profile]["ssh_public_key_path"] = ssh_public_key_path_to_save
    cfg[resolved_profile]["ssh_private_key_path"] = ssh_private_key_path_to_save

    # Sensitive
    if token:
        cfg[resolved_profile]["token"] = token

    if application_credential_id:
        cfg[resolved_profile]["application_credential_id"] = application_credential_id

    if application_credential_secret:
        cfg[resolved_profile][
            "application_credential_secret"
        ] = application_credential_secret

    os.makedirs(os.path.dirname(profiles_file_path), exist_ok=True)
    with open(profiles_file_path, "w") as f:
        cfg.write(f)


def load_cli_profile(
    profile: Optional[str] = None,
    federee: Optional[str] = None,
    tenant_name: Optional[str] = None,
    profiles_file_path: Path = ewc_hub_config.EWC_CLI_PROFILES_PATH,
    dry_run: bool = False
) -> Dict[str, Optional[str]]:
    """Load all profile data from the profiles file."""
    try:
        return _config_service.load_cli_profile(
            profile=profile,
            federee=federee,
            tenant_name=tenant_name,
            profiles_file_path=profiles_file_path,
            dry_run=dry_run,
        )
    except ConfigError as e:
        click.secho(f"❌ {e}", fg="red", bold=True)
        raise click.Abort()


def generate_random_id(length: int = 10):
    """Generate random ID."""
    characters = string.ascii_letters + string.digits
    random_part = "".join(secrets.choice(characters) for _ in range(length))
    date_part = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{date_part}-{random_part}"


def run_command_from_host(
    description: str,
    command: List[str],
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    dry_run: bool = False,
) -> Tuple[int, str]:
    """Run command with subprocess."""
    _LOGGER.debug(
        '"%s" -> exec command "%s" with timeout %s', description, command, timeout
    )

    if dry_run:
        return 0, "Dry run. No actions."

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,  # The output is decoded to a string
            shell=True,
            check=True,  # raise CalledProcessError if non-zero exit code
            cwd=cwd,
            env=env,
        )
        message = ""
        if result.stdout:
            message = f"📤 STDOUT:\n{result.stdout.strip()}"
        return result.returncode, message

    except subprocess.CalledProcessError as e:
        error_message = ""
        if e.stderr:
            error_message = f"📥 STDERR:\n{e.stderr.strip()}"
        return e.returncode, error_message


def run_command_from_host_live(
    description: str,
    command: str,
    timeout: Optional[str] = None,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    dry_run: bool = False,
):
    """Run a shell command, streaming output live to the terminal."""
    _LOGGER.info(
        '"%s" -> exec command "%s" with timeout %s', description, command, timeout
    )

    if dry_run:
        return 0, "Dry run. No actions."

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,  # for automatic decoding (Python 3.7+)
            bufsize=1,  # line-buffered
            cwd=cwd,
            env=env,
            shell=True,
        )
    except Exception as e:
        return 1, f"Failed to start process: {e}"

    def read_first_line(file: Optional[IO[str]]) -> Optional[str]:
        if file is None:
            return None
        return file.readline()

    try:
        while True:
            line = read_first_line(process.stdout)
            if line == "" and process.poll() is not None:
                break
            if line:
                _LOGGER.info(line, end="")

        return process.wait(), "Finishes successfully"

    except Exception as e:
        process.kill()
        return 1, f"\nError running command: {e}"


def download_items(force: bool = False):
    """Download items for the community hub."""
    _config_service.download_items(force=force)


def load_ssh_private_key(encoded_key: Optional[str] = None):
    """Load SSH private key"""
    result = _keypair_service.load_ssh_private_key(encoded_key=encoded_key)
    if result is None and encoded_key is None:
        sys.exit(1)
    return result


def load_ssh_public_key(encoded_key: Optional[str] = None):
    """Load SSH public key from a base64-encoded string."""
    result = _keypair_service.load_ssh_public_key(encoded_key=encoded_key)
    if result is None and encoded_key is None:
        sys.exit(1)
    return result


def verify_private_key(private_key: str):
    """Verify SSH private key using cryptography."""
    try:
        _keypair_service.verify_private_key(private_key=private_key)
    except KeyPairError as e:
        _LOGGER.error(str(e))
        sys.exit(1)


def check_ssh_keys_match(ssh_private_key_path: str, ssh_public_key_path: str) -> bool:
    """Check whether an SSH private key corresponds to a given public key."""
    return _keypair_service.check_ssh_keys_match(
        ssh_private_key_path=ssh_private_key_path,
        ssh_public_key_path=ssh_public_key_path,
    )


def save_ssh_key(ssh_key, path_key):
    """Store SSH key to the provided path."""
    _keypair_service.save_ssh_key(ssh_key=ssh_key, path_key=path_key)


def save_encoded_ssh_keys(
    ssh_public_key_path: str,
    ssh_private_key_path: str,
    ssh_public_encoded: Optional[str] = None,
    ssh_private_encoded: Optional[str] = None,
):
    """Store SSH keys provided as encoded strings."""
    return _keypair_service.save_encoded_ssh_keys(
        ssh_public_key_path=ssh_public_key_path,
        ssh_private_key_path=ssh_private_key_path,
        ssh_public_encoded=ssh_public_encoded,
        ssh_private_encoded=ssh_private_encoded,
    )


def generate_ssh_keypair(
    resolved_profile: str
) -> Tuple[str, str]:
    """Generate RSA SSH Key Pair and save to ~/.ssh"""
    return _keypair_service.generate_ssh_keypair(resolved_profile=resolved_profile)
