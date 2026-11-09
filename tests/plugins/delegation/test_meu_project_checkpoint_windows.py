"""Native Windows readers must not discard a completed helper's checkpoint."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest


@pytest.mark.platforms("windows")
def test_checkpoint_survives_a_reader_holding_the_previous_file(tmp_path, monkeypatch):
    from plugins.delegation.meu_coordinator import projects

    file = tmp_path / "project.json"
    state = projects.Project(file, {"state": "running"})
    state.save()
    refused = Event()
    publish = projects.durable_write_bytes

    def record_hold(*args):
        try:
            return publish(*args)
        except PermissionError:
            refused.set()
            raise

    monkeypatch.setattr(projects, "durable_write_bytes", record_hold)
    state.record["state"] = "needs_review"
    with ThreadPoolExecutor(max_workers=1) as pool:
        with file.open("rb") as reader:
            saving = pool.submit(state.save)
            assert refused.wait(10), "The native Windows reader must hold the old file"
            assert json.loads(reader.read()) == {"state": "running"}
        saving.result(timeout=10)
    assert json.loads(file.read_text()) == {"state": "needs_review"}
    assert not list(tmp_path.glob(".publish-*"))
