# Adding a Cluster (and Adding Apps to It)

This repo's core claim: **if you only have one cluster, you fill out one
overlay — and the same layout scales to n clusters.** This page is the
walkthrough that makes the claim concrete. It assumes nothing beyond basic
Kustomize and Argo CD knowledge.

## The model in one diagram

```text
manifests/apps/<category>/<app>/base/    # shared, portable app source
        ▲                ▲
        │                │
clusters/talos/apps/...  clusters/openshift/apps/...   # per-cluster overlays
        ▲                ▲
        │                │
   talos Argo CD     openshift Argo CD   # one local Argo CD per cluster
```

Rules that keep it honest:

- **Shared bases are distribution-neutral.** No Talos-only storage classes
  (use `vanillax-local-rwo`), no cluster hostnames, no CNI-specific policy.
  Standard Kubernetes APIs only — that is the "Kubernetes is Kubernetes"
  thesis, enforced by CI (`scripts/validate-cluster-layout.sh`,
  `scripts/validate-openshift-app-renders.sh`).
- **Each cluster's Argo CD reads only `clusters/<cluster>/`** and deploys only
  to itself. No hub/spoke, no remote cluster registration, no cross-cluster
  file references (CI fails an OpenShift overlay that imports
  `clusters/talos/...`).
- **Talos is the complete reference cluster:** every shared base must have a
  Talos overlay. **Every other cluster opts in per-app** — a lab cluster
  deploys a curated subset, and a missing overlay simply means "this cluster
  doesn't run that app."
- **Cluster-specific differences live in the overlay,** as Kustomize patches:
  storage class mapping, backup-label removal (Talos-only pvc-plumber),
  HTTPRoute domains and parentRefs, SCC/securityContext differences.

## Anatomy of a cluster tree

```text
clusters/<name>/
├── bootstrap/          # root Application + namespace + Argo CD Helm values
│   ├── ns.yaml
│   ├── root.yaml       # points Argo CD at clusters/<name>/argocd
│   └── values.yaml
├── argocd/             # the cluster's control plane, applied by root.yaml
│   ├── appsets/        # directory-discovery ApplicationSets:
│   │   ├── apps-appset.yaml            # clusters/<name>/apps/*/*
│   │   ├── database-appset.yaml        # clusters/<name>/database/*/*  (selfHeal: false)
│   │   └── infrastructure-appset.yaml  # explicit infra path list
│   ├── core-dependencies/  # wave-0 essentials (secrets plumbing, projects)
│   └── projects.yaml
├── infra/              # cluster-owned infrastructure (CNI, gateway, storage,
│                       # external-dns, cert-manager, ...). Sync waves matter here.
├── apps/<category>/<app>/   # one overlay dir per opted-in app
├── database/           # CNPG operator + per-DB lineages (optional)
└── monitoring/         # optional; Talos uses kube-prometheus-stack,
                        # OpenShift uses built-in user-workload monitoring
```

## Adding cluster number n+1

1. **Copy the closest existing tree** — `clusters/openshift/` is the smaller,
   more readable starting point; `clusters/talos/` is the full production
   reference. Rename to `clusters/<name>/`.
2. **Fix the identity files first:**
   - `bootstrap/root.yaml` → path `clusters/<name>/argocd`, your repo URL.
   - `argocd/appsets/*.yaml` → discovery paths `clusters/<name>/apps/*/*` and
     `clusters/<name>/database/*/*`.
   - `argocd/projects.yaml` → AppProject destinations.
3. **Decide the platform-mapping layer in `infra/`:**
   - **CNI:** Talos installs Cilium at bootstrap; OpenShift keeps stock
     OVN-Kubernetes. Either works — shared bases only use standard
     NetworkPolicy and Gateway API, so the CNI is a cluster decision.
   - **Storage:** provide a `vanillax-local-rwo` StorageClass mapped to
     whatever the cluster has (Longhorn on Talos, TrueNAS iSCSI on SNO).
   - **Gateway:** a Gateway API implementation + a Gateway with a TLS
     listener for the cluster's domain. Each cluster owns its domain
     (`vanillax.me` = Talos, `vanillax.xyz` = SNO) and its own external-dns
     `txtOwnerId`, so clusters never fight over DNS records.
   - **Secrets:** 1Password Connect + External Secrets + ClusterSecretStore.
     This is wave 0; nearly everything depends on it.
4. **Bootstrap:** add a profile to `scripts/bootstrap-cluster.sh` (or run its
   steps by hand the first time): apply Gateway API CRDs, install Argo CD via
   the upstream Helm chart with `bootstrap/values.yaml`, apply
   `bootstrap/root.yaml`. From there Git drives everything.
5. **Opt in to apps** — see below. Start with `development/nginx`; it is the
   smallest possible overlay and proves gateway + storage + discovery
   end-to-end.

## Adding an app to a cluster (the everyday operation)

The app already has a shared base under `manifests/apps/<category>/<app>/base`
(if not, see `/project:new-app`). Opting a cluster in is one directory:

```text
clusters/<name>/apps/<category>/<app>/
├── kustomization.yaml
├── httproute.yaml          # cluster-owned: domain + parentRef differ per cluster
└── patches/                # only if the cluster needs to diverge from base
```

Minimal real example (`clusters/openshift/apps/development/nginx/`):

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: nginx-example
resources:
  - "../../../../../manifests/apps/development/nginx/base"
  - httproute.yaml
patches:
  - path: patches/remove-talos-backup-namespace-nginx-example.yaml
  - path: patches/remove-talos-backup-persistentvolumeclaim-storage.yaml
```

That's the whole opt-in. The cluster's apps ApplicationSet discovers the
directory on the next sync — no Application YAML to write, nothing to
register. The two patches strip Talos-only pvc-plumber backup labels; a
cluster with its own backup story would patch differently or not at all.

Per-cluster route rules:

- **Talos external** routes need `labels: external-dns: "true"`, annotation
  `external-dns.alpha.kubernetes.io/target: vanillax.me`, and
  `sectionName: https` on the parentRef.
- **OpenShift (SNO) external** routes need the same label **plus** a hostname
  entry in `clusters/openshift/infra/cloudflared/config.yaml` — the tunnel is
  an explicit allowlist, and CI fails if the two drift apart in either
  direction.
- Internal-only routes get no label and a Firewalla LAN DNS entry
  (`firewalla-dns-config*.txt`).

## What CI enforces (so a follower can't silently break the model)

| Guard | Failure it prevents |
|-------|---------------------|
| Talos overlay required per shared base | reference cluster developing gaps |
| Overlay must point at a real shared base | orphan overlays after a base rename |
| No `clusters/talos` imports from other clusters | hidden cross-cluster coupling |
| No Talos storage classes / gateway parentRefs in OpenShift renders | unportable bases |
| cloudflared allowlist ⇄ externally-labeled routes (both directions) | public DNS that 404s, or stale public exposure |
| Per-cluster render of every overlay (`kustomize build --enable-helm`) | broken manifests reaching Argo CD |

## Current cluster roles

- **`clusters/talos` — production.** Complete app catalog, Longhorn,
  pvc-plumber/VolSync backups, kube-prometheus-stack, dual internal/external
  gateways on `vanillax.me`.
- **`clusters/openshift` — AI box + learning lab.** Curated subset (AI stack,
  nginx, gitea + CNPG, searxng, excalidraw) on `vanillax.xyz`, OVN-Kubernetes,
  TrueNAS CSI, single gateway + cloudflared allowlist, built-in user-workload
  monitoring. Read this tree first — it is the on-ramp.
