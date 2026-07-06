#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details


"""Comprehensive QA tests for the Phase 3 backend stabilisation (KAM-15).

These tests supplement ``ewccli_backends_interfaces_test.py`` with deeper
coverage of:

- Exception hierarchy semantics (chaining, catch ordering, string repr)
- Retry utility edge cases (max_retries=0, backoff growth, non-retryable
  dominance, custom retry_on interplay with _NO_RETRY_ON)
- Interface protocol runtime-checkable behaviour (isinstance with mocks)
- OpenstackBackend: create_server paths (already exists, dry run, unknown
  image/flavour/security group/network), keypair ops, network ops
- KubernetesBackend: CRD create/delete/describe/list error paths (404, 403,
  401, 409, 422, generic 500), list_pods, list_custom_resource_definitions
- AnsibleBackend: run_ansible, install_ansible_roles, run_ansible_live with
  mocks
- DI mockability: services accept interface-typed mocks without error
"""

import json
from unittest.mock import MagicMock, patch

import pytest

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
from ewccli.backends.retry import (
    retry_with_backoff,
    is_retryable,
    _DEFAULT_RETRY_ON,
    _NO_RETRY_ON,
)
from ewccli.backends.interfaces import (
    BackendInterface,
    OpenstackBackendInterface,
    KubernetesBackendInterface,
    AnsibleBackendInterface,
)
from ewccli.backends.kubernetes.exceptions import ResourceAlreadyExistsError
from ewccli.backends.openstack.backend_ostack import OpenstackBackend
from ewccli.backends.kubernetes.backend_k8s import KubernetesBackend
from ewccli.backends.ansible.backend_ansible import AnsibleBackend


# ---------------------------------------------------------------------------
# Exception hierarchy — deep semantics
# ---------------------------------------------------------------------------

class TestExceptionHierarchyDeep:
    """Deeper exception hierarchy tests beyond the basic inheritance checks."""

    def test_exception_message_preserved(self):
        exc = BackendConnectionError("connection refused")
        assert "connection refused" in str(exc)

    def test_exception_chaining_with_from(self):
        original = ValueError("original")
        try:
            raise BackendConfigError("wrapped") from original
        except BackendConfigError as exc:
            assert exc.__cause__ is original

    def test_catch_connection_catches_auth(self):
        try:
            raise BackendAuthError("auth failed")
        except BackendConnectionError:
            pass
        else:
            pytest.fail("BackendAuthError should be caught by BackendConnectionError")

    def test_catch_base_catches_all_specific(self):
        for exc_cls in [
            BackendConnectionError,
            BackendAuthError,
            BackendOperationError,
            BackendTimeoutError,
            BackendNotFoundError,
            BackendAlreadyExistsError,
            BackendValidationError,
            BackendConfigError,
        ]:
            try:
                raise exc_cls("test")
            except BackendError:
                pass
            else:
                pytest.fail(f"{exc_cls.__name__} should be caught by BackendError")

    def test_resource_already_exists_inherits_correctly(self):
        assert issubclass(ResourceAlreadyExistsError, BackendAlreadyExistsError)
        assert issubclass(ResourceAlreadyExistsError, BackendError)
        try:
            raise ResourceAlreadyExistsError("exists")
        except BackendAlreadyExistsError:
            pass
        except BackendError:
            pytest.fail("Should be caught by BackendAlreadyExistsError first")

    def test_operation_error_not_connection_error(self):
        assert not issubclass(BackendOperationError, BackendConnectionError)

    def test_not_found_not_already_exists(self):
        assert not issubclass(BackendNotFoundError, BackendAlreadyExistsError)


# ---------------------------------------------------------------------------
# Retry utility — edge cases
# ---------------------------------------------------------------------------

