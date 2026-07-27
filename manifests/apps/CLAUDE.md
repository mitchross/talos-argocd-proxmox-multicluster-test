# Application Guidelines

## Adding New Applications

Shared workload source lives in `manifests/apps/category/app-name/base/`; each
cluster gets a deployable overlay at `clusters/<cluster>/apps/category/app-name/`
(see `manifests/apps/development/nginx/` for the pattern).

The cluster-local app ApplicationSets
directory-discover `clusters/<cluster>/apps/*/*`, derive the Application name,
project, namespace, and source path, and deploy only to
`https://kubernetes.default.svc`. Do not add app `.argocd/config.json` files.
Each cluster owns its own complete HTTPRoute. OpenShift must never reference
`clusters/talos`, and Talos must never reference `clusters/openshift`.

### Application with Web Access

Services MUST have named ports for HTTPRoute to work:

```yaml
# service.yaml
spec:
  ports:
    - name: http        # CRITICAL - HTTPRoute fails silently without this
      port: 8080
      targetPort: 8080

# clusters/talos/apps/category/app-name/httproute.yaml - TALOS EXTERNAL
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: app-route
  namespace: app-name
  labels:
    external-dns: "true"                                    # REQUIRED - external-dns won't create DNS without this
  annotations:
    external-dns.alpha.kubernetes.io/target: vanillax.me    # REQUIRED - CNAMEs to Cloudflare tunnel
spec:
  parentRefs:
  - kind: Gateway
    name: gateway-external
    namespace: gateway
    sectionName: https          # REQUIRED - must bind to HTTPS listener, not just the gateway
  hostnames:
  - app.vanillax.me
  rules:
  - backendRefs:
    - name: app-service
      port: 8080
```

Internal-only Talos routes bind to `gateway-internal` instead (no external-dns
label/annotation, no `sectionName`).

OpenShift routes are separate complete files under
`clusters/openshift/apps/...`. Do not copy Talos `gateway-external`,
`gateway-internal`, Cloudflare tunnel targets, or `vanillax.me` assumptions
into OpenShift. Before changing OpenShift route hostnames, read
`docs/domains/multicluster/handoff-notes.md`; the live OpenShift Gateway DNS
boundary is not yet resolved.

### Deployment Strategy for Apps with PVCs

**CRITICAL**: Any Deployment that mounts a `ReadWriteOnce` PVC **must** use `strategy: type: Recreate`. The default `RollingUpdate` creates a deadlock — the new pod can't attach the RWO volume while the old pod still holds it, so the rollout hangs forever in `ContainerCreating`.

```yaml
# deployment.yaml
spec:
  strategy:
    type: Recreate    # REQUIRED for RWO PVCs - RollingUpdate causes Multi-Attach deadlock
  replicas: 1
```

### Jobs with ArgoCD Hooks (Migration/Setup Jobs)

**CRITICAL**: Kubernetes Jobs are immutable after creation. When Renovate bumps an image tag, ArgoCD can't apply the updated spec and sync fails with "field is immutable". All Jobs must have ArgoCD hook annotations.

**For standalone Job YAML files** (you control the manifest):
```yaml
# job.yaml
metadata:
  annotations:
    argocd.argoproj.io/hook: Sync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
    argocd.argoproj.io/sync-wave: "1"   # optional, controls ordering
```

