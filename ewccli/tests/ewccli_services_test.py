#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025, 2026 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details


"""Tests for the service-layer modules.

These tests exercise the service classes directly (not through the
CLI wrappers) and verify that no ``click`` / ``rich_click`` imports
leak into the service package.
"""

import os
import base64
import importlib
import pkgutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime

import pytest

from ewccli.services.config_service import ConfigService
from ewccli.services.keypair_service import KeyPairService
from ewccli.services.dns_service import DnsService
from ewccli.services.server_service import ServerService
from ewccli.services.hub_deploy_service import HubDeployService, HUB_ENV_VARIABLES_MAP
from ewccli.services.exceptions import (
    ServiceError,
    ConfigServiceError,
    KeyPairServiceError,
    DnsServiceError,
    ServerServiceError,
    HubDeployServiceError,
)
from ewccli.services import exceptions as exceptions_mod


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class TestServiceExceptions:
    def test_service_error_is_exception(self):
        assert issubclass(ServiceError, Exception)

    def test_subclass_inheritance(self):
        for sub in [
            ConfigServiceError,
            KeyPairServiceError,
            DnsServiceError,
            ServerServiceError,
            HubDeployServiceError,
        ]:
            assert issubclass(sub, ServiceError)


# ---------------------------------------------------------------------------
# ConfigService
# ---------------------------------------------------------------------------

class TestConfigService:
    def test_resolve_profile_explicit(self):
        assert ConfigService.resolve_profile(profile="my-profile") == "my-profile"

    def test_resolve_profile_auto(self):
        result = ConfigService.resolve_profile(
            federee="EUMETSAT", region="R1", tenant_name="team"
        )
        assert result == "eumetsat-r1-team"

    def test_resolve_profile_missing_args(self):
        with pytest.raises(ConfigServiceError):
            ConfigService.resolve_profile(federee="EUMETSAT")

    def test_validate_config_name_valid(self):
        assert ConfigService.validate_config_name("a-b-c-d") == "a-b-c-d"

    def test_validate_config_name_empty(self):
        assert ConfigService.validate_config_name("") == ""

    def test_validate_config_name_invalid(self):
        with pytest.raises(ConfigServiceError):
            ConfigService.validate_config_name("invalid")

    def test_split_config_name_valid(self):
        federee, tenant = ConfigService.split_config_name("fed-tenant-a-b")
        assert federee == "fed"
        assert tenant == "tenant-a-b"

    def test_split_config_name_invalid(self):
        with pytest.raises(ValueError):
            ConfigService.split_config_name("only-three-parts")

    def test_generate_random_id(self):
        rid = ConfigService.generate_random_id()
        assert len(rid) > 10
        assert "-" in rid

    def test_generate_random_id_custom_length(self):
        rid = ConfigService.generate_random_id(length=5)
        # date_part is always the same length, so total length > 5
        assert rid is not None

    def test_save_and_load_profile(self, tmp_path):
        profiles_file = tmp_path / "profiles"
        ConfigService.save_cli_profile(
            federee="EUMETSAT",
            region="R1",
            tenant_name="team",
            ssh_private_key_path_to_save="/tmp/id",
            ssh_public_key_path_to_save="/tmp/id.pub",
            profiles_file_path=profiles_file,
        )
        data = ConfigService.load_cli_profile(
            profile="eumetsat-r1-team",
            profiles_file_path=profiles_file,
        )
        assert data["federee"] == "EUMETSAT"
        assert data["tenant_name"] == "team"

    def test_save_existing_profile_raises(self, tmp_path):
        profiles_file = tmp_path / "profiles"
        kwargs = dict(
            federee="EUMETSAT",
            region="R1",
            tenant_name="team",
            ssh_private_key_path_to_save="/tmp/id",
            ssh_public_key_path_to_save="/tmp/id.pub",
            profiles_file_path=profiles_file,
        )
        ConfigService.save_cli_profile(**kwargs)
        with pytest.raises(ConfigServiceError):
            ConfigService.save_cli_profile(**kwargs)

    def test_load_missing_profile_raises(self, tmp_path):
        with pytest.raises(ConfigServiceError):
            ConfigService.load_cli_profile(
                profile="nonexistent",
                profiles_file_path=tmp_path / "profiles",
            )

    def test_load_dry_run(self):
        data = ConfigService.load_cli_profile(dry_run=True)
        assert data["profile"] == "dry-run"

    def test_save_default_login_profile_skips_existing(self, tmp_path):
        profiles_file = tmp_path / "profiles"
        ConfigService.save_default_login_profile(
            federee="EUMETSAT",
            region="R1",
            tenant_name="team",
            ssh_private_key_path_to_save="/tmp/id",
            ssh_public_key_path_to_save="/tmp/id.pub",
            profiles_file_path=profiles_file,
        )
        # Second call should be a no-op
        ConfigService.save_default_login_profile(
            federee="EUMETSAT",
            region="R1",
            tenant_name="team",
            ssh_private_key_path_to_save="/tmp/id",
            ssh_public_key_path_to_save="/tmp/id.pub",
            profiles_file_path=profiles_file,
        )
        data = ConfigService.load_cli_profile(
            profile="default",
            profiles_file_path=profiles_file,
        )
        assert data["federee"] == "EUMETSAT"


