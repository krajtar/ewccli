#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details


"""Tests for the unified backend exception hierarchy, retry utilities,
and interface protocols introduced in Phase 3 (KAM-8).
"""

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
from ewccli.backends.ansible.backend_ansible import AnsibleBackend


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class TestBackendExceptionHierarchy:
    """Verify the unified exception hierarchy is correct."""

    def test_base_is_exception(self):
        assert issubclass(BackendError, Exception)

    def test_all_subclasses_inherit_base(self):
        for sub in [
            BackendConnectionError,
            BackendAuthError,
            BackendOperationError,
            BackendTimeoutError,
            BackendNotFoundError,
            BackendAlreadyExistsError,
            BackendValidationError,
            BackendConfigError,
        ]:
            assert issubclass(sub, BackendError)

    def test_auth_is_connection_error(self):
        assert issubclass(BackendAuthError, BackendConnectionError)

    def test_catch_base_catches_subclass(self):
        try:
            raise BackendTimeoutError("timeout")
        except BackendError:
            pass
        else:
            pytest.fail("BackendTimeoutError should be caught by BackendError")


# ---------------------------------------------------------------------------
# Retry utility
# ---------------------------------------------------------------------------

class TestRetryWithBackoff:
    """Tests for the retry_with_backoff decorator."""

    def test_no_retry_on_success(self):
        calls = 0

        @retry_with_backoff(max_retries=3, initial_delay=0)
        def succeed():
            nonlocal calls
            calls += 1
            return "ok"

        assert succeed() == "ok"
        assert calls == 1

    def test_retries_on_retryable_exception(self):
        calls = 0

        @retry_with_backoff(max_retries=3, initial_delay=0)
        def flaky():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise BackendTimeoutError("timeout")
            return "ok"

        assert flaky() == "ok"
        assert calls == 3

    def test_raises_after_max_retries(self):
        calls = 0

        @retry_with_backoff(max_retries=2, initial_delay=0)
        def always_fail():
            nonlocal calls
            calls += 1
            raise BackendTimeoutError("timeout")

        with pytest.raises(BackendTimeoutError):
            always_fail()
        assert calls == 3  # 1 initial + 2 retries

    def test_no_retry_on_non_retryable(self):
        calls = 0

        @retry_with_backoff(max_retries=3, initial_delay=0)
        def fail_operation():
            nonlocal calls
            calls += 1
            raise BackendOperationError("not retryable")

        with pytest.raises(BackendOperationError):
            fail_operation()
        assert calls == 1

    def test_custom_retry_on(self):
        calls = 0

        @retry_with_backoff(
            max_retries=2,
            initial_delay=0,
            retry_on=(ValueError,),
        )
        def fail_value():
            nonlocal calls
            calls += 1
            raise ValueError("custom")

        with pytest.raises(ValueError):
            fail_value()
        assert calls == 3


class TestIsRetryable:
    """Tests for the is_retryable helper."""

    def test_timeout_is_retryable(self):
        assert is_retryable(BackendTimeoutError("t")) is True

    def test_connection_is_retryable(self):
        assert is_retryable(BackendConnectionError("c")) is True

    def test_operation_not_retryable(self):
        assert is_retryable(BackendOperationError("o")) is False

    def test_generic_exception_not_retryable(self):
        assert is_retryable(ValueError("v")) is False


# ---------------------------------------------------------------------------
# Interface protocol compliance
# ---------------------------------------------------------------------------

class TestInterfaceProtocols:
    """Verify that concrete backends satisfy their interface protocols."""

    def test_openstack_backend_is_backend_interface(self):
        assert isinstance(OpenstackBackend.__new__(OpenstackBackend),
                          type) or issubclass(OpenstackBackend, BackendInterface)

    def test_openstack_backend_is_openstack_interface(self):
        assert issubclass(OpenstackBackend, OpenstackBackendInterface)

    def test_kubernetes_backend_is_kubernetes_interface(self):
        assert issubclass(KubernetesBackend, KubernetesBackendInterface)

    def test_ansible_backend_is_ansible_interface(self):
        assert issubclass(AnsibleBackend, AnsibleBackendInterface)

    def test_all_backends_are_backend_interface(self):
        for cls in [OpenstackBackend, KubernetesBackend, AnsibleBackend]:
            assert issubclass(cls, BackendInterface)


