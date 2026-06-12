# Multi-Cluster Handoff Notes

> **Canonical continuation note:** Read this file before any multicluster,
> OpenShift, Gateway API, LVM Storage, route-domain, or bootstrap work.
> As of June 11, 2026 the SNO is **bootstrapped, on 4.22.0 GA, and being
> stabilized** — the June 10–11 section below is authoritative; older
> sections (including the June 9 "reformat at 4.21 GA" plan and every
> "not ready for bootstrap" claim) are historical record only.

## June 10–11, 2026 (LATEST, supersedes June 9) — 4.22.0 GA inline upgrade done; SNO bootstrapped; live stabilization triage

Operator decisions and verified facts (these dates):

- **4.22.0 GA shipped and the SNO inline-upgraded — the reformat plan is
  dead.** Path taken: fix the upgrade blocker (below), `oc adm upgrade
  channel candidate-4.22` (the GA release is not reachable from rc.5 inside
  `stable-4.22`), `oc adm upgrade --to=4.22.0`, then back to `stable-4.22`.
  Completed 2026-06-11; all ClusterOperators healthy at 4.22.0. Reinstall via
  Assisted Installer remains only a disaster fallback.
- **The SNO IS fully bootstrapped** (contrary to older sections of this file):
  local upstream Helm Argo CD in `argocd`, **67 Applications**,
  external-secrets + 1passwordconnect live, CNPG with all 4 databases
  healthy. Live app changes MUST go through Git — Argo selfHeal reverts
  kubectl edits.
- **Upgrade blocker root cause (fixed, commit `c9c2ac32`):** the rc.5
  kube-state-metrics image lacked tzdata; ANY CronJob with `spec.timeZone`
  panicked KSM → monitoring ClusterOperator down → CVO `Failing=True` refused
  to start the update. Fix: renovate base drops `timeZone`; the OpenShift
  overlay sets `suspend: true` (the bot runs from Talos only). Standing rule:
  **never set `spec.timeZone` on CronJobs in this repo.**
- **Catalog state (verified fresh on 2026-06-11, not a stale image):**
  `gpu-operator-certified` + `nfd` ARE published → the staged
  `clusters/openshift/infra/gpu-operator/` entry is enable-ready.
  `lvms-operator` is still ABSENT from the v4.22 index → LVMS stays staged;
  catalogs re-poll every 240m, recheck with
  `kubectl get packagemanifests -n openshift-marketplace | grep -i lvms`.
  (Red herring note: catalog pods' main container image is
  `quay.io/openshift-release-dev/ocp-v4.0-art-dev@…` — that is the opm
  registry-server from the release payload, NOT leftover rc mirroring; the
  index content comes from the `extract-content` init container pulling
  `registry.redhat.io/redhat/redhat-operator-index:v4.22` with
  `pullPolicy: Always`.)

### Target hardware decision (2026-06-10) — SNO moves to the bare-metal 2950X with the dual 3090s; vLLM staged

Operator decision (brainstormed and recorded this date): the SNO's
**permanent home is the Threadripper 2950X** (16c/32t, 128GB quad-channel,
x16/x16 PCIe) **as bare metal**, with **both RTX 3090s** moving over from
the DL360's external-PSU rig. Rationale: the GPUs follow OpenShift because
that is the work-practice cluster (GPU Operator + vLLM is the enterprise
pattern, and bare-metal SNO exercises MachineConfigs/node-tuning a VM
cannot); the DL360 stays a general Proxmox lab (other VMs, possibly one
CPU pulled for power); Proxmox-on-the-2950X was rejected (SNO snapshots
age badly under cert rotation, and a second hypervisor duplicates what the
DL360 already provides); multi-cluster experiments later use this SNO +
throwaway VMs on the DL360.

Consequences and sequencing (meshes with the triage + pre-nuke checklist
below):

1. **Stabilize the SNO on current hardware FIRST** (triage items 2 and 3 —
   iSCSI data path, Gateway TLS). Do not move a half-broken cluster.
2. **Pulling the 3090s out of the DL360 kills Talos GPU apps early**
   (llama-cpp, comfyui) — before any Talos nuke. Inventory `vanillax.me`
   AI consumers before the cards move.
3. **The move itself is an Assisted Installer reinstall on the 2950X**,
   keeping the cluster's network identity (hostname `sno-ai-lab`, node IP
   `192.168.10.10`, all existing DNS records) so nothing else changes.
   This is a NEW-hardware reinstall — it does not contradict "reinstall
   remains only a disaster fallback" above, which is about the current box.
4. **Reinstall survival matrix:** TrueNAS iSCSI (`vanillax-local-rwo`,
   Retain) and NFS/SMB data survive — that was the point of defaulting to
   off-node storage. Everything on `local-path` **dies with the node**,
   including CNPG data volumes → restore the 4 databases from the
   `cnpg-sno` Barman lineage (bump serverName to `…-sno-v2`, recovery
   overlays exist per-DB). Treat the rest of the local-path tier as
   disposable or migrate it ahead of the move.
