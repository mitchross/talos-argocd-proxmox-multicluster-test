#!/usr/bin/env bash
# validate-cluster-layout.sh - enforce the cluster-centric Kustomize layout.

set -euo pipefail

ERRORS=0

fail() {
  echo "ERROR: $*"
  ERRORS=$((ERRORS + 1))
}

echo "=== Cluster-Centric Kustomize Layout Validation ==="

while IFS= read -r path; do
  fail "legacy deploy-target entrypoint remains: $path"
done < <(find manifests -path '*/deploy-targets/*/kustomization.yaml' -print | sort)

while IFS= read -r path; do
  fail "Argo metadata must live under clusters/<cluster>: $path"
done < <(find manifests -path '*/.argocd/config.json' -print | sort)

while IFS= read -r path; do
  fail "app overlay metadata is derivable and must not remain: $path"
done < <(
  find clusters/talos/apps clusters/openshift/apps \
    -path '*/.argocd/config.json' -type f -print | sort
)

for cluster in talos openshift; do
  while IFS= read -r metadata; do
    source_path="$(
      python3 - "$metadata" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    print(json.load(fh).get("sourcePath", ""))
PY
    )"

    case "$source_path" in
      "clusters/$cluster/"*) ;;
      *) fail "$metadata sourcePath must start with clusters/$cluster/: $source_path" ;;
    esac
  done < <(find "clusters/$cluster" -path '*/.argocd/config.json' -print | sort)
done

while IFS= read -r path; do
  fail "OpenShift overlay imports Talos content: $path"
done < <(rg -l 'clusters/talos|\.\./talos' clusters/openshift --glob 'kustomization.yaml' || true)

while IFS= read -r path; do
  fail "OpenShift Gateway API resources must use *.vanillax.xyz, not the cluster's *.apps.sno-ai-lab router domain: $path"
done < <(
  rg -n 'sno-ai-lab\.vanillax\.xyz' clusters/openshift --glob '*.{yaml,yml}' || true
)

while IFS= read -r path; do
  fail "OpenShift route points external-dns at the Talos domain (use target: vanillax.xyz): $path"
done < <(
  rg -l 'external-dns\.alpha\.kubernetes\.io/target:\s*vanillax\.me' clusters/openshift --glob '*.{yaml,yml}' || true
)

# Drift guard: the cloudflared tunnel allowlist must exactly mirror the set
# of hostnames on HTTPRoutes labeled external-dns: 'true'. A labeled route
# missing from cloudflared = public DNS record pointing at a tunnel that 404s
# it; a cloudflared entry without a labeled route = stale exposure surface.
# Routes commented out of their kustomization (e.g. kolibri) are also
# commented in the cloudflared config, so both sides of this comparison use
# the same source of truth: route files reachable from a kustomization.
cloudflared_config="clusters/openshift/infra/cloudflared/config.yaml"
if [ -f "$cloudflared_config" ]; then
  labeled_hosts="$(
    rg -l "external-dns: 'true'" clusters/openshift --glob '*httproute*.yaml' \
      | while IFS= read -r route; do
          # skip route files no kustomization references via an UNCOMMENTED
          # resource entry (disabled apps, e.g. kolibri)
          base="$(basename "$route")"
          rel="$(dirname "$route")"
          subpath="$(basename "$rel")/$base"
          if rg -q "^\s*-\s+(\./)?${base}\s*$" "$rel/kustomization.yaml" 2>/dev/null \
             || rg -q "^\s*-\s+(\./)?${subpath}\s*$" "$rel/../kustomization.yaml" 2>/dev/null; then
            # Per-YAML-document: a file can hold an internal AND an external
            # route (posthog); only hostnames from labeled documents count.
            # Line-based state machine — portable across gawk/mawk (multi-char
            # RS is not POSIX).
            awk '
              function flush() {
                if (labeled) for (i = 1; i <= n; i++) print hosts[i]
                labeled = 0; n = 0
              }
              /^---[[:space:]]*$/ { flush(); next }
              /external-dns: .true./ { labeled = 1 }
              /^[[:space:]]+- [a-z0-9.-]+\.vanillax\.xyz[[:space:]]*$/ {
                line = $0
                gsub(/^[[:space:]]+- |[[:space:]]+$/, "", line)
                hosts[++n] = line
              }
              END { flush() }
            ' "$route" || true
          fi
        done | sort -u
  )"
  tunnel_hosts="$(
    rg -o '^\s+- hostname:\s+([a-z0-9.-]+\.vanillax\.xyz)' -r '$1' "$cloudflared_config" \
      | rg -v '^vanillax\.xyz$' | sort -u
  )"
  while IFS= read -r host; do
    [ -n "$host" ] || continue
    fail "externally labeled route hostname missing from cloudflared allowlist: $host"
  done < <(comm -23 <(printf '%s\n' "$labeled_hosts") <(printf '%s\n' "$tunnel_hosts"))
  while IFS= read -r host; do
    [ -n "$host" ] || continue
    fail "cloudflared allowlist entry has no externally labeled route: $host"
  done < <(comm -13 <(printf '%s\n' "$labeled_hosts") <(printf '%s\n' "$tunnel_hosts"))
