# Metaagent on CoreWeave

The webpage is `https://metaagent.cwd1f0-new-cluster.coreweave.app/` and
the authenticated MCP endpoint is the same host at `/mcp`. The application
runs on the Mac so it can inventory local agents and use the existing durable
overseer registry. CoreWeave runs only a dedicated HTTPS/SSH relay.

```text
Browser ── TLS / shared sign-in ──┐
                                ├─ metaagent-relay Caddy
MCP client ── TLS / Bearer ──────┘       │ 127.0.0.1:8768 in relay pod
                                        │ independent reverse SSH tunnel
                                  Mac 127.0.0.1:8768
                                        │
                       existing Hexapod Lab/overseer/overseer.sqlite3
```

The existing camera relay's `PermitListen` allows only ports 8766 and 8767.
This deployment uses its own Deployment, Service, keys, Caddy configuration,
certificate volume and Mac tunnel. Do not edit `camera-relay`, restart Robot
Lab or its tunnel, or run `experiment_lab/deploy/apply-sso.sh` for this rollout.
Installing the HTTP service/tunnel does not schedule reviews or authorize
agent/robot actions. Existing execution owners and shared spending caps remain
authoritative; a dashboard request does not bypass the durable budget store.

## Application prerequisites

Stage the reviewed application in a stable checkout outside Documents and
`/tmp`, for example
`~/Library/Application Support/Hexapod Metaagent/runtime/`. Use that checkout's
own `uv` environment. The service entry point is:

```sh
uv run python -m rl_move.metaagent serve --host 127.0.0.1 --port 8768
```

Configure its environment through the private Mac launcher:

| Name | Value/source |
| --- | --- |
| `METAAGENT_API_TOKEN` | Dedicated random token, read from a private file or Keychain; never put it in a plist, command argument, URL or Git. |
| `HEXAPOD_METAAGENT_DIR` | `$HOME/Library/Application Support/Hexapod Lab/overseer` — the existing directory, retaining `overseer.sqlite3` and its $20/wake and $80/rolling-day caps. |
| `METAAGENT_SSO_SECRET_FILE` | `$HOME/.hexapod/sso_secret` — existing private controller cookie-verification key, mode 0600. |

Do not copy the database or create a second registry for the web service.
Confirm that the service reads the existing history and caps before exposure.
Application authentication must verify signed, unexpired `hexapod_sso` cookies
for an explicit permitted user and verify Bearer credentials itself. The proxy
strips identity headers; `X-Hexapod-User` is never an authentication source.

The controller already issues cookies for
`.cwd1f0-new-cluster.coreweave.app` and accepts this direct-subdomain return
URL; no controller configuration change is needed. The actual Mac key uses
an underscore (`sso_secret`), although an older Lab runbook spells it with a
hyphen. If provisioning after rotation is needed, obtain the current
`/workspace/.sso_secret` from the controller into a private temporary file,
verify it is nonempty, and atomically install it as mode 0600. Never display it.

## Prepare new resources

Run from the reviewed repository root. These assignments contain paths and
resource names only. `D` contains tracked deployment files; `K` is private.

```sh
D="$PWD/hexapod_walker/prototype_sts3215/rl_move/overseer/deploy"
K="$HOME/.hexapod/metaagent-tunnel"
export KUBECONFIG="$HOME/.kube/coreweave.yaml"
umask 077
mkdir -p "$K"
chmod 700 "$K"

# Generate once. Preserve both identities on redeploys.
test -f "$K/id_ed25519" || ssh-keygen -q -t ed25519 -N '' -C metaagent-tunnel -f "$K/id_ed25519"
test -f "$K/ssh_host_ed25519_key" || ssh-keygen -q -t ed25519 -N '' -C metaagent-relay-host -f "$K/ssh_host_ed25519_key"
printf 'restrict,port-forwarding,permitlisten="127.0.0.1:8768" %s\n' "$(cat "$K/id_ed25519.pub")" > "$K/authorized_keys"
printf '[metaagent.cwd1f0-new-cluster.coreweave.app]:2222 %s\n' "$(cat "$K/ssh_host_ed25519_key.pub")" > "$K/known_hosts"
chmod 600 "$K/authorized_keys" "$K/known_hosts"

caddy adapt --config "$D/metaagent.Caddyfile" --adapter caddyfile >/dev/null
sh -n "$D/run-tunnel.sh"
plutil -lint "$D/com.lbiewald.hexapod-metaagent-tunnel.plist"
```

The host key is pinned from the key being provisioned; do not replace this
with `StrictHostKeyChecking=no` or trust an unauthenticated `ssh-keyscan`.
The SSH server permits remote forwarding only to `127.0.0.1:8768` and denies
interactive/command sessions. No service exposes port 8768 directly.

## Deploy the reviewed relay

These commands mutate only new `metaagent-relay*` resources. Run this section
only when executing the reviewed deployment, after local application checks.

```sh
kubectl create secret generic metaagent-relay-ssh \
  --from-file=authorized_keys="$K/authorized_keys" \
  --from-file=ssh_host_ed25519_key="$K/ssh_host_ed25519_key" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap metaagent-relay-caddy \
  --from-file=Caddyfile="$D/metaagent.Caddyfile" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$D/metaagent-relay.yaml"
kubectl rollout status deployment/metaagent-relay --timeout=180s
kubectl get service metaagent-relay
```

The CoreWeave Service annotation creates the `metaagent` hostname. Allow DNS
and certificate issuance to finish. On later Caddy/sshd config changes, their
`subPath` mounts need a rollout of **only** `deployment/metaagent-relay`.
Retain `metaagent-relay-data` so TLS state survives redeploys. The manifest
uses the existing cluster's `shared-vast` storage class and requires no GPU.

