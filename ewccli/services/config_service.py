"""Configuration and profile management service.

Handles CLI profile loading/saving, hub-catalog loading, and config-name parsing.
No click / rich_click imports.
"""

import os
import sys
from pathlib import Path
from typing import Optional, Dict
from configparser import ConfigParser

import yaml
import requests

from ewccli.configuration import config as ewc_hub_config
from ewccli.enums import Federee
from ewccli.logger import get_logger
from ewccli.services.exceptions import ConfigError

_LOGGER = get_logger(__name__)


class ConfigService:
    """Manage EWC CLI profiles, hub catalog, and configuration helpers."""

    def __init__(self, profiles_path: Path = None, hub_items_path: Path = None):
        self._profiles_path = profiles_path or ewc_hub_config.EWC_CLI_PROFILES_PATH
        self._hub_items_path = hub_items_path or ewc_hub_config.EWC_CLI_HUB_ITEMS_PATH

    # ------------------------------------------------------------------ #
    # Profile name resolution
    # ------------------------------------------------------------------ #
    @staticmethod
    def resolve_profile(
        profile: Optional[str] = None,
        federee: Optional[str] = None,
        region: Optional[str] = None,
        tenant_name: Optional[str] = None,
    ) -> str:
        """Return explicit profile or auto-generate one using federee-region-tenant."""
        if profile is not None:
            return profile

        if not federee or not region or not tenant_name:
            raise ConfigError(
                "Either 'profile' must be provided or all of 'federee', "
                "'region', and 'tenant_name'."
            )

        return f"{federee.lower()}-{region.lower()}-{tenant_name.lower()}"

    # ------------------------------------------------------------------ #
    # Profile save
    # ------------------------------------------------------------------ #
    def save_cli_profile(
        self,
        federee: str,
        region: str,
        tenant_name: str,
        ssh_private_key_path_to_save: str,
        ssh_public_key_path_to_save: str,
        profile: Optional[str] = None,
        token: Optional[str] = None,
        application_credential_id: Optional[str] = None,
        application_credential_secret: Optional[str] = None,
        profiles_file_path: Path = None,
    ) -> None:
        """Save all profile data into the profiles file."""
        resolved_profile = self.resolve_profile(
            profile, federee, region, tenant_name
        )
        target_path = profiles_file_path or self._profiles_path

        cfg = ConfigParser()
        cfg.read(target_path)

        if resolved_profile in cfg:
            raise ConfigError(
                f"Profile '{resolved_profile}' already exists in {target_path}. "
                "Use a different profile name or delete the existing profile first."
            )

        cfg[resolved_profile] = {}
        cfg[resolved_profile]["federee"] = federee
        cfg[resolved_profile]["region"] = region
        cfg[resolved_profile]["tenant_name"] = tenant_name
        cfg[resolved_profile]["ssh_private_key_path"] = ssh_private_key_path_to_save
        cfg[resolved_profile]["ssh_public_key_path"] = ssh_public_key_path_to_save

        if application_credential_id:
            cfg[resolved_profile]["application_credential_id"] = application_credential_id
        if application_credential_secret:
            cfg[resolved_profile]["application_credential_secret"] = application_credential_secret
        if token:
            cfg[resolved_profile]["token"] = token

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w") as f:
            cfg.write(f)

    def save_default_login_profile(
        self,
        federee: str,
        region: str,
        tenant_name: str,
        ssh_private_key_path_to_save: str,
        ssh_public_key_path_to_save: str,
        application_credential_id: Optional[str] = None,
        application_credential_secret: Optional[str] = None,
        token: Optional[str] = None,
        profiles_file_path: Path = None,
    ) -> None:
        """Save the default login profile if it does not already exist."""
        target_path = profiles_file_path or self._profiles_path
        resolved_profile = self.resolve_profile(
            profile=ewc_hub_config.EWC_CLI_DEFAULT_PROFILE_NAME,
        )

        cfg = ConfigParser()
        cfg.read(target_path)

        if resolved_profile in cfg:
            return

        self.save_cli_profile(
            federee=federee,
            region=region,
            tenant_name=tenant_name,
            ssh_private_key_path_to_save=ssh_private_key_path_to_save,
            ssh_public_key_path_to_save=ssh_public_key_path_to_save,
            profile=resolved_profile,
            token=token,
            application_credential_id=application_credential_id,
            application_credential_secret=application_credential_secret,
            profiles_file_path=target_path,
        )

    # ------------------------------------------------------------------ #
    # Profile load
    # ------------------------------------------------------------------ #
    def load_cli_profile(
        self,
        profile: Optional[str] = None,
        federee: Optional[str] = None,
        tenant_name: Optional[str] = None,
        profiles_file_path: Path = None,
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

        target_path = profiles_file_path or self._profiles_path

        if profile is None:
            if not federee or not tenant_name:
                raise ConfigError(
                    "Either 'profile' must be provided or both "
                    "'federee' and 'tenant_name'."
                )
            profile = self.resolve_profile(profile, federee, tenant_name)

        cfg = ConfigParser()
        cfg.read(target_path)

        if not os.path.exists(target_path) or not cfg.sections():
            raise ConfigError(
                f"No profiles found. Searched in: {target_path}. "
                "Please run 'ewc login' first to create a profile."
            )

        default_profile = ewc_hub_config.EWC_CLI_DEFAULT_PROFILE_NAME

        if profile and profile not in cfg:
            available = cfg.sections()
            hint = ""
            if available:
                hint = f" Available profiles: {', '.join(available)}."
                if default_profile in cfg:
                    hint += " You can use the default without --profile."
                hint += " Or run 'ewc login' to create a new profile."
            raise ConfigError(
                f"Profile '{profile}' not found in {target_path}.{hint}"
            )

        section = cfg[profile]

        federee_val = section.get("federee")

        allowed_federees = [r.value for r in Federee]
        if federee_val not in allowed_federees:
            raise ConfigError(
                f"`{federee_val}` federee not supported. "
                f"Please use one from: {allowed_federees}"
            )

        region = section.get("region")
        allowed_regions = ewc_hub_config.allowed_regions(federee_val)
        if not region:
            raise ConfigError(
                "Since ewccli v0.4.0 `region` is mandatory into a profile. "
                f"Allowed values: {allowed_regions} for {federee_val}."
            )

        ssh_public_key_path = section.get("ssh_public_key_path")
        if not ssh_public_key_path:
            raise ConfigError(
                f"`ssh_public_key_path` key is missing from profile {profile}."
            )

        ssh_private_key_path = section.get("ssh_private_key_path")
        if not ssh_private_key_path:
            raise ConfigError(
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
    def download_items(self, force: bool = False) -> None:
        """Download the community-hub items YAML from the remote URL."""
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
            _LOGGER.error("Items download request timed out.")
        except requests.RequestException as e:
            _LOGGER.error(f"Failed to download items file: {e}")

    def load_hub_items(self, path_to_catalog: str = None) -> dict:
        """Load EWC Hub Items from the catalog YAML file."""
        self.download_items()

        catalog_path = path_to_catalog or self._hub_items_path

        with open(catalog_path, "r") as file:
            items_file = yaml.safe_load(file)

            if not items_file:
                raise ConfigError("items.yaml is empty.")

            items_spec = items_file.get("spec")

            if not items_spec:
                raise ConfigError("spec key is missing from items.yaml.")

            items = items_spec.get("items")

            if not items:
                raise ConfigError(
                    "items key is missing from spec key in items.yaml."
                )

            return items

    # ------------------------------------------------------------------ #
    # Config name helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def split_config_name(config_name: str) -> tuple[str, str]:
        """Split config_name into federee and tenant_name.

        Assumes format: <federee>-<tenant-part1>-<tenant-part2>-<tenant-part3>
        """
        parts = config_name.split("-")
        if len(parts) != 4:
            raise ValueError(
                "config_name must have exactly 4 parts separated by '-'"
            )
        federee = parts[0]
        tenant_name = "-".join(parts[1:])
        return federee, tenant_name