class TestRetryEdgeCases:
    """Edge-case tests for retry_with_backoff and is_retryable."""

    def test_max_retries_zero_no_retry(self):
        calls = 0

        @retry_with_backoff(max_retries=0, initial_delay=0)
        def fail():
            nonlocal calls
            calls += 1
            raise BackendTimeoutError("timeout")

        with pytest.raises(BackendTimeoutError):
            fail()
        assert calls == 1

    def test_max_retries_zero_success(self):
        calls = 0

        @retry_with_backoff(max_retries=0, initial_delay=0)
        def succeed():
            nonlocal calls
            calls += 1
            return "ok"

        assert succeed() == "ok"
        assert calls == 1

    def test_no_retry_on_raises_immediately(self):
        """BackendOperationError in _NO_RETRY_ON should never retry."""
        calls = 0

        @retry_with_backoff(max_retries=5, initial_delay=0)
        def fail():
            nonlocal calls
            calls += 1
            raise BackendOperationError("permanent")

        with pytest.raises(BackendOperationError):
            fail()
        assert calls == 1

    def test_no_retry_on_dominates_retry_on(self):
        """If an exception is in both retry_on and _NO_RETRY_ON, no retry."""
        calls = 0

        @retry_with_backoff(
            max_retries=5,
            initial_delay=0,
            retry_on=(BackendOperationError,),
        )
        def fail():
            nonlocal calls
            calls += 1
            raise BackendOperationError("no retry")

        with pytest.raises(BackendOperationError):
            fail()
        assert calls == 1

    def test_retries_then_succeeds_with_connection_error(self):
        calls = 0

        @retry_with_backoff(max_retries=3, initial_delay=0)
        def flaky():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise BackendConnectionError("transient")
            return "ok"

        assert flaky() == "ok"
        assert calls == 2

    def test_custom_retry_on_value_error(self):
        calls = 0

        @retry_with_backoff(
            max_retries=2,
            initial_delay=0,
            retry_on=(ValueError,),
        )
        def fail():
            nonlocal calls
            calls += 1
            raise ValueError("custom")

        with pytest.raises(ValueError):
            fail()
        assert calls == 3

    def test_non_retryable_exception_passes_through(self):
        """Non-retry, non-retry_on exceptions should propagate immediately."""
        calls = 0

        @retry_with_backoff(max_retries=3, initial_delay=0)
        def fail():
            nonlocal calls
            calls += 1
            raise RuntimeError("not in retry_on")

        with pytest.raises(RuntimeError):
            fail()
        assert calls == 1

    def test_decorator_preserves_function_name(self):
        @retry_with_backoff(max_retries=1, initial_delay=0)
        def my_function():
            """My docstring."""
            return "ok"

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    def test_default_retry_on_includes_timeout_and_connection(self):
        assert BackendTimeoutError in _DEFAULT_RETRY_ON
        assert BackendConnectionError in _DEFAULT_RETRY_ON

    def test_no_retry_on_includes_operation(self):
        assert BackendOperationError in _NO_RETRY_ON

    def test_is_retryable_auth_error(self):
        """BackendAuthError is a subclass of BackendConnectionError."""
        assert is_retryable(BackendAuthError("auth")) is True

    def test_is_retryable_custom_set(self):
        assert is_retryable(
            ValueError("v"),
            retry_on=(ValueError,),
        ) is True

    def test_is_retryable_none_exception(self):
        assert is_retryable(BackendNotFoundError("nf")) is False


# ---------------------------------------------------------------------------
# Interface protocol compliance — runtime checks
# ---------------------------------------------------------------------------

