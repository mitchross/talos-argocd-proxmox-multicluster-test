# democratic-csi (OpenShift) — TrueNAS-backed storage

OpenShift-only storage component. Talos uses Longhorn; OpenShift uses
democratic-csi against the existing TrueNAS at **192.168.10.133** (10G).

## Why this instead of LVMS

`lvms-operator` is an **OLM operator**. The live `4.22.0-rc.5` cluster's
`redhat-operators` catalog does **not** publish `lvms-operator` (verified by
PackageManifest lookup, June 5 2026), so it cannot resolve. democratic-csi is a
**Helm CSI driver**, so it is independent of the OLM catalog. It also needs no
host LVM volume group (RHCOS is immutable), and gives ZFS snapshots/clones for
free on TrueNAS.

## What it provides

| StorageClass | Release | Access | Backed by |
|---|---|---|---|
| `vanillax-local-rwo` (default) | `truenas-iscsi` | RWO block | TrueNAS iSCSI zvols |
| `truenas-nfs-csi` | `truenas-nfs` | RWX/RWO file | TrueNAS NFS datasets |

The existing **static** `csi-driver-nfs` / `csi-driver-smb` shares are kept
as-is for media apps that mount pre-existing data; `truenas-nfs-csi` is the
*dynamic* complement.

## Required 1Password items (pre-seed before sync)

Two items in the vault behind ClusterSecretStore `1password`, each with a
single field **`config`** holding the FULL democratic-csi driver config YAML.
ESO materializes each as a Secret keyed `driver-config-file.yaml`.

- `democratic-csi-truenas-iscsi`
- `democratic-csi-truenas-nfs`

### iSCSI `config` field template (fill in your TrueNAS specifics)

```yaml
driver: freenas-api-iscsi
instance_id:
httpConnection:
  protocol: http
  host: 192.168.10.133
  port: 80
  apiKey: "<TrueNAS API key>"   # System Settings -> API Keys
  allowInsecure: true
zfs:
  datasetParentName: <pool>/k8s/iscsi/v        # zvol parent for volumes
  detachedSnapshotsDatasetParentName: <pool>/k8s/iscsi/s
  zvolBlocksize: 16K
  zvolEnableReservation: false
iscsi:
  targetPortal: "192.168.10.133:3260"
  interface:
  namePrefix: csi-
  nameSuffix: "-cluster"
  targetGroups:
    - targetGroupPortalGroup: 1
      targetGroupInitiatorGroup: 1
      targetGroupAuthType: None
  extentInsecureTpc: true
  extentBlocksize: 512
  extentRpm: "7200"
```

### NFS `config` field template

```yaml
driver: freenas-api-nfs
instance_id:
httpConnection:
  protocol: http
  host: 192.168.10.133
  port: 80
  apiKey: "<TrueNAS API key>"
  allowInsecure: true
zfs:
  datasetParentName: <pool>/k8s/nfs/v
  detachedSnapshotsDatasetParentName: <pool>/k8s/nfs/s
  datasetEnableQuotas: true
nfs:
  shareHost: 192.168.10.133
  shareAlldirs: false
  shareAllowedHosts: []
  shareMaprootUser: root
  shareMaprootGroup: root
```

> Driver type note: `freenas-api-*` drivers use only the TrueNAS HTTP API key
> (no SSH). If your TrueNAS SCALE version needs the SSH-based `freenas-nfs` /
> `freenas-iscsi` drivers instead, change `driver:` here AND
> `driver.config.driver` in the matching `values-*.yaml`, and add an
> `sshConnection:` block.

## After sync — verify

```bash
oc get pods -n democratic-csi
oc get sc vanillax-local-rwo truenas-nfs-csi
# bind test:
oc create -f - <<'EOF'
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: dcsi-test, namespace: default }
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: vanillax-local-rwo
  resources: { requests: { storage: 1Gi } }
EOF
oc get pvc dcsi-test -n default -w   # expect Bound
```
