# talos-argocd-proxmox (multicluster)

A production-grade GitOps Kubernetes platform on **Talos Linux** with
**self-managing ArgoCD**: applications are discovered from directory
structure, storage is backed up declaratively via PVC labels, and the whole
cluster can be destroyed and rebuilt **unattended** — restores included.
This repo is the multicluster variant: Talos is the complete reference
cluster; OpenShift SNO is an expansion target with its own overlays.

> Source repository: [`mitchross/talos-argocd-proxmox-multicluster-test`](https://github.com/mitchross/talos-argocd-proxmox-multicluster-test)
> · upstream single-cluster reference: [`mitchross/talos-argocd-proxmox`](https://github.com/mitchross/talos-argocd-proxmox)

> [!TIP]
> **The headline claim, with receipts:** the upstream Talos cluster was fully
> destroyed and rebuilt twice in 36 hours (2026-06-12/13 — once unplanned,
> once planned). Both times, every protected volume restored automatically
> from the off-cluster Kopia repository. The second rebuild took ~75 minutes
> with **zero manual storage steps**. See
> [disaster-recovery.md](disaster-recovery.md#proof-history).

> [!WARNING]
> **Current multicluster/OpenShift state (2026-06-11):**
> - live OpenShift `sno-ai-lab` is **bootstrapped and on 4.22.0 GA**
>   (inline-upgraded from rc.5 — the "reformat at 4.21 GA" plan is dead);
>   local Argo CD runs 67 Applications
> - stabilization is **in progress**: many apps are Degraded (storage data
>   path, Gateway TLS cert, per-app SCC crashes) — see the handoff notes'
>   2026-06-11 section for the live triage and the pre-Talos-nuke checklist
> - **target hardware decided (2026-06-10):** the SNO moves to the
>   bare-metal Threadripper 2950X with both RTX 3090s (Assisted Installer
>   reinstall, same network identity); **vLLM is staged** at
>   `manifests/apps/ai/vllm/` as the flagship workload for that box
> - read [multicluster handoff notes](domains/multicluster/handoff-notes.md)
>   before OpenShift or multicluster work

## Stack

- **OS**: Talos Linux on Proxmox VMs, provisioned via Omni / Sidero
- **CNI**: Cilium with Gateway API + LoadBalancer
- **GitOps**: ArgoCD (self-managing, one local instance per cluster) + ApplicationSets for auto-discovery
- **Storage**: Longhorn (V1 engine, 2× replicas) on Talos; TrueNAS CSI on OpenShift
- **Backup**: VolSync + Kopia → RustFS S3, wired by [pvc-plumber](https://github.com/mitchross/pvc-plumber) from PVC labels
- **Database**: CloudNativePG (Postgres) with Barman backups to S3
- **Secrets**: 1Password Connect + External Secrets Operator
- **Observability**: kube-prometheus-stack, Loki, Tempo, OpenTelemetry
- **AI**: llama-cpp (Qwen3.6-35B multimodal) + ComfyUI on dedicated GPUs

## Documentation

### 🚰 Storage & backups (start here)

1. **[storage-architecture.md](storage-architecture.md)** — **the one doc.**
   Why it exists, plain-English explanation, the label contract, every
   diagram, day-2 operations (add/exempt/verify/drill), troubleshooting,
   adapting it to your cluster, honest limitations. *Send people this link.*
   Visual learner? **[🎮 the interactive simulator](simulator.html)** lets you
   nuke a toy cluster and watch the restore.
2. **[backup-repository-setup.md](backup-repository-setup.md)** — the one-time
   backend setup: S3 box, bucket, credentials, fan-out, the fail-closed gate.
3. **[disaster-recovery.md](disaster-recovery.md)** — the full-cluster
   destroy/rebuild runbook: pre-nuke checklist, calibrated restore-wave
   expectations, proof history, the restore canary.

### 🔍 pvc-plumber deep dives

1. **[pvc-plumber-start-here](pvc-plumber-start-here.md)** — visual intro: what it is, the architecture, what it does NOT do, v4-vs-v5.
2. **[pvc-plumber-cheatsheet](pvc-plumber-cheatsheet.md)** — one-page poster.
3. **[pvc-plumber-dynamic-workflow](pvc-plumber-dynamic-workflow.md)** — how the operator thinks (decision trees, `/audit` actions).
4. **[talos-argocd-pvc-plumber-integration](talos-argocd-pvc-plumber-integration.md)** — how this repo uses it (add-a-PVC checklist, labels).

### 🛠️ Operate the platform

- **[adding-a-cluster](adding-a-cluster.md)** — the n-cluster onboarding path: cluster tree anatomy, 1:1 parity contract, per-app overlay shape, CI guardrails.
- **[volsync-storage-recovery](volsync-storage-recovery.md)** — PVC backup/restore single source of truth + restore-drill runbook.
- **[kopia-maintenance-plan](domains/storage/kopia-maintenance-plan.md)** — repository maintenance (healthy; manual full not needed).
- **[storage-architecture-future](domains/storage/architecture-future.md)** — Longhorn-vs-restore-DR tiering (future idea).
- **[pvc-plumber-v4-cutover](pvc-plumber-v4-cutover.md)** — day-of cutover runbook (label model, ownership, rollback).
- **[pvc-plumber-v4-migration-readiness](pvc-plumber-v4-migration-readiness.md)** — per-PVC migration status (campaign closed).
- **[cluster-dr-nuke-restore-runbook](cluster-dr-nuke-restore-runbook.md)** — full cluster rebuild/restore runbook.

### Bootstrap rules from the full nuke

- CRDs first, controllers/apps second, CRs third.
- Observability is optional. Core apps must bootstrap without Prometheus.
- Do not install Prometheus Operator CRDs early to satisfy bootstrap apps.
- `kube-prometheus-stack` remains the sole owner of `monitoring.coreos.com` CRDs.

### 📐 Design / PRD

- **[pvc-plumber-v4-prd](pvc-plumber-v4-prd.md)** — locked design + **§0 canonical status** (shipped vs design).
- **[pvc-plumber-v4-roadmap](pvc-plumber-v4-roadmap.md)** — post-PRD backlog.
- **[pvc-plumber-v5-kopia-native-future](pvc-plumber-v5-kopia-native-future.md)** — v5 fork (VolSync-strict vs Kopia-native) — **parked, not built.**
- **[multicluster-prd](domains/multicluster/prd.md)** — multicluster design.

### 🗃️ Other domains

- **Databases**: [cnpg-disaster-recovery](domains/cnpg/disaster-recovery.md) · [cnpg-explained](domains/cnpg/explained.md)
- **GitOps / ArgoCD**: [argocd](domains/argocd/argocd.md) · [argocd-entrypoints](domains/argocd/entrypoints.md)
- **Networking**: [network-topology](domains/networking/topology.md) · [network-policy](domains/networking/policy.md)
- **Storage**: [rustfs-credential-runbook](domains/rustfs/credential-runbook.md) · [kopia-maintenance-plan](domains/storage/kopia-maintenance-plan.md) · [RWO/RWX model & sizing](domains/storage/storage-model-rwo-rwx-and-sizing.md) · [storage-architecture-future](domains/storage/architecture-future.md)
- **Multicluster**: [handoff notes](domains/multicluster/handoff-notes.md) · [prd](domains/multicluster/prd.md) · [OpenShift storage/apps](domains/multicluster/openshift-storage-and-app-migration.md)
- **Observability**: [radar-ng-observability](domains/observability/radar-ng.md)
- **AI / GPU**: [ai-model-catalog](domains/ai-gpu/model-catalog.md) · [3090-llm-optimization](domains/ai-gpu/3090-llm-optimization.md)

### 🗄️ Archive (historical only)

Historical migration, incident, design, and presentation docs live under
**[`archive/`](archive/README.md)** — preserved for context, **not** current runbooks.
Older research and plans remain under `research/` and `plans/` (also historical).

## How to read these docs

- Start with [storage-architecture.md](storage-architecture.md) for the
  current storage/backup model, then the pvc-plumber visual docs.
- Use the storage recovery page for application PVC operations.
- Use the CNPG DR page only for CNPG recovery.
- Use the nuke runbook only for full rebuild planning.
- Treat `archive/`, `research/`, and `plans/` as historical context.

## Adopting any of this

This is one operator's homelab, not a product. The patterns are portable —
the label-driven backup contract, the off-cluster repository, the
restore-canary idea, the sync-wave bootstrap — but the image tags, hostnames,
and 1Password item names are not. Start with
[storage-architecture.md](storage-architecture.md).