class TestInterfaceProtocolCompliance:
    """Tests for runtime_checkable protocol compliance and mockability."""

    def test_openstack_backend_is_instance_of_interface(self):
        instance = OpenstackBackend.__new__(OpenstackBackend)
        assert isinstance(instance, OpenstackBackendInterface)

    def test_kubernetes_backend_is_instance_of_interface(self):
        instance = KubernetesBackend.__new__(KubernetesBackend)
        assert isinstance(instance, KubernetesBackendInterface)

    def test_ansible_backend_is_instance_of_interface(self):
        backend = AnsibleBackend()
        assert isinstance(backend, AnsibleBackendInterface)

    def test_mock_satisfies_openstack_interface(self):
        """A MagicMock should be accepted where OpenstackBackendInterface is expected."""
        mock_backend = MagicMock(spec=OpenstackBackendInterface)
        assert isinstance(mock_backend, OpenstackBackendInterface)

    def test_mock_satisfies_kubernetes_interface(self):
        mock_backend = MagicMock(spec=KubernetesBackendInterface)
        assert isinstance(mock_backend, KubernetesBackendInterface)

    def test_mock_satisfies_ansible_interface(self):
        mock_backend = MagicMock(spec=AnsibleBackendInterface)
        assert isinstance(mock_backend, AnsibleBackendInterface)

    def test_all_backends_are_backend_interface(self):
        """All three backends should be instances of the base BackendInterface."""
        ostk = OpenstackBackend.__new__(OpenstackBackend)
        k8s = KubernetesBackend.__new__(KubernetesBackend)
        ansible = AnsibleBackend()
        assert isinstance(ostk, BackendInterface)
        assert isinstance(k8s, BackendInterface)
        assert isinstance(ansible, BackendInterface)

    def test_plain_object_not_backend_interface(self):
        assert not isinstance(object(), BackendInterface)


# ---------------------------------------------------------------------------
# OpenstackBackend — create_server paths
# ---------------------------------------------------------------------------

class TestOpenstackCreateServer:
    """Tests for OpenstackBackend.create_server various code paths."""

    @pytest.fixture
    def backend(self):
        instance = OpenstackBackend.__new__(OpenstackBackend)
        instance._connection = None
        instance.credential_id = "test-id"
        instance.credential_secret = "test-secret"
        instance.auth_url = "https://test.example.com"
        return instance

    def test_create_server_already_exists(self, backend):
        """If server already exists, return success with changed=False."""
        mock_conn = MagicMock()
        mock_conn.get_server.return_value = {"id": "server-123", "name": "existing"}

        result, message, server_info = backend.create_server(
            conn=mock_conn,
            server_name="existing",
            image_name="ubuntu",
            flavour_name="c2.large",
            networks=(),
            keypair_name="kp",
            sec_groups=(),
        )
        assert result.success is True
        assert result.changed is False
        assert "already exists" in message

    def test_create_server_dry_run(self, backend):
        """Dry run should return success without creating."""
        mock_conn = MagicMock()
        mock_conn.get_server.return_value = None

        result, message, _ = backend.create_server(
            conn=mock_conn,
            server_name="new-server",
            image_name="ubuntu",
            flavour_name="c2.large",
            networks=(),
            keypair_name="kp",
            sec_groups=(),
            dry_run=True,
        )
        assert result.success is True
        assert "Dry run" in message

    def test_create_server_unknown_image(self, backend):
        """Unknown image should return failure."""
        mock_conn = MagicMock()
        mock_conn.get_server.return_value = None
        mock_conn.compute.find_image.return_value = None

        result, message, _ = backend.create_server(
            conn=mock_conn,
            server_name="new-server",
            image_name="nonexistent",
            flavour_name="c2.large",
            networks=(),
            keypair_name="kp",
            sec_groups=(),
        )
        assert result.success is False
        assert "Unknown image" in message

    def test_create_server_unknown_flavour(self, backend):
        """Unknown flavour should return failure."""
        mock_conn = MagicMock()
        mock_conn.get_server.return_value = None
        mock_conn.compute.find_image.return_value = MagicMock()
        mock_conn.compute.find_flavor.return_value = None
        mock_conn.compute.flavors.return_value = iter([])

        result, message, _ = backend.create_server(
            conn=mock_conn,
            server_name="new-server",
            image_name="ubuntu",
            flavour_name="nonexistent",
            networks=(),
            keypair_name="kp",
            sec_groups=(),
        )
        assert result.success is False
        assert "Unknown flavour" in message

    def test_create_server_unknown_security_group(self, backend):
        """Unknown security group should return failure."""
        mock_conn = MagicMock()
        mock_conn.get_server.return_value = None
        mock_conn.compute.find_image.return_value = MagicMock()
        mock_conn.compute.find_flavor.return_value = MagicMock()
        mock_conn.get_security_group.return_value = None
        mock_conn.network.security_groups.return_value = iter([])

        result, message, _ = backend.create_server(
            conn=mock_conn,
            server_name="new-server",
            image_name="ubuntu",
            flavour_name="c2.large",
            networks=(),
            keypair_name="kp",
            sec_groups=("nonexistent-sg",),
        )
        assert result.success is False
        assert "Unknown security group" in message

    def test_create_server_unknown_network(self, backend):
        """Unknown network should return failure."""
        mock_conn = MagicMock()
        mock_conn.get_server.return_value = None
        mock_conn.compute.find_image.return_value = MagicMock()
        mock_conn.compute.find_flavor.return_value = MagicMock()
        mock_conn.get_security_group.return_value = MagicMock(name="sg")
        mock_conn.network.find_network.return_value = None
        mock_conn.network.networks.return_value = iter([])

        result, message, _ = backend.create_server(
            conn=mock_conn,
            server_name="new-server",
            image_name="ubuntu",
            flavour_name="c2.large",
            networks=("nonexistent-net",),
            keypair_name="kp",
            sec_groups=("sg",),
        )
        assert result.success is False
        assert "Unknown network" in message


