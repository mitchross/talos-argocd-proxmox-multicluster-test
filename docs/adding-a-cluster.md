# Adding a Cluster (and Adding Apps to It)

This repo's core claim: **the same shared app sources deploy to n clusters
across Kubernetes distributions, with Kustomize overlays absorbing the
platform differences.** Talos and OpenShift run the *entire* app catalog in
1:1 parity — that parity is the proof that "Kubernetes is Kubernetes." This
page is the walkthrough that makes the claim concrete. It assumes nothing
beyond basic Kustomize and Argo CD knowledge.

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
- **1:1 parity is the contract:** every shared app base has an overlay in
  *every* cluster, both directions enforced by CI (a base without an overlay
  in some cluster fails; an overlay without a base fails). Which apps
  actually *run* on a given cluster is a runtime decision (the operator can
  disable Argo apps by hand) — but the overlays stay in Git, because they
  are the portability proof.
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
├── apps/<category>/<app>/   # one overlay dir per shared app base (1:1 parity)
├── database/           # CNPG operator + per-DB lineages
└── monitoring/         # optional; Talos uses kube-prometheus-stack,
                        # OpenShift uses built-in user-workload monitoring
```

## Adding cluster number n+1

1. **Copy the closest existing tree** — `clusters/openshift/` shows the
   minimum a second cluster needs; `clusters/talos/` is the full production
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
5. **Create the app overlays.** Parity means one overlay per shared base —
   start with `development/nginx` to prove gateway + storage + discovery
   end-to-end, then work through the catalog. Most overlays are
   near-identical (base reference + httproute + backup-label patches), so
   this is mechanical; the 44/44 Talos→OpenShift migration was done exactly
   this way.

## Adding an app (the everyday operation)

A new app means a shared base under `manifests/apps/<category>/<app>/base`
(see `/project:new-app`) **plus one overlay per cluster** — CI fails until
every cluster has one:

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

That's a whole per-cluster opt-in. The cluster's apps ApplicationSet
discovers the directory on the next sync — no Application YAML to write,
nothing to register. The two patches strip Talos-only pvc-plumber backup
labels; a cluster with its own backup story would patch differently or not
at all.

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
| Overlay required in every cluster per shared base (1:1 parity, count derived from `manifests/apps`) | a cluster silently developing catalog gaps |
| Overlay must point at a real shared base | orphan overlays after a base rename |
| No `clusters/talos` imports from other clusters | hidden cross-cluster coupling |
| No Talos storage classes / gateway parentRefs in OpenShift renders | unportable bases |
| cloudflared allowlist ⇄ externally-labeled routes (both directions) | public DNS that 404s, or stale public exposure |
| Per-cluster render of every overlay (`kustomize build --enable-helm`) | broken manifests reaching Argo CD |

## Current cluster roles

- **`clusters/talos` — production.** Longhorn, pvc-plumber/VolSync backups,
  kube-prometheus-stack, dual internal/external gateways on `vanillax.me`.
- **`clusters/openshift` — AI box + learning lab.** Same full catalog on
  `vanillax.xyz` (parity is the point), OVN-Kubernetes, TrueNAS CSI, single
  gateway + cloudflared allowlist, built-in user-workload monitoring. Which
  apps stay powered on there is a runtime decision, made by hand — not a
  Git-tree decision.
