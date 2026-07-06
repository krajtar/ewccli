#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""SSH key-pair service — check, generate, validate, save.

No ``click`` / ``rich_click`` imports.  Errors are raised as
:class:`~ewccli.services.exceptions.KeyPairServiceError`.
"""

import os
import base64
import sys
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from rich.console import Console
from rich.panel import Panel

from ewccli.configuration import config as ewc_hub_config
from ewccli.logger import get_logger
from ewccli.services.exceptions import KeyPairServiceError

_LOGGER = get_logger(__name__)

_console = Console()


class KeyPairService:
    """Pure business logic for SSH key-pair management."""

    @staticmethod
    def check_ssh_keys_exist(
        ssh_public_key_path: Path, ssh_private_key_path: Path
    ) -> bool:
        """Verify that both SSH key files exist."""
        missing_msgs = []

        if not ssh_private_key_path.is_file():
            missing_msgs.append(
                f"Missing Private Key: {ssh_private_key_path}"
            )
        if not ssh_public_key_path.is_file():
            missing_msgs.append(
                f"Missing Public Key: {ssh_public_key_path}"
            )

        if missing_msgs:
            panel_content = (
                "\n".join(missing_msgs)
                + "\n\n"
                + "Tip: You can run ewc login and create them.\n"
                + "Tip: You can specify custom paths with:\n"
                + 'export EWC_CLI_SSH_PRIVATE_KEY_PATH="/path/to/id_rsa"\n'
                + 'export EWC_CLI_SSH_PUBLIC_KEY_PATH="/path/to/id_rsa.pub"'
            )
            _console.print(
                Panel(
                    panel_content,
                    title="SSH Key Check Failed",
                    style="red",
                    expand=False,
                )
            )
            return False

        return True

    @staticmethod
    def check_ssh_keys_match(
        ssh_private_key_path: str, ssh_public_key_path: str
    ) -> bool:
        """Check whether a private key corresponds to a public key."""
        for p in [ssh_private_key_path, ssh_public_key_path]:
            if not Path(p).expanduser().is_file():
                raise ValueError(f"SSH key file does not exist: {p}")

        with open(ssh_private_key_path, "rb") as f:
            private_data = f.read()

        private_key = None

        try:
            private_key = serialization.load_pem_private_key(private_data, password=None)
        except ValueError:
            try:
                private_key = serialization.load_ssh_private_key(
                    private_data, password=None
                )
            except ValueError:
                raise ValueError("Unsupported or invalid private key format")

        derived_public = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )

        with open(ssh_public_key_path, "r") as f:
            parts = f.read().strip().split()
            if len(parts) < 2:
                raise ValueError(f"Invalid public key format: {ssh_public_key_path}")
            provided_public = " ".join(parts[:2]).encode()

        return derived_public == provided_public

    @staticmethod
    def load_ssh_private_key(encoded_key: Optional[str] = None):
        """Load SSH private key from a base64-encoded string."""
        if encoded_key is None:
            raise KeyPairServiceError(
                "EWC_CLI_ENCODED_SSH_PRIVATE_KEY environment variable not set."
            )

        try:
            private_key = base64.b64decode(encoded_key).decode("utf-8")
            return private_key
        except Exception as e:
            _LOGGER.error(f"Error decoding private key: {e}")
            return None

    @staticmethod
    def load_ssh_public_key(encoded_key: Optional[str] = None):
        """Load SSH public key from a base64-encoded string."""
        if encoded_key is None:
            raise KeyPairServiceError(
                "EWC_CLI_ENCODED_SSH_PUBLIC_KEY environment variable not set."
            )

        try:
            public_key = base64.b64decode(encoded_key).decode("utf-8")
            return public_key
        except Exception as e:
            _LOGGER.error(f"Error decoding public key: {e}")
            return None

    @staticmethod
    def verify_private_key(private_key: str):
        """Verify SSH private key using cryptography."""
        error = False
        try:
            key_bytes = private_key.encode("utf-8")
            serialization.load_pem_private_key(
                key_bytes,
                password=None,
                backend=default_backend(),
            )
            _LOGGER.info("Private key is valid.")
        except ValueError as e:
            _LOGGER.error(f"Invalid SSH key (ValueError): {e}")
            error = True
        except TypeError as e:
            _LOGGER.error(f"SSH key error (TypeError): {e}")
            error = True
        except Exception as e:
            _LOGGER.error(f"Unexpected error while verifying SSH key: {e}")
            error = True
        if error:
            raise KeyPairServiceError("Invalid SSH private key.")

    @staticmethod
    def save_ssh_key(ssh_key, path_key):
        """Store SSH key to the provided path."""
        key_path = os.path.expanduser(path_key)
        os.makedirs(os.path.dirname(key_path), exist_ok=True)

        with open(key_path, "w") as key_file:
            key_file.write(ssh_key)

        os.chmod(key_path, 0o600)

        _LOGGER.debug(
            f"Key saved temporarily into the container to {key_path} "
            "with 0600 permissions."
        )

    @staticmethod
    def save_encoded_ssh_keys(
        ssh_public_key_path: str,
        ssh_private_key_path: str,
        ssh_public_encoded: Optional[str] = None,
        ssh_private_encoded: Optional[str] = None,
    ):
        """Store SSH keys provided as encoded strings."""
        public_written = False
        private_written = False

        if ssh_public_encoded:
            _LOGGER.info("Using encoded public key provided.")
            public_key = KeyPairService.load_ssh_public_key(
                encoded_key=ssh_public_encoded
            )

            if public_key is not None:
                ssh_public_key_path.parent.mkdir(parents=True, exist_ok=True)
                KeyPairService.save_ssh_key(
                    ssh_key=public_key, path_key=ssh_public_key_path
                )
                public_written = True

        if ssh_private_encoded:
            _LOGGER.info("Using encoded private key provided.")
            private_key = KeyPairService.load_ssh_private_key(
                encoded_key=ssh_private_encoded
            )

            if private_key is not None:
                ssh_private_key_path.parent.mkdir(parents=True, exist_ok=True)
                KeyPairService.verify_private_key(private_key=private_key)
                KeyPairService.save_ssh_key(
                    ssh_key=private_key, path_key=ssh_private_key_path
                )
                private_written = True

        return public_written, private_written

    @staticmethod
    def generate_ssh_keypair(resolved_profile: str) -> Tuple[str, str]:
        """Generate RSA SSH Key Pair and save to ~/.ssh."""
        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )

        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

        public_key = private_key.public_key()
        public_key_ssh = public_key.public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )

        Path(ewc_hub_config.EWC_CLI_HUB_SSH_REPO_PATH).mkdir(parents=True, exist_ok=True)

        ssh_private_key_path = (
            ewc_hub_config.EWC_CLI_HUB_SSH_REPO_PATH / f"{resolved_profile}_id_rsa"
        )

        with open(ssh_private_key_path, "wb") as f:
            f.write(private_key_pem)

        os.chmod(ssh_private_key_path, 0o600)

        ssh_public_key_path = (
            ewc_hub_config.EWC_CLI_HUB_SSH_REPO_PATH / f"{resolved_profile}_id_rsa.pub"
        )
        with open(ssh_public_key_path, "wb") as f:
            f.write(public_key_ssh)

        os.chmod(ssh_public_key_path, 0o644)

        _LOGGER.info(
            f"SSH key pair generated at {ssh_private_key_path} and "
            f"{ssh_public_key_path}"
        )

        return ssh_private_key_path.as_posix(), ssh_public_key_path.as_posix()

    @staticmethod
    def check_user_ssh_keys(
        ssh_public_key_path: Optional[str] = None,
        ssh_private_key_path: Optional[str] = None,
        dry_run: bool = False,
    ):
        """Check if SSH keys are compatible or missing."""
        if dry_run:
            _LOGGER.info(
                "Dry Run enable: Skipping checking SSH private and public keys..."
            )
            return

        keys_exist = KeyPairService.check_ssh_keys_exist(
            ssh_private_key_path=Path(ssh_private_key_path),
            ssh_public_key_path=Path(ssh_public_key_path),
        )

        if not keys_exist:
            raise KeyPairServiceError("\n Exiting.")

        is_matching = KeyPairService.check_ssh_keys_match(
            ssh_private_key_path=ssh_private_key_path,
            ssh_public_key_path=ssh_public_key_path,
        )

        if not is_matching:
            raise KeyPairServiceError(
                "SSH keys provided are not a correct keypair:"
                f"\nSSH public key path: {ssh_public_key_path}"
                f"\nSSH private key path: {ssh_private_key_path}"
                "\nMake sure either you pass correct SSH keypair in the EWC login "
                "command through the following flags `--ssh-private-key-path` and "
                "`--ssh-public-key-path` or let the `ewc login` command create them "
                "for you. Exiting."
            )
        else:
            _LOGGER.info("SSH private and public keys are matching! Continuing...")