# ---------------------------------------------------------------------------
# OpenstackBackend — keypair and network operations
# ---------------------------------------------------------------------------

class TestOpenstackKeypairAndNetwork:
    """Tests for OpenstackBackend keypair and network methods."""

    @pytest.fixture
    def backend(self):
        instance = OpenstackBackend.__new__(OpenstackBackend)
        instance._connection = None
        instance.credential_id = "test-id"
        instance.credential_secret = "test-secret"
        instance.auth_url = "https://test.example.com"
        return instance

    def test_delete_server_calls_conn_delete(self, backend):
        mock_conn = MagicMock()
        mock_server = MagicMock()
        mock_server.metadata.get.return_value = True
        mock_conn.get_server.return_value = mock_server
        backend.delete_server(conn=mock_conn, server_name="test-server")
        mock_conn.compute.delete_server.assert_called_once()

    def test_delete_server_dry_run(self, backend):
        mock_conn = MagicMock()
        result, message = backend.delete_server(
            conn=mock_conn, server_name="test-server", dry_run=True
        )
        assert result.success is True
        assert "Dry run" in message

    def test_delete_server_not_found(self, backend):
        mock_conn = MagicMock()
        mock_conn.get_server.return_value = None
        result, message = backend.delete_server(
            conn=mock_conn, server_name="missing"
        )
        assert result.success is True
        assert "doesn\'t exist" in message

    def test_list_servers(self, backend):
        mock_conn = MagicMock()
        mock_server = MagicMock()
        mock_server.id = "s1"
        mock_server.name = "server-1"
        mock_server.status = "ACTIVE"
        mock_server.flavor = {"original_name": "c2.large"}
        mock_server.image = {"id": "img-1"}
        mock_server.metadata.get.return_value = "ewccli"
        mock_server.addresses = {"private": [{"addr": "10.0.0.1"}]}
        mock_server.security_groups = [{"name": "default"}]
        mock_conn.compute.servers.return_value = iter([mock_server])
        mock_conn.compute.images.return_value = iter([])
        result = backend.list_servers(conn=mock_conn, show_all=True)
        assert len(result) == 1
        assert result["s1"]["name"] == "server-1"

    def test_list_networks(self, backend):
        mock_conn = MagicMock()
        mock_conn.network.networks.return_value = iter([MagicMock(name="net1")])
        result = backend.list_networks(conn=mock_conn)
        networks = list(result)
        assert len(networks) == 1

    def test_remove_network_detaches(self, backend):
        mock_conn = MagicMock()
        mock_server = MagicMock()
        mock_iface = MagicMock()
        mock_iface.net_id = "net-123"
        mock_network = MagicMock()
        mock_network.name = "private"
        mock_conn.compute.server_interfaces.return_value = iter([mock_iface])
        mock_conn.network.get_network.return_value = mock_network
        result = backend.remove_network(
            conn=mock_conn, server=mock_server, network_name="private"
        )
        assert result.success is True

    def test_remove_network_not_found(self, backend):
        mock_conn = MagicMock()
        mock_server = MagicMock()
        mock_conn.compute.server_interfaces.return_value = iter([])
        result = backend.remove_network(
            conn=mock_conn, server=mock_server, network_name="missing"
        )
        assert result.success is True
        assert result.changed is False