5. **After the reinstall on metal:** flip the gpu-operator marker (catalog
   check already passes, see above) → expect `nvidia.com/gpu: 2`. The old
   single-GPU caveats are void: llmfit's dual-GPU job becomes schedulable,
   and llama-cpp/comfyui can hold a card each without time-slicing.
6. **vLLM is the flagship workload for the new box**, staged at
   `manifests/apps/ai/vllm/` (+ both cluster overlays, namespace-only via
   the dvwa idiom): `Qwen/Qwen3-32B-AWQ`, TP=2 across both 3090s,
   OpenAI-compatible `/v1` at `vllm-service.vllm.svc:8000`. Enable
   checklist in that README. The Talos overlay is parity-only — never
   enable it; Talos loses its GPUs in this move.
7. **LVMS stays double-gated:** catalog (still absent from v4.22 index)
   AND hardware — the "second SSD" by-id identity must be re-discovered
   on the 2950X after the reinstall. `vllm-hf-cache` is a planned
   `lvms-vg1` tenant once both gates clear.

### Live stabilization triage (2026-06-11) — what is actually broken and why

Cluster core is healthy; the app layer is not. ~36 of 67 Applications not
Synced/Healthy, ~29 pods down, all failures pre-dating the upgrade (present
since bootstrap). Root causes, triaged:

1. **[FIXED in Git, this commit] csi-driver-nfs / csi-driver-smb pods were
   SCC-forbidden since bootstrap.** The upstream charts create no SCCs;
   restricted-v2 rejected every controller/node pod (hostNetwork, hostPath,
   privileged), so `nfs.csi.k8s.io`/`smb.csi.k8s.io` never registered on the
   node. Symptom signature: Argo app "Synced/Degraded" with ZERO pods in the
   namespace, NFS mounts failing "driver name not found", dynamic SMB PVCs
   Pending on "waiting for external provisioner". Fix mirrors the
   metallb/cert-manager pattern: `scc-rolebinding.yaml` in each overlay
   granting `system:openshift:scc:privileged` to the 4 chart SAs.
2. **[USER ACTION — TrueNAS/iSCSI data path broken cluster-wide.]** Every
   `vanillax-local-rwo` (iSCSI) mount fails:
   `iscsiadm sendtargets to 192.168.10.133:3260 → exit 21` (portal answers —
   TCP 3260 is open — but returns no targets for this initiator). Provisioning
   works (PVCs Bound), staging fails, so pods sit in ContainerCreating
   (immich-ml, jellyfin, posthog clickhouse, zomboid, …). Likely related:
   the `truenas-api-credentials` ExternalSecret has failed for ~4 days with
   "could not get secret data from provider" — check the 1Password
   `truenas-csi` item (field `apiKey`) AND the TrueNAS iSCSI target/initiator
   config (did a TrueNAS change ~June 7 revoke the key + drop the targets?).
3. **[USER ACTION — Gateway TLS cert never issued → all HTTPRoutes down.]**
   `Gateway/openshift-gateway` listener references
   `openshift-ingress/cert-openshift-gateway-apps`, which doesn't exist:
   the ACME DNS01 challenges have been pending for days with *"Found no Zones
   for domain _acme-challenge.vanillax.xyz"* — the Cloudflare API token (the
   shared item from the Talos/vanillax.me setup) is **not scoped to the
   vanillax.xyz zone**. Fix in the Cloudflare dashboard (token zone scope);
   cert-manager will finish on its own. This also keeps the
   `openshift-infra-gateway` app stuck OutOfSync/Degraded.
4. **[PRE-NUKE LANDMINE — `registry.vanillax.me` is unresolvable from the
   SNO node]** (`lookup registry.vanillax.me: no such host` via node DNS) →
   ImagePullBackOff for every LAN-registry image (news-reader v0.2.4;
   radar-ng app Missing). The registry and its DNS live behind Talos-side
   infrastructure. See the pre-nuke checklist below.
5. **[CAMPAIGN — per-app SCC crashes, ~15 apps, never worked on OpenShift.]**
   Pattern proven on nginx-example: image needs a writable path
   (`mkdir /var/cache/nginx: Permission denied`) or a fixed UID under
   restricted-v2's random UID. Affected (500+ restarts each since bootstrap):
   nginx-example, home-assistant, fizzy, karakeep, n8n, pairdrop, excalidraw,
   stirling-pdf, vert, paperless-ngx, perplexica, qdrant + kafka
   (project-nomad/posthog), headlamp (`runAsNonRoot` + non-numeric image
   user — needs an explicit numeric `runAsUser`). Each needs an OpenShift
   overlay patch (writable emptyDir mounts, numeric UID, or an unprivileged
   image variant). This is a follow-up campaign — do NOT bulk-"fix" by
   loosening SCCs cluster-wide.