# ---------------------------------------------------------------------------
# KeyPairService
# ---------------------------------------------------------------------------

class TestKeyPairService:
    def test_check_ssh_keys_exist_both_missing(self, tmp_path):
        result = KeyPairService.check_ssh_keys_exist(
            ssh_public_key_path=tmp_path / "missing.pub",
            ssh_private_key_path=tmp_path / "missing",
        )
        assert result is False

    def test_check_ssh_keys_exist_both_present(self, tmp_path):
        priv = tmp_path / "id_rsa"
        pub = tmp_path / "id_rsa.pub"
        priv.write_text("private")
        pub.write_text("public")
        result = KeyPairService.check_ssh_keys_exist(
            ssh_public_key_path=pub,
            ssh_private_key_path=priv,
        )
        assert result is True

    def test_load_ssh_private_key_none_raises(self):
        with pytest.raises(KeyPairServiceError):
            KeyPairService.load_ssh_private_key(encoded_key=None)

    def test_load_ssh_public_key_none_raises(self):
        with pytest.raises(KeyPairServiceError):
            KeyPairService.load_ssh_public_key(encoded_key=None)

    def test_load_ssh_private_key_valid(self):
        encoded = base64.b64encode(b"-----BEGIN KEY-----\ndata\n-----END KEY-----").decode()
        result = KeyPairService.load_ssh_private_key(encoded_key=encoded)
        assert "BEGIN KEY" in result

    def test_load_ssh_public_key_valid(self):
        encoded = base64.b64encode(b"ssh-rsa AAAA").decode()
        result = KeyPairService.load_ssh_public_key(encoded_key=encoded)
        assert "ssh-rsa" in result

    def test_load_ssh_private_key_invalid(self):
        result = KeyPairService.load_ssh_private_key(encoded_key="!!!notbase64!!!")
        assert result is None

    def test_save_ssh_key(self, tmp_path):
        path = tmp_path / "subdir" / "id_rsa"
        KeyPairService.save_ssh_key(ssh_key="secret", path_key=str(path))
        assert path.exists()
        assert path.read_text() == "secret"
        assert oct(path.stat().st_mode & 0o777) == "0o600"

    def test_verify_private_key_invalid_raises(self):
        with pytest.raises(KeyPairServiceError):
            KeyPairService.verify_private_key("not a key")

    def test_generate_ssh_keypair(self, tmp_path, monkeypatch):
        from ewccli.configuration import config as ewc_hub_config
        monkeypatch.setattr(ewc_hub_config, "EWC_CLI_HUB_SSH_REPO_PATH", tmp_path)
        priv, pub = KeyPairService.generate_ssh_keypair(resolved_profile="test")
        assert Path(priv).exists()
        assert Path(pub).exists()
        assert "PRIVATE KEY" in Path(priv).read_text()
        assert Path(pub).read_text().startswith("ssh-")

    def test_check_user_ssh_keys_dry_run(self):
        # Should not raise in dry-run mode
        KeyPairService.check_user_ssh_keys(
            ssh_public_key_path="/nonexistent",
            ssh_private_key_path="/nonexistent",
            dry_run=True,
        )

    def test_check_user_ssh_keys_missing_raises(self):
        with pytest.raises(KeyPairServiceError):
            KeyPairService.check_user_ssh_keys(
                ssh_public_key_path="/nonexistent/pub",
                ssh_private_key_path="/nonexistent/priv",
                dry_run=False,
            )


