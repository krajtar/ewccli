"""Hub item deployment service.

Contains catalog validation, source classification, git clone,
ansible execution, and deploy-orchestration logic extracted from
``commands/hub/`` modules.  No click / rich_click imports.
"""

import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse

import requests
import yaml
from openstack import connection

from ewccli.configuration import config as ewc_hub_config
from ewccli.enums import (
    Federee,
    HubItemTechnologyAnnotation,
    HubItemCategoryAnnotation,
    HubItemCLIKeys,
)
from ewccli.backends.ansible.backend_ansible import AnsibleBackend
from ewccli.logger import get_logger
from ewccli.services.exceptions import HubDeployError, ValidationError
from ewccli.utils import run_command_from_host

_LOGGER = get_logger(__name__)


HUB_ENV_VARIABLES_MAP = {
    "os_network_name": {Federee.ECMWF.value: None, Federee.EUMETSAT.value: "private"},
    "os_subnet_name": {
        Federee.ECMWF.value: None,
        Federee.EUMETSAT.value: "private-subnet",
    },
    "os_subnet_cidr": {
        Federee.ECMWF.value: "192.168.1.0/24",
        Federee.EUMETSAT.value: "10.0.0.0/24",
    },
    "dns_domain": {
        Federee.ECMWF.value: None,
        Federee.EUMETSAT.value: None,
    },
}


