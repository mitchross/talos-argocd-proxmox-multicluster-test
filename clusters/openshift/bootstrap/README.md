# OpenShift Argo CD Bootstrap

This directory contains the hand-run upstream Helm Argo CD bootstrap inputs for
the OpenShift cluster.

This repo does not use the OpenShift GitOps Operator for OpenShift bootstrap.
It uses the same shape as Talos:

```text
helm install upstream Argo CD -> apply root Application -> local Argo CD self-manages
```

> **Live `sno-ai-lab` bootstrap is blocked as of June 4, 2026.**
> Read `docs/domains/multicluster/handoff-notes.md` before running any command
> below. Storage (democratic-csi), load-balancing (MetalLB) and Postgres
> (CNPG) are all **Helm-installed now** — no OLM operators — so the
> unresolvable `lvms-operator`/`metallb-operator` catalog gap is gone. What
> remains live-unverified: `.230` L2 advertisement, authoritative DNS for
> `*.vanillax.xyz`, the three Connect bootstrap secrets,
> and the two TrueNAS driver-config 1Password items. The profile wrapper does
> not prove `.230`/DNS before installing Argo CD.

Use the repo-level script from the repository root:

```bash
./scripts/bootstrap-cluster.sh openshift
```

The profile wrapper:

- `kubectl` or `oc` points at the intended OpenShift cluster.
- verifies OpenShift-managed Gateway API CRDs;
- rejects a conflicting Service Mesh Operator v2 subscription;
- requires no OLM PackageManifests (storage/LB/DB are all Helm-installed);
- never installs Cilium or upstream Gateway API CRDs;
- verifies the three pre-seeded 1Password secrets;
- calls `scripts/bootstrap-argocd.sh openshift` after prerequisites pass.

Git owns GatewayClass `openshift-default` with controller
`openshift.io/gateway-controller/v1`, MetalLB operator/config manifests, the
democratic-csi storage component, the upstream MetalLB Helm chart + config, the
CNPG database tree, and the dedicated Gateway app domain
`*.vanillax.xyz`. Only the `.230` L2 advertisement and
authoritative DNS still require live verification.

The original feature branch points Argo CD at the original repository's
`main`. Use the isolated test repository's `main` branch for live OpenShift
testing:

```text
https://github.com/mitchross/talos-argocd-proxmox-multicluster-test
```

Direct `scripts/bootstrap-argocd.sh openshift` invocation is the focused
Argo-only step and assumes every platform prerequisite is already complete.

Manual equivalent:

```bash
kubectl apply -f clusters/openshift/bootstrap/ns.yaml
helm upgrade --install argocd argo-cd \
  --repo https://argoproj.github.io/argo-helm \
  --version 9.5.17 \
  --namespace argocd \
  --values clusters/openshift/bootstrap/values.yaml \
  --wait \
  --timeout 10m
kubectl wait --for condition=established --timeout=60s crd/applications.argoproj.io
kubectl wait --for=condition=Available deployment/argocd-server -n argocd --timeout=300s
kubectl apply -f clusters/openshift/bootstrap/root.yaml
```

`kustomization.yaml` renders the Helm bootstrap locally for validation. The root
Application is applied separately after the Application CRD exists.
