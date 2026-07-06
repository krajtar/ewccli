# Backend Architecture

> **Phase 3 (KAM-8)** — Stabilize & Interface Backend Clients
>
> This document describes the architecture of the `ewccli.backends` package
> after the Phase 3 refactoring. It covers the interface protocols, exception
> hierarchy, retry/timeout utilities, connection lifecycle, dependency
> injection patterns, and the Crossplane decision.

## Overview

The `ewccli.backends` package wraps three external infrastructure backends —
**OpenStack**, **Kubernetes**, and **Ansible** — behind clean
`typing.Protocol` interfaces. This allows the service layer to depend on
contracts rather than concrete implementations, enabling:

- **Swappability** — any implementation satisfying the protocol can replace
  the default client.
- **Testability** — services receive mock backends in unit tests; no heavy
  SDK dependencies are imported during testing.
- **Consistency** — all backends share a unified exception hierarchy,
  retry/timeout behavior, and connection lifecycle.

### Package Layout

```
ewccli/backends/
├── __init__.py                  # Package docstring & exports
├── interfaces.py                # Protocol definitions (BackendInterface + sub-protocols)
├── exceptions.py                # Unified exception hierarchy
├── retry.py                     # retry_with_backoff decorator & is_retryable helper
├── CROSSPLANE_DECISION.md       # Decision record: defer Crossplane commands
├── openstack/
│   └── backend_ostack.py        # OpenstackBackend (implements OpenstackBackendInterface)
├── kubernetes/
│   ├── backend_k8s.py           # KubernetesBackend (implements KubernetesBackendInterface)
│   └── exceptions.py            # ResourceAlreadyExistsError (extends BackendAlreadyExistsError)
└── ansible/
    └── backend_ansible.py       # AnsibleBackend (implements AnsibleBackendInterface)
```

---

## 1. Backend Interface Protocols

All backend contracts are defined in `ewccli/backends/interfaces.py` using
`typing.Protocol` with the `@runtime_checkable` decorator. Structural typing
means concrete backend classes do **not** need to explicitly inherit from the
protocol — they just need to implement the required methods. However, the
concrete classes do subclass their protocol for documentation clarity.

### Base Protocol: `BackendInterface`

Every backend implements three connection-lifecycle methods:

| Method | Signature | Purpose |
|--------|-----------|---------|
| `connect` | `connect(*args, **kwargs) -> Any` | Establish a connection to the backend service. Raises `BackendError` on failure. |
| `close` | `close() -> None` | Release resources (connections, sessions). |
| `is_connected` | `is_connected() -> bool` | Return `True` if the backend has an active connection. |

All concrete backends also implement the context-manager protocol
(`__enter__` / `__exit__`) so they can be used in `with` statements:

```python
with OpenstackBackend(...) as backend:
    conn = backend.get_connection()
    # ... use conn ...
# close() called automatically on exit
```

### `OpenstackBackendInterface`

Extends `BackendInterface`. Methods accept an active `conn`
(`openstack.connection.Connection`) obtained via `get_connection()` or
`connect()`.