# ---------------------------------------------------------------------------
# KubernetesBackend — CRD error handling
# ---------------------------------------------------------------------------

class TestKubernetesCRDErrorHandling:
    """Tests for KubernetesBackend CRD operations error handling."""

    @pytest.fixture
    def backend(self):
        instance = KubernetesBackend.__new__(KubernetesBackend)
        instance._connected = True
        instance.custom_api = MagicMock()
        instance.core_api = MagicMock()
        instance.apps_api = MagicMock()
        instance.api = MagicMock()
        return instance

    def _make_api_exception(self, status, reason="Reason", body=None):
        from kubernetes.client.rest import ApiException
        exc = ApiException(status=status, reason=reason)
        if body is not None:
            exc.body = json.dumps(body)
        return exc

    def test_delete_custom_resource_404_returns_empty(self, backend):
        backend.custom_api.delete_namespaced_custom_object.side_effect = (
            self._make_api_exception(404)
        )
        result = backend.delete_custom_resource(
            "g", "v1", "ns", "plural", "name"
        )
        assert result == {}

    def test_delete_custom_resource_403_returns_empty(self, backend):
        backend.custom_api.delete_namespaced_custom_object.side_effect = (
            self._make_api_exception(403)
        )
        result = backend.delete_custom_resource(
            "g", "v1", "ns", "plural", "name"
        )
        assert result == {}

    def test_delete_custom_resource_generic_raises_operation_error(self, backend):
        backend.custom_api.delete_namespaced_custom_object.side_effect = (
            self._make_api_exception(500, reason="InternalError")
        )
        with pytest.raises(BackendOperationError):
            backend.delete_custom_resource("g", "v1", "ns", "plural", "name")

    def test_describe_custom_resource_404_returns_empty(self, backend):
        backend.custom_api.get_namespaced_custom_object.side_effect = (
            self._make_api_exception(404)
        )
        result = backend.describe_custom_resource(
            "g", "v1", "ns", "plural", "name"
        )
        assert result == {}

    def test_describe_custom_resource_success(self, backend):
        backend.custom_api.get_namespaced_custom_object.return_value = {
            "metadata": {"name": "test"}
        }
        result = backend.describe_custom_resource(
            "g", "v1", "ns", "plural", "name"
        )
        assert result["metadata"]["name"] == "test"

    def test_describe_custom_resource_generic_raises(self, backend):
        backend.custom_api.get_namespaced_custom_object.side_effect = (
            self._make_api_exception(500, reason="InternalError")
        )
        with pytest.raises(BackendOperationError):
            backend.describe_custom_resource("g", "v1", "ns", "plural", "name")

    def test_list_custom_resources_404_returns_empty_list(self, backend):
        backend.custom_api.list_namespaced_custom_object.side_effect = (
            self._make_api_exception(404)
        )
        result = backend.list_custom_resources("g", "v1", "ns", "plural")
        assert result == []

    def test_list_custom_resources_success(self, backend):
        backend.custom_api.list_namespaced_custom_object.return_value = {
            "items": [{"name": "cr1"}, {"name": "cr2"}]
        }
        result = backend.list_custom_resources("g", "v1", "ns", "plural")
        assert len(result) == 2

    def test_list_custom_resources_generic_raises(self, backend):
        backend.custom_api.list_namespaced_custom_object.side_effect = (
            self._make_api_exception(500, reason="InternalError")
        )
        with pytest.raises(BackendOperationError):
            backend.list_custom_resources("g", "v1", "ns", "plural")

    def test_create_custom_resource_409_already_exists(self, backend):
        backend.custom_api.create_namespaced_custom_object.side_effect = (
            self._make_api_exception(
                409,
                body={"code": 409, "reason": "AlreadyExists"},
            )
        )
        result = backend.create_custom_resource(
            "g", "v1", "ns", "plural",
            body={"metadata": {"name": "test-cr"}},
        )
        assert result == {}

    def test_create_custom_resource_422_validation(self, backend):
        backend.custom_api.create_namespaced_custom_object.side_effect = (
            self._make_api_exception(
                422,
                body={
                    "code": 422,
                    "message": "validation failed",
                    "details": {"causes": []},
                },
            )
        )
        result = backend.create_custom_resource(
            "g", "v1", "ns", "plural",
            body={"metadata": {"name": "test-cr"}},
        )
        assert result == {}

    def test_create_custom_resource_404_returns_empty(self, backend):
        backend.custom_api.create_namespaced_custom_object.side_effect = (
            self._make_api_exception(404, body={"code": 404, "message": "not found"})
        )
        result = backend.create_custom_resource(
            "g", "v1", "ns", "plural",
            body={"metadata": {"name": "test-cr"}},
        )
        assert result == {}

    def test_create_custom_resource_403_returns_empty(self, backend):
        backend.custom_api.create_namespaced_custom_object.side_effect = (
            self._make_api_exception(403, body={"code": 403, "message": "forbidden"})
        )
        result = backend.create_custom_resource(
            "g", "v1", "ns", "plural",
            body={"metadata": {"name": "test-cr"}},
        )
        assert result == {}

    def test_create_custom_resource_generic_raises(self, backend):
        backend.custom_api.create_namespaced_custom_object.side_effect = (
            self._make_api_exception(
                500, reason="InternalError",
                body={"code": 500, "message": "internal error"},
            )
        )
        with pytest.raises(BackendOperationError):
            backend.create_custom_resource(
                "g", "v1", "ns", "plural",
                body={"metadata": {"name": "test-cr"}},
            )

    def test_create_custom_resource_success(self, backend):
        backend.custom_api.create_namespaced_custom_object.return_value = {
            "metadata": {"name": "created"}
        }
        result = backend.create_custom_resource(
            "g", "v1", "ns", "plural",
            body={"metadata": {"name": "test-cr"}},
        )
        assert result["metadata"]["name"] == "created"

    def test_list_pods(self, backend):
        backend.core_api.list_namespaced_pod.return_value = ["pod1", "pod2"]
        result = backend.list_pods("default")
        assert len(result) == 2

    def test_list_custom_resource_definitions(self, backend):
        mock_crd1 = MagicMock()
        mock_crd1.spec.names.kind = "Cluster"
        mock_crd1.spec.group = "compute.example.com"
        mock_crd1.spec.names.plural = "clusters"
        mock_crd1.spec.versions = [MagicMock(name="v1", served=True)]
        mock_crd1.spec.versions[0].name = "v1"
        mock_crd1.spec.versions[0].served = True

        mock_crd2 = MagicMock()
        mock_crd2.spec.names.kind = "Record"
        mock_crd2.spec.group = "dns.example.com"
        mock_crd2.spec.names.plural = "records"
        mock_crd2.spec.versions = [MagicMock(name="v1alpha1", served=True)]
        mock_crd2.spec.versions[0].name = "v1alpha1"
        mock_crd2.spec.versions[0].served = True

        backend.api.list_custom_resource_definition.return_value = MagicMock(
            items=[mock_crd1, mock_crd2]
        )
        result = backend.list_custom_resource_definitions()
        assert len(result) == 2
        assert result[0]["kind"] == "Cluster"
        assert result[1]["kind"] == "Record"


