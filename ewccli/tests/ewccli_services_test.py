"""Tests for the service layer modules.

Verifies that service modules contain no click/rich_click imports and
that business logic functions work correctly when called directly.
"""

import pytest
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

from ewccli.services.config_service import ConfigService
from ewccli.services.keypair_service import KeyPairService
from ewccli.services.dns_service import DnsService
from ewccli.services.server_service import ServerService
from ewccli.services.hub_deploy_service import HubDeployService
from ewccli.services.exceptions import (
    ServiceError,
    ConfigError,
    ValidationError,
    KeyPairError,
    DnsError,
    ServerOperationError,
    HubDeployError,
)


# ------------------------------------------------------------------ #
# Exception hierarchy
# ------------------------------------------------------------------ #
class TestServiceExceptions:
    def test_all_inherit_from_service_error(self):
        for exc in [
            ConfigError,
            ValidationError,
            KeyPairError,
            DnsError,
            ServerOperationError,
            HubDeployError,
        ]:
            assert issubclass(exc, ServiceError)

    def test_server_operation_error_carries_diffs(self):
        err = ServerOperationError("conflict", diffs=[("Image", "A", "B")], server_name="vm1")
        assert err.diffs == [("Image", "A", "B")]
        assert err.server_name == "vm1"
        assert str(err) == "conflict"


# ------------------------------------------------------------------ #
# ConfigService
# ------------------------------------------------------------------ #
class TestConfigService:
    def test_resolve_profile_explicit(self):
        assert ConfigService.resolve_profile(profile="myprofile") == "myprofile"

    def test_resolve_profile_auto(self):
        result = ConfigService.resolve_profile(
            federee="EUMETSAT", region="ECIS-R1", tenant_name="my-tenant"
        )
        assert result == "eumetsat-ecis-r1-my-tenant"

    def test_resolve_profile_missing_args(self):
        with pytest.raises(ConfigError):
            ConfigService.resolve_profile(federee="EUMETSAT")

    def test_split_config_name(self):
        federee, tenant = ConfigService.split_config_name("ECMWF-part1-part2-part3")
        assert federee == "ECMWF"
        assert tenant == "part1-part2-part3"

    def test_split_config_name_invalid(self):
        with pytest.raises(ValueError):
            ConfigService.split_config_name("invalid")

    def test_save_and_load_profile(self, tmp_path):
        svc = ConfigService(profiles_path=tmp_path / "profiles")
        svc.save_cli_profile(
            federee="EUMETSAT",
            region="ECIS-R1",
            tenant_name="my-tenant",
            ssh_private_key_path_to_save="/tmp/id_rsa",
            ssh_public_key_path_to_save="/tmp/id_rsa.pub",
            profile="test-profile",
        )
        loaded = svc.load_cli_profile(profile="test-profile")
        assert loaded["federee"] == "EUMETSAT"
        assert loaded["region"] == "ECIS-R1"
        assert loaded["tenant_name"] == "my-tenant"

    def test_load_cli_profile_not_found(self, tmp_path):
        svc = ConfigService(profiles_path=tmp_path / "profiles")
        svc.save_cli_profile(
            federee="EUMETSAT",
            region="ECIS-R1",
            tenant_name="t",
            ssh_private_key_path_to_save="/tmp/id",
            ssh_public_key_path_to_save="/tmp/id.pub",
            profile="default",
        )
        with pytest.raises(ConfigError):
            svc.load_cli_profile(profile="nonexistent")

    def test_load_cli_profile_dry_run(self):
        svc = ConfigService()
        result = svc.load_cli_profile(dry_run=True)
        assert result["profile"] == "dry-run"


