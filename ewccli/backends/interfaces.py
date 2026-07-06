#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details


"""Backend interface protocols.

Defines :class:`typing.Protocol` interfaces for each backend client so
that services can depend on the *contract* rather than the concrete
implementation.  This enables dependency injection and mock-based unit
testing without importing heavy SDK dependencies.

Each protocol declares the public methods that the service layer calls.
Concrete backend classes (``OpenstackBackend``, ``KubernetesBackend``,
``AnsibleBackend``) implement these protocols structurally — no explicit
inheritance is required, but they may also subclass for clarity.
"""

from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable


# ---------------------------------------------------------------------------
# Base protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class BackendInterface(Protocol):
    """Common contract for all backend clients.

    Every backend must provide connection lifecycle management so that
    the service layer can centralise connect / close logic.
    """

    def connect(self, *args: Any, **kwargs: Any) -> Any:
        """Establish a connection to the backend service.

        :raises BackendError: If the connection cannot be established.
        """
        ...

    def close(self) -> None:
        """Release any resources held by the backend (connections, sessions)."""
        ...

    def is_connected(self) -> bool:
        """Return ``True`` if the backend has an active connection."""
        ...


# ---------------------------------------------------------------------------
# Openstack
# ---------------------------------------------------------------------------

@runtime_checkable
class OpenstackBackendInterface(BackendInterface, Protocol):
    """Contract for the OpenStack backend client.

    Methods accept an active ``conn`` (``openstack.connection.Connection``)
    obtained via :meth:`connect` or :meth:`get_connection`.
    """

    def get_connection(self) -> Any:
        """Return a cached or newly-created OpenStack connection.

        Centralises connection lifecycle so that callers no longer
        invoke ``connect()`` per-command.

        :raises BackendConnectionError: If the connection fails.
        """
        ...

    def create_server(
        self,
        conn: Any,
        server_name: str,
        image_name: str,
        flavour_name: str,
        networks: tuple,
        keypair_name: str,
        sec_groups: tuple,
        **kwargs: Any,
    ) -> Tuple[Any, Optional[str], Dict[Any, Any]]:
        """Create an OpenStack server (VM)."""
        ...

    def delete_server(self, conn: Any, server_name: str, **kwargs: Any) -> Any:
        """Delete an OpenStack server by name."""
        ...

    def list_servers(self, conn: Any, **kwargs: Any) -> List[Any]:
        """List all servers visible to the current credentials."""
        ...

    def find_latest_image(self, conn: Any, prefix: str) -> Any:
        """Find the latest image whose name starts with *prefix*."""
        ...

    def check_server_inputs(
        self, conn: Any, **kwargs: Any
    ) -> Tuple[bool, Optional[str]]:
        """Validate server creation inputs against OpenStack resources."""
        ...

    def add_external_ip(self, conn: Any, server_name: str, **kwargs: Any) -> Any:
        """Attach a floating IP to a server."""
        ...

    def remove_external_ip(self, conn: Any, server_name: str, **kwargs: Any) -> Any:
        """Detach a floating IP from a server."""
        ...

    def list_networks(self, conn: Any, **kwargs: Any) -> List[Any]:
        """List available networks."""
        ...

    def remove_network(self, conn: Any, network_id: str, **kwargs: Any) -> Any:
        """Remove a network by ID."""
        ...

    def create_keypair(
        self, conn: Any, keypair_name: str, public_key_path: Any, **kwargs: Any
    ) -> Tuple[Any, str]:
        """Create or verify an SSH keypair in OpenStack."""
        ...

    def delete_keypair(
        self, conn: Any, keypair_name: str, **kwargs: Any
    ) -> Tuple[Any, str]:
        """Delete an SSH keypair from OpenStack."""
        ...


# ---------------------------------------------------------------------------
# Kubernetes
# ---------------------------------------------------------------------------

@runtime_checkable
class KubernetesBackendInterface(BackendInterface, Protocol):
    """Contract for the Kubernetes backend client."""

    def create_custom_resource(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a namespaced custom resource."""
        ...

    def delete_custom_resource(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        name: str,
    ) -> Dict[str, Any]:
        """Delete a namespaced custom resource by name."""
        ...

    def describe_custom_resource(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        name: str,
    ) -> Dict[str, Any]:
        """Retrieve a single custom resource by name."""
        ...

    def list_custom_resources(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
    ) -> List[Dict[str, Any]]:
        """List custom resources in a namespace."""
        ...

    def list_pods(self, namespace: str) -> Any:
        """List pods in a namespace."""
        ...

    def list_custom_resource_definitions(self) -> List[Dict[str, str]]:
        """List all CRDs in the cluster."""
        ...


# ---------------------------------------------------------------------------
# Ansible
# ---------------------------------------------------------------------------

@runtime_checkable
class AnsibleBackendInterface(BackendInterface, Protocol):
    """Contract for the Ansible backend client."""

    def run_ansible_live(
        self,
        working_directory_path: str,
        cmdline: List[str],
        **kwargs: Any,
    ) -> int:
        """Run an Ansible task with live output streaming.

        :returns: The ansible-runner return code.
        :raises BackendError: If the task fails.
        """
        ...

    def run_ansible(
        self,
        description: str,
        command: List[str],
        **kwargs: Any,
    ) -> Tuple[int, str]:
        """Run an ansible command.

        :returns: A ``(return_code, message)`` tuple.
        """
        ...

    def install_ansible_roles(
        self, requirements_path: str, **kwargs: Any
    ) -> Tuple[int, str]:
        """Install Ansible roles from a requirements file.

        :returns: A ``(return_code, message)`` tuple.
        """
        ...
