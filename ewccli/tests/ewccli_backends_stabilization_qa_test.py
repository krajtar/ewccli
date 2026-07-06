#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details

"""QA tests for Phase 3 backend stabilization (KAM-18).

Complements ``ewccli_backends_interfaces_test.py`` with gap-filling
coverage: KubernetesBackend interface/lifecycle, backoff timing,
custom retry_on, BackendValidationError propagation, deeper DI
delegation, and no-retry precedence.
"""

import pytest
from unittest.mock import MagicMock, patch

from ewccli.backends.exceptions import (
    BackendConnectionError,
    BackendOperationError,
    BackendTimeoutError,
    BackendNotFoundError,
    BackendValidationError,
)
from ewccli.backends.retry import retry_with_backoff, is_retryable
from ewccli.backends.interfaces import (
    BackendInterface,
    OpenstackBackendInterface,
    KubernetesBackendInterface,
    AnsibleBackendInterface,
)
from ewccli.backends.kubernetes.exceptions import ResourceAlreadyExistsError


# ---------------------------------------------------------------------------
# Kubernetes interface & lifecycle
# ---------------------------------------------------------------------------

class TestKubernetesInterface:
    """Verify KubernetesBackendInterface compliance."""

    def test_kubernetes_interface_is_protocol(self):
        assert hasattr(KubernetesBackendInterface, "_is_protocol")
        assert KubernetesBackendInterface._is_protocol is True

    def test_kubernetes_interface_is_runtime_checkable(self):
        assert hasattr(KubernetesBackendInterface, "_is_runtime_protocol")

    def test_mock_satisfies_kubernetes_interface(self):
        mock = MagicMock(spec=KubernetesBackendInterface)
        mock.create_custom_resource.return_value = {}
        mock.delete_custom_resource.return_value = {}
        mock.describe_custom_resource.return_value = {}
        mock.list_custom_resources.return_value = []
        mock.list_pods.return_value = []
        mock.list_custom_resource_definitions.return_value = []
        mock.connect.return_value = mock
        mock.close.return_value = None
        mock.is_connected.return_value = True
        assert isinstance(mock, KubernetesBackendInterface)


class TestKubernetesConnectionLifecycle:
    """Verify KubernetesBackend connection lifecycle."""

    def test_init_raises_connection_error_on_kubeconfig_failure(self):
        from ewccli.backends.kubernetes.backend_k8s import KubernetesBackend
        with patch(
            "ewccli.backends.kubernetes.backend_k8s.config.load_kube_config",
            side_effect=__import__(
                "kubernetes.config.config_exception", fromlist=["ConfigException"]
            ).ConfigException("no kubeconfig"),
        ):
            with pytest.raises(BackendConnectionError):
                KubernetesBackend()

    def test_init_raises_connection_error_on_token_host_failure(self):
        from ewccli.backends.kubernetes.backend_k8s import KubernetesBackend
        with patch(
            "ewccli.backends.kubernetes.backend_k8s.client.Configuration"
        ) as mock_cfg:
            mock_cfg.return_value.host = ""
            mock_cfg.side_effect = Exception("bad config")
            with pytest.raises(BackendConnectionError):
                KubernetesBackend(token="tok", host="https://k8s.example")

    def test_connect_close_is_connected_cycle(self):
        from ewccli.backends.kubernetes.backend_k8s import KubernetesBackend
        with patch(
            "ewccli.backends.kubernetes.backend_k8s.config.load_kube_config"
        ), patch(
            "ewccli.backends.kubernetes.backend_k8s.client"
        ):
            backend = KubernetesBackend()
            assert backend.is_connected() is True
            assert backend.connect() is backend
            backend.close()
            assert backend.is_connected() is False


# ---------------------------------------------------------------------------
# Backoff timing
# ---------------------------------------------------------------------------

class TestBackoffTiming:
    """Verify exponential backoff and max_delay capping."""

    def test_exponential_backoff_delays(self):
        delays = []

        @retry_with_backoff(
            max_retries=3,
            initial_delay=1.0,
            backoff_factor=2.0,
            max_delay=100.0,
        )
        def func():
            raise BackendConnectionError("transient")

        with patch("ewccli.backends.retry.time.sleep") as mock_sleep:
            mock_sleep.side_effect = lambda d: delays.append(d)
            with pytest.raises(BackendConnectionError):
                func()

        assert delays == [1.0, 2.0, 4.0]
        assert mock_sleep.call_count == 3

    def test_max_delay_caps_backoff(self):
        delays = []

        @retry_with_backoff(
            max_retries=4,
            initial_delay=2.0,
            backoff_factor=3.0,
            max_delay=10.0,
        )
        def func():
            raise BackendTimeoutError("timeout")

        with patch("ewccli.backends.retry.time.sleep") as mock_sleep:
            mock_sleep.side_effect = lambda d: delays.append(d)
            with pytest.raises(BackendTimeoutError):
                func()

        assert delays == [2.0, 6.0, 10.0, 10.0]


# ---------------------------------------------------------------------------
# Custom retry_on
# ---------------------------------------------------------------------------

