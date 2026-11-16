"""A desktop-owned mutable source install still checks its selected dependencies."""
import json

import pm
from hermes_cli.venv_sync import check_runtime


def test_source_seed_checks_pm_without_treating_it_as_an_unmanaged_dev_tree(tmp_path, monkeypatch):
    root = tmp_path / "core"
    root.mkdir()
    (root / ".git").mkdir()
    stamp = root / "install-stamp.json"
    calls = []
    def activate():
        calls.append(True)
        return ["venv: fixture plugin dependencies missing"]
    monkeypatch.setattr(pm, "activate", activate)
    stamp.write_text(json.dumps({"source": "ci", "distribution": "desktop-app",
        "updateMechanism": "app-installer", "payload": "bootstrap", "sourceSeed": {"schema": 1}}))
    assert "run `hermes pm install`" in check_runtime(root)
    assert calls == [True]
    stamp.write_text(json.dumps({"source": "local", "updateMechanism": "app-installer"}))
    assert check_runtime(root) is None
    assert calls == [True]
