"""The cycle command line: spawn_cycle appends the prompt as the LAST
positional argument, and claude's --add-dir is variadic, so no variadic
option may be the final option (2026-09-16: the first post-split cycle died
with "Input must be provided" because --add-dir ate the prompt)."""
import watch_loop


def test_agent_cmd_prefix_and_add_dir_position():
    cmd = watch_loop.agent_cmd("claude-sonnet-5")
    assert cmd[:3] == ["claude", "-p", "--bare"]  # restart_watcher.sh greps this
    i = cmd.index("--add-dir")
    assert cmd[i + 1] == str(watch_loop.ORCH_ROOT)
    # the token after the add-dir value must be another option, never the end
    assert i + 2 < len(cmd) and cmd[i + 2].startswith("--")
    assert not cmd[-1].startswith("--add-dir")


def test_agent_cmd_appended_prompt_is_a_separate_positional():
    cmd = watch_loop.agent_cmd("m") + ["the prompt"]
    # walk the option grammar: every --add-dir value is exactly one token
    for j, tok in enumerate(cmd):
        if tok == "--add-dir":
            assert cmd[j + 2].startswith("--")
    assert cmd[-1] == "the prompt"


def test_prompt_placeholders_all_filled():
    import re
    txt = watch_loop.fill_roots(watch_loop.PROMPT_PATH.read_text())
    assert not re.findall(r"\{(ORCH_ROOT|HEXAPOD_REPO|PROTO|STATE_DIR)\}", txt)
    assert str(watch_loop.state_dir.STATE_DIR) + "/rl_docs/tracks/<track>/STATUS.md" in txt
    assert str(watch_loop.ORCH_ROOT) + "/orchestrator/launch_run.py status" in txt
