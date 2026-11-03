"""Settings and skill choices do not load the retired feature-usage collector."""

import builtins

from hermes_cli import config


def test_settings_persist_without_feature_tracking(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tmp_path / "config.yaml"
    path.write_text(
        "# Keep user choices\nmodel:\n  provider: deepseek\nmemory:\n  memory_enabled: true\n",
        encoding="utf-8",
    )
    imported = []
    original_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name.endswith("shared_metrics_disabled"):
            imported.append(name)
            raise ImportError("Feature tracking is not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    saved = config.load_config()
    saved.setdefault("skills", {})["disabled"] = ["fixture-skill"]
    config.save_config(saved)
    config.set_config_value("display.show_reasoning", "false")
    config._persist_migration(config.load_config())
    reread = config.load_config()
    assert reread["skills"]["disabled"] == ["fixture-skill"]
    assert reread["display"]["show_reasoning"] is False
    assert reread["memory"]["memory_enabled"] is True
    assert reread["model"]["provider"] == "deepseek"
    assert "# Keep user choices" in path.read_text(encoding="utf-8")
    assert imported == []
    assert not (tmp_path / "telemetry").exists()