6. **[RESIDUE — console-installed OLM operators, violates the minimal-OLM
   stance, none in Git:]** loki-operator v6.5.1 + cluster-logging v6.5.1
   (their `maxOpenShiftVersion: 4.22` will hard-block the 4.23 upgrade),
   cluster-observability-operator, kernel-module-management,
   **kubevirt-hyperconverged v4.21.8 (CNV — still on the 4.21 channel on a
   4.22 cluster; bump its Subscription channel or remove it)**, nmstate, and
   a `redhat-ods-operator` namespace. Decide: adopt into Git or uninstall.
7. **Expected-degraded (no action until GPU operator is enabled):** llama-cpp,
   comfyui, swarmui, open-webui (mcpo), llmfit — no NVIDIA stack yet; and the
   `local-path` PVCs shown Pending are just WaitForFirstConsumer waiting on
   their (blocked) consumer pods, not a provisioner failure.

### Pre-Talos-nuke checklist (operator intent 2026-06-11: nuke Talos, rebuild as SNO)

Before destroying the Talos cluster:

1. **`registry.vanillax.me`** — the LAN registry (and the `vanillax.me`
   DNS/ingress serving it) lives behind Talos. Mirror or rebuild it somewhere
   that survives (TrueNAS app, the SNO itself, …) and fix DNS so the SNO node
   can resolve+pull, or every LAN-registry image on the SNO is permanently
   unpullable.
2. **Renovate** — the bot now runs ONLY on Talos (the SNO overlay suspends
   it, `clusters/openshift/apps/development/renovate/patches/`). After the
   nuke, drop the `suspend: true` patch op so the SNO instance takes over.
3. **Get SNO storage + ingress green first** (items 2 and 3 above) so the SNO
   is a functioning daily driver before its sibling disappears.
4. **What survives without Talos:** RustFS S3 + TrueNAS shares are on
   `192.168.10.133` (independent box) — Talos Kopia/Barman backup data
   remains readable. 1Password Connect is per-cluster (SNO has its own).
   Argo CD pulls from GitHub, not Talos.
5. **What dies with Talos:** every `*.vanillax.me` service (llama-cpp
   backend for any tool pointed at it, gitea if it hosts repos/the registry,
   monitoring). Inventory anything external (Firewalla DNS entries, phones,
   bookmarks, n8n/Home-Assistant webhooks) pointing at `vanillax.me`.
6. **CNPG lineage rule still applies** if databases are ever restored onto
   the SNO: never reuse a Talos `serverName`/S3 prefix (`cnpg/<db>` is Talos;
   the SNO uses `cnpg-sno/<db>` and `<db>-database-sno-v1`).

## June 9, 2026 — reformat to 4.21 GA planned; LVMS staged for the second SSD (SUPERSEDED by June 10–11: inline upgrade happened instead)

Operator decisions (this date):

- **The SNO will be REINSTALLED at 4.21 GA via the Assisted Installer** (same
  wizard as the original install). There is no downgrade path from
  4.22.0-rc.5, the cluster carries no workloads yet, and Git is the source of
  truth — reinstall + `scripts/bootstrap-cluster.sh openshift` is the cheap
  and correct move. Stop treating rc.5 catalog gaps as a live constraint;
  treat 4.21 GA as the target platform and fix workarounds accordingly.
- **The box has a SECOND SSD → LVM Storage (LVMS).** A complete staged entry
  exists at `clusters/openshift/infra/lvm-storage/` (Namespace +
  OperatorGroup + Subscription + LVMCluster, marker
  `.argocd/config.json.disabled`). Its README has the full enable checklist:
  catalog check, find the disk's `/dev/disk/by-id` path, `wipefs`, fill in
  the placeholder, flip the marker. Resulting class: `lvms-vg1` (NOT
  default; CSI snapshots/clones — the future VolSync/pvc-plumber path on
  this cluster). TrueNAS iSCSI stays the `vanillax-local-rwo` default for
  app data that must survive reinstalls. `local-path-provisioner` becomes a
  retirement candidate once LVMS is live. ODF/Ceph was considered and
  rejected (3-node Ceph platform, wrong for SNO); Longhorn-on-OpenShift was
  considered and rejected (possible, but LVMS is the native equivalent
  without iscsid MachineConfigs/SCC grants).
- **Minimal-OLM stance, stated explicitly:** no console-clicked OperatorHub
  installs, no OpenShift GitOps operator — ever. OLM Subscriptions ARE
  acceptable when declared in Git and synced by our own Argo CD, but only
  for products that ship exclusively through OLM (LVMS, NVIDIA
  certified GPU operator + NFD). Everything with a viable Helm path stays
  Helm (MetalLB, cert-manager, external-dns, truenas-csi, cloudflared, ...)
  — on GA this is now a *preference*, no longer a catalog workaround.
- **After the reinstall**, the GPU stack catalog check
  (`clusters/openshift/infra/gpu-operator/README.md`) is expected to pass on
  the GA catalog; flip that marker too.

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