class TestCustomRetryOn:
    """Verify custom retry_on parameter."""

    def test_retries_on_custom_exception(self):
        call_count = 0

        @retry_with_backoff(
            max_retries=2,
            initial_delay=0,
            retry_on=(BackendNotFoundError,),
        )
        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise BackendNotFoundError("not found")
            return "found"

        assert func() == "found"
        assert call_count == 3

    def test_does_not_retry_non_listed_exception(self):
        call_count = 0

        @retry_with_backoff(
            max_retries=5,
            initial_delay=0,
            retry_on=(BackendTimeoutError,),
        )
        def func():
            nonlocal call_count
            call_count += 1
            raise BackendConnectionError("not in retry_on")

        with pytest.raises(BackendConnectionError):
            func()
        assert call_count == 1


# ---------------------------------------------------------------------------
# No-retry precedence
# ---------------------------------------------------------------------------

class TestNoRetryPrecedence:
    """Verify _NO_RETRY_ON takes precedence over retry_on."""

    def test_no_retry_overrides_retry_on(self):
        call_count = 0

        @retry_with_backoff(
            max_retries=5,
            initial_delay=0,
            retry_on=(BackendOperationError,),
        )
        def func():
            nonlocal call_count
            call_count += 1
            raise BackendOperationError("in both lists")

        with pytest.raises(BackendOperationError):
            func()
        assert call_count == 1


# ---------------------------------------------------------------------------
# BackendValidationError propagation
# ---------------------------------------------------------------------------

class TestBackendValidationError:
    """Verify BackendValidationError raised for long server name."""

    def test_create_server_raises_validation_error(self):
        from ewccli.backends.openstack.backend_ostack import OpenstackBackend
        backend = OpenstackBackend(
            application_credential_id="id",
            application_credential_secret="secret",
            auth_url="https://test.example:5000/v3",
        )
        long_name = "x" * 100
        mock_conn = MagicMock()
        with pytest.raises(BackendValidationError):
            backend.create_server(
                conn=mock_conn,
                server_name=long_name,
                image_name="img",
                flavour_name="flav",
                networks=("net",),
                keypair_name="kp",
                sec_groups=("sg",),
            )


# ---------------------------------------------------------------------------
# ResourceAlreadyExistsError retryability
# ---------------------------------------------------------------------------

class TestResourceAlreadyExistsRetryability:
    """Verify ResourceAlreadyExistsError is not retried by default."""

    def test_not_retryable_by_default(self):
        assert is_retryable(ResourceAlreadyExistsError("exists")) is False

    def test_not_retried_by_decorator(self):
        call_count = 0

        @retry_with_backoff(max_retries=3, initial_delay=0)
        def func():
            nonlocal call_count
            call_count += 1
            raise ResourceAlreadyExistsError("exists")

        with pytest.raises(ResourceAlreadyExistsError):
            func()
        assert call_count == 1


# ---------------------------------------------------------------------------
# BackendInterface base protocol
# ---------------------------------------------------------------------------

class TestBackendInterfaceProtocol:
    """Verify BackendInterface base protocol."""

    def test_is_protocol(self):
        assert hasattr(BackendInterface, "_is_protocol")
        assert BackendInterface._is_protocol is True

    def test_is_runtime_checkable(self):
        assert hasattr(BackendInterface, "_is_runtime_protocol")


# ---------------------------------------------------------------------------
# Deeper DI delegation
# ---------------------------------------------------------------------------

class TestDependencyInjectionDelegation:
    """Verify services delegate to injected interface-typed backends."""

    def test_server_service_delegates_find_latest_image(self):
        from ewccli.services.server_service import ServerService
        mock_backend = MagicMock(spec=OpenstackBackendInterface)
        mock_image = MagicMock()
        mock_image.name = "ubuntu-22.04"
        mock_backend.find_latest_image.return_value = mock_image
        mock_conn = MagicMock()

        code, msg, result = ServerService.resolve_image_and_flavor(
            conn=mock_conn,
            openstack_backend=mock_backend,
            federee="ECMWF",
            region="CC1",
            flavour_name="c2.large",
            image_name="Ubuntu-22.04",
        )

        assert code == 0
        mock_backend.find_latest_image.assert_called_once()

    def test_hub_deploy_service_delegates_run_ansible_live(self):
        from ewccli.services.hub_deploy_service import HubDeployService
        mock_backend = MagicMock(spec=AnsibleBackendInterface)
        mock_backend.run_ansible_live.return_value = 0
        mock_backend.install_ansible_roles.return_value = None
        mock_backend.connect.return_value = mock_backend
        mock_backend.close.return_value = None
        mock_backend.is_connected.return_value = True

        with patch("builtins.open", MagicMock()), patch(
            "ewccli.services.hub_deploy_service.time.sleep"
        ):
            HubDeployService.run_ansible_item(
                item="test-item",
                item_inputs=None,
                server_name="srv",
                ip_machine="10.0.0.1",
                username="ubuntu",
                main_file_path="/fake/main.yml",
                requirements_file_path="/fake/req.yml",
                working_directory_path="/fake",
                ssh_private_key_path="/fake/key",
                ansible_backend=mock_backend,
            )

        mock_backend.install_ansible_roles.assert_called_once()
        mock_backend.run_ansible_live.assert_called_once()
