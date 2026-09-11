# Metaagent

Metaagent inventories project agents, checks progress and spending, and writes
an evidence-based review with proposed actions. Recurring reviews are explicitly
opt-in through the deterministic scheduler below. Importing the package does nothing. A preview never invokes a model,
creates/updates a registry, sends a message, or changes a worker/service/queue.

Run from `hexapod_walker/prototype_sts3215`:

```sh
uv run python -m rl_move.metaagent preview
uv run python -m rl_move.metaagent status
```

Reports are Markdown plus JSON under repository-root `artifacts/metaagent/`.
`--output DIR` selects another destination. JSON retains bounded historical job
records; the Markdown groups inactive history so it cannot look like hundreds of
running agents. These local reports are private operational data; do not commit
them by default.

## Current source coverage

- Claude: live process identity, session metadata and a bounded transcript tail.
  An alive idle CLI is not a running reasoning job. No full prompts are exported.
- Codex: a fresh authenticated `list_threads` export. A child agent should register
  its own stable ID and parent/task IDs because the app listing does not expose
  every internal child. App usage percentages are not per-task dollar costs.
- Robot Lab: read-only legacy queue history plus Robot Lab v2 plan/run counts,
  recent wall times, hypotheses, findings, spend, events and its 10/60/120/900
  second timing contract. A historical run is evidence, not a live worker.
- Cloud RL: a fresh authenticated `orchestrator_activity` export. Active cycles
  and watcher liveness are separate; old zombie records are not active cycles.
  A broken status poll means trainer status may need independent verification.
- RL strategy: bounded public excerpts from `/llm/brief.md` and `/llm/runs.md`
  supply the campaign hypotheses, run families and outcomes needed to distinguish
  useful replication from low-information repetition. They are read-only data.
- Canonical goals and accepted evidence: bounded excerpts from `RL_GOALS.md`,
  `STATUS.md`, `CURRENT_TRUTHS.md`, and the Robot Lab v2 design/history README.
  Operational liveness never proves walking.

The CLI deliberately does not scrape app databases or extract credentials to
make cloud calls. Use the project's authenticated MCP tools, or its documented
JSON-RPC fallback, and save each result in this envelope:

```json
{"collected_at":"2026-09-09T04:00:00Z","data":{"content":[{"type":"text","text":"tool response"}]}}
```

```sh
uv run python -m rl_move.metaagent preview \
  --codex-threads /private/path/codex.json \
  --cloud-activity /private/path/cloud.json \
  --strategy-evidence /private/path/strategy.json \
  --self-agent codex:THIS_OVERSEER_THREAD_ID
```

Use the actual collection timestamp, not the time a saved file is replayed.
Missing/stale sources are disclosed. `--snapshot FILE` uses an already normalized
snapshot instead of local discovery, useful for reproducible tests. Preview reads
existing overseer state in SQLite read-only mode. Its only writes are reports.

## Registration and progress checkpoints

Discovery gives visibility; explicit registration gives ownership and purpose.
Register a logical task and its children with a shared `task_id`, distinct
`agent_id`, and the actual execution owner. Do not invent dollar costs from a
token sample or treat a registered resource name as authority to control hardware.

```json
{
  "agent_id":"claude:SESSION_ID",
  "task_id":"hexapod:joystick-demo",
  "parent_id":null,
  "name":"Joystick simulation delivery",
  "provider":"claude",
  "execution_owner":"interactive session owner",
  "scope":"simulation",
  "goals":["any_means"],
  "status":"running",
  "cost_status":"unknown"
}
```

```sh
uv run python -m rl_move.metaagent register /private/path/agent.json
uv run python -m rl_move.metaagent heartbeat claude:SESSION_ID /private/path/checkpoint.json
```

At a meaningful checkpoint, supply `status`, `last_progress_at`,
`progress_evidence` (artifact/commit/run references) and `assessment`:
`progress`, `evidence`, `decision` (`continue`, `change`, `stop`), `next_step`.
Ask: did this close a gap in either walking goal; what evidence changed; is a
different approach better; what is the next bounded step? A heartbeat or a log
write alone must not advance `last_progress_at`. Mark termination/idle explicitly.

