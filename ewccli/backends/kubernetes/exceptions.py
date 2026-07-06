#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""Exceptions class for Kubernetes backend."""


from ewccli.backends.exceptions import BackendAlreadyExistsError


class ResourceAlreadyExistsError(BackendAlreadyExistsError):
    """Exception raised when a Kubernetes resource already exists in the cluster.

    Inherits from :class:`~ewccli.backends.exceptions.BackendAlreadyExistsError`
    so it is part of the unified backend exception hierarchy.
    """