## Connect the Mac

First run `"$D/run-tunnel.sh"` in the foreground and verify the new public
routes. It uses a dedicated SSH connection and never attaches to an existing
SSH control socket. To keep only this connection alive afterward:

```sh
M="$HOME/Library/Application Support/Hexapod Metaagent"
mkdir -p "$M" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
install -m 700 "$D/run-tunnel.sh" "$M/run-tunnel.sh"
install -m 600 "$D/com.lbiewald.hexapod-metaagent-tunnel.plist" \
  "$HOME/Library/LaunchAgents/com.lbiewald.hexapod-metaagent-tunnel.plist"
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.lbiewald.hexapod-metaagent-tunnel.plist"
```

Stop the foreground test tunnel before bootstrapping the LaunchAgent; two
connections cannot bind the same relay loopback port. The app's own launcher
is separate and should run only the HTTP server, with no timer or review loop.

## Acceptance and rollback

Verify all of these without launching paid reviews or agent actions:

- The local app reads the same registry/history and spending caps as the CLI.
- Browser `/` redirects to the existing sign-in and returns afterward; a
  valid shared session can view the page. Forged cookies and identity headers
  fail authentication. Invalid Bearer credentials cannot bypass the app gate.
- `/mcp` without a token returns an authentication error, not a sign-in page;
  valid Bearer `initialize` and `tools/list` calls work. Check the server's
  documented read-only tools before invoking any mutation tool.
- `/api/*` retains application authentication. `/healthz` reveals only service
  health, and `/robots.txt` disallows indexing.
- A disconnected new tunnel produces an explicit 503 webpage/API response
  instead of reporting cached agent state as current. The existing camera,
  Robot Lab and RL status endpoints retain their prior behavior.

Use a private curl config or the MCP client's credential facility for tokens;
do not place Bearer values in shell arguments or screenshots. Status-only
public checks can use `curl -s -o /dev/null -w '%{http_code}\n' URL`.

Rollback disconnects only the new tunnel and removes the new public relay:

```sh
launchctl bootout "gui/$(id -u)/com.lbiewald.hexapod-metaagent-tunnel"
kubectl delete service metaagent-relay
kubectl delete deployment metaagent-relay
```

Stop the separate metaagent HTTP service only if needed. Preserve the existing
overseer database, relay keys, ConfigMaps and certificate PVC for investigation
or redeploy. Do not touch Robot Lab's launch jobs or queue state during rollback.

## Installed HTTP launcher

`run-server.sh` reads the dedicated `api-token` file from the private
`~/Library/Application Support/Hexapod Metaagent` directory and starts only the
HTTP process in its stable `runtime` checkout. The checked-in
`com.lbiewald.hexapod-metaagent.plist` keeps that HTTP process available; it has
no review timer or scheduled model call. Install these alongside the independent
tunnel launcher after syncing the runtime's own uv environment.

The private client configuration is `~/.hexapod/metaagent-mcp.json`; keep it
outside Git. Both provider configuration examples are under `../reviewers/`.
The versioned default follows the runtime checkout after deployment; use an
explicit `--reviewer-config` path for a private override after verifying prices,
context limits, and reasoning controls. Manual Claude runs need `ANTHROPIC_API_KEY`; manual Codex
runs need `OPENAI_API_KEY`. The HTTP service needs neither provider credential.

## Recurring reviews

Lukas requested recurring operation on 2026-09-09 after the manual trial. The
separate `com.lbiewald.hexapod-metaagent-scheduler` LaunchAgent invokes a free
deterministic gate every five minutes. Each invocation exits. At most once every
six hours, changed eligible work may request one bounded API review. The timer
does not invoke a Codex/Claude agent CLI to reason about whether it should run.
The old Codex watchdog automations remain paused.

Install `run-scheduler.sh` mode 0700 in the existing Metaagent home and its plist
mode 0600 in `~/Library/LaunchAgents`. The launcher reads a private, owner-only
0600 `reviewer-credentials.json` in Metaagent home, containing the selected
provider's existing API credential under `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.
Never include credentials in plists, Git, shell arguments or logs. This file is
separate from the read-only HTTP service. Credential rotation must update it.

Run in the stable runtime checkout, preserving the original state directory:

```sh
uv run --frozen python -m rl_move.overseer.scheduler configure --enable --provider claude
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.lbiewald.hexapod-metaagent-scheduler.plist"
uv run --frozen python -m rl_move.overseer.scheduler status
launchctl print "gui/$(id -u)/com.lbiewald.hexapod-metaagent-scheduler"
```

The dashboard shows saved enablement and actual last-check evidence separately.
An overdue expected check indicates a sleeping/offline host or missing runner,
not successful supervision. Sources use bounded authenticated reads; unavailable
Codex runtime status or costs stay unknown. Partial coverage can review known
active work, but cannot establish that the whole project is idle.

Idle/unchanged checks and budget waits spend no tokens. Failed/uncertain paid
reviews create a persistent hold, visible on the dashboard. Inspect the original
wake, usage and corrected configuration before explicitly enabling again; never
erase pending reservations or resume a wake automatically. Recommendations and
outbox notifications remain proposals for existing owners.

Disable scheduling without removing the website or history:

```sh
uv run --frozen python -m rl_move.overseer.scheduler configure --disable
launchctl bootout "gui/$(id -u)/com.lbiewald.hexapod-metaagent-scheduler"
```

Initial public acceptance on 2026-09-09 verified HTTPS, existing SSO sign-in,
unauthenticated/forged credential rejection, authenticated status and costs,
and MCP initialization plus tool discovery. The original Robot Lab and camera
relay services were not restarted.