# ------------------------------------------------------------------ #
# DnsService
# ------------------------------------------------------------------ #
class TestDnsService:
    def test_build_dns_record_name(self):
        result = DnsService.build_dns_record_name("server1", "tenancyA", "fra")
        assert result == "server1.tenancyA.fra.ewcloud.host"

    def test_build_dns_record_name_missing_args(self):
        with pytest.raises(DnsError):
            DnsService.build_dns_record_name(None, "t1", "fra")

    @patch("socket.gethostbyname", return_value="1.2.3.4")
    @patch("time.sleep", return_value=None)
    def test_wait_for_dns_record_success(self, mock_sleep, mock_gethost):
        assert DnsService.wait_for_dns_record("test.host", "1.2.3.4") is True

    @patch("socket.gethostbyname", side_effect=socket.gaierror())
    @patch("time.sleep", return_value=None)
    def test_wait_for_dns_record_timeout(self, mock_sleep, mock_gethost):
        import socket
        assert DnsService.wait_for_dns_record("test.host", "1.2.3.4", timeout_minutes=0) is False


# ------------------------------------------------------------------ #
# KeyPairService
# ------------------------------------------------------------------ #
class TestKeyPairService:
    def test_check_ssh_keys_exist_both_missing(self, tmp_path):
        svc = KeyPairService()
        assert svc.check_ssh_keys_exist(tmp_path / "pub", tmp_path / "priv") is False

    def test_check_ssh_keys_exist_both_exist(self, tmp_path):
        pub = tmp_path / "id.pub"
        priv = tmp_path / "id"
        pub.write_text("pub")
        priv.write_text("priv")
        svc = KeyPairService()
        assert svc.check_ssh_keys_exist(pub, priv) is True

    def test_check_user_ssh_keys_dry_run(self):
        svc = KeyPairService()
        svc.check_user_ssh_keys(dry_run=True)  # should not raise


# ------------------------------------------------------------------ #
# ServerService
# ------------------------------------------------------------------ #
class TestServerService:
    def test_normalize_os_image_short_cpu(self):
        result, is_short = ServerService.normalize_os_image(
            "Rocky-9", "EUMETSAT", "WAW3-1"
        )
        assert result == "Rocky-9"
        assert is_short is True

    def test_normalize_os_image_rocky_timestamp(self):
        result, is_short = ServerService.normalize_os_image(
            "Rocky-9.6-20251107141503", "EUMETSAT", "WAW3-1"
        )
        assert result == "Rocky-9"
        assert is_short is False

    def test_normalize_os_image_ubuntu_timestamp(self):
        result, is_short = ServerService.normalize_os_image(
            "Ubuntu-24.04-20251107141503", "EUMETSAT", "WAW3-1"
        )
        assert result == "Ubuntu-24.04"
        assert is_short is False

    def test_normalize_os_image_unknown(self):
        result, is_short = ServerService.normalize_os_image(
            "UnknownOS", "EUMETSAT", "WAW3-1"
        )
        assert result is None
        assert is_short is False

    def test_resolve_machine_ip_no_addresses(self):
        sc, msg, result = ServerService.resolve_machine_ip(
            "EUMETSAT", {"addresses": None}
        )
        assert sc == 1
        assert result is None

    def test_get_deployed_server_info_basic(self):
        server_info = {
            "id": "123",
            "name": "vm1",
            "flavor": {"original_name": "m1.small"},
            "key_name": "mykey",
            "status": "ACTIVE",
            "addresses": {},
            "security_groups": [{"name": "ssh"}],
        }
        vm_info = ServerService.get_deployed_server_info(
            "EUMETSAT", server_info, image_name="Ubuntu-22.04"
        )
        assert vm_info["id"] == "123"
        assert vm_info["name"] == "vm1"
        assert vm_info["flavor"] == "m1.small"
        assert vm_info["image"] == "Ubuntu-22.04"
        assert vm_info["security-groups"] == ["ssh"]

    def test_check_server_conflict_no_server(self):
        assert ServerService.check_server_conflict_with_inputs(None) is None


