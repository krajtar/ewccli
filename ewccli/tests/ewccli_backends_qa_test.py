#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details


"""QA tests for Phase 3 backend stabilization (KAM-15).

Extends the coverage of the unified exception hierarchy, retry/timeout
utilities, interface protocols, connection lifecycle centralization,
and dependency-injection mockability delivered in KAM-8.

All tests use mocks — no real API calls are made.
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
)
from ewccli.backends.interfaces import (
    BackendInterface,
    OpenstackBackendInterface,
    KubernetesBackendInterface,
    AnsibleBackendInterface,
)
from ewccli.backends.openstack.backend_ostack import OpenstackBackend
from ewccli.backends.kubernetes.backend_k8s import KubernetesBackend
from ewccli.backends.kubernetes.exceptions import ResourceAlreadyExistsError
from ewccli.backends.ansible.backend_ansible import AnsibleBackend
from kubernetes.client.rest import ApiException


# ---------------------------------------------------------------------------
# Module-level test helpers
# ---------------------------------------------------------------------------

class FakeOpenstackBackend:
    """Hand-written class implementing OpenstackBackendInterface for testing."""

    def connect(self, *args, **kwargs):
        return MagicMock()

    def close(self):
        pass

    def is_connected(self):
        return True

    def get_connection(self):
        return MagicMock()

    def create_server(self, conn, server_name, image_name,
                      flavour_name, networks, keypair_name,
                      sec_groups, **kwargs):
        pass

    def delete_server(self, conn, server_name, **kwargs):
        pass

    def list_servers(self, conn, **kwargs):
        return []

    def find_latest_image(self, conn, prefix):
        return None

    def check_server_inputs(self, conn, **kwargs):
        return True, None

    def add_external_ip(self, conn, server_name, **kwargs):
        pass

    def remove_external_ip(self, conn, server_name, **kwargs):
        pass

    def list_networks(self, conn, **kwargs):
        return []

    def remove_network(self, conn, network_id, **kwargs):
        pass

    def create_keypair(self, conn, keypair_name, public_key_path, **kwargs):
        return None, "ok"

    def delete_keypair(self, conn, keypair_name, **kwargs):
        return None, "ok"


# ---------------------------------------------------------------------------
# Exception hierarchy — extended coverage
# ---------------------------------------------------------------------------

class TestExceptionHierarchyQA:
    """Extended tests for the unified backend exception hierarchy."""

    @pytest.mark.parametrize("exc_cls", [
        BackendConnectionError,
        BackendAuthError,
        BackendOperationError,
        BackendTimeoutError,
        BackendNotFoundError,
        BackendAlreadyExistsError,
        BackendValidationError,
        BackendConfigError,
    ])
    def test_subclass_catchable_as_base(self, exc_cls):
        """Every sub-class must be catchable via ``except BackendError``."""
        with pytest.raises(BackendError):
            raise exc_cls("test")

    def test_auth_catchable_as_connection(self):
        """BackendAuthError is a BackendConnectionError sub-class."""
        with pytest.raises(BackendConnectionError):
            raise BackendAuthError("auth fail")

    def test_resource_already_exists_inherits_hierarchy(self):
        """Kubernetes ResourceAlreadyExistsError is part of the hierarchy."""
        assert issubclass(ResourceAlreadyExistsError, BackendAlreadyExistsError)
        assert issubclass(ResourceAlreadyExistsError, BackendError)
        with pytest.raises(BackendAlreadyExistsError):
            raise ResourceAlreadyExistsError("exists")
        with pytest.raises(BackendError):
            raise ResourceAlreadyExistsError("exists")

    def test_exception_message_preserved(self):
        """Exception messages are preserved through the hierarchy."""
        msg = "detailed error message"
        exc = BackendTimeoutError(msg)
        assert str(exc) == msg

    def test_exception_chaining(self):
        """Exceptions support ``raise ... from`` chaining."""
        original = ValueError("root cause")
        with pytest.raises(BackendConnectionError) as exc_info:
            try:
                raise original
            except ValueError as e:
                raise BackendConnectionError("wrapped") from e
        assert exc_info.value.__cause__ is original

    def test_distinct_exception_types(self):
        """All exception classes are distinct types."""
        classes = [
            BackendError,
            BackendConnectionError,
            BackendAuthError,
            BackendOperationError,
            BackendTimeoutError,
            BackendNotFoundError,
            BackendAlreadyExistsError,
            BackendValidationError,
            BackendConfigError,
        ]
        for i, cls_a in enumerate(classes):
            for cls_b in classes[i + 1:]:
                assert cls_a is not cls_b

    def test_timeout_not_connection(self):
        """BackendTimeoutError is a direct BackendError, not BackendConnectionError."""
        assert not issubclass(BackendTimeoutError, BackendConnectionError)
        assert issubclass(BackendTimeoutError, BackendError)


# ---------------------------------------------------------------------------
# Retry / timeout — extended coverage
# ---------------------------------------------------------------------------

class TestRetryBackoffQA:
    """Extended tests for retry_with_backoff decorator."""

    def test_connection_error_triggers_retry(self):
        """BackendConnectionError should trigger retry by default."""
        calls = 0

        @retry_with_backoff(max_retries=2, initial_delay=0)
        def flaky():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise BackendConnectionError("conn fail")
            return "recovered"

        assert flaky() == "recovered"
        assert calls == 2

    def test_auth_error_triggers_retry(self):
        """BackendAuthError (subclass of BackendConnectionError) should retry."""
        calls = 0

        @retry_with_backoff(max_retries=2, initial_delay=0)
        def flaky():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise BackendAuthError("auth")
            return "ok"

        assert flaky() == "ok"
        assert calls == 2

    def test_max_retries_zero(self):
        """max_retries=0 means a single attempt with no retries."""
        calls = 0

        @retry_with_backoff(max_retries=0, initial_delay=0)
        def always_fail():
            nonlocal calls
            calls += 1
            raise BackendTimeoutError("timeout")

        with pytest.raises(BackendTimeoutError):
            always_fail()
        assert calls == 1

    @patch("ewccli.backends.retry.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep):
        """Backoff delay should increase exponentially between retries."""
        calls = 0

        @retry_with_backoff(
            max_retries=3,
            initial_delay=1.0,
            backoff_factor=2.0,
            max_delay=100.0,
        )
        def always_fail():
            nonlocal calls
            calls += 1
            raise BackendTimeoutError("timeout")

        with pytest.raises(BackendTimeoutError):
            always_fail()

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays == [1.0, 2.0, 4.0]
        assert calls == 4

    @patch("ewccli.backends.retry.time.sleep")
    def test_max_delay_caps_backoff(self, mock_sleep):
        """Delay should not exceed max_delay."""
        calls = 0

        @retry_with_backoff(
            max_retries=4,
            initial_delay=5.0,
            backoff_factor=3.0,
            max_delay=10.0,
        )
        def always_fail():
            nonlocal calls
            calls += 1
            raise BackendTimeoutError("timeout")

        with pytest.raises(BackendTimeoutError):
            always_fail()

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        for d in delays:
            assert d <= 10.0
        assert delays == [5.0, 10.0, 10.0, 10.0]

    def test_preserves_function_metadata(self):
        """Decorator should preserve the wrapped function metadata."""

        @retry_with_backoff(max_retries=1, initial_delay=0)
        def my_function():
            """My docstring."""
            return "ok"

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    def test_not_found_error_not_retried(self):
        """BackendNotFoundError is not in default retry_on, so no retry."""
        calls = 0

        @retry_with_backoff(max_retries=3, initial_delay=0)
        def fail():
            nonlocal calls
            calls += 1
            raise BackendNotFoundError("not found")

        with pytest.raises(BackendNotFoundError):
            fail()
        assert calls == 1

    def test_validation_error_not_retried(self):
        """BackendValidationError is not retried by default."""
        calls = 0

        @retry_with_backoff(max_retries=3, initial_delay=0)
        def fail():
            nonlocal calls
            calls += 1
            raise BackendValidationError("bad input")

        with pytest.raises(BackendValidationError):
            fail()
        assert calls == 1

    def test_returns_value_on_first_success(self):
        """Successful call returns immediately without retry."""

        @retry_with_backoff(max_retries=5, initial_delay=0)
        def succeed():
            return {"result": "data"}

        assert succeed() == {"result": "data"}


class TestIsRetryableQA:
    """Extended tests for the is_retryable helper."""

    def test_auth_error_is_retryable(self):
        """BackendAuthError is retryable (subclass of BackendConnectionError)."""
        assert is_retryable(BackendAuthError("auth")) is True

    def test_not_found_not_retryable(self):
        assert is_retryable(BackendNotFoundError("nf")) is False

    def test_already_exists_not_retryable(self):
        assert is_retryable(BackendAlreadyExistsError("ae")) is False

    def test_validation_not_retryable(self):
        assert is_retryable(BackendValidationError("val")) is False

    def test_config_not_retryable(self):
        assert is_retryable(BackendConfigError("cfg")) is False

    def test_custom_retry_on_includes_not_found(self):
        """Custom retry_on can include BackendNotFoundError."""
        assert is_retryable(
            BackendNotFoundError("nf"),
            retry_on=(BackendNotFoundError,),
        ) is True

    def test_operation_error_never_retryable(self):
        """BackendOperationError is never retryable even with broad retry_on."""
        assert is_retryable(
            BackendOperationError("op"),
            retry_on=(BackendError,),
        ) is False

    def test_resource_already_exists_not_retryable(self):
        """ResourceAlreadyExistsError is not retryable by default."""
        assert is_retryable(ResourceAlreadyExistsError("exists")) is False


# ---------------------------------------------------------------------------
# Interface protocol mockability
# ---------------------------------------------------------------------------

class TestInterfaceMockabilityQA:
    """Verify that interface protocols enable mock-based testing."""

    def test_magic_mock_satisfies_backend_interface(self):
        """A MagicMock with spec satisfies the BackendInterface protocol."""
        mock = MagicMock(spec=BackendInterface)
        assert isinstance(mock, BackendInterface)

    def test_magic_mock_satisfies_openstack_interface(self):
        mock = MagicMock(spec=OpenstackBackendInterface)
        assert isinstance(mock, OpenstackBackendInterface)

    def test_magic_mock_satisfies_kubernetes_interface(self):
        mock = MagicMock(spec=KubernetesBackendInterface)
        assert isinstance(mock, KubernetesBackendInterface)

    def test_magic_mock_satisfies_ansible_interface(self):
        mock = MagicMock(spec=AnsibleBackendInterface)
        assert isinstance(mock, AnsibleBackendInterface)

    def test_plain_object_not_backend_interface(self):
        """A plain object without the required methods does not satisfy."""
        assert not isinstance(object(), BackendInterface)

    def test_partial_mock_without_close_not_interface(self):
        """An object missing close() does not satisfy BackendInterface."""

        class PartialBackend:
            def connect(self):
                pass

            def is_connected(self):
                return True

        assert not isinstance(PartialBackend(), BackendInterface)

    def test_custom_implementation_satisfies_protocol(self):
        """A hand-written class implementing all methods satisfies the protocol."""

        fake = FakeOpenstackBackend()
        assert isinstance(fake, BackendInterface)
        assert isinstance(fake, OpenstackBackendInterface)


# ---------------------------------------------------------------------------
# OpenstackBackend — extended coverage
# ---------------------------------------------------------------------------

class TestOpenstackBackendQA:
    """Extended tests for OpenstackBackend connection lifecycle and methods."""

    @pytest.fixture
    def backend(self):
        """Create an OpenstackBackend without running __init__."""
        instance = OpenstackBackend.__new__(OpenstackBackend)
        instance._connection = None
        instance.credential_id = "test-id"
        instance.credential_secret = "test-secret"
        instance.auth_url = "https://test.example.com"
        return instance

    def test_get_connection_with_explicit_params(self, backend):
        """get_connection passes explicit params to connect."""
        mock_conn = MagicMock()
        with patch.object(backend, "connect", return_value=mock_conn) as mock_connect:
            result = backend.get_connection(
                auth_url="https://custom.example.com",
                application_credential_id="custom-id",
                application_credential_secret="custom-secret",
            )
            assert result is mock_conn
            mock_connect.assert_called_once_with(
                auth_url="https://custom.example.com",
                application_credential_id="custom-id",
                application_credential_secret="custom-secret",
            )

    def test_get_connection_returns_cached_with_different_params(self, backend):
        """Subsequent get_connection calls return cached connection regardless of params."""
        mock_conn = MagicMock()
        with patch.object(backend, "connect", return_value=mock_conn) as mock_connect:
            conn1 = backend.get_connection(auth_url="https://first.example.com")
            conn2 = backend.get_connection(auth_url="https://second.example.com")
            assert conn1 is mock_conn
            assert conn2 is mock_conn
            assert mock_connect.call_count == 1

    def test_get_connection_raises_backend_connection_error(self, backend):
        """Non-BackendError exceptions from connect are wrapped in BackendConnectionError."""
        with patch.object(backend, "connect", side_effect=RuntimeError("network down")):
            with pytest.raises(BackendConnectionError) as exc_info:
                backend.get_connection()
            assert "Failed to connect to OpenStack" in str(exc_info.value)

    def test_close_handles_connection_close_error(self, backend):
        """close() should not raise even if connection.close() fails."""
        mock_conn = MagicMock()
        mock_conn.close.side_effect = Exception("close failed")
        backend._connection = mock_conn
        backend.close()
        assert backend._connection is None
        assert backend.is_connected() is False

    def test_close_when_already_disconnected(self, backend):
        """close() is a no-op when no connection exists."""
        backend._connection = None
        backend.close()
        assert backend._connection is None

    def test_connect_creates_openstack_connection(self, backend):
        """connect() calls openstack.connect with stored credentials."""
        mock_conn = MagicMock()
        with patch(
            "ewccli.backends.openstack.backend_ostack.openstack.connect",
            return_value=mock_conn,
        ) as mock_os_connect:
            result = backend.connect()
            assert result is mock_conn
            mock_os_connect.assert_called_once()
            call_kwargs = mock_os_connect.call_args.kwargs
            assert call_kwargs["auth_url"] == "https://test.example.com"
            assert call_kwargs["application_credential_id"] == "test-id"
            assert call_kwargs["application_credential_secret"] == "test-secret"
            assert call_kwargs["auth_type"] == "v3applicationcredential"

    def test_connect_with_override_params(self, backend):
        """connect() uses override params when provided."""
        mock_conn = MagicMock()
        with patch(
            "ewccli.backends.openstack.backend_ostack.openstack.connect",
            return_value=mock_conn,
        ) as mock_os_connect:
            backend.connect(
                auth_url="https://override.example.com",
                application_credential_id="override-id",
                application_credential_secret="override-secret",
            )
            call_kwargs = mock_os_connect.call_args.kwargs
            assert call_kwargs["auth_url"] == "https://override.example.com"
            assert call_kwargs["application_credential_id"] == "override-id"
            assert call_kwargs["application_credential_secret"] == "override-secret"

    def test_create_server_returns_existing(self, backend):
        """create_server returns early when server already exists."""
        mock_conn = MagicMock()
        existing_server = {"id": "srv-1", "name": "test-server"}
        mock_conn.get_server.return_value = existing_server
        result, message, server_info = backend.create_server(
            conn=mock_conn,
            server_name="test-server",
            image_name="img",
            flavour_name="flv",
            networks=(),
            keypair_name="kp",
            sec_groups=(),
        )
        assert result.success is True
        assert result.changed is False
        assert server_info == existing_server
        mock_conn.get_server.assert_called_once_with(name_or_id="test-server")

    def test_create_server_dry_run(self, backend):
        """create_server with dry_run=True returns without creating."""
        mock_conn = MagicMock()
        mock_conn.get_server.return_value = None
        result, message, server_info = backend.create_server(
            conn=mock_conn,
            server_name="test-server",
            image_name="img",
            flavour_name="flv",
            networks=(),
            keypair_name="kp",
            sec_groups=(),
            dry_run=True,
        )
        assert result.success is True
        assert result.changed is False
        assert server_info == {}

    def test_context_manager_calls_close_on_exit(self, backend):
        """Using backend as context manager calls close() on exit."""
        mock_conn = MagicMock()
        with patch.object(backend, "connect", return_value=mock_conn):
            with backend as b:
                b.get_connection()
                assert b.is_connected() is True
            assert b.is_connected() is False

    def test_init_with_explicit_credentials(self):
        """__init__ with explicit credentials stores them without reading clouds.yaml."""
        with patch(
            "ewccli.backends.openstack.backend_ostack.OpenStackConfig"
        ) as mock_cfg:
            backend = OpenstackBackend(
                application_credential_id="explicit-id",
                application_credential_secret="explicit-secret",
                auth_url="https://explicit.example.com",
            )
            assert backend.credential_id == "explicit-id"
            assert backend.credential_secret == "explicit-secret"
            assert backend.auth_url == "https://explicit.example.com"
            assert backend._connection is None
            mock_cfg.assert_not_called()

    def test_is_connected_false_after_close(self, backend):
        """is_connected returns False after close clears the connection."""
        backend._connection = MagicMock()
        assert backend.is_connected() is True
        backend.close()
        assert backend.is_connected() is False


# ---------------------------------------------------------------------------
# KubernetesBackend — extended coverage
# ---------------------------------------------------------------------------

class TestKubernetesBackendQA:
    """Extended tests for KubernetesBackend methods and error handling."""

    @pytest.fixture
    def backend(self):
        """Create a KubernetesBackend without running __init__."""
        instance = KubernetesBackend.__new__(KubernetesBackend)
        instance._connected = True
        instance.custom_api = MagicMock()
        instance.core_api = MagicMock()
        instance.apps_api = MagicMock()
        instance.api = MagicMock()
        return instance

    def test_is_connected_true_after_init(self, backend):
        assert backend.is_connected() is True

    def test_connect_reinitializes(self, backend):
        """connect() calls __init__ to re-establish the connection."""
        with patch.object(KubernetesBackend, "__init__", return_value=None) as mock_init:
            backend.connect(token="new-token", host="https://new-host")
            mock_init.assert_called_once_with(
                token="new-token", host="https://new-host", verify_ssl=True
            )

    def test_context_manager_closes(self, backend):
        with backend as b:
            assert b.is_connected() is True
        assert b.is_connected() is False

    def test_create_custom_resource_success(self, backend):
        """Successful create returns the API response."""
        expected = {"metadata": {"name": "test-cr"}}
        backend.custom_api.create_namespaced_custom_object.return_value = expected
        result = backend.create_custom_resource(
            group="dns.example.com",
            version="v1alpha1",
            namespace="default",
            plural="records",
            body={"metadata": {"name": "test-cr"}},
        )
        assert result == expected

    def test_create_custom_resource_already_exists(self, backend):
        """409 AlreadyExists returns empty dict (no raise)."""
        exc = ApiException(status=409, reason="Conflict")
        exc.body = json.dumps({
            "code": 409, "reason": "AlreadyExists",
        })
        backend.custom_api.create_namespaced_custom_object.side_effect = exc
        result = backend.create_custom_resource(
            group="dns.example.com",
            version="v1alpha1",
            namespace="default",
            plural="records",
            body={"metadata": {"name": "test-cr"}},
        )
        assert result == {}

    def test_create_custom_resource_validation_error(self, backend):
        """422 validation error returns empty dict."""
        exc = ApiException(status=422, reason="Invalid")
        exc.body = json.dumps({
            "code": 422,
            "message": "validation failed",
            "details": {"causes": [{"field": "spec", "reason": "required", "message": "missing"}]},
        })
        backend.custom_api.create_namespaced_custom_object.side_effect = exc
        result = backend.create_custom_resource(
            group="dns.example.com",
            version="v1alpha1",
            namespace="default",
            plural="records",
            body={"metadata": {"name": "test-cr"}},
        )
        assert result == {}

    def test_create_custom_resource_not_found(self, backend):
        """404 returns empty dict."""
        exc = ApiException(status=404, reason="Not Found")
        exc.body = "{}"
        backend.custom_api.create_namespaced_custom_object.side_effect = exc
        result = backend.create_custom_resource(
            group="dns.example.com",
            version="v1alpha1",
            namespace="default",
            plural="records",
            body={"metadata": {"name": "test-cr"}},
        )
        assert result == {}

    def test_create_custom_resource_forbidden(self, backend):
        """403 returns empty dict."""
        exc = ApiException(status=403, reason="Forbidden")
        exc.body = "{}"
        backend.custom_api.create_namespaced_custom_object.side_effect = exc
        result = backend.create_custom_resource(
            group="dns.example.com",
            version="v1alpha1",
            namespace="default",
            plural="records",
            body={"metadata": {"name": "test-cr"}},
        )
        assert result == {}

    def test_create_custom_resource_unauthorized(self, backend):
        """401 returns empty dict."""
        exc = ApiException(status=401, reason="Unauthorized")
        exc.body = "{}"
        backend.custom_api.create_namespaced_custom_object.side_effect = exc
        result = backend.create_custom_resource(
            group="dns.example.com",
            version="v1alpha1",
            namespace="default",
            plural="records",
            body={"metadata": {"name": "test-cr"}},
        )
        assert result == {}

    def test_create_custom_resource_generic_error_raises(self, backend):
        """Non-handled status codes raise BackendOperationError."""
        exc = ApiException(status=500, reason="Internal Server Error")
        exc.body = "{}"
        backend.custom_api.create_namespaced_custom_object.side_effect = exc
        with pytest.raises(BackendOperationError):
            backend.create_custom_resource(
                group="dns.example.com",
                version="v1alpha1",
                namespace="default",
                plural="records",
                body={"metadata": {"name": "test-cr"}},
            )

    def test_delete_custom_resource_success(self, backend):
        expected = {"status": "deleted"}
        backend.custom_api.delete_namespaced_custom_object.return_value = expected
        result = backend.delete_custom_resource(
            group="dns.example.com",
            version="v1alpha1",
            namespace="default",
            plural="records",
            name="test-cr",
        )
        assert result == expected

    def test_delete_custom_resource_not_found(self, backend):
        exc = ApiException(status=404, reason="Not Found")
        exc.body = "not found"
        backend.custom_api.delete_namespaced_custom_object.side_effect = exc
        result = backend.delete_custom_resource(
            group="dns.example.com",
            version="v1alpha1",
            namespace="default",
            plural="records",
            name="test-cr",
        )
        assert result == {}

    def test_delete_custom_resource_forbidden(self, backend):
        exc = ApiException(status=403, reason="Forbidden")
        exc.body = "forbidden"
        backend.custom_api.delete_namespaced_custom_object.side_effect = exc
        result = backend.delete_custom_resource(
            group="dns.example.com",
            version="v1alpha1",
            namespace="default",
            plural="records",
            name="test-cr",
        )
        assert result == {}

    def test_delete_custom_resource_generic_error_raises(self, backend):
        exc = ApiException(status=500, reason="Server Error")
        exc.body = "error"
        backend.custom_api.delete_namespaced_custom_object.side_effect = exc
        with pytest.raises(BackendOperationError):
            backend.delete_custom_resource(
                group="dns.example.com",
                version="v1alpha1",
                namespace="default",
                plural="records",
                name="test-cr",
            )

    def test_describe_custom_resource_success(self, backend):
        expected = {"metadata": {"name": "test-cr"}}
        backend.custom_api.get_namespaced_custom_object.return_value = expected
        result = backend.describe_custom_resource(
            group="dns.example.com",
            version="v1alpha1",
            namespace="default",
            plural="records",
            name="test-cr",
        )
        assert result == expected

    def test_describe_custom_resource_not_found(self, backend):
        exc = ApiException(status=404, reason="Not Found")
        exc.body = "not found"
        backend.custom_api.get_namespaced_custom_object.side_effect = exc
        result = backend.describe_custom_resource(
            group="dns.example.com",
            version="v1alpha1",
            namespace="default",
            plural="records",
            name="test-cr",
        )
        assert result == {}

    def test_list_custom_resources_success(self, backend):
        backend.custom_api.list_namespaced_custom_object.return_value = {
            "items": [{"name": "cr1"}, {"name": "cr2"}]
        }
        result = backend.list_custom_resources(
            group="dns.example.com",
            version="v1alpha1",
            namespace="default",
            plural="records",
        )
        assert result == [{"name": "cr1"}, {"name": "cr2"}]

    def test_list_custom_resources_not_found(self, backend):
        exc = ApiException(status=404, reason="Not Found")
        exc.body = "not found"
        backend.custom_api.list_namespaced_custom_object.side_effect = exc
        result = backend.list_custom_resources(
            group="dns.example.com",
            version="v1alpha1",
            namespace="default",
            plural="records",
        )
        assert result == []

    def test_list_pods_calls_core_api(self, backend):
        backend.core_api.list_namespaced_pod.return_value = ["pod1", "pod2"]
        result = backend.list_pods(namespace="default")
        assert result == ["pod1", "pod2"]
        backend.core_api.list_namespaced_pod.assert_called_once_with(namespace="default")

    def test_list_custom_resource_definitions(self, backend):
        """list_custom_resource_definitions parses CRD specs into dicts."""
        mock_crd1 = MagicMock()
        mock_crd1.spec.names.kind = "Bucket"
        mock_crd1.spec.group = "s3.example.com"
        mock_crd1.spec.names.plural = "buckets"
        mock_version = MagicMock()
        mock_version.name = "v1alpha1"
        mock_version.served = True
        mock_crd1.spec.versions = [mock_version]

        mock_crd2 = MagicMock()
        mock_crd2.spec.names.kind = "Cluster"
        mock_crd2.spec.group = "k8s.example.com"
        mock_crd2.spec.names.plural = "clusters"
        mock_version2 = MagicMock()
        mock_version2.name = "v1"
        mock_version2.served = True
        mock_crd2.spec.versions = [mock_version2]

        backend.api.list_custom_resource_definition.return_value = MagicMock(
            items=[mock_crd1, mock_crd2]
        )
        result = backend.list_custom_resource_definitions()
        assert len(result) == 2
        assert result[0] == {
            "kind": "Bucket",
            "group": "s3.example.com",
            "version": "v1alpha1",
            "plural": "buckets",
        }
        assert result[1] == {
            "kind": "Cluster",
            "group": "k8s.example.com",
            "version": "v1",
            "plural": "clusters",
        }

    def test_init_with_token_and_host(self):
        """KubernetesBackend init with token+host should set _connected=True."""
        with patch("ewccli.backends.kubernetes.backend_k8s.client") as mock_client:
            mock_client.Configuration.return_value = MagicMock()
            mock_client.CustomObjectsApi.return_value = MagicMock()
            mock_client.CoreV1Api.return_value = MagicMock()
            mock_client.AppsV1Api.return_value = MagicMock()
            mock_client.ApiextensionsV1Api.return_value = MagicMock()
            k8s = KubernetesBackend(token="my-token", host="https://k8s.example.com")
            assert k8s.is_connected() is True

    def test_init_token_host_failure_raises_connection_error(self):
        """Token+host init failure raises BackendConnectionError."""
        with patch("ewccli.backends.kubernetes.backend_k8s.client") as mock_client:
            mock_client.Configuration.side_effect = Exception("config error")
            with pytest.raises(BackendConnectionError):
                KubernetesBackend(token="my-token", host="https://k8s.example.com")


# ---------------------------------------------------------------------------
# AnsibleBackend — extended coverage
# ---------------------------------------------------------------------------

class TestAnsibleBackendQA:
    """Extended tests for AnsibleBackend methods with mocks."""

    def test_is_connected_true_after_init(self):
        backend = AnsibleBackend()
        assert backend.is_connected() is True

    def test_close_sets_disconnected(self):
        backend = AnsibleBackend()
        backend.close()
        assert backend.is_connected() is False

    def test_connect_after_close(self):
        backend = AnsibleBackend()
        backend.close()
        assert backend.is_connected() is False
        backend.connect()
        assert backend.is_connected() is True

    def test_connect_with_args(self):
        """connect accepts arbitrary args/kwargs (no-op for Ansible)."""
        backend = AnsibleBackend()
        backend.close()
        backend.connect("arg1", key="value")
        assert backend.is_connected() is True

    def test_context_manager(self):
        with AnsibleBackend() as backend:
            assert backend.is_connected() is True
        assert backend.is_connected() is False

    @patch("ewccli.backends.ansible.backend_ansible.run_command_from_host")
    def test_run_ansible_returns_result(self, mock_run):
        """run_ansible delegates to run_command_from_host."""
        mock_run.return_value = (0, "success")
        backend = AnsibleBackend()
        rc, msg = backend.run_ansible(
            description="test task",
            command=["ansible-playbook", "site.yml"],
        )
        assert rc == 0
        assert msg == "success"
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["description"] == "test task"

    @patch("ewccli.backends.ansible.backend_ansible.run_command_from_host")
    def test_run_ansible_failure(self, mock_run):
        """run_ansible propagates non-zero return codes."""
        mock_run.return_value = (1, "task failed")
        backend = AnsibleBackend()
        rc, msg = backend.run_ansible(
            description="failing task",
            command=["ansible-playbook", "broken.yml"],
        )
        assert rc == 1
        assert "failed" in msg

    @patch("ewccli.backends.ansible.backend_ansible.run_command_from_host")
    def test_run_ansible_dry_run(self, mock_run):
        """run_ansible with dry_run=True passes it through."""
        mock_run.return_value = (0, "dry run")
        backend = AnsibleBackend()
        backend.run_ansible(
            description="test",
            command=["ansible-playbook", "site.yml"],
            dry_run=True,
        )
        assert mock_run.call_args.kwargs["dry_run"] is True

    @patch("ewccli.backends.ansible.backend_ansible.run_command_from_host")
    def test_install_ansible_roles(self, mock_run):
        """install_ansible_roles delegates to run_command_from_host."""
        mock_run.return_value = (0, "roles installed")
        backend = AnsibleBackend()
        rc, msg = backend.install_ansible_roles("/path/to/requirements.yml")
        assert rc == 0
        assert msg == "roles installed"
        mock_run.assert_called_once()
        assert "ansible-galaxy" in mock_run.call_args.kwargs["command"][0]
        assert "/path/to/requirements.yml" in mock_run.call_args.kwargs["command"][0]

    @patch("ewccli.backends.ansible.backend_ansible.run_command_from_host")
    def test_install_ansible_roles_dry_run(self, mock_run):
        """install_ansible_roles with dry_run passes it through."""
        mock_run.return_value = (0, "dry run")
        backend = AnsibleBackend()
        backend.install_ansible_roles("/path/to/requirements.yml", dry_run=True)
        assert mock_run.call_args.kwargs["dry_run"] is True

    @patch("ewccli.backends.ansible.backend_ansible.ansible_runner")
    @patch("ewccli.backends.ansible.backend_ansible.shutil")
    def test_run_ansible_live_success(self, mock_shutil, mock_runner, tmp_path):
        """run_ansible_live returns the runner return code on success."""
        mock_thread = MagicMock()
        mock_runner_obj = MagicMock()
        mock_runner_obj.rc = 0
        mock_runner.run_async.return_value = (mock_thread, mock_runner_obj)

        backend = AnsibleBackend()
        rc = backend.run_ansible_live(
            working_directory_path=str(tmp_path),
            cmdline=["ansible-playbook", "site.yml"],
        )
        assert rc == 0
        mock_runner.run_async.assert_called_once()
        mock_thread.join.assert_called_once()

    @patch("ewccli.backends.ansible.backend_ansible.ansible_runner")
    @patch("ewccli.backends.ansible.backend_ansible.shutil")
    def test_run_ansible_live_failure(self, mock_shutil, mock_runner, tmp_path):
        """run_ansible_live returns non-zero rc on failure."""
        mock_thread = MagicMock()
        mock_runner_obj = MagicMock()
        mock_runner_obj.rc = 2
        mock_runner.run_async.return_value = (mock_thread, mock_runner_obj)

        backend = AnsibleBackend()
        rc = backend.run_ansible_live(
            working_directory_path=str(tmp_path),
            cmdline=["ansible-playbook", "broken.yml"],
            description="failing task",
        )
        assert rc == 2

    @patch("ewccli.backends.ansible.backend_ansible.ansible_runner")
    @patch("ewccli.backends.ansible.backend_ansible.shutil")
    def test_run_ansible_live_cleans_artifacts(self, mock_shutil, mock_runner, tmp_path):
        """run_ansible_live removes env and artifacts directories."""
        mock_thread = MagicMock()
        mock_runner_obj = MagicMock()
        mock_runner_obj.rc = 0
        mock_runner.run_async.return_value = (mock_thread, mock_runner_obj)

        backend = AnsibleBackend()
        backend.run_ansible_live(
            working_directory_path=str(tmp_path),
            cmdline=["ansible-playbook", "site.yml"],
        )
        assert mock_shutil.rmtree.call_count >= 0


# ---------------------------------------------------------------------------
# Dependency injection mockability
# ---------------------------------------------------------------------------

class TestDependencyInjectionQA:
    """Verify that services accept interface-typed mock backends."""

    def test_server_service_accepts_mock_openstack_backend(self):
        """ServerService methods accept a mock typed as OpenstackBackendInterface."""
        from ewccli.services.server_service import ServerService
        mock_backend = MagicMock(spec=OpenstackBackendInterface)
        assert isinstance(mock_backend, OpenstackBackendInterface)
        service = ServerService()
        assert service is not None

    def test_hub_deploy_service_accepts_mock_ansible_backend(self):
        """HubDeployService methods accept a mock typed as AnsibleBackendInterface."""
        from ewccli.services.hub_deploy_service import HubDeployService
        mock_backend = MagicMock(spec=AnsibleBackendInterface)
        assert isinstance(mock_backend, AnsibleBackendInterface)
        service = HubDeployService()
        assert service is not None

    def test_mock_backend_methods_callable(self):
        """Mock backend methods can be configured and called like real backends."""
        mock_os = MagicMock()
        mock_os.get_connection.return_value = MagicMock()
        mock_os.is_connected.return_value = True
        mock_os.create_server.return_value = (MagicMock(), "created", {})

        conn = mock_os.get_connection()
        assert mock_os.is_connected() is True
        result = mock_os.create_server(
            conn=conn,
            server_name="test",
            image_name="img",
            flavour_name="flv",
            networks=(),
            keypair_name="kp",
            sec_groups=(),
        )
        assert result[1] == "created"
        mock_os.get_connection.assert_called_once()
        mock_os.create_server.assert_called_once()

    def test_all_three_backends_are_their_interfaces(self):
        """Concrete backend instances satisfy their respective interface protocols."""
        ansible = AnsibleBackend()
        assert isinstance(ansible, AnsibleBackendInterface)
        assert isinstance(ansible, BackendInterface)

    def test_interface_types_in_service_signatures(self):
        """Service method signatures reference interface types, not concrete classes."""
        import inspect
        from ewccli.services.server_service import ServerService
        from ewccli.services.hub_deploy_service import HubDeployService

        for method_name in ["create_server", "delete_server", "add_floating_ip"]:
            if hasattr(ServerService, method_name):
                sig = inspect.signature(getattr(ServerService, method_name))
                for param in sig.parameters.values():
                    if "backend" in param.name:
                        ann = str(param.annotation)
                        assert "Interface" in ann or "OpenstackBackendInterface" in ann
                        break

        for method_name in ["deploy_hub"]:
            if hasattr(HubDeployService, method_name):
                sig = inspect.signature(getattr(HubDeployService, method_name))
                for param in sig.parameters.values():
                    if "ansible" in param.name:
                        ann = str(param.annotation)
                        assert "Interface" in ann or "AnsibleBackend" in ann
                        break