# ---------------------------------------------------------------------------
# DnsService
# ---------------------------------------------------------------------------

class TestDnsService:
    def test_build_dns_record_name_valid(self):
        result = DnsService.build_dns_record_name("srv", "t1", "fra")
        assert result == "srv.t1.fra.ewcloud.host"

    def test_build_dns_record_name_missing_args(self):
        with pytest.raises(ValueError):
            DnsService.build_dns_record_name("", "t1", "fra")

    def test_wait_for_dns_record_success(self):
        with patch("ewccli.services.dns_service.socket.gethostbyname", return_value="1.2.3.4"):
            with patch("ewccli.services.dns_service.time.sleep"):
                result = DnsService.wait_for_dns_record("test.host", "1.2.3.4", interval=0, timeout_minutes=1)
                assert result is True

    def test_wait_for_dns_record_timeout(self):
        with patch("ewccli.services.dns_service.socket.gethostbyname", side_effect=OSError("not found")):
            with patch("ewccli.services.dns_service.time.sleep"):
                result = DnsService.wait_for_dns_record("test.host", "1.2.3.4", interval=0, timeout_minutes=0)
                assert result is False

    def test_wait_for_dns_record_wrong_ip(self):
        with patch("ewccli.services.dns_service.socket.gethostbyname", return_value="9.9.9.9"):
            with patch("ewccli.services.dns_service.time.sleep"):
                result = DnsService.wait_for_dns_record("test.host", "1.2.3.4", interval=0, timeout_minutes=0)
                assert result is False


# ---------------------------------------------------------------------------
# ServerService
# ---------------------------------------------------------------------------