`any_means` permits scripted/assisted walking. `rl_only` permits no demonstrations
anywhere in training ancestry. Both require a named interactive joystick sim,
video and reproducible launch, and independent physical walking evidence.

Report nonoverlapping cost increments with immutable event IDs:

```sh
uv run python -m rl_move.metaagent spend claude:SESSION_ID PROVIDER_REQUEST_ID 1.25 \
  --occurred-at 2026-09-09T04:00:00Z --source provider-usage-receipt
```

Replaying an identical receipt is harmless; changing it under the same ID fails.
Parent totals must exclude separately recorded child costs. The $100 threshold
aggregates unreviewed receipts across a logical task. Existing Claude/Codex
sessions often have **unknown** dollar coverage; their $100 triggers cannot be
guaranteed until their launchers/providers submit complete receipts. Discovery
does not silently convert lifetime cost snapshots into repeated new charges.

## Wake and action policy

The pure policy requests a review for changed project portfolio evidence or
fresh active work due at six hours, at least $100 unreviewed task spending, or a
new persistent failure/ownership issue.
It exits without a model call when nothing qualifies. An unchanged blocked
state does not purchase another review just because the timer fires. Overseer
work and descendants marked `is_overseer`/`overseer_wake_id` cannot trigger
themselves. A resolved incident can recur as a new episode.

Elapsed time, repeated commands and idle GPUs alone do not prove a loop. A stop
proposal requires repeated same-operation failures, unchanged progress, and no
progressing children; the execution owner must verify the evidence and preserve
useful trainers/checkpoints. Paused/disabled desired state survives recovery.
Authentication incidents use only bounded documented recovery, then one
actionable notification when help is needed. Credential values stay private.

This version is an advisory review and handoff system. Stop, repair and automation
engineering actions are **proposals**, not executed commands. Existing owners
(cloud controller, interactive task owner, guarded Robot Lab runner) remain the
only execution paths. There is no generic kill/restart executor, queue resume,
model-generated shell command, or physical-control adapter. Robot Lab checks its
durable hardware pause at engineering admission and launch, and revokes active
attempts when their pause/lease/cancellation state changes. Any future automated
handoff must continue through that existing owner. Nothing in this tool activates it.

## Durable reviews and notifications

`review` saves a wake, report and action outbox; by default it is still a
deterministic review with no model charge. `--force` requests a manual review
even if no trigger qualifies. Preview does not alter review/notification history.

```sh
uv run python -m rl_move.metaagent review --force
uv run python -m rl_move.metaagent actions
uv run python -m rl_move.metaagent acknowledge INCIDENT_ID /private/path/owner-receipt.json
uv run python -m rl_move.metaagent notify INCIDENT_ID --recipient EXPLICIT_IMESSAGE_ADDRESS
```

The owner receipt requires `owner`, `evidence` and `outcome` (`resolved`,
`needs_attention`, `declined`). `notify` is an explicit manual iMessage send on
macOS, never called by preview/review. It claims the incident before dispatch;
uncertain submission stays claimed and is not retried blindly. Submitted means
accepted by Messages, not confirmed delivery. Recovery messages are separately
queued after an owner confirms resolution of a previously submitted alert.

Deterministic reviews do not acknowledge cost receipts. A completed bounded
model review can acknowledge the task receipts captured when the wake started.
For an actual human review, use `acknowledge-review RECEIPT.json` with `owner`,
`evidence`, `reviewed_agent_ids` and `review_seq` (the snapshot's
`unreviewed_through_seq`); never clear costs just to reset a threshold.

## $20 per wake, $80 per rolling day

Runtime state is separate from the controller-owned `.state` repo:
`~/Library/Application Support/Hexapod Lab/overseer/overseer.sqlite3` on macOS,
or `$XDG_STATE_HOME/hexapod-overseer` on Linux. `HEXAPOD_METAAGENT_DIR` (preferred), `HEXAPOD_OVERSEER_DIR` (compatible), or
the global `--state-dir DIR` overrides this for tests. Every reviewer and child
must use the same durable database and `wake_id`; separate databases do not
share a cap. There is one active wake. Never change state paths to escape a cap.

