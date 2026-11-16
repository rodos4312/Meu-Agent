"""Retired account selections cannot charge a direct account or call a hosted gateway."""
import json
from unittest.mock import Mock

import pytest


@pytest.fixture
def media_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("TOOL_GATEWAY_USER_TOKEN", "retired-token")
    monkeypatch.setenv("FAL_KEY", "own-fal-key")
    monkeypatch.setenv("OPENAI_API_KEY", "own-openai-key")
    monkeypatch.setenv("KREA_API_KEY", "own-krea-key")

    def save(section, selection):
        # Deliberately emulate a legacy file already on disk; supported config writes
        # reject this data before persistence (covered separately below).
        (tmp_path / "config.yaml").write_text(json.dumps({section: selection}), encoding="utf-8")
    return save


@pytest.mark.parametrize("section", ["image_gen", "video_gen", "stt"])
@pytest.mark.parametrize("legacy", [False, True])
def test_retired_selection_refuses_direct_credentials(media_home, monkeypatch, section, legacy):
    from tools import image_generation_tool, transcription_cloud
    from plugins.video_gen import fal

    media_home(section, {"provider": "fal" if legacy else "nous", "use_gateway": legacy})
    sdk = Mock()
    monkeypatch.setattr(image_generation_tool, "_load_fal_client", lambda: sdk)
    monkeypatch.setattr(fal, "_load_fal_client", lambda: sdk)
    calls = {
        "image_gen": lambda: image_generation_tool._submit_fal_request("example/model", {}),
        "video_gen": lambda: fal._submit_fal_video_request("example/model", {}),
        "stt": transcription_cloud._resolve_openai_audio_client_config,
    }
    from hermes_cli.config_backend import ConfigBackendUnavailable
    with pytest.raises(ConfigBackendUnavailable, match="Retired Nous settings"):
        calls[section]()
    sdk.submit.assert_not_called()
    if section == "image_gen":
        with pytest.raises(ConfigBackendUnavailable, match="Retired Nous settings"):
            image_generation_tool.image_generate_tool("a cat")
        with pytest.raises(ConfigBackendUnavailable, match="Retired Nous settings"):
            image_generation_tool.check_image_generation_requirements()
    sdk.submit.assert_not_called()


@pytest.mark.parametrize("section", ["image_gen", "video_gen"])
def test_direct_fal_submission_preserves_payload(media_home, monkeypatch, section):
    from tools import image_generation_tool
    from plugins.video_gen import fal

    media_home(section, {"provider": "fal"})
    sdk = Mock()
    module = image_generation_tool if section == "image_gen" else fal
    monkeypatch.setattr(module, "_load_fal_client", lambda: sdk)
    submit = module._submit_fal_request if section == "image_gen" else module._submit_fal_video_request
    payload = {"prompt": "example", "seed": 42}
    assert submit("vendor/model", payload) is sdk.submit.return_value
    args, kwargs = sdk.submit.call_args
    assert args == ("vendor/model",)
    assert kwargs["arguments"] == payload
    assert set(kwargs["headers"]) == {"x-idempotency-key"}
    assert "retired-token" not in repr(sdk.mock_calls)


def test_missing_fal_key_does_not_use_retired_token(media_home, monkeypatch):
    from tools import image_generation_tool
    media_home("image_gen", {"provider": "fal"})
    monkeypatch.delenv("FAL_KEY")
    sdk = Mock()
    monkeypatch.setattr(image_generation_tool, "_load_fal_client", lambda: sdk)
    with pytest.raises(ValueError, match="FAL_KEY"):
        image_generation_tool._submit_fal_request("vendor/model", {})
    sdk.submit.assert_not_called()


@pytest.mark.parametrize("section", ["image_gen", "video_gen", "stt"])
def test_retired_media_config_cannot_replace_an_existing_valid_file(tmp_path, monkeypatch, section):
    from hermes_cli.config import atomic_config_write
    from hermes_cli.config_backend import ConfigValueError

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config = tmp_path / "config.yaml"
    atomic_config_write(config, {section: {"provider": "openai"}})
    before = config.read_bytes()
    with pytest.raises(ConfigValueError, match="Retired Nous settings"):
        atomic_config_write(config, {section: {"provider": "nous"}})
    assert config.read_bytes() == before
