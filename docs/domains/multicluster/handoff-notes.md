# Multi-Cluster Handoff Notes

> **Canonical continuation note:** Read this file before any multicluster,
> OpenShift, Gateway API, LVM Storage, route-domain, or bootstrap work. The
> structural migration is locally accepted, but the live OpenShift target is
> **not ready for bootstrap** as of June 4, 2026.

## June 9, 2026 (later) — 1:1 parity is deliberate; do NOT trim overlays

Operator decision (explicit, this date): **keep full 1:1 app parity between
Talos and OpenShift in Git.** The complete overlay catalog is the proof that
the Kustomize layout ports across distributions — that is the repo's purpose
(work-learning: "Kubernetes is Kubernetes", lab vs prod). Duplicate running
apps (immich, frigate, ...) are acceptable; the operator will power things
off **by hand at runtime** as desired. A curated-subset trim was attempted
and reverted the same day — do not re-attempt it. Agents: never delete
`clusters/openshift/apps` overlays to "reduce scope"; CI enforces parity in
both directions (overlay count derived from `manifests/apps`, plus an
orphan-overlay guard). The n-cluster onboarding path is documented in
`docs/adding-a-cluster.md`.

## June 9, 2026 Update — supersedes stale details below

The tree moved past several statements in the body of this document. Where
they conflict, this section wins:

- **Storage: democratic-csi was replaced by the official iXsystems
  `truenas-csi` driver** (`csi.truenas.io`, vendored v1.0.4, commit
  `99c3576`). TrueNAS 26 removed the REST API democratic-csi depends on; the
  official driver uses the WebSocket API. `vanillax-local-rwo` (default,
  iSCSI zvols under `BigTank/k8s/iscsi/v`, `reclaimPolicy: Retain`) and
  `truenas-nfs-csi` (RWX NFS under `BigTank/k8s/nfs/v`) are both provisioned
  by `csi.truenas.io`. See `clusters/openshift/infra/truenas-csi/`.
  - **Secret contract changed:** the two `democratic-csi-truenas-{iscsi,nfs}`
    1Password items described below are obsolete. The driver now reads ONE
    item, `truenas-csi` (field `apiKey`), in `homelab-prod`, via the
    `truenas-api-credentials` ExternalSecret.
- **Route/domain model changed: OpenShift Gateway apps use flat
  `*.vanillax.xyz`**, not `*.gateway.apps.sno-ai-lab.vanillax.xyz`. The
  single `openshift-gateway` (namespace `openshift-ingress`, MetalLB
  `192.168.10.230`) carries listeners for `*.vanillax.xyz`; cert-manager's
  gateway-shim issues `cert-openshift-gateway-apps` from the Gateway
  annotation; cloudflared tunnels `*.vanillax.xyz` to `.230:443`; external-dns
  (txtOwnerId `openshift-sno`, domainFilter `vanillax.xyz`) publishes ONLY
  routes labeled `external-dns: "true"`. Internal-only apps have no public
  DNS record and need Firewalla local DNS entries for `vanillax.xyz` →
  `192.168.10.230` (the existing `firewalla-dns-config.txt` covers only
  `vanillax.me`). The default OpenShift router keeps
  `*.apps.sno-ai-lab.vanillax.xyz` → `.10` untouched. The validators in
  `scripts/` now enforce the flat-domain model.
- **GPU PriorityClasses now exist on OpenShift**
  (`clusters/openshift/infra/gpu-priority-classes/`). The shared AI bases
  reference `gpu-workload-high`/`gpu-workload-preemptible` by name, and a
  missing PriorityClass rejects pod creation outright.
- **Open GPU blocker:** the cluster has NO NVIDIA stack (no Node Feature
  Discovery, no GPU Operator, no `nvidia` RuntimeClass, no `nvidia.com/gpu`
  capacity). llama-cpp, comfyui, swarmui, and llmfit cannot run until one is
  installed. **A complete OLM-path install is STAGED at
  `clusters/openshift/infra/gpu-operator/`** (NFD + gpu-operator-certified
  Subscriptions + ClusterPolicy, kubeconform-validated) but deliberately not
  discovered — its AppSet marker is `.argocd/config.json.disabled`. Run the
  live catalog check in that README first
  (`kubectl get packagemanifests -n openshift-marketplace | grep -Ei
  'gpu-operator|nfd'` — the rc.5 catalogs were missing lvms/metallb), then
  rename the marker to enable. Helm fallback documented in the same README.
  llmfit's dual-GPU job assumes 2 GPUs and will stay Pending on a single-GPU
  SNO; llama-cpp and comfyui contend for one card without time-slicing.
