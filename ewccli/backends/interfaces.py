#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""Backend interface protocols.

Defines ``typing.Protocol`` interfaces for each backend client so that
services depend on the *contract* rather than the concrete implementation.
This enables dependency injection and mock-based unit testing without
importing heavy SDK dependencies.

Transitional: these contracts will be reused by the standalone
``ewc-backend`` service (Phase 4, KAM-9).
"""

from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable


@runtime_checkable
class BackendInterface(Protocol):
    """Common contract for all backend clients."""

    def connect(self, *args: Any, **kwargs: Any) -> Any:
        """Establish a connection to the backend service."""
        ...

    def close(self) -> None:
        """Release any resources held by the backend."""
        ...

    def is_connected(self) -> bool:
        """Return ``True`` if the backend has an active connection."""
        ...


@runtime_checkable
class OpenstackBackendInterface(BackendInterface, Protocol):
    """Contract for the OpenStack backend client."""

    def get_connection(self, **kwargs: Any) -> Any:
        """Return a cached or newly-created OpenStack connection."""
        ...

    def create_server(
        self, conn: Any, server_name: str, **kwargs: Any
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

    def check_server_inputs(self, conn: Any, **kwargs: Any) -> Any:
        """Validate server creation inputs against OpenStack resources."""
        ...

    def add_external_ip(self, conn: Any, **kwargs: Any) -> Any:
        """Assign an external floating IP to a server."""
        ...

    def remove_external_ip(self, conn: Any, **kwargs: Any) -> Any:
        """Remove an external floating IP from a server."""
        ...

    def list_networks(self, conn: Any, **kwargs: Any) -> List[Any]:
        """List available networks."""
        ...

    def remove_network(self, conn: Any, **kwargs: Any) -> Any:
        """Remove a network."""
        ...

    def create_keypair(self, conn: Any, keypair_name: str, public_key_path: Any, **kwargs: Any) -> Tuple[Any, str]:
        """Create or verify a keypair from an SSH public key."""
        ...

    def delete_keypair(self, conn: Any, keypair_name: str, **kwargs: Any) -> Tuple[Any, str]:
        """Delete a keypair from OpenStack."""
        ...

    def ssh_key_matches_openstack(self, public_key_path: str, keypair: dict) -> bool:
        """Check whether a local SSH public key matches an OpenStack keypair."""
        ...


@runtime_checkable
class KubernetesBackendInterface(BackendInterface, Protocol):
    """Contract for the Kubernetes backend client."""

    def create_custom_resource(
        self, group: str, version: str, namespace: str, plural: str, name: str, crd: Any, **kwargs: Any
    ) -> dict:
        """Create a custom resource in the cluster."""
        ...

    def delete_custom_resource(self, group: str, version: str, namespace: str, plural: str, name: str) -> dict:
        """Delete a custom resource by name."""
        ...

    def describe_custom_resource(self, group: str, version: str, namespace: str, plural: str, name: str) -> dict:
        """Describe (get) a custom resource by name."""
        ...

    def list_custom_resources(self, group: str, version: str, namespace: str, plural: str, **kwargs: Any) -> List[dict]:
        """List custom resources of a given CRD type."""
        ...

    def list_pods(self, namespace: str) -> List[dict]:
        """List pods in a namespace."""
        ...

    def list_custom_resource_definitions(self) -> List[dict]:
        """List all custom resource definitions in the cluster."""
        ...


@runtime_checkable
class AnsibleBackendInterface(BackendInterface, Protocol):
    """Contract for the Ansible backend client."""

    def run_ansible_live(self, working_directory_path: str, cmdline: List[str], **kwargs: Any) -> Any:
        """Run an Ansible task and stream output live."""
        ...

    def run_ansible(self, **kwargs: Any) -> Any:
        """Run an Ansible playbook (non-streaming)."""
        ...

    def install_ansible_roles(self, requirements_path: str, dry_run: bool = False) -> None:
        """Install Ansible roles from a requirements file."""
        ...