fi

while IFS= read -r path; do
  fail "escaped inline patch string remains: $path"
done < <(
  rg -l 'patch:\s*".*\\n' clusters manifests --glob 'kustomization.yaml' || true
)

while IFS= read -r path; do
  fail "multiline inline patch remains: $path"
done < <(
  rg -l '^[[:space:]]+patch:[[:space:]]+\|[-+]?$' \
    clusters manifests --glob 'kustomization.yaml' || true
)

while IFS= read -r path; do
  fail "deprecated Kustomize patch field remains: $path"
done < <(
  rg -l '^[[:space:]]*(patchesStrategicMerge|patchesJson6902|bases):' \
    clusters manifests --glob 'kustomization.yaml' || true
)

while IFS= read -r path; do
  fail "manifest-generate-paths must not use a source-relative clusters/ path: $path"
done < <(rg -l 'manifest-generate-paths:[[:space:]]+clusters/' clusters --glob '*.yaml' || true)

while IFS= read -r path; do
  fail "manifest-generate-paths must include consumed shared bases: $path"
done < <(rg -l -F 'manifest-generate-paths: "{{.sourcePath}}"' clusters --glob '*.yaml' || true)

# Talos is the complete production reference: every shared app base must have
# a Talos overlay. Other clusters opt in per-app — the SNO lab deploys a
# curated teaching subset, so a missing openshift overlay is intentional, but
# any overlay that DOES exist must point at a real shared base (catches
# orphans left behind when a base is renamed or retired).
while IFS= read -r base; do
  relative_app="${base#manifests/apps/}"
  relative_app="${relative_app%/base}"
  if [ ! -f "clusters/talos/apps/$relative_app/kustomization.yaml" ]; then
    fail "missing talos overlay for shared app base: $base"
  fi
done < <(find manifests/apps -mindepth 3 -maxdepth 3 -type d -name base | sort)

for cluster in talos openshift; do
  while IFS= read -r overlay; do
    relative_app="${overlay#clusters/$cluster/apps/}"
    relative_app="${relative_app%/kustomization.yaml}"
    if [ ! -d "manifests/apps/$relative_app/base" ]; then
      fail "$cluster overlay has no shared app base: clusters/$cluster/apps/$relative_app"
    fi
  done < <(
    find "clusters/$cluster/apps" -mindepth 3 -maxdepth 3 \
      -name kustomization.yaml -print | sort
  )
done

while IFS= read -r path; do
  fail "shared app base contains a cluster-specific local storage class: $path"
done < <(rg -l 'storageClass(Name)?:\s*(longhorn|lvms-vg1)' manifests/apps --glob '*.{yaml,yml}' || true)

if [ "$ERRORS" -gt 0 ]; then
  echo "FAILED: $ERRORS cluster layout error(s)"
  exit 1
fi

echo "PASSED: cluster layout is cluster-centric"
