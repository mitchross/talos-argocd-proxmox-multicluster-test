# vLLM (STAGED — enable after the 2950X bare-metal move)

OpenAI-compatible inference server, staged as the **flagship GPU workload
for the SNO's target hardware**: the bare-metal Threadripper 2950X with
2x RTX 3090 (decision 2026-06-10, recorded in
`docs/domains/multicluster/handoff-notes.md`). Unlike llama-cpp (GGUF,
single-card), vLLM here runs **tensor-parallel across both 3090s**
(48GB pooled) — the same serving stack used on OpenShift AI at work.

Until that box exists, the base deploys the namespace only (the
`development/dvwa` staging idiom): there is no `nvidia.com/gpu` capacity
anywhere, so the pod could never schedule, and parity CI stays satisfied
because both cluster overlays exist.

## What you get when enabled

- `vllm serve Qwen/Qwen3-32B-AWQ` with `--tensor-parallel-size 2`,
  served-model-name `qwen3-32b`, 32K context.
- OpenAI-compatible API at
  `http://vllm-service.vllm.svc.cluster.local:8000/v1` (same `/v1`
  contract as llama-cpp — in-cluster consumers like open-webui can add it
  as a second backend).
- HF model cache on the 100Gi `vllm-hf-cache` PVC (`vanillax-local-rwo`;
  backup-exempt — it is re-downloadable). When LVMS lands
  (`clusters/openshift/infra/lvm-storage/`), repoint this PVC to
  `lvms-vg1` via an OpenShift overlay patch for node-local NVMe speed.

## Enable checklist (run AFTER `nvidia.com/gpu: 2` is allocatable)

1. GPU stack live: `clusters/openshift/infra/gpu-operator/` marker flipped,
   `kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}'`
   returns `2`.
2. Uncomment `pvc.yaml`, `deployment.yaml`, `service.yaml` in
   `base/kustomization.yaml`.
3. In `clusters/openshift/apps/ai/vllm/kustomization.yaml`: uncomment
   `httproute.yaml` and the `patches:` block (fsGroup removal for
   restricted-v2 + Talos backup-label strip).
4. Uncomment the `vllm.vanillax.xyz` line in `firewalla-dns-config-xyz.txt`
   and apply it to Firewalla (internal-only app — no `external-dns` label,
   no cloudflared entry).
5. First start is slow: ~19GB download + dual-GPU load; the startupProbe
   allows ~1h. Watch `kubectl logs -n vllm deploy/vllm-server -f`.
6. GPU contention is hand-managed (operator decision 2026-06-09): with
   TP=2 vLLM wants BOTH cards — scale llama-cpp/comfyui/swarmui to zero
   first, or set `--tensor-parallel-size 1` + a ≤20GB model
   (e.g. `Qwen/Qwen3-14B-AWQ`) to share the pair.

## Knobs

| Change | Where |
|---|---|
| Model | first `args:` entry (AWQ/GPTQ/FP8 quants sized for 24/48GB) |
| Single-card mode | `--tensor-parallel-size 1` + smaller model |
| Context length | `--max-model-len` |
| NCCL hang at TP init on X399 | uncomment `NCCL_P2P_DISABLE=1` in `deployment.yaml` |
| Gated models (Llama etc.) | add an ExternalSecret for `HF_TOKEN` (1Password) — do NOT commit tokens |

## Talos overlay

`clusters/talos/apps/ai/vllm/` exists for the 1:1 parity contract (CI
counts overlays in both clusters). Do not enable it: the 3090s leave the
Talos GPU worker as part of this same hardware move, and Talos keeps
llama-cpp as its (remote) backend story afterward.
