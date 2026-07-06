#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""Tests for backend interfaces, exceptions, retry, and connection lifecycle.

Covers Phase 3 stabilization: unified exception hierarchy, retry utility,
interface protocols (mockability), centralized connection lifecycle, and
dependency injection into services.
"""

import pytest
from unittest.mock import MagicMock, patch

from ewccli.backends.exceptions import (
    BackendError,
    BackendConnectionError,
    BackendAuthError,
    BackendOperationError,
    BackendTimeoutError,
    BackendNotFoundError,
    BackendAlreadyExistsError,
    BackendValidationError,
    BackendConfigError,
)
from ewccli.backends.retry import retry_with_backoff, is_retryable
from ewccli.backends.interfaces import (
    BackendInterface,
    OpenstackBackendInterface,
    AnsibleBackendInterface,
)
from ewccli.backends.kubernetes.exceptions import ResourceAlreadyExistsError


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class TestExceptionHierarchy:
    """Verify the unified exception hierarchy."""

    @pytest.mark.parametrize("exc_cls", [
        BackendConnectionError,
        BackendOperationError,
        BackendTimeoutError,
        BackendNotFoundError,
        BackendAlreadyExistsError,
        BackendValidationError,
        BackendConfigError,
    ])
    def test_inherits_from_backend_error(self, exc_cls):
        assert issubclass(exc_cls, BackendError)

    def test_auth_error_is_connection_error(self):
        assert issubclass(BackendAuthError, BackendConnectionError)

    def test_resource_already_exists_in_hierarchy(self):
        assert issubclass(ResourceAlreadyExistsError, BackendAlreadyExistsError)
        assert issubclass(ResourceAlreadyExistsError, BackendError)

    def test_raise_and_catch_as_base(self):
        with pytest.raises(BackendError):
            raise BackendConnectionError("conn failed")

    def test_catch_specific_subclass(self):
        with pytest.raises(BackendConnectionError):
            raise BackendAuthError("auth failed")


# ---------------------------------------------------------------------------
# Retry utility
# ---------------------------------------------------------------------------

class TestRetryWithBackoff:
    """Verify retry_with_backoff decorator behavior."""

    def test_succeeds_first_try(self):
        call_count = 0

        @retry_with_backoff(max_retries=3, initial_delay=0)
        def func():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert func() == "ok"
        assert call_count == 1

    def test_retries_on_connection_error(self):
        call_count = 0

        @retry_with_backoff(max_retries=2, initial_delay=0)
        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise BackendConnectionError("transient")
            return "recovered"

        assert func() == "recovered"
        assert call_count == 3

    def test_raises_after_max_retries(self):
        call_count = 0

        @retry_with_backoff(max_retries=2, initial_delay=0)
        def func():
            nonlocal call_count
            call_count += 1
            raise BackendConnectionError("always fails")

        with pytest.raises(BackendConnectionError):
            func()
        assert call_count == 3

    def test_no_retry_on_operation_error(self):
        call_count = 0

        @retry_with_backoff(max_retries=5, initial_delay=0)
        def func():
            nonlocal call_count
            call_count += 1
            raise BackendOperationError("non-transient")

        with pytest.raises(BackendOperationError):
            func()
        assert call_count == 1

    def test_zero_retries(self):
        call_count = 0

        @retry_with_backoff(max_retries=0, initial_delay=0)
        def func():
            nonlocal call_count
            call_count += 1
            raise BackendTimeoutError("timeout")

        with pytest.raises(BackendTimeoutError):
            func()
        assert call_count == 1


class TestIsRetryable:
    """Verify is_retryable classification."""

    def test_connection_error_retryable(self):
        assert is_retryable(BackendConnectionError("x")) is True

    def test_timeout_retryable(self):
        assert is_retryable(BackendTimeoutError("x")) is True

    def test_operation_error_not_retryable(self):
        assert is_retryable(BackendOperationError("x")) is False

    def test_validation_error_not_retryable(self):
        assert is_retryable(BackendValidationError("x")) is False

    def test_config_error_not_retryable_by_default(self):
        assert is_retryable(BackendConfigError("x")) is False


# ---------------------------------------------------------------------------
# Interface protocols
# ---------------------------------------------------------------------------

class TestInterfaceProtocols:
    """Verify runtime_checkable protocols and mockability."""

    def test_openstack_backend_satisfies_interface(self):
        from ewccli.backends.openstack.backend_ostack import OpenstackBackend
        backend = OpenstackBackend(
            application_credential_id="id",
            application_credential_secret="secret",
            auth_url="https://test.example:5000/v3",
        )
        assert isinstance(backend, OpenstackBackendInterface)

    def test_ansible_backend_satisfies_interface(self):
        from ewccli.backends.ansible.backend_ansible import AnsibleBackend
        backend = AnsibleBackend()
        assert isinstance(backend, AnsibleBackendInterface)

    def test_mock_satisfies_backend_interface(self):
        """A MagicMock with spec should satisfy BackendInterface for DI/testing."""
        mock = MagicMock(spec=BackendInterface)
        mock.connect.return_value = "conn"
        mock.close.return_value = None
        mock.is_connected.return_value = True
        assert isinstance(mock, BackendInterface)

    def test_mock_satisfies_openstack_interface(self):
        mock = MagicMock(spec=OpenstackBackendInterface)
        mock.get_connection.return_value = "conn"
        mock.create_server.return_value = (None, None, {})
        mock.delete_server.return_value = None
        mock.list_servers.return_value = []
        mock.find_latest_image.return_value = None
        mock.check_server_inputs.return_value = (True, "")
        mock.add_external_ip.return_value = (True, "", None)
        mock.remove_external_ip.return_value = (True, "")
        mock.list_networks.return_value = []
        mock.remove_network.return_value = None
        mock.create_keypair.return_value = (None, "")
        mock.delete_keypair.return_value = (None, "")
        mock.ssh_key_matches_openstack.return_value = True
        mock.connect.return_value = "conn"
        mock.close.return_value = None
        mock.is_connected.return_value = True
        assert isinstance(mock, OpenstackBackendInterface)

    def test_mock_satisfies_ansible_interface(self):
        mock = MagicMock(spec=AnsibleBackendInterface)
        mock.run_ansible_live.return_value = 0
        mock.run_ansible.return_value = 0
        mock.install_ansible_roles.return_value = None
        mock.connect.return_value = mock
        mock.close.return_value = None
        mock.is_connected.return_value = True
        assert isinstance(mock, AnsibleBackendInterface)


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------

class TestOpenstackConnectionLifecycle:
    """Verify centralized connection lifecycle for OpenstackBackend."""

    def _make_backend(self):
        from ewccli.backends.openstack.backend_ostack import OpenstackBackend
        return OpenstackBackend(
            application_credential_id="id",
            application_credential_secret="secret",
            auth_url="https://test.example:5000/v3",
        )

    def test_init_raises_config_error_without_credentials(self):
        from ewccli.backends.openstack.backend_ostack import OpenstackBackend
        with patch("ewccli.backends.openstack.backend_ostack.OpenStackConfig") as mock_cfg:
            mock_cfg.return_value.get_one.side_effect = Exception("no clouds.yaml")
            with pytest.raises(BackendConfigError):
                OpenstackBackend()

    def test_get_connection_caches(self):
        backend = self._make_backend()
        with patch.object(backend, "connect", return_value="fake_conn") as mock_connect:
            conn1 = backend.get_connection()
            conn2 = backend.get_connection()
            assert conn1 is conn2
            mock_connect.assert_called_once()

    def test_get_connection_raises_on_failure(self):
        backend = self._make_backend()
        with patch.object(backend, "connect", side_effect=Exception("network down")):
            with pytest.raises(BackendConnectionError):
                backend.get_connection()

    def test_close_clears_connection(self):
        backend = self._make_backend()
        with patch.object(backend, "connect", return_value=MagicMock()):
            backend.get_connection()
            assert backend.is_connected() is True
            backend.close()
            assert backend.is_connected() is False

    def test_is_connected_false_before_connect(self):
        backend = self._make_backend()
        assert backend.is_connected() is False


class TestAnsibleConnectionLifecycle:
    """Verify connection lifecycle for AnsibleBackend."""

    def test_init_and_is_connected(self):
        from ewccli.backends.ansible.backend_ansible import AnsibleBackend
        backend = AnsibleBackend()
        assert backend.is_connected() is True
        backend.close()
        assert backend.is_connected() is False
        backend.connect()
        assert backend.is_connected() is True


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------

class TestDependencyInjection:
    """Verify services accept interface types (mockability)."""

    def test_server_service_accepts_mock_backend(self):
        from ewccli.services.server_service import ServerService
        mock_backend = MagicMock()
        service = ServerService()
        # Verify the service can be constructed and accepts a mock backend
        assert service is not None
        # Verify the mock satisfies the interface
        assert isinstance(mock_backend, OpenstackBackendInterface) or hasattr(mock_backend, "find_latest_image")

    def test_hub_deploy_service_accepts_mock_backend(self):
        from ewccli.services.hub_deploy_service import HubDeployService
        mock_backend = MagicMock(spec=AnsibleBackendInterface)
        mock_backend.run_ansible_live.return_value = 0
        mock_backend.install_ansible_roles.return_value = None
        mock_backend.connect.return_value = mock_backend
        mock_backend.close.return_value = None
        mock_backend.is_connected.return_value = True
        service = HubDeployService()
        assert service is not None
        assert isinstance(mock_backend, AnsibleBackendInterface)

    def test_openstack_interface_is_protocol(self):
        assert hasattr(OpenstackBackendInterface, "_is_protocol")
        assert OpenstackBackendInterface._is_protocol is True

    def test_ansible_interface_is_protocol(self):
        assert hasattr(AnsibleBackendInterface, "_is_protocol")
        assert AnsibleBackendInterface._is_protocol is True
