# SNO Cert-Manager Reconcile Design

## Problem

`redlib.vanillax.xyz` reaches the SNO Cloudflare tunnel, but the tunnel cannot
connect to `192.168.10.230:443` because the Gateway HTTPS listener has no TLS
Secret.

The certificate is pending because cert-manager reads the Talos-only
`cert-manager-proxmox/api-token` value. Git correctly renders
`cloudflared-sno/api-token`, but Argo CD repeatedly reports a successful apply
without changing the live ExternalSecret.

## Root Cause

The ExternalSecret CRD declares `spec.data` as an atomic list. Argo CD globally
ignores webhook-defaulted fields below `spec.data[]`, and the cert-manager
Application enables `RespectIgnoreDifferences=true`. During sync, Argo CD
preserves the live atomic list to respect those ignored child fields. This also
preserves the stale `remoteRef.key`, so self-heal becomes a successful no-op.

## Design

Remove `RespectIgnoreDifferences=true` only from the cert-manager Application.
Keep server-side apply and the global comparison ignores. This lets Argo CD
replace the ExternalSecret atomic list while limiting behavioral change to the
application that needs to change its Cloudflare token source.

Perform a one-time live reconcile from the rendered Git manifest, force the
ExternalSecret refresh, and wait for cert-manager to issue the wildcard
certificate. The existing Gateway and Redlib HTTPRoute remain unchanged.

## Verification

1. Assert the cert-manager Application no longer enables
   `RespectIgnoreDifferences=true`.
2. Confirm the rendered ExternalSecret uses `cloudflared-sno/api-token`.
3. Confirm the live Secret changes to the known SNO Cloudflare token.
4. Confirm the wildcard Certificate is Ready and the Gateway HTTPS listener is
   Programmed.
5. Confirm `https://redlib.vanillax.xyz` returns an application response instead
   of Cloudflare 502.

