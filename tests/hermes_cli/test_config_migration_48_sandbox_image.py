"""Migration 47->48 under Meu: there is no default sandbox image (``DEFAULT_SANDBOX_IMAGE`` is
empty), so a saved image -- an older upstream default included -- is the image the user runs and is
never dropped. Driven through ``run_migrations`` against a temp home.
"""

import os
from unittest.mock import patch

import hermes_yaml as yaml


def _run(tmp_path, config):
    from hermes_cli.config_migrations import run_migrations

    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    with patch.dict(os.environ, {"HERMES_HOME": str(tmp_path)}):
        run_migrations(46, {"env_added": [], "config_added": [], "warnings": []}, quiet=True)
    return yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))["terminal"]


def test_saved_images_survive_because_meu_has_no_default_to_follow(tmp_path):
    from hermes_cli.config import load_config
    from hermes_cli.config_defaults import DEFAULT_SANDBOX_IMAGE, LEGACY_SANDBOX_IMAGE, LEGACY_SANDBOX_IMAGES

    assert DEFAULT_SANDBOX_IMAGE == "", "Meu never names a vendor image as the default"
    saved = {
        "backend": "docker",
        "docker_image": LEGACY_SANDBOX_IMAGE,
        "daytona_image": LEGACY_SANDBOX_IMAGES[1],
        "singularity_image": f"docker://{LEGACY_SANDBOX_IMAGE}",
        "modal_image": "ghcr.io/me/custom:1",
    }
    terminal = _run(tmp_path, {"_config_version": 46, "terminal": dict(saved)})
    for key in ("docker_image", "daytona_image", "singularity_image", "modal_image"):
        assert terminal[key] == saved[key], f"{key} is the user's image and must survive"
    with patch.dict(os.environ, {"HERMES_HOME": str(tmp_path)}):
        merged = load_config()["terminal"]
    assert merged["docker_image"] == LEGACY_SANDBOX_IMAGE
