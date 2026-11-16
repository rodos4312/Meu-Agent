"""Private RC validates its bundled core without invoking the public source installer."""
from pathlib import Path

import hermes_yaml as yaml
import pytest

from tests.ci import _gha_expr as gha
from tests.ci import workflow_steps

ROOT = Path(__file__).resolve().parents[2]


def workflow():
    return yaml.safe_load((ROOT / ".github/workflows/meu-windows-validation.yml").read_text(encoding="utf-8"))


def context(repo, private=True, branch="dev/meu-foundation"):
    return {"github": {"repository": repo, "event": {"repository": {"private": private}},
                       "ref": "refs/heads/" + branch}, "env": {"MEU_RELEASE_REQUEST": "false"}}


@pytest.mark.parametrize("repo,private,branch,private_core,source_upgrade", [
    ("rodos4312/Meu-Agent-RC-private", True, "dev/meu-foundation", True, False),
    ("rodos4312/Meu-Agent-RC-private", False, "dev/meu-foundation", False, False),
    ("rodos4312/Meu-Agent-RC-private", True, "main", False, False),
    ("rodos4312/Meu-Agent", False, "dev/meu-foundation", False, True),
    ("other/Meu-Agent-RC-private", True, "dev/meu-foundation", False, False),
])
def test_validation_uses_only_the_repositorys_actual_distribution(repo, private, branch, private_core, source_upgrade):
    jobs, scope = workflow()["jobs"], context(repo, private, branch)
    assert gha.condition(jobs["private-runtime-compatibility"]["if"], scope) == private_core
    assert gha.condition(jobs["backend-upgrade"]["if"], scope) == source_upgrade


def test_private_compatibility_replays_real_runtime_chat_and_rpc_selection():
    job = workflow()["jobs"]["private-runtime-compatibility"]
    step = next(s for s in job["steps"] if s.get("name", "").startswith("Verify private runtime"))
    _, calls = workflow_steps._run(step, {}, ROOT, receipt=True)
    assert len(calls) == 1 and calls[0][0] == "pytest"
    assert {"tests/meu_coding", "tests/tools/test_coding_task_tool.py", "tests/tui_gateway/test_coding_rpc.py",
            "tests/scripts/test_bundle_native.py", "tests/scripts/test_bundle_payload.py"} <= set(calls[0])
    assert "--file-retries" in calls[0] and calls[0][calls[0].index("--file-retries") + 1] == "0"


@pytest.mark.parametrize("name", [
    "Package Meu Windows application", "Package Meu Windows installer",
    "Scan Meu installer and unpacked application before upload",
    "Prove an unsigned preview cannot pass the signed-release gate",
    "Upload Meu installer for manual Windows testing", "Smoke-test Meu installer and desktop shortcuts",
    "Upload unpacked preview for review only",
])
def test_private_validation_never_packages_or_uploads_a_legacy_public_installer(name):
    step = next(s for s in workflow()["jobs"]["windows-identity-and-safety"]["steps"] if s.get("name") == name)
    assert not gha.condition(step["if"], context("rodos4312/Meu-Agent-RC-private"))
    assert gha.condition(step["if"], context("rodos4312/Meu-Agent", False))