class TestServerService:
    def test_normalize_os_image_short_name(self):
        from ewccli.configuration import config as ewc_hub_config
        result, is_short = ServerService.normalize_os_image(
            "Ubuntu-22.04", "EUMETSAT", "WAW3-1"
        )
        assert result == "Ubuntu-22.04"
        assert is_short is True

    def test_normalize_os_image_rocky_timestamp(self):
        result, is_short = ServerService.normalize_os_image(
            "Rocky-9.6-20250202020202", "EUMETSAT", "WAW3-1"
        )
        assert result == "Rocky-9"
        assert is_short is False

    def test_normalize_os_image_ubuntu_timestamp(self):
        result, is_short = ServerService.normalize_os_image(
            "Ubuntu-24.04-20250202020202", "EUMETSAT", "WAW3-1"
        )
        assert result == "Ubuntu-24.04"
        assert is_short is False

    def test_normalize_os_image_unrecognized(self):
        result, is_short = ServerService.normalize_os_image(
            "Windows-Server-2022", "EUMETSAT", "WAW3-1"
        )
        assert result is None
        assert is_short is False

    def test_check_server_conflict_no_server(self):
        result = ServerService.check_server_conflict_with_inputs(server_info=None)
        assert result is None

    def test_check_server_conflict_matching(self):
        server = MagicMock()
        server.key_name = "mykey"
        server.flavor.original_name = "m1.small"
        server.addresses = {"private": []}
        server.security_groups = [{"name": "ssh"}]

        diffs = ServerService.check_server_conflict_with_inputs(
            server_info=server,
            server_info_image="Ubuntu-22.04",
            image_name="Ubuntu-22.04",
            keypair_name="mykey",
            flavour_name="m1.small",
        )
        assert diffs == []

    def test_check_server_conflict_mismatch(self):
        server = MagicMock()
        server.key_name = "otherkey"
        server.flavor.original_name = "m1.large"
        server.addresses = {"private": []}
        server.security_groups = [{"name": "ssh"}]

        diffs = ServerService.check_server_conflict_with_inputs(
            server_info=server,
            server_info_image="Ubuntu-22.04",
            image_name="Ubuntu-22.04",
            keypair_name="mykey",
            flavour_name="m1.small",
        )
        assert len(diffs) == 2  # keypair and flavour differ

    def test_get_deployed_server_info_eumetsat(self):
        server_info = {
            "id": "abc123",
            "name": "vm1",
            "flavor": {"original_name": "m1.small"},
            "key_name": "mykey",
            "status": "ACTIVE",
            "addresses": {
                "private": [
                    {"OS-EXT-IPS:type": "fixed", "addr": "10.0.0.5"},
                    {"OS-EXT-IPS:type": "floating", "addr": "1.2.3.4"},
                ]
            },
            "security_groups": [{"name": "ssh"}],
        }
        vm_info = ServerService.get_deployed_server_info(
            federee="EUMETSAT", server_info=server_info, image_name="Ubuntu-22.04"
        )
        assert vm_info["name"] == "vm1"
        assert vm_info["flavor"] == "m1.small"
        assert vm_info["image"] == "Ubuntu-22.04"
        assert "network-private-fixed" in vm_info["networks"]

    def test_get_deployed_server_info_no_addresses(self):
        server_info = {
            "id": "abc",
            "name": "vm",
            "flavor": None,
            "key_name": None,
            "status": "SHUTOFF",
            "addresses": None,
            "security_groups": [],
        }
        vm_info = ServerService.get_deployed_server_info(
            federee="EUMETSAT", server_info=server_info
        )
        assert vm_info["networks"] == {}
        assert vm_info["flavor"] is None

    def test_resolve_machine_ip_eumetsat(self):
        server_info = {
            "addresses": {
                "private": [
                    {"OS-EXT-IPS:type": "fixed", "addr": "10.0.0.5"},
                    {"OS-EXT-IPS:type": "floating", "addr": "1.2.3.4"},
                ]
            }
        }
        code, msg, result = ServerService.resolve_machine_ip("EUMETSAT", server_info)
        assert code == 0
        assert result["internal_ip_machine"] == "10.0.0.5"
        assert result["external_ip_machine"] == "1.2.3.4"

    def test_resolve_machine_ip_no_addresses(self):
        code, msg, result = ServerService.resolve_machine_ip("EUMETSAT", {"addresses": None})
        assert code == 1

    def test_create_server_command_dry_run(self):
        backend = MagicMock()
        conn = MagicMock()
        server_inputs = {
            "server_name": "vm1",
            "keypair_name": "mykey",
            "is_gpu": False,
            "image_name": None,
            "flavour_name": None,
            "external_ip": False,
            "networks": ("private",),
            "security_groups": ("ssh",),
            "item_default_security_groups": (),
        }
        code, msg, outputs = ServerService.create_server_command(
            openstack_backend=backend,
            openstack_api=conn,
            federee="EUMETSAT",
            region="WAW3-1",
            server_inputs=server_inputs,
            ssh_public_key_path="/tmp/id.pub",
            ssh_private_key_path="/tmp/id",
            dry_run=True,
        )
        # In dry_run, pre_deploy returns (0, msg, {}) with empty outputs,
        # so create_server_command returns (1, msg, {})
        assert code == 1


# ---------------------------------------------------------------------------
# HubDeployService
# ---------------------------------------------------------------------------

