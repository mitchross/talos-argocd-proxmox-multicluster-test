# LVM Storage (LVMS) — staged for the 4.21 GA reinstall

Red Hat's purpose-built local storage for single-node OpenShift: thin LVM on
the node's **second SSD**, with CSI **snapshots and clones** (the feature
TrueNAS-only SNO lacks, and the prerequisite for ever extending the
VolSync/pvc-plumber backup flow to this cluster). The rc.5
`redhat-operators` catalog did not publish `lvms-operator`; the 4.21 GA
catalog does — this entry stays staged until the reinstall.

## Why an OLM Subscription when this repo avoids OperatorHub

The repo's stance is **GitOps-installed everything, no console-clicked
OperatorHub, no OpenShift GitOps operator**. LVMS (like the NVIDIA certified
operator) ships *only* through OLM — there is no upstream Helm chart — so the
Subscription itself is declared here in Git and installed by our own Argo CD.
That is the same staging pattern as `../gpu-operator/`. Everything with a
viable Helm path (MetalLB, cert-manager, external-dns, truenas-csi, ...) stays
Helm.

## Enable checklist (run AFTER the 4.21 GA reinstall)

1. **Catalog check** — prove the GA catalog publishes the package:

   ```bash
   kubectl get packagemanifests -n openshift-marketplace | grep -i lvms
   ```

2. **Find the second SSD's stable path** (never use /dev/sdX — it can swap
   across reboots):

   ```bash
   NODE="$(kubectl get nodes -o name | head -1)"
   oc debug "$NODE" -- chroot /host lsblk -o NAME,SIZE,TYPE,MODEL,SERIAL,MOUNTPOINTS
   oc debug "$NODE" -- chroot /host ls -l /dev/disk/by-id/
   ```

   Pick the `/dev/disk/by-id/...` entry for the disk that is NOT the install
   disk (no mountpoints). Prefer the `wwn-` or `nvme-`/`ata-` + serial form.

3. **Verify the disk is empty** — LVMS refuses disks with filesystem or
   partition-table signatures:

   ```bash
   oc debug "$NODE" -- chroot /host wipefs /dev/disk/by-id/<the-disk>
   # if it prints signatures and you are SURE the disk is expendable:
   oc debug "$NODE" -- chroot /host wipefs -a /dev/disk/by-id/<the-disk>
   ```

4. **Edit `lvm-storage.yaml`**: replace `CHANGEME-second-ssd` with the by-id
   path.
5. **Flip the marker**: rename `.argocd/config.json.disabled` →
   `.argocd/config.json`, commit, push; the infrastructure AppSet discovers
   it.
6. **Verify**:

   ```bash
   kubectl get lvmcluster -n openshift-storage          # Ready
   kubectl get storageclass lvms-vg1                    # exists, NOT default
   kubectl get volumesnapshotclass | grep lvms          # snapshot support
   ```

## Storage strategy (cluster roles)

| Class | Backing | Use for |
|-------|---------|---------|
| `vanillax-local-rwo` (default) | TrueNAS iSCSI (off-node, Retain) | app data that must survive a node reinstall |
| `lvms-vg1` (this entry) | second SSD, thin LVM, snapshots | model caches, scratch, vector DBs — fast node-local |
| `truenas-nfs-csi` | TrueNAS NFS (RWX) | shared media |

`lvms-vg1` is deliberately **not** the cluster default, and shared app bases
must never name it directly (CI enforces this) — it is a cluster-owned class
referenced only from `clusters/openshift` overlays. Once LVMS is live,
`../local-path-provisioner/` is a retirement candidate (LVMS covers
node-local persistence properly).
