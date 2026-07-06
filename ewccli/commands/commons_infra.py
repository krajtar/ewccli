"""Common methods for commands using infrastructure.

Business logic has been extracted to ``ewccli.services.server_service``.
This module provides backward-compatible wrappers that delegate to the
service layer and handle CLI-specific concerns (display, ClickException).
"""

import sys
from pathlib import Path
from typing import Optional, Tuple, Dict

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from click import ClickException

from openstack import connection

from ewccli.backends.openstack.backend_ostack import OpenstackBackend
from ewccli.enums import Federee, Region
from ewccli.configuration import config as ewc_hub_config
from ewccli.logger import get_logger
from ewccli.services.server_service import ServerService
from ewccli.services.exceptions import ServerOperationError

_LOGGER = get_logger(__name__)
_EWC_CLI_SLEEP_TIME = 30

console = Console()

_server_service = ServerService()


# ------------------------------------------------------------------ #
# Display functions (presentation layer, not business logic)
# ------------------------------------------------------------------ #
def show_server_input_requested_summary(
    security_groups: tuple,
    networks: tuple,
    image_name: Optional[str] = None,
    flavour_name: Optional[str] = None,
    keypair_name: Optional[str] = None,
):
    """Print table with inputs for the server."""
    table = Table(
        title="Server Configuration Inputs Summary", title_style="bold green"
    )

    table.add_column("Parameter", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    table.add_row("Image", image_name)
    table.add_row("Flavour", flavour_name)
    table.add_row("Network", ", ".join(networks))
    table.add_row("Security Groups", ", ".join(security_groups))
    table.add_row("Keypair", keypair_name)

    console.print(table)


def show_server_inputs_difference_table(server_name: str, diffs: dict):
    """Show table of inputs with differences requested."""
    if not diffs:
        return False

    table = Table(
        title="Configuration mismatch with existing server",
        show_lines=True,
    )
    table.add_column("Parameter", style="bold cyan")
    table.add_column("Existing Value", style="bold yellow")
    table.add_column("Requested Value", style="bold green")

    for param, existing, requested in diffs:
        table.add_row(param, existing, requested)

    console.print(table)

    raise ClickException(
        f"The server '{server_name}' already exists with different configuration."
        " Use a different --server-name or use --force to redeploy."
    )


def list_server_details(vm_info: dict):
    """Print detailed info of a single server in a two-column table."""
    console = Console()

    table = Table(
        show_header=False,
        box=box.MINIMAL_DOUBLE_HEAD,
        title=f"Openstack Server: {vm_info.get('name')}",
    )

    table.add_column("Property", style="bold green", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Name", str(vm_info.get("name")))
    table.add_row("Status", str(vm_info.get("status")))
    table.add_row("Flavor", str(vm_info.get("flavor")))
    table.add_row("Image", str(vm_info.get("image")))
    networks = []
    retrieved_networks = vm_info.get("networks") or {}
    for n_name, n_value in retrieved_networks.items():
        if isinstance(n_value, list):
            networks.append(f"{n_name} ({', '.join(n_value)})")
        else:
            networks.append(f"{n_name} ({n_value})")

    table.add_row("Networks", "\n".join(networks))
    table.add_row("Security Groups", ",".join(vm_info.get("security-groups") or []))
    table.add_row("ID", str(vm_info.get("id", "")))

    console.print(table)


def check_ssh_keys_exist(ssh_public_key_path: Path, ssh_private_key_path: Path) -> bool:
    """Check if both SSH key files exist."""
    missing_msgs = []

    if not ssh_private_key_path.is_file():
        missing_msgs.append(
            f"Missing Private Key: {ssh_private_key_path}"
        )
    if not ssh_public_key_path.is_file():
        missing_msgs.append(
            f"Missing Public Key: {ssh_public_key_path}"
        )

    if missing_msgs:
        panel_content = (
            "\n".join(missing_msgs)
            + "\n\n"
            + "Tip: You can run ewc login and create them.\n"
            + "Tip: You can specify custom paths with:\n"
            + 'export EWC_CLI_SSH_PRIVATE_KEY_PATH="/path/to/id_rsa"\n'
            + 'export EWC_CLI_SSH_PUBLIC_KEY_PATH="/path/to/id_rsa.pub"'
        )

        console.print(
            Panel(
                panel_content, title="SSH Key Check Failed", style="red", expand=False
            )
        )
        return False

    return True


# ------------------------------------------------------------------ #
# Business-logic wrappers (delegate to ServerService)
# ------------------------------------------------------------------ #
def check_user_ssh_keys(
    ssh_public_key_path: Optional[str] = None,
    ssh_private_key_path: Optional[str] = None,
    dry_run: bool = False,
):
    """Check if SSH keys are compatible or missing."""
    try:
        _server_service.check_user_ssh_keys(
            ssh_public_key_path=ssh_public_key_path,
            ssh_private_key_path=ssh_private_key_path,
            dry_run=dry_run,
        )
    except ServerOperationError as e:
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
    return _server_service.check_server_conflict_with_inputs(
        server_info=server_info,
        server_info_image=server_info_image,
        image_name=image_name,
        keypair_name=keypair_name,
        flavour_name=flavour_name,
        networks=networks,
        security_groups=security_groups,
    )


def normalize_os_image(
    image_name: str,
    federee: str,
    region: str,
) -> tuple[str | None, bool]:
    """Normalize OS image names."""
    return _server_service.normalize_os_image(
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
    return _server_service.resolve_image_and_flavor(
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
    return _server_service.resolve_machine_ip(
        federee=federee,
        server_info=server_info,
    )


def get_deployed_server_info(
    federee: str,
    server_info: dict,
    image_name: Optional[str] = None,
):
    """Get deployed server info."""
    return _server_service.get_deployed_server_info(
        federee=federee,
        server_info=server_info,
        image_name=image_name,
    )


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
    return _server_service.pre_deploy_server_setup(
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
        return _server_service.identify_server_reconfiguration(
            openstack_api=openstack_api,
            server_inputs=server_inputs,
            pre_deploy_server_outputs=pre_deploy_server_outputs,
        )
    except ServerOperationError as e:
        diffs = getattr(e, "diffs", None)
        server_name = getattr(e, "server_name", "")
        if diffs:
            show_server_inputs_difference_table(
                server_name=server_name, diffs=diffs
            )
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
    sc, msg, outputs = _server_service.deploy_server(
        openstack_backend=openstack_backend,
        openstack_api=openstack_api,
        federee=federee,
        server_inputs=server_inputs,
        pre_deploy_server_outputs=pre_deploy_server_outputs,
        boot_from_volume=boot_from_volume,
        dry_run=dry_run,
        force=force,
    )

    # Display functions (presentation layer)
    if sc == 0 and outputs:
        resolved_image_name = pre_deploy_server_outputs.get("resolved_image_name", "")
        resolved_flavour_name = pre_deploy_server_outputs.get(
            "resolved_flavour_name", ""
        )
        networks = server_inputs.get("networks", ())
        security_groups = server_inputs.get("security_groups", ())
        keypair_name = server_inputs.get("keypair_name", "")

        show_server_input_requested_summary(
            image_name=resolved_image_name,
            flavour_name=resolved_flavour_name,
            networks=networks,
            security_groups=security_groups,
            keypair_name=keypair_name,
        )

        vm_info = outputs.get("vm_info")
        if vm_info:
            list_server_details(vm_info)

    return sc, msg, outputs


def post_deploy_server_setup(
    openstack_backend: OpenstackBackend,
    openstack_api: connection.Connection,
    federee: str,
    server_inputs: dict,
    server_info: dict,
    dry_run: bool = False,
):
    """Post deploy server setup steps."""
    return _server_service.post_deploy_server_setup(
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
    try:
        return _server_service.create_server(
            openstack_backend=openstack_backend,
            openstack_api=openstack_api,
            federee=federee,
            region=region,
            server_inputs=server_inputs,
            ssh_private_encoded=ssh_private_encoded,
            ssh_public_encoded=ssh_public_encoded,
            ssh_public_key_path=ssh_public_key_path,
            ssh_private_key_path=ssh_private_key_path,
            dry_run=dry_run,
            force=force,
        )
    except ServerOperationError as e:
        console.print(Panel(str(e), title="Error", style="red"))
        sys.exit(1)
