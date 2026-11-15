"""Release helpers never default to or inspect a Nous-owned container image."""
from unittest.mock import Mock

import pytest

from scripts.releases.docker import DockerReleaseError, stable_alias_digest

@pytest.mark.parametrize("image", [None, "nousresearch/hermes-agent", "docker.io/nousresearch/hermes-agent"])
def test_unconfigured_or_retired_registry_has_no_docker_command(monkeypatch,image):
    monkeypatch.delenv("IMAGE_NAME",raising=False)
    if image is not None:
        monkeypatch.setenv("IMAGE_NAME",image)
    run=Mock(return_value="sha256:"+"a"*64)
    with pytest.raises(DockerReleaseError,match="IMAGE_NAME|retired|Retired"):
        stable_alias_digest(run=run)
    run.assert_not_called()


def test_explicit_independent_registry_preserves_digest_readback(monkeypatch):
    monkeypatch.setenv("IMAGE_NAME","exampleorg/meu-agent")
    digest="sha256:"+"a"*64
    run=Mock(return_value=digest)
    assert stable_alias_digest(run=run) == digest
    command=run.call_args.args[0]
    assert "exampleorg/meu-agent:stable" in command
