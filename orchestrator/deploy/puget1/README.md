# GCP controller and Puget1 worker

This replaces the CoreWeave controller and sixteen-worker configuration.
The public controller runs at `https://rl.l2k.dev` on GKE `l2k-services`
(`l2k-infra-2026`, `us-west1-a`, namespace `l2k`). Training is queued onto
one RTX 5090 in `default/hexapod-mjx-train-puget1` on Puget1. Guardrails,
not the number of historical ledger pods, select the current worker.

## Worker

`setup-node.sh` is a one-time, root installation for Puget1, not a general
installer. It refuses an existing K3s configuration and a different Tailnet
IP. It preserves the installed NVIDIA driver. The API binds only to
`100.102.65.120:6443`; it is not exposed on the public Internet or LAN.

Place the manifests at `/home/user/hexapod-migration`, run setup with sudo,
then apply `state-mirror.yaml` and `controller-access.yaml` with the local
admin credentials. Copy `runtime/` to `/srv/hexapod/worker/runtime/` and the
explicit trainer code revision to `/srv/hexapod/worker/prototype_sts3215/`,
including its `.code_sha`. Apply `worker.yaml`. Do not substitute a different
MuJoCo version or a CPU backend when its GPU startup check fails.

The training environment has its own `pyproject.toml` and `uv.lock` because
workers receive only the prototype tree, independently of the whole subject
checkout. It pins the tested CUDA stack. The workspace is host storage at
`/srv/hexapod/worker`; deleting the Pod retains it. The runtime-state mirror
uses the retained local `hexapod-state` PV at `/srv/hexapod/state`.

The controller credential grants node/pod reads, pod logs and pod exec. It
cannot create Pods, change the cluster or read Secrets. Pod exec can access
the worker's filesystem and credentials, so keep the kubeconfig private.
Keep the separate admin kubeconfig on the operator machine.

## Controller

The existing `l2k/controller-workspace` 1 TiB PVC holds both checkouts,
research state, saved policies, service secrets and Tailscale node state.
It is a retained GCP Persistent Disk with the infrastructure snapshot policy.
No GCP service-account token is mounted into the controller.

For migration apply `gcp-migration-stage.yaml`. Authorize `l2k-controller`
in the existing Tailnet, with incoming connections blocked and routes/DNS
disabled. Its userspace daemon supplies the local HTTP CONNECT proxy
`127.0.0.1:1055`. The limited worker kubeconfig must specify this `proxy-url`.
Do not run two Tailscale daemons against the same saved state.

Restore the controller's verified workspace and state archives before
startup, preserving `/workspace/hexapod` and `/workspace/hexapod-orchestrator`.
Keep all migration holds (`PAUSE`, `WRAPUP`, `LAUNCH_HOLD`) set until cutover.
Place the original service files at their existing paths:

- `/workspace/.sso_secret`, `.lab_login.json`, `.status_token`, `.mcp_key`
- `/workspace/controller-private/orchestrator.env` and `.git-credentials`
- `/workspace/hexapod/hexapod_walker/prototype_sts3215/rl_move/sim/wandb.env`
- `/workspace/.kube/puget1.yaml` (limited worker credential with proxy)
- `/workspace/hexapod/.state/pod_torch_capability.json` (verified new worker)

Private directories use mode 700 and credential files mode 600. No credential
is part of a ConfigMap or Git. The startup script refuses missing files,
reuses existing API credentials, overrides retired cluster/runtime settings,
and synchronizes each checkout from its lockfile. It installs the same Claude
Code version as the source controller. It does not reset login passwords,
MCP keys or research history. The sanctioned restart script also handles
container shutdown with `--stop`, allowing in-flight cycles to wrap up.
Remove the temporary CoreWeave kubeconfig and credential-transfer bundle
from Cloud Shell and the staging directory after copying and verifying the
backups. Keep only the service credentials and limited Puget1 worker config.

Delete the staging Pod, then apply this directory with `kubectl apply -k`.
Its shared Ingress contains both BuildViz and RL routes and certificates.
Per-app manifests must not redefine that Ingress. Verify:

1. `kubectl get nodes` through the worker credential reports Puget1 only;
   the worker is Ready and `capacity.py` reports one GPU slot.
2. State counts and archive hashes match the source; checkpoints open.
3. `/login` works, unauthenticated private pages redirect to sign-in, `/mcp`
   refuses missing/wrong keys, and the existing key still works.
4. Both GCP managed certificates are Active and the RL backend is healthy.
5. Switch BuildViz's login authority to `hexapod-controller.l2k.svc.cluster.local`
   with its GCP manifest, then verify browser and API authentication again.

The cookie domain is `.l2k.dev`. The explicit redirect allowlist also admits
the old lab domain during compatibility, preserving camera/metaagent sign-in.

## Cutover and retention

Archive every old ephemeral controller/worker workspace before deleting its
Pod. Exclude only regenerable environments and caches. Verify successful tar
exit, archive size and SHA-256 at the destination. Do not mistake a partial
transfer or a second copy on the same ephemeral Pod for a backup. Keep the
originals until the restored GCP disk has a fresh snapshot. Check free disk
space before restoring or retaining another archive.

The compatibility proxy in `coreweave-legacy-proxy.yaml` uses the existing
`hexapod-state` PVC subdirectory `controller-legacy-caddy`, populated with the
old `/workspace/.caddy` TLS storage. Stage it with the old kubeconfig and
wait for readiness. Only then patch Service `hexapod-status` to selector
`app: hexapod-status-legacy`. Verify old-host MCP and authentication before
removing `hexapod-sweep-friction`. The manifest deliberately omits the Service
so staging cannot change traffic. Remove the proxy once all clients and lab
relays use the new authority.

Release the GCP hold flags after validation; never release the old controller.
The separate vision GPU servers and camera/metaagent relays are not part of
this controller/worker manifest and require their own migration before the
CoreWeave account is fully decommissioned.

## Operator commands

Worker commands default to `~/.kube/puget1.yaml`; `KUBECONFIG` overrides it.
Operator commands that execute on the GCP controller use
`HEXAPOD_CONTROLLER_KUBECONFIG` (default `~/.kube/gcp.yaml`), namespace `l2k`
and target `deploy/hexapod-controller`. Set up that separate GCP config with
normal `gcloud container clusters get-credentials` authentication. Do not
export a Cloud Shell session token to a laptop.

MCP remains the preferred operator interface. A local `state_sync.sh pull`
using the worker config can read the Puget1 state mirror; a live GCP-controller
read requires its separate controller credentials. Daily disk snapshots and
the Puget1 state mirror complement each other; neither includes the other
machine's whole disk.