The optional reviewer makes one bounded, tool-free call using either Claude
(Anthropic Messages API) or Codex (OpenAI Responses API):

```sh
uv run python -m rl_move.metaagent review --force \
  --reviewer-config /private/path/verified-reviewer.json
```

After a blocked attempt, an explicit manual continuation can use the remaining
budget of that **same wake**:

```sh
uv run python -m rl_move.metaagent review --resume-wake WAKE_ID \
  --reviewer-config /private/path/verified-reviewer.json
```

This makes at most one new call, with a new operation ID. It never replays the
timed-out request, creates another wake, refunds an uncertain charge, or schedules
a retry. Only a finished `blocked` wake can resume, with no other active wake.
The original start time, reason, receipt cutoff and all reservations survive.
Continuation is rejected once cumulative charges reach the $15 wrap-up threshold;
every new reservation still has to fit the $20 wake and $80 rolling-day caps.
Choose an explicitly verified reviewer whose maximum reservation fits the
remaining budget. An active wake requires inspection and explicit `finish-wake`
before continuation; a successful wake cannot resume.

Each continuation has an immutable report identified by its new operation ID;
`wake.wake_id` continues to identify the original wake. Its `prior_attempts` lists
earlier report IDs, timestamps, outcomes and model results, and the earlier full
reports remain stored. `budget.additional_model_cost_usd` counts this invocation;
`budget.wake_charged_usd` includes previous attempts and uncertain reservations.
Receipt acknowledgement after success retains the original wake's cutoff, so
spending that arrived later remains due for a future review.

`ReviewConfig` requires an explicit model, `input_usd_per_million`,
`output_usd_per_million`, `model_context_tokens`, `pricing_verified:true`, and a
`pricing_reference`. Verify the model's enforced context and the **highest
applicable rates**, including long-context/cache premiums. Choose `provider: "claude"` with `ANTHROPIC_API_KEY`, or `provider: "codex"`
with `OPENAI_API_KEY`. Credentials never belong in config or reports. These
are bounded model API backends, so they cannot run unrestricted CLI tools. No default price is
guessed. Output defaults to 2048 tokens, timeout 45 seconds, no retries or tools.
Codex counts reasoning tokens inside its output limit. Optional explicit
`cached_input_usd_per_million` and `cache_write_usd_per_million` record those
usage categories; reservations use the highest applicable input rate.

Claude requests schema-constrained JSON through `output_config.format`; the
local validator still checks every response before accepting advice. Invalid
paid responses retain their usage, provider response ID when available, and a
bounded, redacted excerpt of visible text for private diagnosis. Reasoning and
tool inputs are not retained in that excerpt. This permits inspection without
buying the same model work again. Current Claude profiles allow 180 seconds for
one response; the configurable maximum is 300 seconds, with no automatic retry.

Before dispatch, reserve the full context at the supplied maximum input rate
plus bounded output. This conservative admission cap depends on those provider
limits/rates being correct; it is not a provider-enforced invoice cap. At $15,
begin wrapping up; no new investigation calls. All review/subreview reservations
share the $20 total and $80 rolling-day allowance. Operational engineering
proposals cannot launch uncapped agent CLIs under the label of a bounded review.

Crashes/timeouts keep the entire reservation charged, even beyond 24 hours,
until actual usage is reconciled. Duplicate operation IDs never authorize
another call. Known charges use rolling 24-hour settlement time. Actual overruns
are recorded, never clamped away. Inspect `reconcile-cost OPERATION_ID AMOUNT`
only with an actual usage receipt; `finish-wake ID --outcome blocked` closes an
abandoned wake without refunding uncertain operations. The coding conversation
that builds this package is outside these future runtime reservations.

## Validation

```sh
uv run pytest rl_move/tests/test_overseer_*.py
```