- **OpenShift CNPG backups are now declared in Git** (this branch): the
  Barman Cloud plugin (`v0.12.0`, co-located in `cloudnative-pg`, discovered
  by the database AppSet at syncWave 3), a shared `cnpg-s3-credentials`
  ExternalSecret (`postgres-global-secrets`, reads the SAME 1Password
  `rustfs` item Talos uses — no new pre-seed), and per-DB
  ObjectStore + ScheduledBackup + `spec.plugins` for all 4 Clusters.
  - **Lineage isolation from Talos is structural:** destinationPath uses
    `s3://postgres-backups/cnpg-sno/<db>` (Talos uses `cnpg/<db>`) AND
    serverName is `<db>-database-sno-v1`. Never share a prefix or serverName
    across clusters.
  - Schedules run on the half-hour (immich 02:30, temporal 03:30, gitea
    04:30, paperless 05:30) so the two clusters never hit RustFS together.
  - Each DB also has an inactive `overlays/recovery` mirroring the Talos DR
    flow: bump base serverName to sno-vN+1, point the recovery overlay at
    sno-vN, flip the root kustomization line, delete Cluster + PVCs.
  - Live verification still pending: first `Backup` CR must reach
    `completed` and `barman-cloud` WAL archiving must go green on each
    Cluster after bootstrap.
- **cloudflared ingress is now an explicit hostname allowlist** (this
  branch) — the previous `*.vanillax.xyz` wildcard would have exposed
  internal apps (Home Assistant, Frigate, Paperless, ArgoCD) publicly the
  moment any wildcard DNS record appeared. Adding an external app now means:
  label the HTTPRoute `external-dns: "true"` AND add the hostname to
  `clusters/openshift/infra/cloudflared/config.yaml`.
- **LAN DNS for vanillax.xyz**: `firewalla-dns-config-xyz.txt` (repo root)
  lists every internal hostname → `192.168.10.230`; internal apps resolve
  ONLY via Firewalla, never Cloudflare.
- **User-workload monitoring is enabled in Git**
  (`clusters/openshift/infra/monitoring-config/`): OpenShift-native UWM
  Prometheus (capped 7d/2GiB/1Gi RAM), CNPG `enablePodMonitor: true` on all
  4 Clusters. No Prometheus Operator is installed — the platform owns the
  monitoring.coreos.com CRDs on OpenShift.

## Current Direction

The branch uses a cluster-centric Kustomize layout:

```text
manifests/**/base -> clusters/talos/**
manifests/**/base -> clusters/openshift/**
```

Talos and OpenShift each run an independent upstream Helm Argo CD. Each Argo CD
scans only its own cluster folder. There is no hub/spoke model, remote cluster
registration, OpenShift GitOps Operator, or OpenShift dependency on Talos files.

## Branch

```text
feat/one-shot-multicluster-kustomize
```

The original repository feature branch uses `targetRevision: main` with Argo CD
URLs pointing at the original repository. Do not bootstrap OpenShift from that
branch checkout: Argo CD would reconcile the original repository's `main`, not
the feature branch.

An isolated public test repository exists specifically for live OpenShift
testing:

```text
https://github.com/mitchross/talos-argocd-proxmox-multicluster-test
branch: main
source feature commit: 1a7f36f1
```

Its test-only commit `4410b906` rewrites Argo CD repository URLs to the
isolated test repository. Its test-only commit `f5239d95` adds manual GitHub
Actions dispatch. Cluster CI passed in that repository:

```text
https://github.com/mitchross/talos-argocd-proxmox-multicluster-test/actions/runs/26975463740
```

Talos can remain on the original repository and current main branch while the
isolated test repository is used against OpenShift. The two local Argo CD
instances are independent.

## Important Decisions