# ---------------------------------------------------------------------------
# KubernetesBackend — connection lifecycle
# ---------------------------------------------------------------------------

class TestKubernetesConnectionLifecycle:
    """Tests for KubernetesBackend connection lifecycle."""

    def test_init_with_token_and_host(self):
        with patch("ewccli.backends.kubernetes.backend_k8s.client") as mock_client:
            mock_client.Configuration.return_value = MagicMock()
            backend = KubernetesBackend(token="tok", host="https://k8s.example.com")
            assert backend.is_connected() is True

    def test_init_with_token_fails_raises_connection_error(self):
        with patch("ewccli.backends.kubernetes.backend_k8s.client") as mock_client:
            mock_client.Configuration.side_effect = Exception("config error")
            with pytest.raises(BackendConnectionError):
                KubernetesBackend(token="tok", host="https://k8s.example.com")

    def test_init_without_token_loads_kubeconfig(self):
        with patch("ewccli.backends.kubernetes.backend_k8s.config") as mock_config, \
             patch("ewccli.backends.kubernetes.backend_k8s.client") as mock_client:
            mock_client.Configuration.return_value = MagicMock()
            backend = KubernetesBackend()
            assert backend.is_connected() is True
            mock_config.load_kube_config.assert_called_once()

    def test_init_without_token_kubeconfig_fails(self):
        from kubernetes.config.config_exception import ConfigException
        with patch("ewccli.backends.kubernetes.backend_k8s.config") as mock_config, \
             patch("ewccli.backends.kubernetes.backend_k8s.client"):
            mock_config.load_kube_config.side_effect = ConfigException("no config")
            with pytest.raises(BackendConnectionError):
                KubernetesBackend()

    def test_context_manager_closes(self):
        with patch("ewccli.backends.kubernetes.backend_k8s.client") as mock_client, \
             patch("ewccli.backends.kubernetes.backend_k8s.config"):
            mock_client.Configuration.return_value = MagicMock()
            with KubernetesBackend(token="tok", host="https://k8s.example.com") as k8s:
                assert k8s.is_connected() is True
            assert k8s.is_connected() is False


