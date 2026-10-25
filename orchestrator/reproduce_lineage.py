#!/usr/bin/env python3
"""Reproduce an exported checkpoint ancestry on one worker, without research cycles.

The plan and progress live outside Git. Training still goes through launch_run;
historical intermediate behavioral failures are not acquisition stop rules.
Only new checkpoints may initialize descendants. Frozen champions are eval only.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time

import launch_run
import state_dir
from roots import HEXAPOD_REPO, PROTO, STATE_DIR

HERE = Path(__file__).resolve().parent
POLICIES = "rl_move/sim/policies"
POD_ROOT = "/workspace/prototype_sts3215"


def command(argv, **kwargs):
    return subprocess.run([str(a) for a in argv], check=True, text=True,
                          **kwargs)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def stages(plan):
    """Validate the ancestry before allowing any placement or code mutation."""
    seen = set()
    result = []
    prefix = plan["prefix"]
    if not re.fullmatch(r"cw-[a-z0-9-]+", prefix):
        raise ValueError("prefix must be a cw- experiment name")
    for role, names in plan["roles"].items():
        if role not in {"stance", "walk", "turn", "lower"}:
            raise ValueError(f"unknown role: {role}")
        for index, name in enumerate(names, 1):
            source = plan["stages"][name]
            if name in seen or not re.fullmatch(r"[0-9a-f]{40}", source["source_code_sha"]):
                raise ValueError("duplicate stage or invalid source commit")
            args = source["argv"]
            if not all(isinstance(a, str) for a in args):
                raise ValueError("trainer argv must contain strings")
            init = option(args, "--init-from")
            parent = source.get("initialization_run")
            if bool(init) != bool(parent) or (parent and parent not in names[:index-1]):
                raise ValueError(f"external or forward initialization: {name}")
            if init and Path(init).name != plan["stages"][parent]["checkpoint_out"] + ".zip":
                raise ValueError(f"initialization artifact disagrees with parent: {name}")
            if int(option(args, "--steps")) != source["steps"] or source["steps"] <= 0:
                raise ValueError(f"step budget disagrees: {name}")
            if any(a.startswith(("--bc-", "--teacher", "--amp-")) for a in args):
                raise ValueError("this runner requires RL-only recipes")
            run = f"{prefix}-{role}-{index:02}"
            result.append(dict(source, original=name, role=role, run=run,
                               output="ppo_goal_" + run.replace("-", "_")))
            seen.add(name)
    if len(seen) != len(plan["stages"]):
        raise ValueError("plan contains unreferenced stages")
    return result


def option(args, key):
    return args[args.index(key) + 1] if key in args else None


def training_args(stage, outputs):
    args, result, i = stage["argv"], [], 0
    owned = {"--run-name", "--steps", "--out-name", "--notes", "--host-workers", "--init-from"}
    while i < len(args):
        if args[i] in owned:
            i += 2
        elif args[i] in {"--defer-final-artifacts", "--no-defer-final-artifacts"}:
            i += 1
        else:
            result.append(args[i])
            i += 1
    result += ["--host-workers", "12", "--out-name", stage["output"],
               "--notes", f"Fresh Puget reproduction of {stage['original']}; "
               f"source {stage['source_code_sha']}; only reproduced ancestors used. "
               "Post-training artifacts drain cooperatively: Puget AppArmor blocks "
               "the deferred worker's terminate signal; learning settings are preserved."]
    parent = stage.get("initialization_run")
    if parent:
        result += ["--init-from", f"{POLICIES}/{outputs[parent]}.zip"]
    # No security relaxation or trainer patch: the ordinary completion path
    # drains results and sends the worker its existing queue sentinel.
    result.append("--no-defer-final-artifacts")
    return result


def evaluation_args(models):
    args = []
    for role, path in models.items():
        args += ["--" + role, path]
    # The harness infers thermal derating only for its exact default relative
    # filename. Both restored references and new checkpoints have other paths.
    return [*args, "--walk-recipe", "slew_smooth_s0", "--rot60",
            "--lower-cfg", "motor.thermal_derate_enable=1",
            "--lower-cfg", "motor.thermal_derate_max_frac=0.5"]


def report_shell(args, log, report, validation, python="/workspace/runtime/.venv/bin/python"):
    """Behavioral misses are results; missing output is an execution failure."""
    quoted = shlex.quote(report)
    previous = shlex.quote(report + ".previous-" + str(time.time_ns()))
    return (f"if test -f {quoted}; then mv {quoted} {previous}; fi; " +
            shlex.join(args) + " > " + shlex.quote(log) + " 2>&1; " +
            shlex.join([python, "-c", validation]))


def ledger_entry(run):
    return next((e for e in reversed(state_dir.load_ledger()) if e.get("run") == run), None)


def update(run, **fields):
    args = [sys.executable, HERE / "launch_run.py", "update", "--run", run]
    for key, value in fields.items():
        args += ["--set", f"{key}={json.dumps(value)}"]
    command(args)


def sync_source(pod, sha, worker_root):
    active = launch_run.pod_trainers(pod)
    if active:
        raise RuntimeError(f"cannot replace training code while processes run: {active}")
    dirty = subprocess.check_output(
        ["git", "-C", str(HEXAPOD_REPO), "status", "--porcelain", "--untracked-files=no"], text=True)
    if dirty:
        raise RuntimeError("runtime source checkout has tracked modifications; inspect before retrying")
    def tracked(revision):
        listing = subprocess.check_output(["git", "-C", str(HEXAPOD_REPO),
            "ls-tree", "-r", "-z", revision + ":hexapod_walker/prototype_sts3215"])
        names = set()
        for item in listing.split(b"\0"):
            if not item:
                continue
            header, name = item.split(b"\t", 1)
            path = name.decode()
            # Gitlinks and runtime output are never deployed as source files.
            if b" blob " in header and not any(part in {
                    ".venv", "__pycache__", "wandb", "logs", "policies", "wandb.env"
                    } for part in Path(path).parts):
                names.add(path)
        return names

    previous = (worker_root / ".code_sha").read_text().strip()
    before, after = tracked(previous), tracked(sha)
    command(["git", "-C", HEXAPOD_REPO, "switch", "--detach", sha])
    # Only retire files known to belong to the previous Git snapshot. Broad
    # rsync --delete can erase training output at an unexpected runtime path.
    for name in before - after:
        target = worker_root / name
        if not target.parent.resolve().is_relative_to(worker_root.resolve()):
            raise RuntimeError(f"source removal escapes worker directory: {name}")
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.exists():
            raise RuntimeError(f"expected old source file, found directory: {name}")
    with tempfile.TemporaryDirectory(prefix="hexapod-source-") as temporary:
        manifest = Path(temporary) / "files"
        manifest.write_bytes(b"\0".join(p.encode() for p in sorted(after)) + b"\0")
        command(["rsync", "-a", "--from0", "--files-from=" + str(manifest),
                 str(PROTO) + "/", str(worker_root) + "/"])
    (worker_root / ".code_sha").write_text(sha + "\n")


def completion(log, steps, checkpoint):
    """A checkpoint alone may be a periodic/early-abort save, not completion."""
    if not re.search(r"\[mjx-train\] done:?\s+" + f"{steps:,}" + r"\s+steps", log):
        # Older trainers omit thousands separators.
        if not re.search(r"\[mjx-train\] done:?\s+" + str(steps) + r"\s+steps", log):
            if not (checkpoint.get("marker_verified") and
                    checkpoint.get("artifact_phase") == "evaluated"):
                raise RuntimeError("trainer exited without a full-budget completion line or verified, finalized marker")
    if not checkpoint.get("finite") or checkpoint.get("timesteps", 0) < steps:
        raise RuntimeError("checkpoint is nonfinite or has fewer timesteps than requested")


def inspect_checkpoint(pod, output):
    # Read tensor data only. Do not unpickle the checkpoint's Python objects.
    script = f"""import hashlib,io,json,zipfile,torch
