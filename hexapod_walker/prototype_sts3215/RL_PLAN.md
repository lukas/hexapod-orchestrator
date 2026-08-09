# RL Plan — raw-joint policies to hardware candidates

**In plain English:** we're training a walking controller for a real
six-legged robot, in simulation, with an autonomous experiment loop.
The sim robot already walks with all six legs; its feet SLIDE along
the ground while stepping, and that sliding (plus two pending
operator pricing decisions) is what stands between us and putting a
policy on the physical robot. Mission and current status in plain
terms: `rl_docs/GOAL.md`. How to run things: `rl_docs/COMMANDS.md`.

Rev 2026-08-09d (condensed). Full previous plan with all evidence
inline: `archive/RL_PLAN_FULL_2026-08-09.md`. Campaign history:
`RL_LOG.md` (condensed) → `archive/RL_LOG_FULL_2026-08-09.md`.
Binding reviews: `archive/EXTERNAL_REVIEW_2026-08-08.md` (priority
sequence), `archive/BEST_PRACTICES_AUDIT_2026-08-08.md` (PPO
settings), `archive/ARCHITECTURE_REVIEW_2026-08-09.md` (model
ladder), `archive/OPERATOR_RULINGS_2026-08-09.md` (design rulings).
**EDIT RULE: keep this file under ~120 lines — net-zero
edits; move superseded detail to archive, don't accumulate it.**

Big goal: fluid real-world motion on the physical hexapod — walking
above all. Objective (operator, binding): **DISTANCE, STABILITY,
RELIABILITY** — covers real ground, stays level, never falls. Not
speed-band tracking.

## Standing rules (binding)

- One variable per run, off the current champion; pre-register
  gate + if-true/if-false BEFORE launch. Probe smoke (150k–1M)
  before any new mechanism; reward changes get a scale audit.
- Warm starts: ent 0.001, inherited std, `--asym-critic`,
  `--no-canary` on walk-only lineages; canaries ON for multi-skill.
  From-scratch: std 1.0, ent 0.005–0.01, target_kl 0.02. Entropy
  runaway (std climbing) = health alarm.
- Identical-config continuations are CLOSED as a move (0-for-5).
  Auto-continue handles segment stitching; the trailing verdict
  cycle can kill it.
- Video eval is the promotion standard; verdicts pathology-first
  with explicit hardware-ready yes/no. A checkpoint that scores
  well but looks wrong means the metric is the bug. ≥12 eps
  (det+sto), eval at DR 0 AND the run's own DR, 15 s horizon.
  Exploit-watch columns: cadence/stance count, per-leg swing
  asymmetry, allowance-riding, unload-sweep, flag leg.
- Reward routing: GLOBAL = safety/limits/current/smoothness only;
  everything else MODE-SPECIFIC. Walk income terms must make
  parking worth less than stepping BY CONSTRUCTION.
- Launches only via `launch_run.py` (capacity, code-SHA gate,
  ledger). Ledger edits only via `launch_run.py update`.
- When nodes are free and multiple sound one-variable arms exist,
  launch them in parallel — idle pods during deliberation is a
  failure mode.
- ASSUME AND GO (operator, 08-09): a design question with a
  plausible recommendation never idles a pod — adopt it, log
  "## ASSUMPTION (operator to review)", launch. Operator-ONLY
  blockers (hardware) ⇒ idle pods pick up parallel lines (guardrails
  `operator_unblock_policy`): command-steering, QUADRUPED MODE
  (pulled forward), mirror-symmetry, contact-aux head.

## Architecture (settled — do not propose arms outside this)

18 joint targets through SafetyLayer; deployable-only actor obs;
asymmetric critic; 8-frame history MLP. Next rung (post-0-c):
DreamWaQ-style concurrent estimator. NO transformers/CPG unless
the archive review's triggers fire.

## State + current defects (walk)

- **CHAMPION: `ppo_goal_cw_walk_longdist_r2.zip` md5 bcddc65c**
  (30s/narrow-band lineage; DR1.0 det slip 1.06, seed-confirmed by
  longdist-s1 at 0.98; slip ≤1.0 gate still unmet; NOT
  hardware-ready; known flaw: sto stalls on specific command draws,
  DR1.0 sto 3/6 both seeds). Prior: anchorgate 35234ddc (1.240).