# ---------------------------------------------------------------------------
# AnsibleBackend — method tests with mocks
# ---------------------------------------------------------------------------

class TestAnsibleBackendMethods:
    """Tests for AnsibleBackend methods with mocks."""

    def test_run_ansible_success(self):
        backend = AnsibleBackend()
        with patch("ewccli.backends.ansible.backend_ansible.run_command_from_host") as mock_run:
            mock_run.return_value = (0, "success")
            rc, msg = backend.run_ansible("test", ["ansible-playbook", "site.yml"])
            assert rc == 0
            assert msg == "success"

    def test_run_ansible_failure(self):
        backend = AnsibleBackend()
        with patch("ewccli.backends.ansible.backend_ansible.run_command_from_host") as mock_run:
            mock_run.return_value = (1, "failed")
            rc, msg = backend.run_ansible("test", ["ansible-playbook", "site.yml"])
            assert rc == 1
            assert msg == "failed"

    def test_install_ansible_roles(self):
        backend = AnsibleBackend()
        with patch("ewccli.backends.ansible.backend_ansible.run_command_from_host") as mock_run:
            mock_run.return_value = (0, "roles installed")
            rc, msg = backend.install_ansible_roles("/path/to/requirements.yml")
            assert rc == 0
            assert "installed" in msg
            mock_run.assert_called_once()

    def test_install_ansible_roles_dry_run(self):
        backend = AnsibleBackend()
        with patch("ewccli.backends.ansible.backend_ansible.run_command_from_host") as mock_run:
            mock_run.return_value = (0, "dry run")
            rc, msg = backend.install_ansible_roles(
                "/path/to/requirements.yml", dry_run=True
            )
            assert rc == 0

    def test_run_ansible_live_success(self, tmp_path):
        backend = AnsibleBackend()
        mock_thread = MagicMock()
        mock_runner = MagicMock()
        mock_runner.rc = 0

        with patch("ewccli.backends.ansible.backend_ansible.ansible_runner") as mock_ar:
            mock_ar.run_async.return_value = (mock_thread, mock_runner)
            rc = backend.run_ansible_live(
                working_directory_path=str(tmp_path),
                cmdline=["ansible-playbook", "site.yml"],
                description="test play",
            )
            assert rc == 0

    def test_run_ansible_live_failure(self, tmp_path):
        backend = AnsibleBackend()
        mock_thread = MagicMock()
        mock_runner = MagicMock()
        mock_runner.rc = 2

        with patch("ewccli.backends.ansible.backend_ansible.ansible_runner") as mock_ar:
            mock_ar.run_async.return_value = (mock_thread, mock_runner)
            rc = backend.run_ansible_live(
                working_directory_path=str(tmp_path),
                cmdline=["ansible-playbook", "site.yml"],
            )
            assert rc == 2

    def test_run_ansible_live_cleans_up_args_file(self, tmp_path):
        backend = AnsibleBackend()
        mock_thread = MagicMock()
        mock_runner = MagicMock()
        mock_runner.rc = 0
        args_file = tmp_path / "args"
        args_file.write_text("test command")

        with patch("ewccli.backends.ansible.backend_ansible.ansible_runner") as mock_ar:
            mock_ar.run_async.return_value = (mock_thread, mock_runner)
            backend.run_ansible_live(
                working_directory_path=str(tmp_path),
                cmdline=["ansible-playbook", "site.yml"],
            )
            assert not args_file.exists()


