#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""Configuration service — profile management, hub-catalog loading, downloads.

No ``click`` / ``rich_click`` imports.  Errors are raised as
:class:`~ewccli.services.exceptions.ConfigServiceError` so that CLI
wrappers can translate them back to click exceptions.
"""

import os
import base64
import subprocess
import secrets
import string
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Tuple, IO, List, Dict

import requests
import yaml
from configparser import ConfigParser

from ewccli.enums import Federee
from ewccli.configuration import config as ewc_hub_config
from ewccli.logger import get_logger
from ewccli.services.exceptions import ConfigServiceError

_LOGGER = get_logger(__name__)


class ConfigService:
    """Pure business logic for configuration, profiles, and downloads."""

    # ------------------------------------------------------------------ #
    # Profile helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def resolve_profile(
        profile: Optional[str] = None,
        federee: Optional[str] = None,
        region: Optional[str] = None,
        tenant_name: Optional[str] = None,
    ) -> str:
        """Return explicit profile or auto-generate one using federee-tenant."""
        if profile is not None:
            return profile

        if not federee or not region or not tenant_name:
            raise ConfigServiceError(
                "Either 'profile' must be provided or all of "
                "'federee', 'region', and 'tenant_name'."
            )

        return f"{federee.lower()}-{region.lower()}-{tenant_name.lower()}"

    @staticmethod
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
        resolved_profile = ConfigService.resolve_profile(
            profile=ewc_hub_config.EWC_CLI_DEFAULT_PROFILE_NAME,
        )

        cfg = ConfigParser()
        cfg.read(profiles_file_path)

        if resolved_profile in cfg:
            return

        ConfigService.save_cli_profile(
            federee=federee,
            region=region,
            tenant_name=tenant_name,
            ssh_private_key_path_to_save=ssh_private_key_path_to_save,
            ssh_public_key_path_to_save=ssh_public_key_path_to_save,
            profile=resolved_profile,
            token=token,
            application_credential_id=application_credential_id,
            application_credential_secret=application_credential_secret,
            profiles_file_path=profiles_file_path,
        )

    @staticmethod
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
        resolved_profile = ConfigService.resolve_profile(
            profile, federee, region, tenant_name
        )
        cfg = ConfigParser()
        cfg.read(profiles_file_path)

        if resolved_profile in cfg:
            raise ConfigServiceError(
                f"Profile '{resolved_profile}' already exists in "
                f"{profiles_file_path}. Use a different profile name or "
                "delete the existing profile first."
            )

        cfg[resolved_profile] = {}
        cfg[resolved_profile]["federee"] = federee
        cfg[resolved_profile]["region"] = region
        cfg[resolved_profile]["tenant_name"] = tenant_name
        cfg[resolved_profile]["ssh_public_key_path"] = ssh_public_key_path_to_save
        cfg[resolved_profile]["ssh_private_key_path"] = ssh_private_key_path_to_save

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

    @staticmethod
    def load_cli_profile(
        profile: Optional[str] = None,
        federee: Optional[str] = None,
        tenant_name: Optional[str] = None,
        profiles_file_path: Path = ewc_hub_config.EWC_CLI_PROFILES_PATH,
        dry_run: bool = False,
    ) -> Dict[str, Optional[str]]:
        """Load all profile data from the profiles file."""
        if dry_run:
            return {
                "profile": "dry-run",
                "federee": "EUMETSAT",
                "region": "ECIS-R1",
                "tenant_name": "internal-ewc-admins",
                "ssh_public_key_path": "/tmp/id_rsa.pub",
                "ssh_private_key_path": "/tmp/id_rsa",
                "token": None,
                "application_credential_id": "",
                "application_credential_secret": "",
            }

        if profile is None:
            if not federee or not tenant_name:
                raise ConfigServiceError(
                    "Either 'profile' must be provided or both "
                    "'federee' and 'tenant_name'."
                )
            profile = ConfigService.resolve_profile(profile, federee, tenant_name)

        cfg = ConfigParser()
        cfg.read(profiles_file_path)

        if not os.path.exists(profiles_file_path) or not cfg.sections():
            raise ConfigServiceError(
                f"No profiles found. Searched in: {profiles_file_path}. "
                "Please run 'ewc login' first to create a profile."
            )

        default_profile = ewc_hub_config.EWC_CLI_DEFAULT_PROFILE_NAME

        if profile and profile not in cfg:
            available = ", ".join(cfg.sections())
            if profile != default_profile:
                msg = (
                    f"Profile '{profile}' not found. "
                    f"Searched in: {profiles_file_path}. "
                    f"Available profiles: {available}."
                )
            else:
                msg = (
                    f"The default profile does not exist. "
                    f"Available profiles: {available}. "
                    "Run 'ewc login' to create the default profile."
                )
            raise ConfigServiceError(msg)

        section = cfg[profile]

        federee_val = section.get("federee")
        allowed_federees = [r.value for r in Federee]
        if federee_val not in allowed_federees:
            raise ConfigServiceError(
                f"`{federee_val}` federee not supported. Check your profiles "
                f"in ~/.ewccli/profiles. Please use one from: {allowed_federees}"
            )

        region_val = section.get("region")
        allowed_regions = ewc_hub_config.allowed_regions(federee_val)
        if not region_val:
            raise ConfigServiceError(
                "Since ewccli v0.4.0 `region` is mandatory into a profile. "
                f"Check your profiles in ~/.ewccli/profiles and add region key "
                f"with allowed values: {allowed_regions} for {federee_val}."
            )

        ssh_public_key_path = section.get("ssh_public_key_path")
        if not ssh_public_key_path:
            raise ConfigServiceError(
                "Since ewccli v0.3.0 `ssh_public_key_path` is mandatory. "
                f"`ssh_public_key_path` key is missing from profile {profile}."
            )

        ssh_private_key_path = section.get("ssh_private_key_path")
        if not ssh_private_key_path:
            raise ConfigServiceError(
                "Since ewccli v0.3.0 `ssh_private_key_path` is mandatory. "
                f"`ssh_private_key_path` key is missing from profile {profile}."
            )

        return {
            "profile": profile,
            "federee": federee_val,
            "region": section.get("region"),
            "tenant_name": section.get("tenant_name"),
            "ssh_public_key_path": ssh_public_key_path,
            "ssh_private_key_path": ssh_private_key_path,
            "token": section.get("token"),
            "application_credential_id": section.get("application_credential_id"),
            "application_credential_secret": section.get("application_credential_secret"),
        }

    # ------------------------------------------------------------------ #
    # Hub catalog
    # ------------------------------------------------------------------ #

    @staticmethod
    def load_hub_items(
        path_to_catalog: str = ewc_hub_config.EWC_CLI_HUB_ITEMS_PATH,
    ) -> dict:
        """Load EWC Hub Items from file."""
        ConfigService.download_items()
        with open(path_to_catalog, "r") as file:
            items_file = yaml.safe_load(file)

            if not items_file:
                raise ConfigServiceError("items.yaml is empty.")

            items_spec = items_file.get("spec")
            if not items_spec:
                raise ConfigServiceError("spec key is missing from items.yaml.")

            items = items_spec.get("items")
            if not items:
                raise ConfigServiceError(
                    "items key is missing from spec key in items.yaml."
                )

            return items

    @staticmethod
    def split_config_name(config_name: str) -> tuple[str, str]:
        """Split config_name into federee and tenant_name."""
        parts = config_name.split("-")
        if len(parts) != 4:
            raise ValueError(
                "config_name must have exactly 4 parts separated by '-'"
            )
        federee = parts[0]
        tenant_name = "-".join(parts[1:])
        return federee, tenant_name

    @staticmethod
    def validate_config_name(value: str) -> str:
        """Validate config name format."""
        if not value:
            return value

        import re

        pattern = r"^[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+$"
        if not re.match(pattern, value):
            raise ConfigServiceError(
                "Config name must be exactly 4 alphanumeric parts separated by "
                "dashes (e.g. tenant-federee-east-zone)."
            )
        return value

    # ------------------------------------------------------------------ #
    # Downloads and command execution
    # ------------------------------------------------------------------ #

    @staticmethod
    def download_items(force: bool = False):
        """Download items for the community hub."""
        url = ewc_hub_config.EWC_CLI_HUB_ITEMS_URL
        config_dir = ewc_hub_config.EWC_CLI_BASE_PATH
        config_dir.mkdir(parents=True, exist_ok=True)
        item_file = ewc_hub_config.EWC_CLI_HUB_ITEMS_PATH

        if item_file.exists() and not force:
            _LOGGER.debug(
                f"Items file already exist at {item_file}. Skipping download."
            )
            return

        if force:
            _LOGGER.debug(
                f"Items file already exist at {item_file}. "
                "Force enabled, redownloading it."
            )

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            item_file.write_text(response.text)
            _LOGGER.debug(f"Downloaded to: {item_file}")
        except requests.Timeout:
            _LOGGER.error("Request timed out.")
        except requests.RequestException as e:
            _LOGGER.error(f"Failed to download file: {e}")

    @staticmethod
    def generate_random_id(length: int = 10):
        """Generate random ID."""
        characters = string.ascii_letters + string.digits
        random_part = "".join(secrets.choice(characters) for _ in range(length))
        date_part = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        return f"{date_part}-{random_part}"

    @staticmethod
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
            '"%s" -> exec command "%s" with timeout %s',
            description,
            command,
            timeout,
        )

        if dry_run:
            return 0, "Dry run. No actions."

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                shell=True,
                check=True,
                cwd=cwd,
                env=env,
            )
            message = ""
            if result.stdout:
                message = f"STDOUT:\n{result.stdout.strip()}"
            return result.returncode, message

        except subprocess.CalledProcessError as e:
            error_message = ""
            if e.stderr:
                error_message = f"STDERR:\n{e.stderr.strip()}"
            return e.returncode, error_message

    @staticmethod
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
            '"%s" -> exec command "%s" with timeout %s',
            description,
            command,
            timeout,
        )

        if dry_run:
            return 0, "Dry run. No actions."

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
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
