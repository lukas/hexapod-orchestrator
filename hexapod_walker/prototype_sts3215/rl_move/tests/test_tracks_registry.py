import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
import tracks


def test_speed_track_is_registered_and_inferred():
    speed = tracks.load()["speed"]

    assert speed["parent_goal"] == "any_means"
    assert speed["lifecycle"] == "open"
    assert tracks.infer("cw-speed-mesh50-stride-canary") == "speed"
    assert tracks.tag("speed") == "track:speed"
