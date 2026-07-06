#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""Common methods for commands using infrastructure — thin wrappers.

All business logic lives in :mod:`ewccli.services.server_service` and
:mod:`ewccli.services.keypair_service`.  These wrappers preserve the
original module-level function names so that existing imports and
test patches continue to work, while translating service-layer
exceptions back to CLI-appropriate exceptions.
"""

import sys
from pathlib import Path
from typing import Optional, Tuple, Dict

from rich.console import Console
from rich.panel import Panel

from click import ClickException
from openstack import connection

from ewccli.backends.openstack.backend_ostack import OpenstackBackend
from ewccli.enums import Region
from ewccli.configuration import config as ewc_hub_config
from ewccli.logger import get_logger
from ewccli.services.server_service import ServerService
from ewccli.services.keypair_service import KeyPairService
from ewccli.services.exceptions import ServerServiceError, KeyPairServiceError

_LOGGER = get_logger(__name__)

console = Console()


def check_user_ssh_keys(
    ssh_public_key_path: Optional[str] = None,
    ssh_private_key_path: Optional[str] = None,
    dry_run: bool = False,
):
    """Check if SSH keys are compatible or missing."""
    try:
        KeyPairService.check_user_ssh_keys(
            ssh_public_key_path=ssh_public_key_path,
            ssh_private_key_path=ssh_private_key_path,
            dry_run=dry_run,
        )
    except KeyPairServiceError as e:
        raise ClickException(str(e))


def check_server_conflict_with_inputs(
    server_info: dict,
    server_info_image: Optional[str] = None,
    image_name: Optional[str] = None,
    keypair_name: Optional[str] = None,
    flavour_name: Optional[str] = None,
    networks: Optional[tuple] = None,
    security_groups: Optional[tuple] = None,
):
    """Check if user-provided values conflict with an existing server."""
    return ServerService.check_server_conflict_with_inputs(
        server_info=server_info,
        server_info_image=server_info_image,
        image_name=image_name,
        keypair_name=keypair_name,
        flavour_name=flavour_name,
        networks=networks,
        security_groups=security_groups,
    )


def show_server_input_requested_summary(
    security_groups: tuple,
    networks: tuple,
    image_name: Optional[str] = None,
    flavour_name: Optional[str] = None,
    keypair_name: Optional[str] = None,
):
    """Print table with inputs for the server."""
    ServerService.show_server_input_requested_summary(
        security_groups=security_groups,
        networks=networks,
        image_name=image_name,
        flavour_name=flavour_name,
        keypair_name=keypair_name,
    )


def show_server_inputs_difference_table(server_name: str, diffs: dict):
    """Show table of inputs with differences requested."""
    try:
        ServerService.show_server_inputs_difference_table(
            server_name=server_name, diffs=diffs
        )
    except ServerServiceError as e:
        raise ClickException(str(e))


def check_ssh_keys_exist(ssh_public_key_path: Path, ssh_private_key_path: Path) -> bool:
    """Verify that both SSH key files exist."""
    return KeyPairService.check_ssh_keys_exist(
        ssh_public_key_path=ssh_public_key_path,
        ssh_private_key_path=ssh_private_key_path,
    )


def normalize_os_image(
    image_name: str,
    federee: str,
    region: str,
) -> tuple[str | None, bool]:
    """Normalize OS image names provided."""
    return ServerService.normalize_os_image(
        image_name=image_name,
        federee=federee,
        region=region,
    )


def resolve_image_and_flavor(
    conn: connection.Connection,
    openstack_backend: OpenstackBackend,
    federee: str,
    region: str,
    flavour_name: Optional[str] = None,
    image_name: Optional[str] = None,
    is_gpu: bool = False,
) -> Tuple[int, str, Dict[str, str]]:
    """Resolve both the image and flavor for the given federee."""
    return ServerService.resolve_image_and_flavor(
        conn=conn,
        openstack_backend=openstack_backend,
        federee=federee,
        region=region,
        flavour_name=flavour_name,
        image_name=image_name,
        is_gpu=is_gpu,
    )


def resolve_machine_ip(
    federee: str,
    server_info: dict,
) -> Tuple[int, str, Optional[Dict[str, Optional[str]]]]:
    """Resolve the internal and external IPs of a machine."""
    return ServerService.resolve_machine_ip(
        federee=federee,
        server_info=server_info,
    )


def get_deployed_server_info(
    federee: str,
    server_info: dict,
    image_name: Optional[str] = None,
):
    """Get deployed server info."""
    return ServerService.get_deployed_server_info(
        federee=federee,
        server_info=server_info,
        image_name=image_name,
    )


def list_server_details(vm_info: dict):
    """Print detailed info of a single server in a two-column table."""
    ServerService.list_server_details(vm_info)


def pre_deploy_server_setup(
    openstack_backend: OpenstackBackend,
    openstack_api: connection.Connection,
    federee: str,
    region: str,
    server_inputs: dict,
    ssh_public_key_path: str,
    ssh_private_key_path: str,
    ssh_private_encoded: Optional[str] = None,
    ssh_public_encoded: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
):
    """Pre deploy server setup steps."""
    return ServerService.pre_deploy_server_setup(
        openstack_backend=openstack_backend,
        openstack_api=openstack_api,
        federee=federee,
        region=region,
        server_inputs=server_inputs,
        ssh_public_key_path=ssh_public_key_path,
        ssh_private_key_path=ssh_private_key_path,
        ssh_private_encoded=ssh_private_encoded,
        ssh_public_encoded=ssh_public_encoded,
        dry_run=dry_run,
        force=force,
    )


def identify_server_reconfiguration(
    openstack_api: connection.Connection,
    server_inputs: dict,
    pre_deploy_server_outputs: dict,
):
    """Identify resources to be reconfigured."""
    try:
        return ServerService.identify_server_reconfiguration(
            openstack_api=openstack_api,
            server_inputs=server_inputs,
            pre_deploy_server_outputs=pre_deploy_server_outputs,
        )
    except ServerServiceError as e:
        raise ClickException(str(e))


def deploy_server(
    openstack_backend: OpenstackBackend,
    openstack_api: connection.Connection,
    federee: str,
    server_inputs: dict,
    pre_deploy_server_outputs: dict,
    boot_from_volume: bool = False,
    dry_run: bool = False,
    force: bool = False,
):
    """Deploy Server in Openstack."""
    return ServerService.deploy_server(
        openstack_backend=openstack_backend,
        openstack_api=openstack_api,
        federee=federee,
        server_inputs=server_inputs,
        pre_deploy_server_outputs=pre_deploy_server_outputs,
        boot_from_volume=boot_from_volume,
        dry_run=dry_run,
        force=force,
    )


def post_deploy_server_setup(
    openstack_backend: OpenstackBackend,
    openstack_api: connection.Connection,
    federee: str,
    server_inputs: dict,
    server_info: dict,
    dry_run: bool = False,
):
    """Post deploy server setup steps."""
    return ServerService.post_deploy_server_setup(
        openstack_backend=openstack_backend,
        openstack_api=openstack_api,
        federee=federee,
        server_inputs=server_inputs,
        server_info=server_info,
        dry_run=dry_run,
    )


def create_server_command(
    openstack_backend: OpenstackBackend,
    openstack_api: connection.Connection,
    federee: str,
    region: str,
    server_inputs: dict,
    ssh_public_key_path: str,
    ssh_private_key_path: str,
    ssh_private_encoded: Optional[str] = None,
    ssh_public_encoded: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
):
    """Create Server command."""
    os_status_code, os_message, outputs = ServerService.create_server_command(
        openstack_backend=openstack_backend,
        openstack_api=openstack_api,
        federee=federee,
        region=region,
        server_inputs=server_inputs,
        ssh_public_key_path=ssh_public_key_path,
        ssh_private_key_path=ssh_private_key_path,
        ssh_private_encoded=ssh_private_encoded,
        ssh_public_encoded=ssh_public_encoded,
        dry_run=dry_run,
        force=force,
    )

    if os_status_code != 0 and not outputs:
        console.print(Panel(os_message, title="Error", style="red"))
        sys.exit(1)

    return os_status_code, os_message, outputs