- Talos remains the default and full-fidelity cluster.
- `clusters/<cluster>` contains every deployable Argo CD entrypoint.
- `manifests/**/base` contains shared sources only.
- All 44 apps have Talos and OpenShift overlays.
- Existing activation state is preserved; intentionally disabled DVWA and
  Project Nomad Kolibri resources remain disabled.
- App overlays are directory-discovered from `clusters/<cluster>/apps/*/*`.
- Explicit infrastructure, database, and monitoring entrypoints retain
  `.argocd/config.json` only where it carries real ordering, allowlist, or
  namespace intent.
- `1passwordconnect`, `cert-manager`, and `external-secrets` are shared
  portable bases under `manifests/infra`.
- Routes are complete per-cluster files.
- OpenShift GitOps owns GatewayClass `openshift-default` with controller
  `openshift.io/gateway-controller/v1`.
- Portable local PVCs use `vanillax-local-rwo`.
- Talos implements portable local storage with Longhorn.
- OpenShift implements portable `vanillax-local-rwo` with democratic-csi
  (Helm CSI driver) backed by TrueNAS iSCSI — NOT the LVMS operator, which the
  `4.22.0-rc.5` `redhat-operators` catalog does not publish. A dynamic
  `truenas-nfs-csi` RWX class is added alongside the kept static NFS/SMB CSI.
  See `clusters/openshift/infra/democratic-csi/`.
- NFS and SMB CSI are shared bases consumed by both clusters.
- Talos backup/restore policy is removed from OpenShift app renders.
- OpenShift does not install Cilium, Longhorn, VolSync, or pvc-plumber.
- `targetRevision` remains `main`.
- OpenShift AppProjects remain `openshift-infrastructure` and `openshift-apps`.
- `scripts/bootstrap-cluster.sh <profile>` is the repeatable operator
  entrypoint; `scripts/bootstrap-argocd.sh <profile>` is the focused Argo-only
  step.

## Implementation Status

The branch implementation and local acceptance completed on June 4, 2026. It
includes app discovery, manifest path correction, portable infrastructure
sharing, patch externalization, profile-driven bootstrap, OpenShift
GatewayClass ownership, and final bootstrap profile isolation. No live cluster
mutation was performed.

Implementation commits:

- `0313c64b` directory-derived app discovery
- `5b4bbca2` corrected manifest-generation paths
- `1d23d748` shared portable infrastructure bases
- `b939f7eb` externalized Kustomize patches
- `872326f2` profile-driven bootstrap and OpenShift GatewayClass
- `96bd15c3` shared-manifest patch-style guardrail
- `49c34706` operator documentation
- `0d3d2c61` bootstrap profile isolation and stronger preflight

## Local Acceptance

- 88/88 app renders are byte-identical to the pre-migration baseline.
- The 88-row generated Application contract is unchanged.
- All repository-local validators and shellcheck pass.
- All 155 cluster kustomizations render successfully.
- OpenShift bootstrap dry-run succeeds without any Talos cluster files.
- No app metadata, escaped or multiline inline patches, deprecated patch
  fields, invalid manifest-generation paths, or `targetRevision: HEAD` values
  remain.
- The render pass emits 27 existing `commonLabels` deprecation warnings; that
  cleanup is separate from this migration.

## OpenShift Readiness Boundary

All apps render through OpenShift overlays, but render success is not the same
as production readiness. Before live sync, verify the OpenShift GatewayClass,
democratic-csi driver health and the `vanillax-local-rwo` StorageClass binding,
CSI driver SCC behavior, application SCC behavior, TrueNAS (`192.168.10.133`)
reachability, and backup expectations.

## Verified Live OpenShift State

All checks below were read-only and used the explicit kubeconfig:

```text
/home/vanillax/Downloads/sno-ai-lab-kubeconfig
context: admin
API: https://api.sno-ai-lab.vanillax.xyz:6443
```

No `kubectl apply`, `oc apply`, Helm mutation, namespace creation, secret
creation, or other live mutation was performed.

Verified cluster facts:

- OpenShift `4.22.0-rc.5`, channel `stable-4.22`; Kubernetes `v1.35.5`.
- Single-node cluster `sno-ai-lab.lan`, node IP `192.168.10.10`.
- Platform `None`, control plane and infrastructure topology `SingleReplica`.
- OVN-Kubernetes; pod network `10.128.0.0/14`; service network
  `172.30.0.0/16`.
