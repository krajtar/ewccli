# Crossplane Backend Commands — Decision: Defer

## Context

The `ewccli.py` entry point currently comments out three Crossplane-backed
command groups:

```python
# from ewccli.commands.k8s_command import ewc_k8s_command
# from ewccli.commands.dns_command import ewc_dns_command
# from ewccli.commands.s3_command import ewc_s3_command
```

These commands depend on Crossplane CRDs (`clusters`, `records`, `buckets`)
being deployed in the target Kubernetes cluster.  They were disabled because
the Crossplane provider stack is not yet production-ready in the European
Weather Cloud.

## Decision

**Defer re-enabling.**  The commands remain commented out for now.

### Rationale

1. **No active Crossplane deployment** — The CRDs these commands target
   (`cluster.europeanweather.cloud`, `dns.europeanweather.cloud`,
   `bucket.europeanweather.cloud`) are not deployed in any production
   EWC environment.  Re-enabling would expose broken commands to users.

2. **KubernetesBackend is now stabilised** — Phase 3 has hardened
   `KubernetesBackend` with a proper interface, exception hierarchy, and
   connection lifecycle.  When Crossplane is ready, the commands can be
   re-enabled with minimal changes (they already use the backend's
   `list_custom_resources`, `create_custom_resource`,
   `delete_custom_resource`, and `describe_custom_resource` methods).

3. **Removal would lose working code** — The command implementations are
   functional and tested.  Removing them would require re-implementation
   when Crossplane is deployed.

4. **Phase 4 (KAM-9) will build the standalone backend API service** which
   may supersede these CLI commands with API-driven equivalents.  Re-evaluating
   at that point avoids wasted effort.

## Re-evaluation Triggers

Re-enable the Crossplane commands when **all** of the following are true:

- Crossplane CRDs are deployed in at least one EWC region.
- The Crossplane provider stack has passed integration testing.
- A decision has been made on whether CLI commands or API endpoints are the
  preferred interface for k8s/dns/s3 resource management.

## Affected Files

| File | Status |
|------|--------|
| `ewccli/ewccli.py` | Commands remain commented out |
| `ewccli/commands/k8s_command.py` | Unchanged — ready for re-enable |
| `ewccli/commands/dns_command.py` | Unchanged — ready for re-enable |
| `ewccli/commands/s3_command.py` | Unchanged — ready for re-enable |
| `ewccli/backends/kubernetes/backend_k8s.py` | Hardened in Phase 3 |
