"""Meu pulls no container image implicitly: with no image configured, image backends fail closed."""
import pytest

from hermes_cli.config_defaults import DEFAULT_SANDBOX_IMAGE, SANDBOX_IMAGE_UNSET_REASON


def test_there_is_no_default_vendor_image():
    assert DEFAULT_SANDBOX_IMAGE == ""


@pytest.mark.parametrize("backend", ["docker", "modal", "daytona"])
def test_an_image_backend_without_an_image_refuses_to_start(backend):
    from tools.terminal_tool_backends import _create_environment

    with pytest.raises(RuntimeError, match="no sandbox image is configured"):
        _create_environment(backend, "", "/workspace", 60)


@pytest.mark.parametrize("backend", ["docker", "modal", "daytona"])
def test_requirements_report_the_missing_image(backend, monkeypatch):
    from tools import terminal_tool

    monkeypatch.setattr(terminal_tool, "_get_env_config",
                        lambda: {"env_type": backend, "docker_image": "", "modal_image": "", "daytona_image": ""})
    monkeypatch.setitem(terminal_tool._REQUIREMENT_CHECKERS, backend, lambda config: True)  # backend otherwise ready
    assert terminal_tool.check_terminal_requirements() is False
    assert terminal_tool.terminal_backend_unavailable_reason() == SANDBOX_IMAGE_UNSET_REASON