**For Jobs rendered by Helm charts** (upstream chart, can't edit directly):
```yaml
# kustomization.yaml - add patches section
patches:
- target:
    kind: Job
  patch: |
    - op: add
      path: /metadata/annotations/argocd.argoproj.io~1hook
      value: Sync
    - op: add
      path: /metadata/annotations/argocd.argoproj.io~1hook-delete-policy
      value: BeforeHookCreation
```

`BeforeHookCreation` deletes the old Job before creating the new one, sidestepping immutability. Failed Jobs stay for debugging until the next sync.

**Do NOT use `Replace=true,Force=true`** — causes duplicate Job execution ([#24005](https://github.com/argoproj/argo-cd/issues/24005)).

### Application with Persistent Storage + Backups

Shared app bases use the portable local storage contract:

```yaml
spec:
  storageClassName: vanillax-local-rwo
```

Talos maps `vanillax-local-rwo` to Longhorn. OpenShift maps it to TrueNAS
iSCSI via the official truenas-csi driver — the live default class, set in
`clusters/openshift/infra/truenas-csi/storageclasses.yaml`. LVM Storage
(`clusters/openshift/infra/lvm-storage/`) is staged/disabled, not the mapping.

Talos backups use pvc-plumber `v4.0.2`. pvc-plumber owns VolSync
`ReplicationSource` and `ReplicationDestination` resources for opted-in PVCs.
Do not add inline RS/RD documents for normal application PVCs.

The shared repo Secret `volsync-kopia-repository` is produced in every
namespace labeled `volsync.backube/privileged-movers: "true"` by
`ClusterExternalSecret/volsync-kopia-repository` (see
`clusters/talos/infra/volsync-backup-cluster/`). Add that label on the
namespace.

A `wait-for-rustfs` init container is auto-injected on every mover Job by
`MutatingAdmissionPolicy/volsync-mover-backend-availability`. Backups fail
fast (and Job-backoff-retry) if RustFS is unreachable.

Reference:
`manifests/apps/media/jellyfin/base/pvc.yaml` and
`manifests/apps/home/paperless-ngx/base/pvc.yaml`. Pattern:

```yaml
# namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: app-name
  labels:
    pvc-plumber.io/managed-namespace: "true"       # Talos software write gate
    volsync.backube/privileged-movers: "true"   # REQUIRED — ClusterES selector

---
# pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: app-data
  namespace: app-name
  labels:
    app: app-name
    restore-policy: "strict"
    pvc-plumber.io/enabled: "true"
    pvc-plumber.io/manage-volsync: "true"
    pvc-plumber.io/tier: "daily"
  annotations:
    # ServerSideDiff dry-runs SSA; the apiserver rejects any change to
    # the immutable dataSourceRef on a Bound PVC and wedges sync. The
    # global Argo `ignoreDifferences` then masks the dataSource drift
    # normally. See docs/domains/argocd/argocd.md "Server-Side Diff & Apply Strategy".
    argocd.argoproj.io/compare-options: ServerSideDiff=false
spec:
  storageClassName: vanillax-local-rwo
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  # Static dataSourceRef — VolSync's volume populator reads the latest
  # snapshot from the shared kopia repo on PVC re-creation (DR / namespace
  # recreate). No-op while the PVC is already Bound.
  dataSourceRef:
    apiGroup: volsync.backube
    kind: ReplicationDestination
    name: app-data-dst
```

Verify the Talos operator-owned resources after syncing:

```
kubectl port-forward -n pvc-plumber svc/pvc-plumber-metrics 8080:8080
curl -fsS http://127.0.0.1:8080/audit
```

**When to back up a PVC**:
- User-generated content (photos, documents, uploads)
- Non-CNPG database volumes (Redis, SQLite, etc.)
- Configuration that's hard to recreate
- AI model caches (large downloads)

**When NOT to back up a PVC** — mark `backup-exempt: "true"` + annotation
`storage.vanillax.dev/backup-exempt-reason: "<reason>"` (the **fully-qualified**
key — bare `backup-exempt-reason` is silently ignored by CI guard):
- Temporary/cache data
- Data synced from external sources
- System namespaces (auto-excluded anyway)
- PVCs that will be frequently deleted/recreated
- **CNPG database PVCs** — these use Barman to S3, not VolSync

OpenShift overlays currently remove Talos pvc-plumber, VolSync, restore labels,
and `dataSourceRef` fields. Do not claim OpenShift backup coverage until an
OpenShift-specific backup policy is selected and tested.

For the complete Talos backup contract, use `.claude/commands/add-backup.md`
and `docs/talos-argocd-pvc-plumber-integration.md`.

Reference examples (Helm + Kustomize, Job hooks, backups, and more) are
tabulated in the root `CLAUDE.md`.