- Base domain `sno-ai-lab.vanillax.xyz`.
- Default OpenShift ingress domain `apps.sno-ai-lab.vanillax.xyz`.
- Default IngressController is healthy and uses `HostNetwork` on
  `192.168.10.10`.
- Gateway API CRDs `v1`/`v1beta1`, bundle `v1.4.1`, are installed.
- No `GatewayClass`, `Gateway`, or `HTTPRoute` exists yet.
- No active OSSM v2 subscription was found.
- No `argocd` namespace or Argo CD CRDs exist.
- Required pre-seeded 1Password namespaces/secrets do not exist.
- June 5, 2026 PackageManifest recheck:
  - `lvms-operator` is not present in the live catalogs.
  - `metallb-operator` is not present in the live catalogs.
  - the only PackageManifest matching broad storage/load-balancer search terms
    was `apelocal-csi` from Certified Operators.

Historical SNO context from `/home/vanillax/programming/openshift-sno-lab`
confirms the intended Gateway split:

- default OpenShift Routes used `*.apps.openshift-lab.vanillax.xyz` on the
  node/router IP;
- Gateway API apps used `*.gateway.apps.openshift-lab.vanillax.xyz`;
- MetalLB advertised `192.168.10.230-192.168.10.240`;
- the GatewayClass was `openshift-default` with controller
  `openshift.io/gateway-controller/v1`;
- the Gateway lived in `openshift-ingress`.

This branch now mirrors that pattern for `sno-ai-lab`:

- default OpenShift ingress stays on `*.apps.sno-ai-lab.vanillax.xyz`;
- GitOps-managed Gateway apps use
  `*.gateway.apps.sno-ai-lab.vanillax.xyz`;
- MetalLB is declared as OpenShift core dependency manifests with pool
  `192.168.10.230-192.168.10.240`.

The OpenShift GatewayClass contract is confirmed by OKD/OpenShift 4.19+
documentation: creating a GatewayClass with
`controllerName: openshift.io/gateway-controller/v1` makes the Ingress
Operator **auto-install a lightweight OpenShift Service Mesh** — it creates an
Istio CR and an `istiod-openshift-gateway` Deployment in `openshift-ingress`.
**Do NOT install `servicemeshoperator3` (or v2) manually**; the operator owns
the mesh. The repo and the `bootstrap-cluster.sh` guard that blocks
`servicemeshoperator` are therefore correct as-is. (The `openshift-sno-lab`
reference repo's README claim that the Service Mesh operator must be installed
first is a stale dev-preview instruction — ignore it.) This auto-install gives
the **control plane only**; external reachability still requires a
LoadBalancer provider — see blocker #2. The exact behavior remains unverified
on the live `4.22.0-rc.5` build.

Primary references:

