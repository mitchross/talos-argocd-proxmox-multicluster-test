# Technitium Split-DNS (Talos `vanillax.me` + OpenShift `vanillax.xyz`)

Internal LAN clients resolve homelab names to a private gateway IP via Technitium
(`192.168.10.15`); everything else forwards to Cloudflare (DoH). Public access via
Cloudflare/tunnel is unchanged. Ported from the proven prod Talos migration —
full background and pitfalls in the prod repo's
`docs/domains/networking/technitium-vanillax-me-migration.md`.

## Per-cluster shape

| | Talos (`vanillax.me`) | OpenShift (`vanillax.xyz`) |
| --- | --- | --- |
| Internal gateway | `gateway-internal-technitium` @ `192.168.10.52` (Cilium) | `openshift-gateway-internal` @ `192.168.10.231` (MetalLB, class `openshift-default`) |
| Route attachment | routes **moved** off `gateway-internal` onto the technitium gateway | routes **dual-homed**: keep `openshift-gateway` (public) + add `openshift-gateway-internal` (private) |
| external-dns instance | `external-dns-technitium` (RFC2136 → Technitium) | `external-dns-technitium` (RFC2136 → Technitium) |
| TSIG key | `externaldns-vanillax` | `externaldns-vanillax-xyz` |
| 1Password item | `external-dns-technitium-vanillax` | `external-dns-technitium-vanillax-xyz` |
| TXT owner id | `talos-prod-technitium` | `sno-prod-technitium` |
| TLS cert | shared `cert-vanillax` wildcard | shared `cert-openshift-gateway-apps` wildcard |
| Net policy | `allow-technitium-dns` CiliumNetworkPolicy | none (OpenShift = OVN + SCC; new SCC RoleBinding instead) |

Why dual-home OpenShift but move Talos: Talos internal routes were already
private-only (`gateway-internal`). OpenShift app routes are public via Cloudflare;
dual-homing adds private LAN resolution **without** dropping public access. The
OpenShift internal gateway deliberately omits the
`external-dns.alpha.kubernetes.io/target` annotation so external-dns publishes the
`.231` A record (not a CNAME) into Technitium.

## The ArgoCD parentRefs landmine (fixed here too)

`clusters/<cluster>/{bootstrap,infra/argocd}/values.yaml` previously ignored
HTTPRoute `/spec/parentRefs` wholesale, which makes ArgoCD silently drop Gateway
re-parenting while reporting **Synced**. Fixed to ignore only the defaulted
`group`/`kind` subfields. Note the deeper gotcha proven in prod: even with that
fix, `RespectIgnoreDifferences=true` + an array-traversing jq still drops
`parentRefs` from the **sync-apply** patch — so an existing route may need a direct
`kubectl patch` (or a sync without `RespectIgnoreDifferences`) to actually move.
Delete-and-recreate also works.

## Manual prerequisites (live side — per cluster, before deploy)

**Talos** uses the SAME Technitium/1Password/zone as prod, so if prod is already
cut over, no new manual work — but if this fork's Talos targets a *separate* live
cluster, give it a distinct `txtOwnerId` to avoid TXT-ownership fights over the
shared `vanillax.me` zone.

**OpenShift** is net-new and needs:
1. **Technitium** `vanillax.xyz` Conditional-Forwarder zone (DoH fallback to
   `https://cloudflare-dns.com/dns-query (1.1.1.1)`).
2. **TSIG key** `externaldns-vanillax-xyz` (HMAC-SHA256) with dynamic-update
   (Security Policy: `*.vanillax.xyz`, types A/AAAA/CNAME/TXT) **and** zone-transfer
   (AXFR) permission on that zone.
3. **1Password** item `external-dns-technitium-vanillax-xyz`, field `tsig-secret` =
   that key's value (base64 as-is).
4. **Firewalla** `server-high=/vanillax.xyz/192.168.10.15`.
5. **MetalLB**: confirm `192.168.10.231` is free in `gateway-pool` (`.230-.240`;
   `.230` is `openshift-gateway`).

## Verify after deploy

```bash
kubectl -n external-dns logs deploy/external-dns-technitium -f   # expect no "bad authentication"/AXFR errors
dig @192.168.10.15 <app>.vanillax.me  +short                     # talos  -> 192.168.10.52
dig @192.168.10.15 <app>.vanillax.xyz +short                     # openshift -> 192.168.10.231
dig @192.168.10.1  <app>.vanillax.me  +short                     # through Firewalla
```
Rotating the TSIG secret requires a pod restart (`rollout restart deploy/external-dns-technitium`) — it is loaded from an env var at startup.
