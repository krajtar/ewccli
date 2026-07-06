#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""Backends for EWC CLI.

Provides backend client interfaces, a unified exception hierarchy, and
retry utilities.  Concrete backend implementations live in sub-packages
(``openstack``, ``kubernetes``, ``ansible``).

Transitional: these contracts will be reused by the standalone
``ewc-backend`` service (Phase 4, KAM-9).
"""

from ewccli.backends.exceptions import (
    BackendError,
    BackendConnectionError,
    BackendAuthError,
    BackendOperationError,
    BackendTimeoutError,
    BackendNotFoundError,
    BackendAlreadyExistsError,
    BackendValidationError,
    BackendConfigError,
)
from ewccli.backends.interfaces import (
    BackendInterface,
    OpenstackBackendInterface,
    KubernetesBackendInterface,
    AnsibleBackendInterface,
)
from ewccli.backends.retry import retry_with_backoff, is_retryable

__all__ = [
    "BackendError",
    "BackendConnectionError",
    "BackendAuthError",
    "BackendOperationError",
    "BackendTimeoutError",
    "BackendNotFoundError",
    "BackendAlreadyExistsError",
    "BackendValidationError",
    "BackendConfigError",
    "BackendInterface",
    "OpenstackBackendInterface",
    "KubernetesBackendInterface",
    "AnsibleBackendInterface",
    "retry_with_backoff",
    "is_retryable",
]