- [OKD 4.20 Gateway API with networking](https://docs.okd.io/4.20/networking/ingress_load_balancing/configuring_ingress_cluster_traffic/ingress-gateway-api.html)
- [OpenShift 4.20 persistent storage using LVM Storage](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html/storage/persistent-storage-using-local-storage)

## Current Live Bootstrap Blockers

Do **not** run `./scripts/bootstrap-cluster.sh openshift` yet. The script
checks Gateway CRDs, OSSM v2, required OLM PackageManifests, and secrets before
installing Argo CD. It still cannot prove authoritative DNS, `.230` L2
advertisement, PVC binding, or app SCC/storage compatibility before the first
sync.

> **Repo status:** RESOLVED in Git by replacing LVMS with democratic-csi. The
> `clusters/openshift/infra/lvm-storage` component and its core-dependency app
> were removed; `clusters/openshift/infra/democratic-csi` now backs
> `vanillax-local-rwo`. Live verification (TrueNAS reachability + PVC bind)
> still pending.

### 1. Local Storage — LVMS replaced by democratic-csi (TrueNAS)

- **Root cause (why LVMS was dropped):** `lvms-operator` is an OLM operator,
  and the June 5, 2026 PackageManifest lookup found it absent from the live
  `4.22.0-rc.5` catalogs. A channel bump cannot fix a package the catalog does
  not publish. RHCOS immutability also makes the required host LVM volume group
  awkward.
- **Resolution:** `vanillax-local-rwo` is now backed by **democratic-csi**, a
  Helm CSI driver (no OLM dependency) provisioning **TrueNAS iSCSI** zvols on
  `192.168.10.133` (the same NAS the Talos cluster uses, 10G). A dynamic
  `truenas-nfs-csi` RWX class is added; static NFS/SMB CSI is kept. See
  `clusters/openshift/infra/democratic-csi/README.md`.
- A node-local `local-path` StorageClass
  (`clusters/openshift/infra/local-path-provisioner/`) is added as a
  non-default tier for persistent data that should NOT depend on TrueNAS. It
  ships a `MachineConfig` that creates + SELinux-labels
  `/opt/local-path-provisioner` and **reboots the SNO node once** on first
  apply. Ephemeral workloads should use `emptyDir`/`emptyDir{medium: Memory}`.
- **Remaining before bootstrap (live, not Git):**
  1. Pre-seed two 1Password items holding the driver config YAML —
     `democratic-csi-truenas-iscsi` and `democratic-csi-truenas-nfs`, each a
     `config` field (TrueNAS API key + pool/dataset + iSCSI portal). Template
     in the component README.
  2. Create the TrueNAS API key and the parent ZFS datasets referenced in the
     config.
  3. After sync, prove a `vanillax-local-rwo` PVC binds (README has a test).
- democratic-csi is Helm-rendered via kustomize `--enable-helm` from
  `https://democratic-csi.github.io/charts/` (chart `0.15.1`), same mechanism
  the repo already uses for `csi-driver-nfs`.

#### OpenShift storage-tier placement policy

Applied per-PVC via the existing `clusters/openshift/apps/*/*/patches/
remove-talos-backup-persistentvolumeclaim-*.yaml` strategic-merge patches
(base stays portable `vanillax-local-rwo`; only the OpenShift overlay changes
`storageClassName`). Talos is unaffected — it keeps Longhorn.

- **RWO, > 20Gi → `vanillax-local-rwo`** (TrueNAS iSCSI). No patch needed; it is
  already the base class and the OpenShift default. (swarmui dlbackend/output,
  gitea-actions cache, posthog clickhouse, nomad-storage, zomboid server-files,
  immich library.)
- **RWO, ≤ 20Gi → `local-path`** (node-local, no TrueNAS dependency). 31 PVCs
  patched.
- **radar-ng (5 PVCs) → `truenas-nfs-csi`, kept RWX.** radar-ng genuinely
  shares volumes across many pods (workers write tiles/grids; tile-servers
  read) — confirmed in `/home/vanillax/programming/radar-ng` `docs/PLAN.md`.
  On multi-node Talos that needs Longhorn RWX; on single-node OpenShift RWO
  would technically suffice (all pods co-locate), but NFS is the faithful port
  and the volumes are large.
- **Already NFS/SMB (comfyui, llama-cpp, swarmui-models, frigate-media, kiwix,
  tubesync media, jellyfin/immich media)** → unchanged.
- **CNPG (gitea/immich/paperless/temporal)** → BUILT at
  `clusters/openshift/database/cloudnative-pg/` (operator decision
  2026-06-05). It is a **simplified port** of the Talos tree, not a verbatim
  copy:
  - **Operator**: same Helm chart `cloudnative-pg/charts` `0.28.0` (no OLM, no
    catalog gap), RBAC + CRD SSA patches copied as-is; the backup-cleanup
    CronJob was dropped.
  - **4 Clusters**: `initdb` only (fresh DBs), `storageClass: local-path` for
    both data and WAL, `enablePodMonitor: false`. immich keeps its vchord
    image + extension postInit; temporal keeps `temporal_visibility`; the
    Talos recovery/initdb overlay machinery is collapsed to initdb.
  - **Dropped vs Talos**: Barman/S3 backups (ObjectStore, ScheduledBackup,
    `spec.plugins`), the recovery overlays, and paperless's Cilium
    LoadBalancer (`192.168.10.42`). So **OpenShift Postgres has NO automated
    backup yet** — DR is a follow-up (add the Barman plugin + ObjectStore +
    `cnpg-s3-credentials` if/when wanted; RustFS at `192.168.10.133:30292`).
  - Discovered by a new `openshift-database` AppSet (wave 5, `selfHeal:false`),
    project `openshift-infrastructure`, namespace `cloudnative-pg`.
  - **Live TODO before it works**: (1) the per-DB ExternalSecrets read the
    `postgres-secrets` 1Password item (`<app>_db_username`/`_password`) — the
    same item Talos uses, so confirm the OpenShift ClusterSecretStore can read
    it. (2) Verify CNPG pods run under OpenShift SCC (CNPG targets
    `restricted-v2`; no special SCC was added — watch the first sync).

Note: RWO restricts to a single *node*, not a single *pod* — on SNO multiple
pods co-locate, so `local-path`/iSCSI RWO volumes can be shared by several
pods. RWX is only mechanically required across nodes.

### 2. Gateway LoadBalancer Publishing Is Declared But Not Live-Proven

- The OpenShift Gateway implementation provisions a `LoadBalancer` Service for
  each Gateway. The GatewayClass auto-installs only the mesh control plane; the
  data-plane Service stays `Pending` forever without an LB provider.
- The live bare-metal/platform-None cluster has no built-in LoadBalancer
  provider. OpenShift ships a Router (HostNetwork on `.10`, serves `Route`s),
  NOT a generic `type: LoadBalancer` implementation — that is why Gateway API
  (which creates a LoadBalancer Service) needs one and ordinary Routes do not.
- **Resolution (2026-06-05):** MetalLB is installed via the **upstream Helm
  chart** (`metallb/metallb` `0.16.1`), NOT the Red Hat OLM `metallb-operator`
  — the June 5 PackageManifest lookup found `metallb-operator` absent from the
  `4.22.0-rc.5` catalog, the same gap that moved storage to democratic-csi.
  - `clusters/openshift/infra/metallb-operator` — Helm chart (controller +
    speaker), L2-only (`frrk8s`/BGP disabled), privileged namespace + a
    ClusterRoleBinding granting the `metallb-speaker` SA the `privileged` SCC
    (the chart, unlike the operator, does not create SCCs). No `kind: MetalLB`
    CR (operator-only concept).
  - `clusters/openshift/infra/metallb-config` — `IPAddressPool gateway-pool`
    `192.168.10.230-192.168.10.240` + `L2Advertisement` only.
- `192.168.10.230` was not reachable pre-install (ARP `FAILED`); expected until
  the speaker advertises it.

Before Gateway sync is considered ready, prove `.230` is advertised (ARP) and
reachable after the speaker is running.

### 3. Route Domain And DNS Currently Collide With Default OpenShift Ingress

Cloudflare currently contains:

```text
*.apps.sno-ai-lab.vanillax.xyz         -> 192.168.10.10
*.gateway.apps.sno-ai-lab.vanillax.xyz -> 192.168.10.230
```

Previous authoritative and local DNS tests both resolved
`test.gateway.apps.sno-ai-lab.vanillax.xyz` to `192.168.10.10`, not `.230`.
The broader `*.apps...` record currently captures the nested name.

The branch now configures the OpenShift Gateway listener, Argo CD URL, and app
HTTPRoutes under `*.gateway.apps.sno-ai-lab.vanillax.xyz`. DNS still needs a
fresh authoritative proof before bootstrap.

The repo previously configured the OpenShift Gateway listener and all app
HTTPRoutes under `*.apps.sno-ai-lab.vanillax.xyz`, which point at the default
OpenShift HostNetwork router on `.10`, not the Gateway API LoadBalancer. That
is now fixed.

Standing rules:

- Preserve `*.apps.sno-ai-lab.vanillax.xyz -> 192.168.10.10` for OpenShift
  console, OAuth, and ordinary Route traffic.
- Keep GitOps-managed Gateway API apps on
  `*.gateway.apps.sno-ai-lab.vanillax.xyz`.
- Do not move the existing default `*.apps...` wildcard away from `.10`; doing
  so would disrupt built-in OpenShift routes.
- Fix authoritative DNS behavior and verify the chosen Gateway IP before
  bootstrap.

### 4. Bootstrap Secrets Are Not Pre-Seeded

**Single source of truth for secrets (decision 2026-06-05):** both clusters use
the *identical* shared bases `manifests/infra/external-secrets/base` (defines
`ClusterSecretStore/1password` → vault **`homelab-prod`**) and
`manifests/infra/1passwordconnect/base`. Same store, same vault, same provider
config on Talos and OpenShift — every ExternalSecret resolves from the one
vault. Nothing cluster-specific in Git.

So the OpenShift bootstrap secret step is **the same as Talos** — seed the same
three Connect credential secrets (same values: same Connect token + vault):

```text
1passwordconnect/1password-credentials      # 1password-credentials.json
1passwordconnect/1password-operator-token   # operator token
external-secrets/1passwordconnect           # Connect token for ESO (key: token)
```

The shared `homelab-prod` vault already contains everything OpenShift
references (`postgres-secrets` with the 4 `<app>_db_*` fields,
`argocd-github-webhook`, and all app items — Talos populated them) EXCEPT the
two items introduced for OpenShift storage, which must be added once:

```text
democratic-csi-truenas-iscsi   # field: config  (iSCSI driver YAML)
democratic-csi-truenas-nfs     # field: config  (NFS driver YAML)
```

Pre-seed the three Connect secrets after the storage, Gateway publishing, and
route-domain items above are resolved.

## Safe Next Actions

1. Create the TrueNAS API key + parent ZFS datasets, seed the two
   `democratic-csi-truenas-{iscsi,nfs}` 1Password items, then after sync prove
   a `vanillax-local-rwo` PVC binds (see democratic-csi README).
2. MetalLB is now the upstream Helm chart (no OLM) — after sync, confirm the
   `metallb-controller` + `metallb-speaker` pods are healthy and prove
   `192.168.10.230` is advertised (ARP) and reachable on the LAN.
3. Verify authoritative DNS resolves
   `test.gateway.apps.sno-ai-lab.vanillax.xyz` to `192.168.10.230`.
4. Re-run read-only preflight checks.
5. Pre-seed the three 1Password bootstrap secrets.
6. Clone the isolated test repository and run
   `./scripts/bootstrap-cluster.sh openshift` with
   `KUBECONFIG=/home/vanillax/Downloads/sno-ai-lab-kubeconfig`.

Do not mutate Talos during OpenShift testing.

## Read-Only Live Recheck

Use the explicit OpenShift kubeconfig for every command:

```bash
export KUBECONFIG=/home/vanillax/Downloads/sno-ai-lab-kubeconfig

kubectl get clusterversion version
kubectl get node -o wide
kubectl get clusteroperator ingress network -o wide
kubectl get gatewayclass,gateway,httproute -A
kubectl get subscriptions.operators.coreos.com -A
kubectl get packagemanifests.packages.operators.coreos.com -n openshift-marketplace | grep -Ei 'metallb|lvm|lvms'
kubectl get subscription lvms-operator -n openshift-storage -o yaml
kubectl get crd | grep -Ei 'gateway|lvm|topolvm'
kubectl get storageclass
kubectl get svc -A -o wide | grep LoadBalancer
kubectl get secret -n 1passwordconnect 1password-credentials
kubectl get secret -n 1passwordconnect 1password-operator-token
kubectl get secret -n external-secrets 1passwordconnect

dig @1.1.1.1 +short A argocd.gateway.apps.sno-ai-lab.vanillax.xyz
dig @1.1.1.1 +short A test.gateway.apps.sno-ai-lab.vanillax.xyz
```

These commands are reads. Do not use `oc debug`, `kubectl apply`, `oc apply`,
Helm install/upgrade, namespace creation, or secret creation during a
read-only recheck.

## Validation Commands

```bash
./scripts/validate-cluster-layout.sh
./scripts/validate-argocd-apps.sh
./scripts/validate-openshift-app-renders.sh
./scripts/validate-bootstrap-profiles.sh

find clusters -type f -name kustomization.yaml -print \
  | while read -r file; do
      kustomize build --enable-helm "$(dirname "$file")" >/dev/null
    done
```

Do not run live `kubectl apply`, `oc apply`, or Helm mutation commands during
review unless the operator explicitly requests a live bootstrap.
