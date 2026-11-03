"""Direct speech credentials, model forwarding and retired-selection handling."""
from types import SimpleNamespace
from unittest.mock import patch
import pytest
import json
from tools import tts_tool, tts_tool_openai

@pytest.fixture
def saved_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    def save(section):
        (tmp_path / "config.yaml").write_text(json.dumps({"tts": section}), encoding="utf-8")
        monkeypatch.setattr(tts_tool, "_load_tts_config", lambda: section)
    return save

@pytest.mark.parametrize("base", [None, "http://localhost:4003/v1"])
def test_config_credentials_precede_environment(saved_config, base):
    config = {"provider": "openai", "openai": {"api_key": "cfg-key"}}
    if base:
        config["openai"]["base_url"] = base
    saved_config(config)
    with patch.object(tts_tool_openai, "resolve_openai_audio_api_key", return_value="env-key"):
        assert tts_tool_openai._resolve_openai_audio_client_config() == (
            "cfg-key", base or tts_tool_openai.DEFAULT_OPENAI_BASE_URL)
        assert tts_tool_openai._has_openai_audio_backend()

@pytest.mark.parametrize("selection", [{"provider": "nous"}, {"provider": "openai", "use_gateway": True}])
def test_retired_selection_never_borrows_direct_credentials(saved_config, selection):
    saved_config({**selection, "openai": {"api_key": "own-key"}})
    with patch.object(tts_tool, "_import_openai_client") as client:
        with pytest.raises(ValueError, match="removed"):
            tts_tool_openai._resolve_openai_audio_client_config()
        assert not tts_tool_openai._has_openai_audio_backend()
    client.assert_not_called()

def test_missing_credentials_explain_setup(saved_config):
    saved_config({"provider": "openai"})
    with patch.object(tts_tool_openai, "resolve_openai_audio_api_key", return_value=""):
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            tts_tool_openai._resolve_openai_audio_client_config()

@pytest.mark.parametrize("model", ["tts-1-hd", "tts-1", "gpt-4o-mini-tts", "custom-speech-model"])
def test_direct_model_is_sent_unchanged(tmp_path, saved_config, model):
    config = {"provider": "openai", "openai": {"api_key": "own-key", "model": model}}
    saved_config(config)
    created = []
    clients = []
    class Client:
        def __init__(self, **kwargs):
            clients.append(kwargs)
            self.audio = SimpleNamespace(speech=SimpleNamespace(create=self.create))
        def create(self, **kwargs):
            created.append(kwargs["model"])
            from pathlib import Path
            return SimpleNamespace(stream_to_file=lambda p: Path(p).write_bytes(b"ID3"))
    with patch.object(tts_tool, "_import_openai_client", return_value=Client):
        tts_tool_openai._generate_openai_tts("Hello", str(tmp_path / "out.mp3"), config)
    assert created == [model]
    assert clients[0]["api_key"] == "own-key"
    assert clients[0]["base_url"] == "https://api.openai.com/v1"
