#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""Service-layer exception hierarchy.

These exceptions replace ``click.ClickException`` / ``click.Abort``
in the service layer so that service modules have no dependency on
``click`` or ``rich_click``.  CLI wrappers catch ``ServiceError``
sub-classes and translate them back to the appropriate click
exception when needed.
"""


class ServiceError(Exception):
    """Base exception for all service-layer errors."""


class ConfigServiceError(ServiceError):
    """Raised by :class:`ConfigService` for configuration errors."""


class KeyPairServiceError(ServiceError):
    """Raised by :class:`KeyPairService` for SSH key-pair errors."""


class DnsServiceError(ServiceError):
    """Raised by :class:`DnsService` for DNS-related errors."""


class ServerServiceError(ServiceError):
    """Raised by :class:`ServerService` for server-provisioning errors."""


class HubDeployServiceError(ServiceError):
    """Raised by :class:`HubDeployService` for hub-deployment errors."""
