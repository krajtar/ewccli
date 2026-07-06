"""SSH keypair management service.

Handles SSH key generation, validation, loading, and storage.
No click / rich_click imports.
"""

import base64
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from ewccli.configuration import config as ewc_hub_config
from ewccli.logger import get_logger
from ewccli.services.exceptions import KeyPairError

_LOGGER = get_logger(__name__)


class KeyPairService:
    """Manage SSH key generation, validation, and storage."""

    # ------------------------------------------------------------------ #
    # Key loading (base64 encoded)
    # ------------------------------------------------------------------ #
    @staticmethod
    def load_ssh_private_key(encoded_key: Optional[str] = None) -> Optional[str]:
        """Decode a base64-encoded SSH private key string."""
        if encoded_key is None:
            _LOGGER.error(
                "EWC_CLI_ENCODED_SSH_PRIVATE_KEY environment variable not set."
            )
            return None

        try:
            private_key = base64.b64decode(encoded_key).decode("utf-8")
            return private_key
        except Exception as e:
            _LOGGER.error(f"Error decoding private key: {e}")
            return None

    @staticmethod
    def load_ssh_public_key(encoded_key: Optional[str] = None) -> Optional[str]:
        """Decode a base64-encoded SSH public key string."""
        if encoded_key is None:
            _LOGGER.error(
                "EWC_CLI_ENCODED_SSH_PUBLIC_KEY environment variable not set."
            )
            return None

        try:
            public_key = base64.b64decode(encoded_key).decode("utf-8")
            return public_key
        except Exception as e:
            _LOGGER.error(f"Error decoding public key: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Key validation
    # ------------------------------------------------------------------ #
    @staticmethod
    def verify_private_key(private_key: str) -> None:
        """Verify SSH private key using cryptography.

        Raises KeyPairError if the key is invalid.
        """
        try:
            key_bytes = private_key.encode("utf-8")
            serialization.load_pem_private_key(
                key_bytes,
                password=None,
                backend=default_backend(),
            )
            _LOGGER.info("Private key is valid.")
        except ValueError as e:
            raise KeyPairError(f"Invalid SSH key (ValueError): {e}")
        except TypeError as e:
            raise KeyPairError(f"SSH key error (TypeError): {e}")
        except Exception as e:
            raise KeyPairError(f"Unexpected error while verifying SSH key: {e}")

    @staticmethod
    def check_ssh_keys_match(
        ssh_private_key_path: str, ssh_public_key_path: str
    ) -> bool:
        """Check whether a private key corresponds to a public key.

        Raises ValueError if the key format is unsupported.
        """
        for p in [ssh_private_key_path, ssh_public_key_path]:
            if not Path(p).expanduser().is_file():
                raise ValueError(f"SSH key file does not exist: {p}")

        with open(ssh_private_key_path, "rb") as f:
            private_data = f.read()

        private_key = None

        try:
            private_key = serialization.load_pem_private_key(
                private_data, password=None
            )
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

    # ------------------------------------------------------------------ #
    # Key storage
    # ------------------------------------------------------------------ #
    @staticmethod
    def save_ssh_key(ssh_key: str, path_key: str) -> None:
        """Store SSH key to the provided path with 0600 permissions."""
        key_path = os.path.expanduser(path_key)
        os.makedirs(os.path.dirname(key_path), exist_ok=True)

        with open(key_path, "w") as key_file:
            key_file.write(ssh_key)
        os.chmod(key_path, 0o600)

        _LOGGER.debug(
            f"Key saved to {key_path} with 0600 permissions."
        )

    def save_encoded_ssh_keys(
        self,
        ssh_public_key_path,
        ssh_private_key_path,
        ssh_public_encoded: Optional[str] = None,
        ssh_private_encoded: Optional[str] = None,
    ) -> Tuple[bool, bool]:
        """Store SSH keys provided as encoded strings.

        Returns (public_written, private_written).
        """
        public_written = False
        private_written = False

        if ssh_public_encoded:
            _LOGGER.info("Using encoded public key provided.")
            public_key = self.load_ssh_public_key(encoded_key=ssh_public_encoded)

            if public_key is not None:
                Path(ssh_public_key_path).parent.mkdir(parents=True, exist_ok=True)
                self.save_ssh_key(
                    ssh_key=public_key, path_key=str(ssh_public_key_path)
                )
                public_written = True

        if ssh_private_encoded:
            _LOGGER.info("Using encoded private key provided.")
            private_key = self.load_ssh_private_key(encoded_key=ssh_private_encoded)

            if private_key is not None:
                Path(ssh_private_key_path).parent.mkdir(parents=True, exist_ok=True)
                self.verify_private_key(private_key=private_key)
                self.save_ssh_key(
                    ssh_key=private_key, path_key=str(ssh_private_key_path)
                )
                private_written = True

        return public_written, private_written

    # ------------------------------------------------------------------ #
    # Keypair generation
    # ------------------------------------------------------------------ #
    @staticmethod
    def generate_ssh_keypair(resolved_profile: str) -> Tuple[str, str]:
        """Generate RSA SSH key pair and save to ~/.ewccli/.ssh."""
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

        Path(ewc_hub_config.EWC_CLI_HUB_SSH_REPO_PATH).mkdir(
            parents=True, exist_ok=True
        )

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
            f"SSH key pair generated at {ssh_private_key_path} "
            f"and {ssh_public_key_path}"
        )

        return ssh_private_key_path.as_posix(), ssh_public_key_path.as_posix()

    # ------------------------------------------------------------------ #
    # Key existence checking
    # ------------------------------------------------------------------ #
    @staticmethod
    def check_ssh_keys_exist(
        ssh_public_key_path: Path, ssh_private_key_path: Path
    ) -> bool:
        """Check if both SSH key files exist."""
        return (
            ssh_private_key_path.is_file()
            and ssh_public_key_path.is_file()
        )

    # ------------------------------------------------------------------ #
    # User-facing SSH key check
    # ------------------------------------------------------------------ #
    def check_user_ssh_keys(
        self,
        ssh_public_key_path: Optional[str] = None,
        ssh_private_key_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        """Check if SSH keys are compatible or missing.

        Raises KeyPairError if keys are missing or mismatched.
        """
        if dry_run:
            _LOGGER.info(
                "Dry Run enabled: Skipping checking SSH private and public keys..."
            )
            return

        keys_exist = self.check_ssh_keys_exist(
            ssh_private_key_path=Path(ssh_private_key_path),
            ssh_public_key_path=Path(ssh_public_key_path),
        )

        if not keys_exist:
            raise KeyPairError(
                f"SSH keys not found. "
                f"Private key: {ssh_private_key_path}, "
                f"Public key: {ssh_public_key_path}. "
                "Run 'ewc login' to create them or specify paths with "
                "EWC_CLI_SSH_PRIVATE_KEY_PATH / EWC_CLI_SSH_PUBLIC_KEY_PATH."
            )

        is_matching = self.check_ssh_keys_match(
            ssh_private_key_path=ssh_private_key_path,
            ssh_public_key_path=ssh_public_key_path,
        )

        if not is_matching:
            raise KeyPairError(
                "SSH keys provided are not a correct keypair:"
                f"\nSSH public key path: {ssh_public_key_path}"
                f"\nSSH private key path: {ssh_private_key_path}"
                "\nMake sure either you pass correct SSH keypair in the "
                "EWC login command through the following flags "
                "`--ssh-private-key-path` and `--ssh-public-key-path`"
                "or let the `ewc login` command create them for you."
            )
        else:
            _LOGGER.info("SSH private and public keys are matching! Continuing...")