| Method | Returns | Description |
|--------|---------|-------------|
| `get_connection(...)` | `Connection` | Return a cached or newly-created OpenStack connection (see [Connection Lifecycle](#3-connection-lifecycle)). |
| `create_server(conn, server_name, image_name, flavour_name, networks, keypair_name, sec_groups, **kwargs)` | `Tuple[Any, Optional[str], Dict]` | Create an OpenStack VM. Raises `BackendValidationError` if the server name exceeds 63 characters. |
| `delete_server(conn, server_name, **kwargs)` | `Any` | Delete a server by name. |
| `list_servers(conn, **kwargs)` | `List[Any]` | List all visible servers. |
| `find_latest_image(conn, prefix)` | `Any` | Find the latest image whose name starts with `prefix`. |
| `check_server_inputs(conn, **kwargs)` | `Tuple[bool, Optional[str]]` | Validate server creation inputs against OpenStack resources. |
| `add_external_ip(conn, server_name, **kwargs)` | `Any` | Attach a floating IP. |
| `remove_external_ip(conn, server_name, **kwargs)` | `Any` | Detach a floating IP. |
| `list_networks(conn, **kwargs)` | `List[Any]` | List available networks. |
| `remove_network(conn, network_id, **kwargs)` | `Any` | Remove a network by ID. |
| `create_keypair(conn, keypair_name, public_key_path, **kwargs)` | `Tuple[Any, str]` | Create or verify an SSH keypair. |
| `delete_keypair(conn, keypair_name, **kwargs)` | `Tuple[Any, str]` | Delete an SSH keypair. |

**Concrete implementation:** `ewccli.backends.openstack.backend_ostack.OpenstackBackend`

### `KubernetesBackendInterface`

Extends `BackendInterface`. All methods operate on the Kubernetes API server
configured at construction time.

| Method | Returns | Description |
|--------|---------|-------------|
| `create_custom_resource(group, version, namespace, plural, body)` | `Dict[str, Any]` | Create a namespaced custom resource. Handles 409 (AlreadyExists) and 422 (validation) gracefully. |
| `delete_custom_resource(group, version, namespace, plural, name)` | `Dict[str, Any]` | Delete a custom resource by name. Returns `{}` on 404. |
| `describe_custom_resource(group, version, namespace, plural, name)` | `Dict[str, Any]` | Retrieve a single custom resource. |
| `list_custom_resources(group, version, namespace, plural)` | `List[Dict[str, Any]]` | List custom resources in a namespace. |
| `list_pods(namespace)` | `Any` | List pods in a namespace. |
| `list_custom_resource_definitions()` | `List[Dict[str, str]]` | List all CRDs (kind, group, version, plural). |

**Concrete implementation:** `ewccli.backends.kubernetes.backend_k8s.KubernetesBackend`

### `AnsibleBackendInterface`

Extends `BackendInterface`. Ansible does not maintain a persistent
connection; `connect`/`close`/`is_connected` are provided for interface
compatibility.

| Method | Returns | Description |
|--------|---------|-------------|
| `run_ansible_live(working_directory_path, cmdline, **kwargs)` | `int` | Run an Ansible task with live output streaming via `ansible_runner`. Returns the runner exit code. |
| `run_ansible(description, command, **kwargs)` | `Tuple[int, str]` | Run an ansible command. Returns `(return_code, message)`. |
| `install_ansible_roles(requirements_path, **kwargs)` | `Tuple[int, str]` | Install Ansible roles from a requirements file. Returns `(return_code, message)`. |

**Concrete implementation:** `ewccli.backends.ansible.backend_ansible.AnsibleBackend`

### Runtime Checking

Protocols are decorated with `@runtime_checkable`, enabling `isinstance()`
checks at runtime:

```python
from ewccli.backends.interfaces import OpenstackBackendInterface
from ewccli.backends.openstack.backend_ostack import OpenstackBackend

assert isinstance(OpenstackBackend(...), OpenstackBackendInterface)
```

---

## 2. Exception Hierarchy

All backend clients raise exceptions from a single unified hierarchy defined
in `ewccli/backends/exceptions.py`. This lets the service layer catch a
single `BackendError` family instead of client-specific exception types.

```
Exception
└── BackendError                          # Base for all backend-layer errors
    ├── BackendConnectionError            # Cannot establish/maintain connection
    │   └── BackendAuthError              # Authentication/authorization failure
    ├── BackendOperationError             # Non-transient operation failure (never retried)
    ├── BackendTimeoutError               # Operation exceeded its timeout (retried by default)
    ├── BackendNotFoundError              # Requested resource not found
    ├── BackendAlreadyExistsError         # Resource already exists on create
    ├── BackendValidationError            # Input rejected by backend validation
    └── BackendConfigError                # Missing/invalid credentials or endpoints
```

### Usage in Concrete Backends

| Backend | Exception | When Raised |
|---------|-----------|-------------|
| OpenStack | `BackendConfigError` | Credentials missing from params, env, or `clouds.yaml` |
| OpenStack | `BackendConnectionError` | `get_connection()` fails to connect |
| OpenStack | `BackendValidationError` | Server name exceeds 63 characters |
| Kubernetes | `BackendConnectionError` | Token+host init fails, or `kubeconfig` load fails |
| Kubernetes | `BackendOperationError` | Unhandled Kubernetes API error (non-404/403/401/409/422) |
| Kubernetes | `ResourceAlreadyExistsError` | (subclass of `BackendAlreadyExistsError`) CRD already exists |
| Ansible | *(returns error codes)* | Ansible backend returns `(return_code, message)` tuples rather than raising |

### Catching Strategy

```python
from ewccli.backends.exceptions import BackendError, BackendConnectionError

try:
    conn = backend.get_connection()
except BackendConnectionError:
    # connection-specific handling (retry, re-auth, user message)
    ...
except BackendError:
    # catch-all for any other backend failure
    ...
```

---

## 3. Connection Lifecycle

### Problem (Pre-Phase 3)

`OpenstackBackend.connect()` was invoked **per-command**, creating a new
OpenStack connection on every CLI invocation. This was inefficient and made
connection management scattered across the codebase.

### Solution: Centralized `get_connection()`

`OpenstackBackend` now provides `get_connection()` which:

1. **Lazily creates** the connection on first call.
2. **Caches** the connection on the instance (`self._connection`).
3. Returns the cached connection on subsequent calls (even if different
   parameters are supplied).

All CLI commands (`infra_command.py`, `hub_command.py`) were updated to call
`get_connection()` instead of `connect()`:

```python
# Before (Phase 2):
openstack_api = ctx.openstack_backend.connect(auth_url=..., ...)

# After (Phase 3):
openstack_api = ctx.openstack_backend.get_connection(auth_url=..., ...)
```

### Per-Backend Lifecycle

| Backend | `connect()` | `close()` | `is_connected()` | Context Manager |
|---------|-------------|-----------|-------------------|-----------------|
| OpenStack | Creates/caches connection via `openstack.connect()` | Closes cached connection, sets `_connection = None` | `True` if `_connection is not None` | Yes |
| Kubernetes | Re-initializes client (called in `__init__`; `connect()` re-inits if credentials change) | Sets `_connected = False` | `True` if client initialized | Yes |
| Ansible | No-op (Ansible manages per-task connections via `ansible_runner`) | Sets `_connected = False` | Always `True` after init (per-task lifecycle) | Yes |

### Resource Cleanup

All backends support the context-manager protocol (`with` statement) for
automatic resource cleanup:

```python
with OpenstackBackend(cred_id, cred_secret, auth_url) as ostack:
    conn = ostack.get_connection()
    servers = ostack.list_servers(conn)
# close() is called automatically — connection released
```

---

## 4. Retry & Timeout Configuration

Retry and timeout utilities are defined in `ewccli/backends/retry.py`.

### `retry_with_backoff` Decorator

Wraps a callable with exponential-backoff retries:

```python
from ewccli.backends.retry import retry_with_backoff
from ewccli.backends.exceptions import BackendTimeoutError, BackendConnectionError

@retry_with_backoff(
    max_retries=3,        # retry attempts (excluding the initial call)
    initial_delay=1.0,    # seconds before first retry
    max_delay=30.0,       # cap on delay between retries
    backoff_factor=2.0,   # multiplier applied after each retry
    retry_on=(BackendTimeoutError, BackendConnectionError),  # retryable exceptions
)
def flaky_operation():
    ...
```

**Behavior:**

1. The decorated function is called once.
2. If it raises an exception in `retry_on`, the decorator waits `delay`
   seconds and retries.
3. After each retry, `delay` is multiplied by `backoff_factor` (capped at
   `max_delay`).
4. After `max_retries` attempts, the last exception is re-raised.
5. Exceptions in `_NO_RETRY_ON` (`BackendOperationError`) are **never**
   retried — they are re-raised immediately.

### Default Retry Policy

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_retries` | `3` | Maximum retry attempts (excluding initial call) |
| `initial_delay` | `1.0` | Seconds before first retry |
| `max_delay` | `30.0` | Maximum delay between retries |
| `backoff_factor` | `2.0` | Delay multiplier after each retry |
| `retry_on` | `(BackendTimeoutError, BackendConnectionError)` | Exceptions that trigger retry |

### Non-Retryable Exceptions

`BackendOperationError` is explicitly listed in `_NO_RETRY_ON` and will
**never** be retried, even if it is a `BackendError` subclass. This prevents
retries on permanent failures (e.g., invalid input, missing resource).

### `is_retryable` Helper

```python
from ewccli.backends.retry import is_retryable
from ewccli.backends.exceptions import BackendTimeoutError, BackendOperationError

assert is_retryable(BackendTimeoutError("timeout"))     # True
assert not is_retryable(BackendOperationError("fail"))  # False
```

---

## 5. Dependency Injection Pattern

### Principle

The service layer depends on **interface protocols**, not concrete backend
classes. Backends are injected into services as parameters, making them
swappable and mockable.

### Before (Phase 2)

Services imported and type-hinted concrete classes:

```python
from ewccli.backends.openstack.backend_ostack import OpenstackBackend

class ServerService:
    @staticmethod
    def deploy_server(
        openstack_backend: OpenstackBackend,  # concrete class — hard to mock
        ...
    ):
        ...
```

### After (Phase 3)

Services type-hint the protocol interface:

```python
from ewccli.backends.interfaces import OpenstackBackendInterface

class ServerService:
    @staticmethod
    def deploy_server(
        openstack_backend: OpenstackBackendInterface,  # protocol — any impl works
        ...
    ):
        ...
```

### Updated Service Signatures

| Service | Method | Parameter Type (Before → After) |
|---------|--------|---------------------------------|
| `ServerService` | `resolve_image_and_flavor` | `OpenstackBackend` → `OpenstackBackendInterface` |
| `ServerService` | `pre_deploy_server_setup` | `OpenstackBackend` → `OpenstackBackendInterface` |
| `ServerService` | `deploy_server` | `OpenstackBackend` → `OpenstackBackendInterface` |
| `ServerService` | `post_deploy_server_setup` | `OpenstackBackend` → `OpenstackBackendInterface` |
| `ServerService` | `create_server_command` | `OpenstackBackend` → `OpenstackBackendInterface` |
| `HubDeployService` | `run_item` | `AnsibleBackend` → `AnsibleBackendInterface` |

### Testing with Mocks

Because services accept the protocol, tests inject mocks without importing
SDK dependencies:

```python
from unittest.mock import MagicMock
from ewccli.services.server_service import ServerService

def test_deploy_server():
    mock_backend = MagicMock()  # satisfies OpenstackBackendInterface structurally
    mock_conn = MagicMock()
    ServerService.deploy_server(
        openstack_backend=mock_backend,
        openstack_api=mock_conn,
        ...
    )
    mock_backend.create_server.assert_called_once()
```

### CLI Context Injection

Backends are stored on the CLI context object (`ctx.openstack_backend`,
`ctx.k8s_backend`, etc.) and passed to services. This centralizes backend
construction and allows the context to be the single injection point.

---

## 6. Crossplane Decision

The Crossplane-backed command groups (`k8s`, `dns`, `s3`) are currently
commented out in `ewccli.py`. The full decision record is documented in
[`CROSSPLANE_DECISION.md`](./CROSSPLANE_DECISION.md).

**Decision: Defer re-enabling.**

### Rationale

1. No active Crossplane deployment in any EWC production environment.
2. `KubernetesBackend` is now stabilized with proper interfaces — re-enabling
   will require minimal changes when Crossplane is ready.
3. The command implementations are functional and tested; removal would lose
   working code.
4. Phase 4 (KAM-9) will build a standalone backend API service that may
   supersede these CLI commands.

### Re-evaluation Triggers

Re-enable when **all** are true:
- Crossplane CRDs deployed in at least one EWC region.
- Crossplane provider stack passed integration testing.
- Decision made on CLI vs API as preferred interface for k8s/dns/s3.

### Affected Files

| File | Status |
|------|--------|
| `ewccli/ewccli.py` | Commands remain commented out |
| `ewccli/commands/k8s_command.py` | Unchanged — ready for re-enable |
| `ewccli/commands/dns_command.py` | Unchanged — ready for re-enable |
| `ewccli/commands/s3_command.py` | Unchanged — ready for re-enable |
| `ewccli/backends/kubernetes/backend_k8s.py` | Hardened in Phase 3 |

---

## Summary

The Phase 3 refactoring transforms the backend layer from ad-hoc, per-command
clients into a clean, interface-driven architecture:

- **Protocols** (`interfaces.py`) define contracts for each backend.
- **Exceptions** (`exceptions.py`) provide a unified, catchable hierarchy.
- **Retry** (`retry.py`) offers configurable exponential backoff.
- **Connection lifecycle** is centralized via `get_connection()` and
  context-manager support.
- **Dependency injection** lets services depend on protocols, enabling
  mock-based testing.
- **Crossplane** commands are deferred with a documented decision record.