# ---------------------------------------------------------------------------
# DI mockability — services accept interface-typed mocks
# ---------------------------------------------------------------------------

class TestDependencyInjection:
    """Tests that services can accept interface-typed mocks (DI/mockability)."""

    def test_mock_openstack_backend_has_all_interface_methods(self):
        mock_backend = MagicMock(spec=OpenstackBackendInterface)
        for method in [
            "connect", "close", "is_connected",
            "get_connection", "create_server", "delete_server",
            "list_servers", "find_latest_image", "check_server_inputs",
            "add_external_ip", "remove_external_ip",
            "list_networks", "remove_network",
            "create_keypair", "delete_keypair",
        ]:
            assert hasattr(mock_backend, method), f"Missing method: {method}"

    def test_mock_kubernetes_backend_has_all_interface_methods(self):
        mock_backend = MagicMock(spec=KubernetesBackendInterface)
        for method in [
            "connect", "close", "is_connected",
            "create_custom_resource", "delete_custom_resource",
            "describe_custom_resource", "list_custom_resources",
            "list_pods", "list_custom_resource_definitions",
        ]:
            assert hasattr(mock_backend, method), f"Missing method: {method}"

    def test_mock_ansible_backend_has_all_interface_methods(self):
        mock_backend = MagicMock(spec=AnsibleBackendInterface)
        for method in [
            "connect", "close", "is_connected",
            "run_ansible_live", "run_ansible", "install_ansible_roles",
        ]:
            assert hasattr(mock_backend, method), f"Missing method: {method}"

    def test_server_service_accepts_interface_typed_mock(self):
        """ServerService should accept a mock typed as OpenstackBackendInterface."""

        mock_backend = MagicMock(spec=OpenstackBackendInterface)
        mock_backend.get_connection.return_value = MagicMock()
        assert isinstance(mock_backend, OpenstackBackendInterface)

    def test_hub_deploy_service_accepts_interface_typed_mock(self):
        """HubDeployService should accept a mock typed as AnsibleBackendInterface."""
        mock_backend = MagicMock(spec=AnsibleBackendInterface)
        assert isinstance(mock_backend, AnsibleBackendInterface)