# ---------------------------------------------------------------------------
# OpenstackBackend connection lifecycle
# ---------------------------------------------------------------------------

class TestOpenstackConnectionLifecycle:
    """Tests for the centralised connection lifecycle in OpenstackBackend."""

    @pytest.fixture
    def backend(self):
        """Create an OpenstackBackend without running __init__."""
        instance = OpenstackBackend.__new__(OpenstackBackend)
        instance._connection = None
        instance.credential_id = "test-id"
        instance.credential_secret = "test-secret"
        instance.auth_url = "https://test.example.com"
        return instance

    def test_get_connection_caches(self, backend):
        """get_connection should cache the connection."""
        mock_conn = MagicMock()
        with patch.object(backend, "connect", return_value=mock_conn) as mock_connect:
            conn1 = backend.get_connection()
            conn2 = backend.get_connection()
            assert conn1 is mock_conn
            assert conn2 is mock_conn
            assert mock_connect.call_count == 1

    def test_get_connection_raises_on_failure(self, backend):
        """get_connection should raise BackendConnectionError on failure."""
        with patch.object(backend, "connect", side_effect=Exception("boom")):
            with pytest.raises(BackendConnectionError):
                backend.get_connection()

    def test_is_connected_false_initially(self, backend):
        assert backend.is_connected() is False

    def test_is_connected_true_after_connect(self, backend):
        mock_conn = MagicMock()
        with patch.object(backend, "connect", return_value=mock_conn):
            backend.get_connection()
            assert backend.is_connected() is True

    def test_close_clears_connection(self, backend):
        backend._connection = MagicMock()
        backend.close()
        assert backend._connection is None
        assert backend.is_connected() is False

    def test_context_manager_closes(self, backend):
        mock_conn = MagicMock()
        with patch.object(backend, "connect", return_value=mock_conn):
            with backend as b:
                b.get_connection()
                assert b.is_connected() is True
            assert b.is_connected() is False

    def test_init_raises_on_missing_credentials(self):
        """__init__ should raise BackendConfigError without credentials."""
        with patch("ewccli.backends.openstack.backend_ostack.OpenStackConfig") as mock_cfg:
            mock_cfg.return_value.get_one.side_effect = Exception("no config")
            with pytest.raises(BackendConfigError):
                OpenstackBackend()

    def test_create_server_raises_on_long_name(self, backend):
        """create_server should raise BackendValidationError for long names."""
        mock_conn = MagicMock()
        long_name = "x" * 100
        with pytest.raises(BackendValidationError):
            backend.create_server(
                conn=mock_conn,
                server_name=long_name,
                image_name="test",
                flavour_name="test",
                networks=(),
                keypair_name="test",
                sec_groups=(),
            )


# ---------------------------------------------------------------------------
# KubernetesBackend error handling
# ---------------------------------------------------------------------------

class TestKubernetesErrorHandling:
    """Tests for KubernetesBackend error handling improvements."""

    def test_init_raises_on_config_failure(self):
        """__init__ should raise BackendConnectionError on config failure."""
        from kubernetes.config.config_exception import ConfigException as K8sConfigException
        with patch(
            "ewccli.backends.kubernetes.backend_k8s.config.load_kube_config",
            side_effect=K8sConfigException("no config"),
        ):
            with pytest.raises(BackendConnectionError):
                KubernetesBackend()

    def test_close_sets_disconnected(self):
        """close should set _connected to False."""
        instance = KubernetesBackend.__new__(KubernetesBackend)
        instance._connected = True
        instance.close()
        assert instance.is_connected() is False


# ---------------------------------------------------------------------------
# AnsibleBackend interface compliance
# ---------------------------------------------------------------------------

class TestAnsibleBackendInterface:
    """Tests for AnsibleBackend interface compliance."""

    def test_init_sets_connected(self):
        backend = AnsibleBackend()
        assert backend.is_connected() is True

    def test_connect_sets_connected(self):
        backend = AnsibleBackend()
        backend.close()
        assert backend.is_connected() is False
        backend.connect()
        assert backend.is_connected() is True

    def test_context_manager(self):
        with AnsibleBackend() as backend:
            assert backend.is_connected() is True
        assert backend.is_connected() is False