- The gait is real (six legs cycling) but transports by **paddling**
  — the sim's optimum under current pricing (cycle 33). Every income
  lever is exhausted (anchor gate −20% then price ceiling, cycle 34);
  **slip root = contact/current pricing = OPERATOR ruling class.**
- Open defects: skating/paddling (slip METRIC now ruled — see
  rulings block; contact/current pricing awaits hardware
  calibration); overspeed + rear-hemisphere RULED (rulings block).
- DR ladder: CLOSED as vacuous (untrained parent passes ≤0.6);
  re-open only if a gait change breaks a DR level the parent passed.
- Stance: heights solved at DR 1.0. Lower line UNBLOCKED for gate +
  support_margin rework per rulings; current-economy arms stay
  blocked until the operator's hardware current calibration.
- Raise: demoted to canary tripwire. No compute.

## Queue

1. **In flight:** never listed here — a static doc can only be
   stale. Live truth: `ops.sh census` (what's training),
   `launch_run.py backlog list` (what's queued),
   `rl_docs/runs/<run>.md` (what each finished run showed).
   Landed verdicts that shape the plan: stepdisp12 + loadslip both
   FAIL/refuted → the walk-reward income side is CLOSED (slip root
   = sim contact/current pricing, operator calibration class),
   pending only the loadslip-s1 seed concordance.
2. **0-c objective arms, in order, one variable each:**
   (i) STABILITY: price |roll|+|pitch| beyond allowance + terminal
   fall charge; fold overspeed pricing in if it's the root cause.
   Gate: 12/12 det+sto zero terminations, gait_valid.
   (ii) DISTANCE: LANDED (longdist 30s narrow-band → champion,
   cycle 44). (iii) RELIABILITY: 12/12 per DR rung + low variance —
   open front: draw-specific sto stalls (both seeds, DR1.0 3/6).
3. Mirror-symmetry augmentation (needs its own implementation
   cycle: mirror index maps + trainer support + probe).
4. Contact-from-proprioception aux head; dense step-decomposition
   and model-size sweep last.

OPERATOR RULINGS 2026-08-09 (BINDING — read
`archive/OPERATOR_RULINGS_2026-08-09.md` before stance/gate work):
(1) 60 mm allowance RETIRED → reference-relative end-state error,
interim cap 25–30 mm, under-reference NOT free; (2) support_margin
= stability backstop only — six-foot end state must out-earn any
hover; (3) stance current economics BLOCKED until the operator's
hardware calibration (2.6 A ≈ stall-scale; hardware = OPERATOR-ONLY);
(4) rear hemisphere DEFERRED — gates draw forward/fwd-diag only;
(5) 0.40 m gate RETIRED → progress_ratio vs commanded displacement,
pass 0.75–1.25; prefer narrow forward band + direct distance gate;
(6) loaded slip accumulates episode-long, NEVER reset by touchdown
(loaded foot-XY travel per meter = primary skating metric);
(7) promotion = multi-seed panels + named corners; fixed panel =
regression canary only.

## Party tricks (operator vision, 08-09)

QUADRUPED is PULLED FORWARD (operator, 08-09): an authorized
parallel line whenever main-line arms can't fill the GPU pods.
Fall recovery still waits for 0-c. (1) **FALL RECOVERY** — fallen
poses become the start distribution; gate "regain stance and hold,
12/12, under DR"; needs orientation-complete obs + fallen-pose
reset generator + hard current pricing (quiet self-righting, no
thrashing — 2026-08-06 incident). (2) **QUADRUPED MODE** — stand/
walk on four rear legs, fronts free as claws: static stance →
weight-shift under DR → quadruped walk. Full design sketches in
`archive/RL_PLAN_FULL_2026-08-09.md`.

## Done =

One policy (or per-skill champion set) that from stance: holds
quietly, lowers/rises on command, walks forward with real
alternating contacts and balanced currents — passing visual eval +
the hardware-candidate gate (full checklist in the archived plan:
20-ep evals, current limits, noise robustness, frozen-policy mass
eval). Then freeze and begin supported sim-to-real validation.
