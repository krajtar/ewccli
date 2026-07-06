#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""Kubernetes-specific backend exceptions.

Extends the unified :mod:`ewccli.backends.exceptions` hierarchy.
"""

from ewccli.backends.exceptions import BackendAlreadyExistsError


class ResourceAlreadyExistsError(BackendAlreadyExistsError):
    """Exception raised when the resource already exists in the cluster."""