# ------------------------------------------------------------------ #
# HubDeployService
# ------------------------------------------------------------------ #
class TestHubDeployService:
    def test_categorize_item_inputs_empty(self):
        required, default = HubDeployService.categorize_item_inputs({}, [])
        assert required == []
        assert default == []

    def test_categorize_item_inputs_with_defaults(self):
        inputs = [
            {"name": "required_var", "type": "str"},
            {"name": "default_var", "type": "str", "default": "value"},
        ]
        required, default = HubDeployService.categorize_item_inputs({}, inputs)
        assert len(required) == 1
        assert required[0]["name"] == "required_var"
        assert len(default) == 1
        assert default[0]["name"] == "default_var"

    def test_check_missing_required_inputs_all_provided(self):
        required = [{"name": "var1"}, {"name": "var2"}]
        parsed = {"var1": "val1", "var2": "val2"}
        missing = HubDeployService.check_missing_required_inputs(parsed, required)
        assert missing == []

    def test_check_missing_required_inputs_some_missing(self):
        required = [{"name": "var1"}, {"name": "var2"}]
        parsed = {"var1": "val1"}
        missing = HubDeployService.check_missing_required_inputs(parsed, required)
        assert "var2" in missing

    def test_validate_item_input_types_valid(self):
        schema = [{"name": "count", "type": "int"}]
        parsed = {"count": 5}
        assert HubDeployService.validate_item_input_types(parsed, schema) == ""

    def test_validate_item_input_types_empty(self):
        assert HubDeployService.validate_item_input_types(None, None) == ""

    def test_extract_annotations_none(self):
        cat, tech = HubDeployService.extract_annotations(None)
        assert cat == []
        assert tech == []

    def test_extract_annotations_with_data(self):
        annotations = {"category": "GPU-accelerated", "technology": "Ansible Playbook"}
        cat, tech = HubDeployService.extract_annotations(annotations)
        assert "GPU-accelerated" in cat
        assert "Ansible Playbook" in tech

    def test_is_github_https_url_valid(self):
        assert HubDeployService.is_github_https_url("https://github.com/user/repo") is True
        assert HubDeployService.is_github_https_url("https://github.com/user/repo.git") is True

    def test_is_github_https_url_invalid(self):
        assert HubDeployService.is_github_https_url("http://github.com/user/repo") is False
        assert HubDeployService.is_github_https_url("https://gitlab.com/user/repo") is False

    def test_classify_source_github(self):
        assert HubDeployService.classify_source("https://github.com/user/repo") == "github"

    def test_classify_source_invalid(self):
        with pytest.raises(ValidationError):
            HubDeployService.classify_source("not-a-valid-source")

    def test_verify_item_is_deployable_ansible(self):
        item_info = {"annotations": {"technology": "Ansible Playbook"}}
        assert HubDeployService.verify_item_is_deployable(item_info) is True

    def test_verify_item_is_deployable_not_deployable(self):
        item_info = {"annotations": {"technology": "Something Else"}}
        assert HubDeployService.verify_item_is_deployable(item_info) is False

    def test_prepare_missing_inputs_error_message(self):
        msg = HubDeployService.prepare_missing_inputs_error_message(["var1", "var2"])
        assert "Missing 2" in msg
        assert "var1" in msg
        assert "var2" in msg


# ------------------------------------------------------------------ #
# No click imports in service modules
# ------------------------------------------------------------------ #
class TestNoClickImports:
    def test_no_click_imports_in_services(self):
        import importlib
        import pkgutil
        import ewccli.services

        for importer, modname, ispkg in pkgutil.iter_modules(
            ewccli.services.__path__
        ):
            full_name = f"ewccli.services.{modname}"
            mod = importlib.import_module(full_name)
            source = open(mod.__file__).read()
            # Check for actual import statements (not docstring mentions)
            for line in source.split("\n"):
                stripped = line.lstrip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                if stripped.startswith("import click") or stripped.startswith("from click"):
                    pytest.fail(f"Found click import in {full_name}: {line}")
                if stripped.startswith("import rich_click") or stripped.startswith("from rich_click"):
                    pytest.fail(f"Found rich_click import in {full_name}: {line}")
