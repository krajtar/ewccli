"""CLI EWC Hub: EWC Hub interaction items specific methods.

Business logic has been extracted to ``ewccli.services.hub_deploy_service``.
This module provides backward-compatible wrappers that delegate to the
service layer.
"""

import sys
from pathlib import Path
from typing import Tuple, Optional

from openstack import connection

from ewccli.configuration import config as ewc_hub_config
from ewccli.enums import Federee
from ewccli.backends.ansible.backend_ansible import AnsibleBackend
from ewccli.logger import get_logger
from ewccli.services.hub_deploy_service import HubDeployService, HUB_ENV_VARIABLES_MAP
from ewccli.services.exceptions import HubDeployError

_LOGGER = get_logger(__name__)

ansible_backend = AnsibleBackend()
_hub_deploy_service = HubDeployService(ansible_backend=ansible_backend)


def get_hub_item_env_variable_value(
    hub_item_env_variables_map: dict,
    federee: str,
    tenancy_name: str,
    variable_name: str,
    openstack_api: Optional[connection.Connection] = None,
) -> str:
    """Retrieve the value of a HUB_ENV_VARIABLES_MAP variable for a given federee."""
    return _hub_deploy_service.get_hub_item_env_variable_value(
        hub_item_env_variables_map=hub_item_env_variables_map,
        federee=federee,
        tenancy_name=tenancy_name,
        variable_name=variable_name,
        openstack_api=openstack_api,
    )


def check_github_repo_accessible(source: str) -> bool:
    """Check if a GitHub repository exists and is publicly accessible."""
    return _hub_deploy_service.check_github_repo_accessible(source)


def git_clone_item(
    source: str,
    repo_name: str,
    command_path: str,
    dry_run: bool = False,
    force: bool = False,
):
    """Git clone item."""
    try:
        return _hub_deploy_service.git_clone_item(
            source=source,
            repo_name=repo_name,
            command_path=command_path,
            dry_run=dry_run,
            force=force,
        )
    except HubDeployError as e:
        _LOGGER.error(str(e))
        sys.exit(1)


def run_ansible_item(
    item: str,
    item_inputs: Optional[dict],
    server_name: str,
    ip_machine: str,
    username: str,
    main_file_path: str,
    requirements_file_path: str,
    working_directory_path: str,
    ssh_private_key_path: str,
    dry_run: bool = False,
):
    """Run item based on Ansible Playbook."""
    return _hub_deploy_service.run_ansible_item(
        item=item,
        item_inputs=item_inputs,
        server_name=server_name,
        ip_machine=ip_machine,
        username=username,
        main_file_path=main_file_path,
        requirements_file_path=requirements_file_path,
        working_directory_path=working_directory_path,
        ssh_private_key_path=ssh_private_key_path,
        dry_run=dry_run,
    )


def run_post_ansible_operations(
    item: str,
    command_path: str,
    repo_name: str,
    server_name: str,
    internal_ip_machine: str,
):
    """Run post ansible operation if something goes wrong."""
    _hub_deploy_service.run_post_ansible_operations(
        item=item,
        command_path=command_path,
        repo_name=repo_name,
        server_name=server_name,
        internal_ip_machine=internal_ip_machine,
    )


def run_ansible_playbook_item(
    item: str,
    server_name: str,
    username: str,
    main_file_path: str,
    requirements_file_path: str,
    working_directory_path: str,
    ip_machine: str,
    ssh_private_key_path: str,
    item_inputs: Optional[dict],
    dry_run: bool = False,
) -> Tuple[int, str]:
    """Deploy Ansible item."""
    return _hub_deploy_service.run_ansible_playbook_item(
        item=item,
        server_name=server_name,
        username=username,
        main_file_path=main_file_path,
        requirements_file_path=requirements_file_path,
        working_directory_path=working_directory_path,
        ip_machine=ip_machine,
        ssh_private_key_path=ssh_private_key_path,
        item_inputs=item_inputs,
        dry_run=dry_run,
    )
