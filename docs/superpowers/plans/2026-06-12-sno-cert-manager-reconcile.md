# SNO Cert-Manager Reconcile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the SNO Gateway HTTPS listener so `redlib.vanillax.xyz` works through Kubernetes Gateway API.

**Architecture:** Limit the GitOps behavior change to the cert-manager Argo CD Application by disabling apply-time respect for globally ignored differences. Reconcile the existing ExternalSecret from rendered Git state, then verify the certificate, Gateway listener, and public Redlib endpoint.

**Tech Stack:** Argo CD, Kustomize, External Secrets Operator, cert-manager, OpenShift Gateway API, Cloudflare Tunnel

---

### Task 1: Correct cert-manager reconciliation

**Files:**
- Modify: `clusters/openshift/argocd/core-dependencies/cert-manager-app.yaml`

- [ ] **Step 1: Verify the regression assertion fails**

Run:

```bash
if rg -q 'RespectIgnoreDifferences=true' clusters/openshift/argocd/core-dependencies/cert-manager-app.yaml; then
  echo "FAIL: cert-manager still respects ignored differences during apply"
  exit 1
fi
```

Expected: FAIL because the option is currently present.

- [ ] **Step 2: Remove the unsafe sync option**

Delete only this line from the cert-manager Application:

```yaml
- RespectIgnoreDifferences=true
```

- [ ] **Step 3: Verify the regression assertion passes**

Run the command from Step 1 again.

Expected: exit 0 with no failure message.

- [ ] **Step 4: Validate rendered resources**

Run:

```bash
kustomize build --enable-helm clusters/openshift/infra/cert-manager
```

Expected: exit 0, with the ExternalSecret rendering
`remoteRef.key: cloudflared-sno`.

### Task 2: Reconcile and verify SNO

**Files:**
- No repository file changes.

- [ ] **Step 1: Apply the corrected Application and rendered ExternalSecret**

Use the SNO kubeconfig to apply the cert-manager Application and the
`cloudflare-api-token` ExternalSecret. Force an ExternalSecret refresh
annotation after the source reference changes.

- [ ] **Step 2: Wait for TLS readiness**

Wait until the `cert-openshift-gateway-apps` Certificate reports Ready and the
`openshift-gateway` HTTPS listener reports Programmed.

- [ ] **Step 3: Verify Redlib**

Run:

```bash
curl -fsSIL --max-time 20 https://redlib.vanillax.xyz
```

Expected: an application HTTP response, not Cloudflare 502.

- [ ] **Step 4: Capture the durable root cause**

Save a Mink resource note describing the atomic ExternalSecret list and
`RespectIgnoreDifferences` interaction.

