#!/usr/bin/env python3
"""Sync upstream talos-argocd-proxmox (single-cluster layout) into this
multicluster repo.

Upstream live trees        -> multicluster targets
  my-apps/<cat>/<app>/        manifests/apps/<cat>/<app>/base/   (sources)
                              clusters/talos/apps/<cat>/<app>/   (httproutes)
  infrastructure/<grp>/<n>/   manifests/infra/<n>/base/ if shared, else
                              clusters/talos/infra/<n>/
  infrastructure/database/*   clusters/talos/database/*
  monitoring/*                clusters/talos/monitoring/*

Transforms applied to app sources copied into manifests/apps bases:
  - storageClassName: longhorn -> vanillax-local-rwo (portable class; Talos
    maps it back to Longhorn, OpenShift maps it to TrueNAS iSCSI)
  - httproute*.yaml / http-route*.yaml move to the Talos overlay and their
    resource entries are stripped from the base kustomization

NEVER touched (multicluster-only adaptations, merged manually instead):
  - clusters/<cluster>/argocd/**        (goTemplate appsets, renamed projects)
  - clusters/openshift/**               (SNO overlays)
  - **/.argocd/config.json              (appset file-generator configs)
  - PRESERVE list below (staged vllm, patch-file factored kustomizations,
    portable storage class, external-secrets SSA patches)

Usage: hack/sync-from-upstream.py [--apply]   (default is dry-run)
"""

import re
import shutil
import sys
from pathlib import Path

UP = Path("/home/vanillax/programming/talos-argocd-proxmox")
MC = Path(__file__).resolve().parent.parent

APPLY = "--apply" in sys.argv

# mc-relative paths (exact file or dir prefix) that are never written/deleted
PRESERVE = [
    "manifests/apps/ai/vllm/base/kustomization.yaml",   # STAGED app — namespace-only until 2950X
    "manifests/apps/development/gitea/base/kustomization.yaml",
    "manifests/apps/development/gitea/base/patches",    # strategic-merge patch files (cluster-side helm render fix)
    "manifests/apps/development/temporal/base/kustomization.yaml",
    "manifests/apps/development/temporal/base/patches",
    "manifests/infra/external-secrets/base/kustomization.yaml",
    "manifests/infra/external-secrets/base/patches",    # CRD SSA patch files (shared with OpenShift)
    "clusters/talos/infra/longhorn/kustomization.yaml", # references portable-storage-class.yaml
    "clusters/talos/infra/longhorn/portable-storage-class.yaml",  # defines vanillax-local-rwo
    # CI (validate-cluster-layout.sh) bans inline multiline patches and
    # patchesStrategicMerge — these keep the patch-file factored form.
    "clusters/talos/monitoring/prometheus-stack/kustomization.yaml",
    "clusters/talos/monitoring/prometheus-stack/patches",
    # upstream keeps this at the component root; mc carries it as
    # patches/alertmanager-config.yaml instead
    "clusters/talos/monitoring/prometheus-stack/alertmanager-config.yaml",
    "clusters/talos/database/cloudnative-pg/cloudnative-pg-operator/kustomization.yaml",
    "clusters/talos/database/cloudnative-pg/cloudnative-pg-operator/patches",
]

SHARED_INFRA = {"1passwordconnect", "cert-manager", "csi-driver-nfs",
                "csi-driver-smb", "external-secrets"}

ROUTE_RE = re.compile(r"^http-?route[\w.-]*\.ya?ml$")
ROUTE_LINE_RE = re.compile(r"^\s*-\s*[\w./-]*http-?route[\w.-]*\.ya?ml\s*$")

stats = {"copy": 0, "delete": 0, "same": 0, "manual": []}


def preserved(mc_rel: str) -> bool:
    return any(mc_rel == p or mc_rel.startswith(p + "/") for p in PRESERVE) \
        or "/.argocd/" in f"/{mc_rel}/"


def transform_app_file(rel: Path, data: bytes) -> bytes:
    if rel.suffix in (".yaml", ".yml", ".env", ".md"):
        txt = data.decode("utf-8", "replace")
        # Covers both PVC specs (storageClassName) and Helm values
        # (storageClass) — CI rejects `longhorn` anywhere under manifests/apps.
        txt = re.sub(r"storageClass(Name)?:\s*longhorn\b",
                     r"storageClass\1: vanillax-local-rwo", txt)
        if rel == Path("kustomization.yaml"):
            txt = "\n".join(l for l in txt.splitlines()
                            if not ROUTE_LINE_RE.match(l)) + "\n"
        return txt.encode()
    return data


