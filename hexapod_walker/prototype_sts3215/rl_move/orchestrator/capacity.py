#!/usr/bin/env python3
"""THE canonical cluster-capacity report. Run this; never guess.

    uv run python rl_move/orchestrator/capacity.py          # human table
    uv run python rl_move/orchestrator/capacity.py --json   # machine-readable

Live truth, queried from the cluster every time: nodes, GPUs, train
pods, what's running where, and how many slots are FREE right now.
Policy (operator, 2026-08-09): the cluster is ONE POOL, at least 4
train slots per machine, one run per slot. If this script and any doc
disagree, this script is right — fix the doc.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from launch_run import KUBECONFIG, load_guardrails, pod_trainers  # noqa: E402


def kubectl_json(*args: str) -> dict:
    out = subprocess.run(
        ["kubectl", "--kubeconfig", KUBECONFIG, *args, "-o", "json"],
        capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    g = load_guardrails()
    gpu_pods = g["compute"]["gpu_pods"]

    nodes = {
        n["metadata"]["name"]: {
            "cpus": n["status"]["allocatable"]["cpu"],
            "gpus": int(n["status"]["allocatable"].get("nvidia.com/gpu", 0)),
        }
        for n in kubectl_json("get", "nodes")["items"]
    }
    pods = {
        p["metadata"]["name"]: {
            "node": p["spec"].get("nodeName"),
            "phase": p["status"]["phase"],
        }
        for p in kubectl_json("get", "pods")["items"]
    }

    report = {"nodes": {}, "slots_total": 0, "slots_ready": 0,
              "slots_free": 0, "free_pods": [], "pending_pods": [],
              "busy": {}}
    for name, info in nodes.items():
        report["nodes"][name] = {**info, "train_pods": []}

    for pod in gpu_pods:
        st = pods.get(pod)
        report["slots_total"] += 1
        if st is None:
            report["pending_pods"].append(pod + " (ABSENT — apply manifest)")
            continue
        if st["phase"] != "Running":
            report["pending_pods"].append(f"{pod} ({st['phase']})")
            if st["node"]:
                report["nodes"][st["node"]]["train_pods"].append(pod)
            continue
        report["nodes"][st["node"]]["train_pods"].append(pod)
        report["slots_ready"] += 1
        try:
            trainers = pod_trainers(pod)
        except Exception as e:  # unreachable pod: not free, not busy
            report["pending_pods"].append(f"{pod} (unreachable: {e})")
            report["slots_ready"] -= 1
            continue
        if trainers:
            report["busy"][pod] = trainers
        else:
            report["slots_free"] += 1
            report["free_pods"].append(pod)

    if a.json:
        print(json.dumps(report, indent=2))
        return 0

    print("=== CLUSTER CAPACITY (live) — one pool, one run per slot ===")
    for name, info in sorted(report["nodes"].items()):
        print(f"{name}: {info['gpus']} H200s, cpu {info['cpus']}, "
              f"train pods: {', '.join(info['train_pods']) or 'NONE'}")
    print(f"slots: {report['slots_total']} total, "
          f"{report['slots_ready']} ready, {report['slots_free']} FREE")
    for pod, runs in sorted(report["busy"].items()):
        print(f"  busy  {pod}: {', '.join(runs)}")
    for pod in report["free_pods"]:
        print(f"  FREE  {pod}  <- launch something here")
    for pod in report["pending_pods"]:
        print(f"  wait  {pod}")
    if report["slots_free"]:
        print(f"{report['slots_free']} free slot(s) and a non-empty "
              "backlog is a bug — drain it: launch_run.py drain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
