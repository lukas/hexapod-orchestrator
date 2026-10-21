# Training capacity

Run `uv run python orchestrator/capacity.py` for live worker availability.
`KUBECONFIG` selects the worker cluster; its default is `~/.kube/puget1.yaml`.
An explicit unavailable cluster fails there and never selects CoreWeave.

Puget1 replaces the sixteen CoreWeave training slots (operator order,
2026-10-21). `guardrails.yaml` selects one GPU pod and one run at a time;
additional justified work stays queued. The controller runs on GCP.

The worker manifest and locked GPU runtime are in `deploy/puget1/`.
The workspace and state mirror use retained local storage on Puget1.
GPU capability measurements live in runtime state, outside Git.