def write(target: Path, data: bytes, label: str):
    mc_rel = str(target.relative_to(MC))
    if preserved(mc_rel):
        if not target.exists() or target.read_bytes() != data:
            stats["manual"].append(f"PRESERVED-DIFFERS {label}: {mc_rel}")
        return
    if target.exists() and target.read_bytes() == data:
        stats["same"] += 1
        return
    stats["copy"] += 1
    print(f"  write  {mc_rel}")
    if APPLY:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def delete_unmapped(target_dir: Path, expected: set):
    """Delete files under target_dir that no upstream file maps to."""
    if not target_dir.exists():
        return
    for f in sorted(target_dir.rglob("*")):
        if not f.is_file():
            continue
        mc_rel = str(f.relative_to(MC))
        if preserved(mc_rel) or f in expected:
            continue
        # Never delete vendored helm chart caches kustomize pulled for the
        # pinned versions — upstream's committed caches can lag its pins.
        if "charts" in f.relative_to(target_dir).parts:
            continue
        stats["delete"] += 1
        print(f"  delete {mc_rel}")
        if APPLY:
            f.unlink()
    if APPLY:  # prune empty dirs
        for d in sorted([p for p in target_dir.rglob("*") if p.is_dir()],
                        reverse=True):
            if not any(d.iterdir()):
                d.rmdir()


def sync_app(app: Path):
    cat, name = app.parts[-2], app.parts[-1]
    base = MC / "manifests/apps" / cat / name / "base"
    overlay = MC / "clusters/talos/apps" / cat / name
    expected = set()
    new_routes = []
    for f in sorted(app.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(app)
        if ROUTE_RE.match(f.name) and "charts" not in rel.parts:
            tgt = overlay / rel
            write(tgt, f.read_bytes(), f"app {cat}/{name}")
            expected.add(tgt)
            new_routes.append(str(rel))
        else:
            tgt = base / rel
            write(tgt, transform_app_file(rel, f.read_bytes()), f"app {cat}/{name}")
            expected.add(tgt)
    delete_unmapped(base, expected)
    # Talos overlay must exist and reference base + routes; generate if absent
    okust = overlay / "kustomization.yaml"
    if not okust.exists():
        ns = ""
        upkust = app / "kustomization.yaml"
        if upkust.exists():
            m = re.search(r"^namespace:\s*(\S+)", upkust.read_text(), re.M)
            ns = f"namespace: {m.group(1)}\n" if m else ""
        body = ("apiVersion: kustomize.config.k8s.io/v1beta1\n"
                "kind: Kustomization\n" + ns + "resources:\n"
                f"- \"../../../../../manifests/apps/{cat}/{name}/base\"\n"
                + "".join(f"- {r}\n" for r in sorted(new_routes)))
        write(okust, body.encode(), f"app {cat}/{name} (generated overlay)")
    else:
        kt = okust.read_text()
        for r in new_routes:
            if r not in kt:
                stats["manual"].append(
                    f"OVERLAY-MISSING-ROUTE clusters/talos/apps/{cat}/{name}/"
                    f"kustomization.yaml lacks {r}")


def sync_mirror(src: Path, dst: Path, label: str):
    expected = set()
    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue
        tgt = dst / f.relative_to(src)
        write(tgt, f.read_bytes(), label)
        expected.add(tgt)
    delete_unmapped(dst, expected)


def main():
    print("== apps ==")
    for app in sorted(UP.glob("my-apps/*/*")):
        if app.is_dir():
            sync_app(app)

    print("== infrastructure ==")
    for grp in ("controllers", "networking", "storage"):
        for comp in sorted((UP / "infrastructure" / grp).iterdir()):
            if not comp.is_dir() or comp.name == "argocd":
                continue
            if comp.name in SHARED_INFRA:
                dst = MC / "manifests/infra" / comp.name / "base"
            elif comp.name == "cloudflare-workers":
                dst = MC / "manifests/infra" / comp.name
            else:
                dst = MC / "clusters/talos/infra" / comp.name
            sync_mirror(comp, dst, f"infra {comp.name}")

    print("== database ==")
    for comp in sorted((UP / "infrastructure/database").iterdir()):
        if comp.is_dir():
            sync_mirror(comp, MC / "clusters/talos/database" / comp.name,
                        f"database {comp.name}")

    print("== monitoring ==")
    for comp in sorted((UP / "monitoring").iterdir()):
        if comp.is_dir():
            sync_mirror(comp, MC / "clusters/talos/monitoring" / comp.name,
                        f"monitoring {comp.name}")

    print("== scripts (new only; changed ones are listed for manual review) ==")
    for f in sorted((UP / "scripts").iterdir()):
        if not f.is_file() or f.suffix == ".gz" or f.name.startswith("k8s-"):
            continue
        tgt = MC / "scripts" / f.name
        if not tgt.exists():
            write(tgt, f.read_bytes(), "script")
            if APPLY:
                tgt.chmod(0o755)
        elif tgt.read_bytes() != f.read_bytes():
            stats["manual"].append(f"SCRIPT-DIFFERS scripts/{f.name}")

    print("== omni ==")
    for f in sorted((UP / "omni").rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(UP / "omni")
        if rel.parts[0] in (".claude",) or "configs/kubeconfig" in str(rel):
            continue
        write(MC / "omni" / rel, f.read_bytes(), "omni")

    print(f"\nsummary: copy={stats['copy']} delete={stats['delete']} "
          f"unchanged={stats['same']} mode={'APPLY' if APPLY else 'DRY-RUN'}")
    if stats["manual"]:
        print("\nMANUAL MERGE NEEDED:")
        for m in stats["manual"]:
            print("  " + m)


if __name__ == "__main__":
    main()
