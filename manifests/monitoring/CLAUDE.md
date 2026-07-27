# Monitoring Guidelines

## Observability Architecture

OTEL Collector Agent (DaemonSet, per-node filelog + OTLP receive) forwards to
the OTEL Collector Gateway (Deployment: k8sattributes, batch, fan-out), which
ships traces to Tempo, logs to Loki, and metrics to Prometheus.

External clients (e.g. the radar-ng mobile app) hit the Gateway over HTTPS at
`otel.vanillax.me/v1/{traces,logs,metrics}` via `collector-gateway-httproute.yaml`.

- **OTEL Operator** (`clusters/talos/infra/opentelemetry-operator/`) — manages Collectors and auto-instrumentation
- **OTEL observability overlay** (`clusters/talos/infra/opentelemetry-operator-observability/`) — the operator's ServiceMonitor, deployed at a wave after kube-prometheus-stack so `monitoring.coreos.com` CRDs exist
- **Prometheus + Grafana** (`clusters/talos/monitoring/prometheus-stack/`) — metrics storage, dashboards, alerting
- **Loki** (`clusters/talos/monitoring/loki-stack/`) — log storage (S3 backend on RustFS)
- **Tempo** (`clusters/talos/monitoring/tempo/`) — trace storage (S3 backend on RustFS)

## Common Pitfalls

- **Tempo/Loki S3 creds**: Use `extraEnvFrom` with secretRef, NOT inline `${VAR}` in config (they don't expand env vars)
- **ArgoCD metrics**: Must be per-component (`controller.metrics`, `server.metrics`, etc.), top-level `metrics:` key does nothing
- **Longhorn ServiceMonitor**: Select `app: longhorn-manager` (NOT `app.kubernetes.io/name: longhorn-manager`)
- **ArgoCD ignoreDifferences**: Use `jqPathExpressions` NOT `jsonPointers` for wildcards (RFC 6901 doesn't support `*`)
- **PVC storage in ignoreDifferences**: Must ignore `.spec.resources.requests.storage` — can't shrink existing PVCs
- **Loki tenant_id**: Multi-tenant mode requires `X-Scope-OrgID` header or `tenant_id` config — 401 without it
- **OTEL Collector CRDs**: Use `v1beta1` API version for `OpenTelemetryCollector`, `v1alpha1` for `Instrumentation`

## Key Files

- Custom ServiceMonitors: `clusters/talos/monitoring/prometheus-stack/custom-servicemonitors.yaml`
- Custom alerts: `clusters/talos/monitoring/prometheus-stack/custom-alerts.yaml`
- GPU alerts: `clusters/talos/monitoring/prometheus-stack/gpu-alerts.yaml`
- OTEL Collector Agent: `clusters/talos/infra/opentelemetry-operator/collector-agent.yaml`
- OTEL Collector Gateway: `clusters/talos/infra/opentelemetry-operator/collector-gateway.yaml`
- OTEL Gateway public HTTPRoute: `clusters/talos/infra/opentelemetry-operator/collector-gateway-httproute.yaml`
- Auto-instrumentation: `clusters/talos/infra/opentelemetry-operator/instrumentation.yaml`
