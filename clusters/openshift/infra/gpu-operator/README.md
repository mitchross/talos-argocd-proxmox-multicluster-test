# NVIDIA GPU stack (STAGED — NOT DEPLOYED)

This directory is **deliberately not discovered** by the infrastructure
AppSet: the marker is `.argocd/config.json.disabled`. Nothing here syncs
until you rename it.

## Why staged

The June 5, 2026 PackageManifest recheck found the `4.22.0-rc.5` catalogs
missing several expected packages (`lvms-operator`, `metallb-operator`).
The GPU operator comes from a DIFFERENT catalog (`certified-operators`,
which demonstrably had at least one package), and NFD comes from
`redhat-operators` (the one with known gaps) — so this path must be proven
against the live cluster before it can be wired in.

> **2026-06-11 update:** the cluster inline-upgraded to **4.22.0 GA** and the
> catalog check below now **passes** — both `gpu-operator-certified`
> (Certified Operators) and `nfd` (Red Hat Operators) are published. This
> entry is ready to enable; only the marker rename remains. (`lvms-operator`
> is still absent from the 4.22 catalogs — that staging is unrelated.)

## Enable procedure

1. **Catalog check (live):**

   ```bash
   kubectl get packagemanifests -n openshift-marketplace \
     | grep -Ei 'gpu-operator|nfd'
   kubectl get packagemanifest gpu-operator-certified \
     -n openshift-marketplace -o jsonpath='{.status.defaultChannel}'
   ```

   Both `gpu-operator-certified` AND `nfd` must be present.
   (The Subscriptions below omit `channel:`, so OLM uses each package's
   defaultChannel — no version guessing in Git.)

2. **Rename the marker:**

   ```bash
   git mv clusters/openshift/infra/gpu-operator/.argocd/config.json.disabled \
          clusters/openshift/infra/gpu-operator/.argocd/config.json
   ```

   The infrastructure AppSet discovers it on the next sync (wave 4).
   First sync NEEDS the AppSet retry behavior: the ClusterPolicy and
   NodeFeatureDiscovery CRs fail until OLM installs the CSVs and their
   CRDs appear (~1-3 min); retry + selfHeal lands them.

3. **Verify (live):**

   ```bash
   kubectl get csv -n nvidia-gpu-operator
   kubectl get clusterpolicy gpu-cluster-policy \
     -o jsonpath='{.status.state}'        # → ready (driver build takes ~10-20 min on first install)
   kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}'
   kubectl get runtimeclass nvidia        # created by the operator
   ```

   Then llama-cpp / comfyui / swarmui pods can schedule (they request
   `nvidia.com/gpu` + `runtimeClassName: nvidia` + the gpu-workload
   PriorityClasses that are already deployed).

## Fallback if the catalog check fails

Use NVIDIA's upstream Helm chart instead (matches this repo's no-OLM
pattern for metallb/cnpg/truenas): repo `https://helm.ngc.nvidia.com/nvidia`,
chart `gpu-operator`, `nfd.enabled=true` (bundles NFD so the redhat-operators
gap stops mattering). Replace the OLM manifests here with a
`helmCharts:` kustomization like `clusters/openshift/infra/metallb-operator`.
NOTE: on OpenShift the Helm path is community-supported, not NVIDIA-official;
the operator still auto-detects OpenShift and uses the Driver Toolkit.

## SNO-specific notes

- **Single GPU**: llmfit's `job-dual-gpu.yaml` requests `nvidia.com/gpu: "2"`
  and will stay Pending forever on a 1-GPU node. Talos's GPU-0/GPU-1 split
  (llama-cpp / comfyui) also cannot apply: with whole-card allocation and one
  card, llama-cpp and comfyui CONTEND for the single GPU — only one schedules
  at a time unless you enable time-slicing in the devicePlugin config.
- `mig.strategy: single` is inert on consumer GPUs (no MIG support).
- The driver build happens in-cluster via the Driver Toolkit; first
  ClusterPolicy reconcile compiles the kernel module — expect 10-20 min.