class HubDeployService:
    """Manage hub item validation, source handling, and deployment."""

    def __init__(self, ansible_backend: AnsibleBackend = None):
        self._ansible_backend = ansible_backend or AnsibleBackend()

    # ------------------------------------------------------------------ #
    # Item input categorization
    # ------------------------------------------------------------------ #
    @staticmethod
    def categorize_item_inputs(
        item_info: dict,
        item_info_inputs: list,
    ) -> Tuple[list, list]:
        """Categorize item inputs into required and default.

        Returns (required_inputs, default_inputs).
        """
        default_inputs = []
        required_inputs = []

        if not item_info_inputs:
            return required_inputs, default_inputs

        for item_input in item_info_inputs:
            if "default" in item_input:
                default_inputs.append(item_input)
            elif item_input.get("name", "") in HUB_ENV_VARIABLES_MAP:
                default_inputs.append(item_input)
            else:
                required_inputs.append(item_input)

        return required_inputs, default_inputs

    # ------------------------------------------------------------------ #
    # Missing input checking
    # ------------------------------------------------------------------ #
    @staticmethod
    def check_missing_required_inputs(
        parsed_inputs: Optional[Dict[str, str]],
        required_item_inputs: List[dict],
    ) -> Optional[List[Any]]:
        """Return list of missing required input names."""
        if not required_item_inputs:
            return []

        required_keys = [
            item_input.get("name") for item_input in required_item_inputs
        ]

        missing_keys = [
            key
            for key in required_keys
            if not parsed_inputs or key not in parsed_inputs
        ]

        return missing_keys

    # ------------------------------------------------------------------ #
    # Input type validation
    # ------------------------------------------------------------------ #
    @staticmethod
    def validate_item_input_types(
        parsed_inputs: Optional[dict],
        item_info_inputs: Optional[list],
    ) -> str:
        """Validate parsed_inputs against a schema using Pydantic.

        Returns "" if valid, otherwise an error string.
        """
        import typing
        from pydantic import ValidationError, create_model

        if not item_info_inputs or not parsed_inputs:
            return ""

        safe_globals = {
            k: getattr(typing, k) for k in dir(typing) if not k.startswith("_")
        }
        safe_globals.update({"Any": Any})

        fields = {}
        expected_types_map = {}

        for entry in item_info_inputs:
            name = entry["name"]
            type_expr = entry["type"]
            expected_types_map[name] = type_expr

            try:
                py_type = eval(type_expr, safe_globals)
            except Exception:
                py_type = Any

            fields[name] = (py_type, ...)

        DynamicInputs = create_model("DynamicInputs", **fields)

        try:
            DynamicInputs(**parsed_inputs)
            return ""

        except ValidationError as e:
            error_lines = []
            for err in e.errors():
                loc = ".".join(str(x) for x in err["loc"])
                msg = err["msg"]
                expected_type = expected_types_map.get(err["loc"][0], "Unknown")
                error_lines.append(
                    f"{loc}: {msg} (expected type: {expected_type})"
                )

            return "Invalid input types:\n  " + "\n  ".join(error_lines)

    # ------------------------------------------------------------------ #
    # Item deployability
    # ------------------------------------------------------------------ #
    @staticmethod
    def verify_item_is_deployable(item_info: dict) -> bool:
        """Verify item is deployable based on technology annotations."""
        annotations = item_info.get("annotations")
        check_deployable = 0

        if annotations:
            technology_annotations = list(annotations.get("technology").split(","))

            for tech_annotation in technology_annotations:
                if tech_annotation in [
                    item.value for item in HubItemTechnologyAnnotation
                ]:
                    check_deployable += 1

                if check_deployable:
                    break

        if not check_deployable:
            _LOGGER.warning(
                "You selected an item that cannot be deployed. "
                f"Only with the following technology annotations are allowed: "
                f"{[item.value for item in HubItemTechnologyAnnotation]}"
                "Exiting."
            )
            return False

        return True

    # ------------------------------------------------------------------ #
    # Annotation extraction
    # ------------------------------------------------------------------ #
    @staticmethod
    def extract_annotations(annotations: Optional[dict] = None):
        """Extract category and technology annotations."""
        annotations_category: List[str] = []
        annotations_technology: List[str] = []

        if not annotations:
            return annotations_category, annotations_technology

        annotations_category = [
            c.strip() for c in annotations.get("category", "").split(",")
        ]
        annotations_technology = [
            c.strip() for c in annotations.get("technology", "").split(",")
        ]

        return annotations_category, annotations_technology

    # ------------------------------------------------------------------ #
    # Source classification
    # ------------------------------------------------------------------ #
    @staticmethod
    def is_github_https_url(source: str) -> bool:
        """Detect HTTPS GitHub URLs (owner/repo format)."""
        if source.endswith(".git"):
            source = source[:-4]
        source = source.rstrip("/")

        parsed = urlparse(source)

        if parsed.scheme != "https":
            return False
        if parsed.netloc != "github.com":
            return False

        parts = parsed.path.strip("/").split("/")
        return len(parts) == 2

    @staticmethod
    def classify_source(source: str) -> str:
        """Classify a source string as 'github', 'directory', or raise.

        Raises ValidationError if source is neither.
        """
        path = Path(source)

        if HubDeployService.is_github_https_url(source):
            return "github"

        if (
            path.exists()
            and path.is_dir()
            and any(path.iterdir())
            and path.is_absolute()
        ):
            return "directory"

        raise ValidationError(
            f"Source provided: {source} is not a valid GitHub repo URL "
            "or an absolute path to a local directory with content."
        )

    # ------------------------------------------------------------------ #
    # Hub environment variable resolution
    # ------------------------------------------------------------------ #
    @staticmethod
    def get_hub_item_env_variable_value(
        hub_item_env_variables_map: dict,
        federee: str,
        tenancy_name: str,
        variable_name: str,
        openstack_api: Optional[connection.Connection] = None,
    ) -> str:
        """Retrieve the value of a HUB_ENV_VARIABLES_MAP variable."""
        os_network_name = "private"
        os_subnetwork_name = "private-subnet"

        if variable_name == "os_network_name" and federee == Federee.ECMWF.value:
            if openstack_api:
                networks = list(openstack_api.network.networks())
                for net in networks:
                    if "private" in net.name.lower():
                        os_network_name = net.name
                raise ValueError("No network containing 'private' found.")

        hub_item_env_variables_map["os_network_name"] = {
            Federee.ECMWF.value: os_network_name,
            Federee.EUMETSAT.value: "private",
        }

        if variable_name == "os_subnet_name" and federee == Federee.ECMWF.value:
            if openstack_api:
                networks = list(openstack_api.network.networks())
                for net in networks:
                    if "private" in net.name.lower():
                        subnets = list(
                            openstack_api.network.subnets(network_id=net.id)
                        )
                        if subnets:
                            os_subnetwork_name = subnets[0].name
                raise ValueError("No subnet found for network containing 'private'.")

        hub_item_env_variables_map["os_subnet_name"] = {
            Federee.ECMWF.value: os_subnetwork_name,
            Federee.EUMETSAT.value: "private-subnet",
        }

        if variable_name == "dns_domain":
            dns_domain = (
                f"{tenancy_name}."
                f"{ewc_hub_config.FEDEREE_DNS_MAPPING[federee]}.ewcloud.host"
            )
            hub_item_env_variables_map["dns_domain"] = {
                federee: dns_domain,
            }

        return hub_item_env_variables_map[variable_name][federee]

    # ------------------------------------------------------------------ #
    # GitHub repo accessibility check
    # ------------------------------------------------------------------ #
    @staticmethod
    def check_github_repo_accessible(source: str) -> bool:
        """Check if a GitHub repository exists and is publicly accessible."""
        if source.endswith(".git"):
            source = source[:-4]
        source = source.rstrip("/")

        api_url = source.replace(
            "https://github.com/", "https://api.github.com/repos/"
        )

        try:
            response = requests.get(api_url, timeout=5)
            if response.status_code == 200:
                _LOGGER.info(f"Repository is accessible: {source}")
                return True
            elif response.status_code == 404:
                _LOGGER.error(f"Repository not found: {source}")
            else:
                _LOGGER.error(
                    f"Unexpected response ({response.status_code}) for: {source}"
                )
        except requests.RequestException as e:
            _LOGGER.error(f"Failed to check repository accessibility: {e}")

        return False

    # ------------------------------------------------------------------ #
    # Git clone
    # ------------------------------------------------------------------ #
    def git_clone_item(
        self,
        source: str,
        repo_name: str,
        command_path: str,
        dry_run: bool = False,
        force: bool = False,
    ) -> Tuple[int, str]:
        """Git clone item."""
        if dry_run:
            return 0, "Dry run: skipping git clone..."

        _LOGGER.info("Git clone item...")

        dir_path = Path(command_path)
        dir_path.mkdir(parents=True, exist_ok=True)

        repo_path = Path(f"{command_path}/{repo_name}")

        if force:
            shutil.rmtree(repo_path)

        if not self.check_github_repo_accessible(source):
            raise HubDeployError(
                f"The repository {source} is not accessible or does not exist."
            )

        if repo_path.exists() and not force:
            return (
                0,
                f"Main Repository {repo_name} already exists at "
                f"{command_path}. Skipping git clone.",
            )

        _LOGGER.info(
            f"Starting to clone the repository '{repo_name}' into "
            f"{command_path}..."
        )
        git_command = [
            f"""[ -d "$(basename '{source}' .git)/.git" ] || git clone '{source}' """
        ]
        return_code, message = run_command_from_host(
            description="git clone repository",
            command=git_command,
            cwd=command_path,
            dry_run=dry_run,
        )

        return return_code, message

    # ------------------------------------------------------------------ #
    # Ansible execution
    # ------------------------------------------------------------------ #
    def run_ansible_item(
        self,
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
    ) -> int:
        """Run item based on Ansible Playbook. Returns exit code."""
        import json

        if dry_run:
            return 0

        # Install roles
        self._ansible_backend.install_ansible_roles(
            requirements_path=requirements_file_path, dry_run=dry_run
        )

        # Create inventory file
        if not ip_machine:
            machine_ips = [""]
        else:
            machine_ips = [ip_machine]

        hosts_file_name = f"hosts-{item}.ini"
        hosts_file_path = f"{working_directory_path}/{hosts_file_name}"
        _LOGGER.debug(f"Saving {hosts_file_name} file to {hosts_file_path}")

        inventory_content = f"[{server_name}]\n"
        inventory_content += "\n".join(machine_ips) + "\n\n"

        _LOGGER.debug(f"Inventory content {inventory_content}")

        with open(hosts_file_path, "w") as f:
            f.write(inventory_content)

        env = {
            "ANSIBLE_HOST_KEY_CHECKING": "False",
            "ANSIBLE_PORT": "2222",
            "ANSIBLE_PYTHON_INTERPRETER": "/usr/bin/python3",
        }

        ansible_command = [
            f"ansible-playbook -i {hosts_file_path} -u {username}"
            f" --private-key {ssh_private_key_path} {main_file_path}"
        ]

        _LOGGER.info(f"Deploying Ansible Playbook item {item}...")
        _LOGGER.info("This could take a few minutes, grab a beverage meanwhile...")

        time.sleep(15)

        if item_inputs:
            extra_vars = json.dumps(item_inputs)
        else:
            extra_vars = ""

        max_attempts = 5
        delay_seconds = 10

        for attempt in range(1, max_attempts + 1):
            _LOGGER.info(f"Running attempt {attempt}/{max_attempts}...")

            return_code = self._ansible_backend.run_ansible_live(
                working_directory_path=f"{working_directory_path}",
                description=ansible_command[0],
                host=server_name,
                cmdline=[
                    "ansible-playbook",
                    "-i",
                    hosts_file_path,
                    "-u",
                    username,
                    "--private-key",
                    ssh_private_key_path,
                    main_file_path,
                ],
                extra_vars=extra_vars,
                env=env,
            )

            if return_code == 0:
                _LOGGER.info(f"Attempt {attempt}/{max_attempts} succeeded.")
                return return_code
            else:
                _LOGGER.warning(f"Attempt {attempt}/{max_attempts} failed")
                if attempt < max_attempts:
                    _LOGGER.info(f"Retrying in {delay_seconds} seconds...")
                    time.sleep(delay_seconds)
                else:
                    _LOGGER.error(
                        f"All attempts failed. EWC CLI could not install "
                        f"{item} Ansible Playbook item."
                    )
                    return_code = 1

        return return_code

    def run_post_ansible_operations(
        self,
        item: str,
        command_path: str,
        repo_name: str,
        server_name: str,
        internal_ip_machine: str,
    ):
        """Run post ansible operation if something goes wrong."""
        hosts_file_name = f"hosts-{item}.ini"
        hosts_file_path = f"{command_path}/{repo_name}/{hosts_file_name}"

        inventory_content = f"[{server_name}]\n"
        inventory_content += "\n".join([internal_ip_machine]) + "\n\n"

        _LOGGER.debug(f"Post run inventory content {inventory_content}")

        with open(hosts_file_path, "w") as f:
            f.write(inventory_content)

    def run_ansible_playbook_item(
        self,
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
        """Deploy Ansible item. Returns (status_code, message)."""
        ansible_return_code = self.run_ansible_item(
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

        if ansible_return_code != 0:
            return ansible_return_code, "Ansible execution failed. Check errors above."

        return 0, "Ansible run successfully"

    # ------------------------------------------------------------------ #
    # Error message helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def prepare_missing_inputs_error_message(missing_inputs: list[str]) -> str:
        """Prepare missing item inputs error message."""
        missing_count = len(missing_inputs)
        lines = [f"Missing {missing_count} required item input(s):"]
        lines += [f"- {input_name}" for input_name in missing_inputs]
        return "\n".join(lines)