p={str(Path(POD_ROOT) / POLICIES / (output + '.zip'))!r}
with zipfile.ZipFile(p) as z:
 assert z.testzip() is None
 data=json.loads(z.read('data'))
 tensors=torch.load(io.BytesIO(z.read('policy.pth')),map_location='cpu',weights_only=True)
 result=dict(sha256=hashlib.sha256(open(p,'rb').read()).hexdigest(),
   timesteps=data.get('num_timesteps',0),finite=all(bool(torch.isfinite(t).all()) for t in tensors.values()),
   tensors=len(tensors))
from pathlib import Path
marker=Path(p).with_suffix('.training_complete.json')
if marker.exists():
 m=json.loads(marker.read_text())
 result['marker_verified']=(m.get('schema')==1 and m.get('checkpoint_path')==p and
  m.get('checkpoint_md5')==hashlib.md5(open(p,'rb').read()).hexdigest() and
  m.get('steps')==result['timesteps'] and m.get('run_name')=={output.removeprefix('ppo_goal_').replace('_', '-')!r})
 state=Path(p).parent/'artifact_handoff'/m['run_name']/'state.json'
 if state.exists():result['artifact_phase']=json.loads(state.read_text()).get('phase')
print(json.dumps(result))
"""
    return json.loads(launch_run.kexec(pod, "/workspace/runtime/.venv/bin/python - <<'PY'\n" + script + "PY", timeout=180))


def wait_for_stage(pod, stage, entry):
    run = stage["run"]
    checked = bool(entry.get("reproduction_checkup"))
    started = time.monotonic()
    while True:
        active = launch_run.pod_trainers(pod)
        if run not in active and run + "+finalizer" not in active:
            break
        if not checked and run in active and time.monotonic() - started >= 300:
            command([sys.executable, HERE / "launch_run.py", "checkup", "--run", run])
            update(run, reproduction_checkup=True)
            checked = True
        time.sleep(30)
    path = shlex.quote(f"/tmp/train_{run}.log")
    log = launch_run.kexec(pod, f"if test -f {path}; then tail -c 40000 {path}; fi")
    checkpoint = inspect_checkpoint(pod, stage["output"])
    completion(log, stage["steps"], checkpoint)
    update(run, status="FINISHED", checkpoint_sha256=checkpoint["sha256"],
           reproduction_checkpoint=checkpoint, hardware_ready=False,
           reproduction_of=stage["original"],
           note="Full requested optimization budget completed; behavioral comparison pending. "
                "Historical intermediate behavior is not an early-stop rule.")
    return checkpoint


def evaluate(plan, pipeline, progress, progress_path):
    spec = plan["evaluation"]
    pod = plan["pod"]
    sync_source(pod, spec["source_sha"], Path(plan["worker_root"]))
    outputs = {s["original"]: s["output"] for s in pipeline}
    new = {role: f"{POD_ROOT}/{POLICIES}/{outputs[target]}.zip" for role, target in plan["targets"].items()}
    ref = {}
    for role, item in spec["references"].items():
        path = Path(item["host_path"])
        if hashlib.file_digest(path.open("rb"), "sha256").hexdigest() != item["sha256"]:
            raise RuntimeError(f"frozen reference checksum mismatch: {role}")
        ref[role] = item["pod_path"]
    destination = spec["pod_output"]
    launch_run.kexec(pod, "mkdir -p " + shlex.quote(destination))
    evaluations = progress.setdefault("evaluations", {})

    def one(label, models, heading):
        name = f"{label}-{heading:03}"
        report = f"{destination}/{name}.json"
        args = ["/workspace/runtime/.venv/bin/python", "-m", "rl_move.sim.eval_lifecycle_full_rlonly"]
        args += [*evaluation_args(models), "--episodes", "20",
                 "--heading-deg", str(heading), "--seed", "0", "--out", report]
        shell = f"cd {POD_ROOT}; export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl; "
        # The harness exits nonzero for behavioral misses; require its report,
        # then preserve those misses in the comparison instead of hiding them.
        shell += report_shell(args, destination + '/' + name + '.log', report,
            f"import json; d=json.load(open({report!r})); assert len(d['episodes'])==20; print(json.dumps(d['summary']))")
        return name, json.loads(launch_run.kexec(pod, shell, timeout=14400))

    tasks = [(label, models, h) for label, models in (("reference", ref), ("puget", new))
             for h in (-135, -90, -45, 0, 45, 90, 135, 180)
             if f"{label}-{h:03}" not in evaluations]
    with ThreadPoolExecutor(max_workers=4) as pool:
        from concurrent.futures import as_completed
        for future in as_completed([pool.submit(one, *task) for task in tasks]):
            name, summary = future.result()
            evaluations[name] = summary
            save(progress_path, progress)
    for label, models in (("reference", ref), ("puget", new)):
        args = ["/workspace/runtime/.venv/bin/python", "-m", "rl_move.sim.joystick_demo_lifecycle"]
        args += [*evaluation_args(models), "--script", "demo1",
                 "--seed", "0", "--out", f"{destination}/{label}-demo.mp4",
                 "--summary-out", f"{destination}/{label}-demo.json"]
        report = f"{destination}/{label}-demo.json"
        summary = launch_run.kexec(pod, f"cd {POD_ROOT}; export OMP_NUM_THREADS=1 MUJOCO_GL=egl; " +
            report_shell(args, f"{destination}/{label}-demo.log", report,
                f"import json,pathlib; d=json.load(open({report!r})); "
                f"assert pathlib.Path({destination + '/' + label + '-demo.mp4'!r}).stat().st_size>0; "
                "print(json.dumps(d))"), timeout=7200)
        progress.setdefault("demos", {})[label] = json.loads(summary)
        save(progress_path, progress)


def run(plan, path):
    pipeline = stages(plan)
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    progress_path = path.parent / "progress.json"
    progress = json.loads(progress_path.read_text()) if progress_path.exists() else {
        "plan_sha256": digest, "status": "training", "completed": {}, "total_steps": sum(s["steps"] for s in pipeline)}
    if progress["plan_sha256"] != digest:
        raise RuntimeError("plan changed since start; inspect existing progress before proceeding")
    progress["execution_policy"] = dict(host_workers=12, defer_final_artifacts=False,
        reason="Cooperative post-training drain avoids Puget AppArmor signal denial; optimizer settings unchanged.")
    progress.pop("error", None)
    outputs = {s["original"]: s["output"] for s in pipeline}
    for stage in pipeline:
        if stage["run"] in progress["completed"]:
            continue
        progress.update(status="training", current=stage["run"], original=stage["original"])
        save(progress_path, progress)
        entry = ledger_entry(stage["run"])
        if not entry:
            parent = stage.get("initialization_run")
            if parent:
                previous = next(s for s in pipeline if s["original"] == parent)
                recorded = progress["completed"][previous["run"]]
                actual = inspect_checkpoint(plan["pod"], previous["output"])
                if actual["sha256"] != recorded["sha256"]:
                    raise RuntimeError("reproduced parent changed since verification; refusing initialization")
            sync_source(plan["pod"], stage["source_code_sha"], Path(plan["worker_root"]))
            log = f"/tmp/train_{stage['run']}.log"
            durable = f"/workspace/reproduction-logs/train_{stage['run']}.log"
            launch_run.kexec(plan["pod"], "mkdir -p /workspace/reproduction-logs && "
                f"ln -s {shlex.quote(durable)} {shlex.quote(log)}")
            command([sys.executable, HERE / "launch_run.py", "status"])
            args = [sys.executable, HERE / "launch_run.py", "launch", "--pod", plan["pod"],
                    "--run", stage["run"], "--steps", str(stage["steps"]),
                    "--phase", stage.get("phase") or "acquisition", "--track", "walkcurr",
                    "--hypothesis", "Reproduce " + stage["original"] + " from fresh lineage roots on Puget1. "
                    "Prediction if true: final matched evaluation approaches the frozen champion. "
                    "If false: behavioral performance regresses; alternative is training variance or runtime drift.",
                    "--gate", "Complete the original optimization budget with finite weights; "
                    "evaluate final four-role composition against frozen references. Sim only.",
                    "--evidence", "Operator requested full reproduction; original lineage and gates exported in the plan. "
                    "Puget 4096-environment, 131072-minibatch GPU capacity test completed with finite weights.",
                    "--allow-no-log-std-final"]
            if stage.get("initialization_run"):
                args += ["--parent", next(s["run"] for s in pipeline if s["original"] == stage["initialization_run"])]
            command([*args, "--", *training_args(stage, outputs)])
            entry = ledger_entry(stage["run"])
        elif entry.get("status") not in {"RUNNING", "FINISHED"}:
            raise RuntimeError(f"{stage['run']} previously {entry.get('status')}; inspect rather than duplicate")
        result = wait_for_stage(plan["pod"], stage, entry)
        progress["completed"][stage["run"]] = dict(result, source_sha=stage["source_code_sha"], steps=stage["steps"])
        save(progress_path, progress)
    progress["status"] = "evaluating"
    save(progress_path, progress)
    evaluate(plan, pipeline, progress, progress_path)
    progress.update(status="complete", current=None)
    save(progress_path, progress)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "reproduction.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            run(json.loads(args.plan.read_text()), args.plan)
        except Exception as error:
            save(args.plan.parent / "error.json", {"error": str(error), "time": time.time()})
            progress_path = args.plan.parent / "progress.json"
            if progress_path.exists():
                progress = json.loads(progress_path.read_text())
                progress.update(status="needs_attention", error=str(error))
                save(progress_path, progress)
            raise


if __name__ == "__main__":
    main()
