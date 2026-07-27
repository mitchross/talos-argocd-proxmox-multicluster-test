# Infrastructure Guidelines

> **Required reading before modifying ArgoCD configuration or sync waves:**
> - `docs/domains/argocd/argocd.md` — Sync wave strategy, Lua health checks, server-side diff, why ApplyOutOfSyncOnly breaks ConfigMaps

> **These two files exist but never auto-load (non-standard filenames) — read
> them explicitly when doing that kind of work:**
> - `manifests/infra/networking-CLAUDE.md` — networking work
> - `manifests/infra/storage-CLAUDE.md` — storage work

## Essential Commands

```bash
# Emergency reset (removes all applications)
kubectl get applications -n argocd -o name | xargs -I{} kubectl patch {} -n argocd --type json -p '[{"op": "remove","path": "/metadata/finalizers"}]'
kubectl delete applications --all -n argocd
./scripts/bootstrap-cluster.sh talos

# Per-mover-Job init container that gates on RustFS reachability:
kubectl get pods -A -l app.kubernetes.io/created-by=volsync -o=jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"  init: "}{.spec.initContainers[*].name}{"\n"}{end}'
```

## Infrastructure AppSet Rules

The Infrastructure AppSet uses an **explicit list of paths** (not glob discovery). To add a new infrastructure component:

1. Add the shared source under `manifests/infra` when it is portable.
2. Add the deploy target under the owning `clusters/<cluster>/infra` tree.
3. Add `.argocd/config.json` metadata if AppSet-managed, or add a standalone
   Application under the owning `clusters/<cluster>/argocd/`.
4. Ensure standalone Argo files are listed in that cluster's Argo
   `kustomization.yaml`.

```bash
# Verify after adding a new file
grep "my-new-appset.yaml" clusters/talos/argocd/kustomization.yaml
kubectl get applicationset -n argocd
```

Databases are auto-discovered separately by `database-appset.yaml` via
`clusters/talos/database/*/*/.argocd/config.json`.

## Debugging ArgoCD

```bash
# Force manual sync
kubectl patch application app-name -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```
