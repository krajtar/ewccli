"""Exception hierarchy for the service layer.

These replace ``click.ClickException`` / ``click.Abort`` in business logic
so that service modules have no click dependency.
"""


class ServiceError(Exception):
    """Base exception for all service-layer errors."""


class ConfigError(ServiceError):
    """Configuration / profile related errors."""


class ValidationError(ServiceError):
    """Input validation errors (bad parameters, type mismatches)."""


class KeyPairError(ServiceError):
    """SSH keypair errors (missing, mismatched, invalid)."""


class DnsError(ServiceError):
    """DNS resolution / record errors."""


class ServerOperationError(ServiceError):
    """Server provisioning / lifecycle errors.

    Optional keyword arguments:
        diffs: list of config conflict tuples (field, existing, requested)
        server_name: name of the server with conflicts
    """

    def __init__(self, message="", diffs=None, server_name=None):
        super().__init__(message)
        self.diffs = diffs
        self.server_name = server_name


class HubDeployError(ServiceError):
    """Hub item deployment errors."""
