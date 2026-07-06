# Crossplane Backend Commands — Decision: Defer

## Status: Deferred

The `k8s`, `dns`, and `s3` CLI commands (Crossplane-backed) remain
commented out in `ewccli.py`. They will **not** be re-enabled in Phase 3.

## Rationale

1. **No active demand.** The commands have been disabled with no reported
   user requests to restore them.
2. **Stabilization is complete.** `KubernetesBackend` now implements
   `KubernetesBackendInterface` with unified error handling. When the
   commands are needed, they can be re-enabled against the stabilized
   backend without further refactoring.
3. **Phase 4 supersedes.** The standalone `ewc-backend` service (KAM-9)
   will expose DNS/S3 management via REST endpoints. The CLI will call
   those endpoints (Phase 6, KAM-11) rather than managing Crossplane
   CRDs directly.
4. **Scope discipline.** Re-enabling commented-out commands would expand
   Phase 3 scope without advancing the stabilization goal.

## Re-enable Path

When demand arises:
1. Uncomment imports and `add_command` calls in `ewccli.py`.
2. Verify `KubernetesBackend` interface coverage for any command-specific
   methods.
3. Add integration tests against a real Crossplane-enabled cluster.