Tests use fixtures and mocked providers/senders. They cover atomic concurrent
budgets, restarts, duplicate requests, unknown billing, idle exits, source
freshness, pause preservation, recurrence, logical-task costs, and preview
side-effect boundaries. They do not send messages or run robot motion.

## Dashboard and authenticated MCP

The CoreWeave dashboard is
<https://metaagent.cwd1f0-new-cluster.coreweave.app/>. It displays saved run
history, each review's provider/model, settled actual cost, uncertain cost
reservations, strategic assessments, recommendations, goal assessments and
missing cost coverage.
The website reads the same durable database as manual reviews. Page refreshes
and MCP reads never run a model. The separate timer runs only when explicitly enabled.

The MCP endpoint is `/mcp` on that host. Use a Metaagent bearer credential;
the browser uses the existing Hexapod SSO cookie or an explicit token sign-in.
Read tools expose status, runs, cost accounting and recommendations. Operator
tools register agents, record progress checkpoints and submit immutable cost
receipts. They do not execute recommendations or expose arbitrary commands.

Start the local data service with:

```sh
uv run python -m rl_move.metaagent serve --host 127.0.0.1 --port 8768
```

Choose a backend for one manual run. Versioned provider defaults live in
`reviewers/claude.json` and `reviewers/codex.json`; pass `--reviewer-config`
to use an operator-managed override:

The supplied Claude default uses Fable 5.1 with adaptive thinking for project
follow-through. Its bounded worst-case reservation remains below the $15
wrap-up threshold. `reviewers/claude-sonnet.json` retains the lower-cost Sonnet
5 option, and
`reviewers/claude-opus.json` retains the Opus 5 option; select it explicitly with
`--reviewer-config` when needed. Neither profile can bypass the shared budget.

```sh
uv run python -m rl_move.metaagent review --force --provider claude
uv run python -m rl_move.metaagent review --force --provider codex
```

Alternatively pass an explicit `--reviewer-config` file, optionally with
`--provider` to require a matching provider. Example verified configuration
shapes are in `reviewers/`; reverify rates, context limits, and reasoning
controls before using them.
Both providers and every child share the same original `overseer.sqlite3`.
The legacy CLI and internal `is_overseer`/`overseer_wake_id` fields remain
compatible; renaming does not reset budget, registry or action history.

See [deployment instructions](deploy/README.md) for the dedicated CoreWeave
relay and Mac services. These services keep the webpage reachable; they do
not wake the reviewer or enable Robot Lab/robot execution.

## Recurring reviews and retained context

The separate deterministic timer is opt-in. It checks every five minutes,
exits when idle or unchanged, and admits at most one paid review per six hours.
The policy still requires changed RL/Robot Lab portfolio evidence, fresh eligible
activity, new task spending of at least $100, or a new supported incident. A
failed/interrupted paid attempt holds future
paid reviews for operator inspection. All calls use the original $20/wake,
$15 wrap-up and $80/rolling-day ledger, including unknown reservations. There is
no automatic continuation, worker control or model-generated command execution.

```sh
uv run python -m rl_move.overseer.scheduler configure --enable --provider claude
uv run python -m rl_move.overseer.scheduler tick
uv run python -m rl_move.overseer.scheduler status
uv run python -m rl_move.overseer.scheduler configure --disable
```

`configure` changes the saved setting; installing the operating system timer is
separate. See [deployment instructions](deploy/README.md#recurring-reviews).
The dashboard/MCP show enablement, last/expected-next check, free checks and paid
attempts. Missing source coverage and overdue checks are not evidence of idleness.

Future reviewers receive bounded prior successful reviews, their three required
strategy assessments, and explicit saved lessons. Historical model recommendations remain hypotheses; owner corrections
have separate provenance and never rewrite old reports. This is retained context,
not model training or autonomous rule changes. `memory` reads the saved context;
`remember-lesson FILE.json` records an explicit operator lesson. The website's
`/api/memory` and MCP `get_memory` are read-only views of that same context.
