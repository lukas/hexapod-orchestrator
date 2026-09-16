"""Stable W&B artifact identifiers without changing experiment identities."""

from __future__ import annotations

import hashlib
from pathlib import Path


def bounded_artifact_name(name: str) -> str:
    """Preserve legacy names; retain a collision-resistant suffix beyond 128."""
    if len(name) <= 128:
        return name
    return name[:95] + "-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:32]


def checkpoint_artifact_name(stem: str) -> str:
    return bounded_artifact_name(f"ckpt-{stem}")


def publish_checkpoint(run, checkpoint: Path, *, run_name: str, steps: int,
                       task: str, parent_ckpt: str | None = None):
    """Publish retained checkpoint bytes to their existing W&B run."""
    import wandb

    checkpoint = Path(checkpoint)
    original = f"ckpt-{checkpoint.stem}"
    art = wandb.Artifact(
        checkpoint_artifact_name(checkpoint.stem), type="policy-checkpoint",
        metadata={"run": run_name,
                  "md5": hashlib.md5(checkpoint.read_bytes()).hexdigest()[:8],
                  "steps": steps, "task": task, "parent_ckpt": parent_ckpt,
                  "checkpoint_filename": checkpoint.name,
                  "original_artifact_name": original})
    art.add_file(str(checkpoint))
    run.log_artifact(art, aliases=["latest", bounded_artifact_name(run_name)])
    return art