class TestHubDeployService:
    def test_categorize_item_inputs_no_inputs(self):
        required, default = HubDeployService.categorize_item_inputs(
            item_info={}, item_info_inputs=[]
        )
        assert required == []
        assert default == []

    def test_categorize_item_inputs_with_defaults(self):
        inputs = [
            {"name": "foo", "default": "bar"},
            {"name": "os_network_name"},
            {"name": "required_var"},
        ]
        required, default = HubDeployService.categorize_item_inputs(
            item_info={}, item_info_inputs=inputs
        )
        assert len(required) == 1
        assert required[0]["name"] == "required_var"
        assert len(default) == 2

    def test_check_missing_required_inputs_all_present(self):
        required_inputs = [{"name": "a"}, {"name": "b"}]
        parsed = {"a": "1", "b": "2"}
        missing = HubDeployService.check_missing_required_inputs(parsed, required_inputs)
        assert missing == []

    def test_check_missing_required_inputs_some_missing(self):
        required_inputs = [{"name": "a"}, {"name": "b"}]
        parsed = {"a": "1"}
        missing = HubDeployService.check_missing_required_inputs(parsed, required_inputs)
        assert "b" in missing

    def test_check_missing_required_inputs_no_required(self):
        missing = HubDeployService.check_missing_required_inputs(None, [])
        assert missing == []

    def test_validate_item_input_types_valid(self):
        schema = [{"name": "foo", "type": "str"}]
        result = HubDeployService.validate_item_input_types({"foo": "bar"}, schema)
        assert result == ""

    def test_validate_item_input_types_empty(self):
        result = HubDeployService.validate_item_input_types(None, None)
        assert result == ""

    def test_validate_item_input_types_invalid(self):
        schema = [{"name": "count", "type": "int"}]
        result = HubDeployService.validate_item_input_types({"count": "not-a-number"}, schema)
        assert "Invalid input types" in result

    def test_verify_item_is_deployable_ansible(self):
        item_info = {"annotations": {"technology": "Ansible Playbook"}}
        assert HubDeployService.verify_item_is_deployable(item_info) is True

    def test_verify_item_is_deployable_not_deployable(self):
        item_info = {"annotations": {"technology": "unknown"}}
        assert HubDeployService.verify_item_is_deployable(item_info) is False

    def test_verify_item_is_deployable_no_annotations(self):
        item_info = {}
        assert HubDeployService.verify_item_is_deployable(item_info) is False

    def test_extract_annotations_none(self):
        cat, tech = HubDeployService.extract_annotations(None)
        assert cat == []
        assert tech == []

    def test_extract_annotations_with_data(self):
        cat, tech = HubDeployService.extract_annotations(
            {"category": "gpu, storage", "technology": "ansible"}
        )
        assert "gpu" in cat
        assert "storage" in cat
        assert "ansible" in tech

    def test_is_github_https_url_valid(self):
        assert HubDeployService.is_github_https_url("https://github.com/user/repo") is True

    def test_is_github_https_url_with_git(self):
        assert HubDeployService.is_github_https_url("https://github.com/user/repo.git") is True

    def test_is_github_https_url_http(self):
        assert HubDeployService.is_github_https_url("http://github.com/user/repo") is False

    def test_is_github_https_url_non_github(self):
        assert HubDeployService.is_github_https_url("https://gitlab.com/user/repo") is False

    def test_classify_source_github(self):
        assert HubDeployService.classify_source("https://github.com/user/repo") == "github"

    def test_classify_source_invalid(self):
        with pytest.raises(HubDeployServiceError):
            HubDeployService.classify_source("not-a-valid-source")

    def test_prepare_missing_inputs_error_message(self):
        msg = HubDeployService.prepare_missing_inputs_error_message(["a", "b"])
        assert "Missing 2" in msg
        assert "- a" in msg
        assert "- b" in msg

    def test_get_hub_item_env_variable_value_static(self):
        result = HubDeployService.get_hub_item_env_variable_value(
            hub_item_env_variables_map=dict(HUB_ENV_VARIABLES_MAP),
            federee="EUMETSAT",
            tenancy_name="team",
            variable_name="os_subnet_cidr",
        )
        assert result == "10.0.0.0/24"

    def test_check_github_repo_accessible_invalid_url(self):
        result = HubDeployService.check_github_repo_accessible("https://github.com/nonexistent/repo12345")
        assert result is False

    def test_git_clone_item_dry_run(self):
        code, msg = HubDeployService.git_clone_item(
            source="https://github.com/user/repo",
            repo_name="repo",
            command_path="/tmp/test",
            dry_run=True,
        )
        assert code == 0
        assert "Dry run" in msg


# ---------------------------------------------------------------------------
# Automated check: no click / rich_click imports in service modules
# ---------------------------------------------------------------------------

class TestNoClickImportsInServices:
    """Verify that no service-layer module imports click or rich_click."""

    @staticmethod
    def _get_service_modules():
        """Return list of module objects for all files in ewccli/services/."""
        import ewccli.services as services_pkg
        modules = []
        for info in pkgutil.iter_modules(services_pkg.__path__):
            mod = importlib.import_module(f"ewccli.services.{info.name}")
            modules.append(mod)
        return modules

    def test_no_click_import(self):
        for mod in self._get_service_modules():
            source = open(mod.__file__).read()
            assert "import click" not in source, f"{mod.__name__} imports click"
            assert "from click" not in source, f"{mod.__name__} imports from click"
            assert "import rich_click" not in source, f"{mod.__name__} imports rich_click"
            assert "from rich_click" not in source, f"{mod.__name__} imports from rich_click"
