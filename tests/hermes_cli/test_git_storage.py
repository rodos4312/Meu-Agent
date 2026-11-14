"""Storage mode and the hardened internal Git environment, without OS fakes."""
from hermes_cli.git_storage import git_storage_overrides


def test_only_proot_needs_emulated_link_compatible_object_publication():
    assert git_storage_overrides("6.17.0-PRoot-Distro") == [("core.createObject", "rename")]
    assert git_storage_overrides("6.17.0-linux") == []
    assert git_storage_overrides("10.0.26100") == []


def test_internal_git_preserves_hardening_while_adding_storage_mode(monkeypatch):
    from hermes_cli._subprocess_compat import noninteractive_git_env
    monkeypatch.setattr("hermes_cli.git_storage.git_storage_overrides", lambda: [("core.createObject", "rename")])
    env = noninteractive_git_env({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "evil"})
    settings = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))}
    assert settings["core.createObject"] == "rename"
    assert settings["core.hooksPath"] != "evil"
    assert env["GIT_TERMINAL_PROMPT"] == "0" and env["GIT_CONFIG_GLOBAL"]
