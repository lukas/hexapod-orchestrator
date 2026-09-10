# Metaagent

Metaagent is the project's bounded review process, with explicit manual runs
and an opt-in deterministic timer for recurring reviews. See
[the operator guide](../overseer/README.md) for provider selection, the private
CoreWeave dashboard, MCP and shared spending limits.

Use `uv run python -m rl_move.metaagent`. The old `rl_move.overseer` CLI,
registry IDs and database remain compatible so naming cannot reset a budget
or lose recommendations.
