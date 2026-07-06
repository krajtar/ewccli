#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""Unified backend exception hierarchy.

All backend clients raise exceptions from this hierarchy so that the
service layer can catch a single ``BackendError`` family instead of
client-specific types.  This makes backends swappable and testable.

Transitional: these contracts will be reused by the standalone
``ewc-backend`` service (Phase 4, KAM-9).
"""


class BackendError(Exception):
    """Base exception for all backend-layer errors."""


class BackendConnectionError(BackendError):
    """Raised when a backend cannot establish or maintain a connection."""


class BackendAuthError(BackendConnectionError):
    """Raised when authentication or authorization fails."""


class BackendOperationError(BackendError):
    """Raised when a backend operation fails for a non-transient reason."""


class BackendTimeoutError(BackendError):
    """Raised when a backend operation exceeds its timeout."""


class BackendNotFoundError(BackendError):
    """Raised when a requested resource is not found."""


class BackendAlreadyExistsError(BackendError):
    """Raised when attempting to create a resource that already exists."""


class BackendValidationError(BackendError):
    """Raised when a backend rejects input due to validation failure."""


class BackendConfigError(BackendError):
    """Raised when backend configuration (credentials, endpoints) is missing or invalid."""
