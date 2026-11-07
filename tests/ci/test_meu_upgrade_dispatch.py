"""An upgrade rehearsal can exercise signed installers without publishing a release."""
from pathlib import Path

import pytest
import hermes_yaml as yaml
from tests.ci import _gha_expr as gha
from tests.ci import workflow_steps


@pytest.mark.parametrize("verify,prepare", [(True, False), (False, True), (False, False)])
def test_rehearsal_and_release_dispatch_have_separate_publication_gates(verify, prepare):
    flow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/meu-windows-validation.yml").read_text(encoding="utf-8"))
    context = {"inputs": {"verify_upgrade": verify, "prepare_release": prepare}, "github": {
        "repository": "rodos4312/Meu-Agent", "ref": "refs/heads/dev/meu-foundation",
        "event": {"head_commit": {"message": "Verify installer consolidation"}},
    }}
    assert gha.truthy(gha.render(flow["env"]["MEU_RELEASE_REQUEST"], context)) == (verify or prepare)
    assert gha.condition(flow["jobs"]["native-upgrade"]["if"], context) == (verify or prepare)
    assert gha.condition(flow["jobs"]["automatic-rollback"]["if"], context) == (verify or prepare)
    assert gha.condition(flow["jobs"]["release-draft"]["if"], context) == prepare
    assert "automatic-rollback" in flow["jobs"]["release-draft"]["needs"]


@pytest.mark.parametrize("event,repo,ref,allowed", [
    ("workflow_dispatch", "rodos4312/Meu-Agent", "dev/meu-foundation", True),
    ("push", "rodos4312/Meu-Agent", "dev/meu-foundation", False),
    ("workflow_dispatch", "other/repository", "dev/meu-foundation", False),
    ("workflow_dispatch", "rodos4312/Meu-Agent", "main", False),
])
def test_diagnostic_is_manual_dev_only_and_cannot_publish(event, repo, ref, allowed):
    flow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/meu-rollback-rehearsal.yml").read_text(encoding="utf-8"))
    assert list(flow["jobs"]) == ["automatic-rollback"]
    assert set(flow["permissions"].values()) == {"read"}
    job = flow["jobs"]["automatic-rollback"]
    context = {"github": {"event_name": event, "repository": repo, "ref": "refs/heads/" + ref}}
    assert gha.condition(job["if"], context) == allowed
    signers = [step for step in job["steps"] if "MEU_RELEASE_PRIVATE_KEY" in step.get("env", {})]
    assert len(signers) == 1
    assert signers[0]["run"] == "node scripts/prepare-meu-release.mjs"
    downloads = [step["with"] for step in job["steps"] if step.get("uses", "").startswith("actions/download-artifact@")]
    assert downloads[0]["repository"] == "rodos4312/Meu-Agent"
    assert downloads[0]["run-id"] == "${{ inputs.candidate_run_id }}"


@pytest.mark.parametrize("scope,expected", [
    ("all", ["startup-failure", "guardian-loss", "locked-package", "interrupted-install"]),
    ("native-faults", ["guardian-loss", "locked-package", "interrupted-install"]),
])
def test_recovery_rerun_scope_selects_only_the_requested_closed_set(scope, expected):
    flow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/meu-rollback-rehearsal.yml").read_text(encoding="utf-8"))
    context = {"inputs": {"scope": scope}}
    scenarios = flow["jobs"]["automatic-rollback"]["strategy"]["matrix"]["scenario"]
    assert gha.render(scenarios, context) == expected


@pytest.mark.parametrize("job_name,step_name", [
    ("installer-consolidation", "Verify remaining build graph and rehearsal gates"),
    ("windows-identity-and-safety", "Verify complete CI dispatch replay on Windows"),
])
def test_meu_ci_invokes_every_split_replay_group(job_name, step_name):
    """Execute the real selection command, intercepting only the test launch."""
    root = Path(__file__).resolve().parents[2]
    flow = yaml.safe_load((root / ".github/workflows/meu-windows-validation.yml").read_text(encoding="utf-8"))
    job = flow["jobs"][job_name]
    step = next(s for s in job["steps"] if s.get("name") == step_name)
    workflow_steps.required(job, {})
    _, calls = workflow_steps._run(step, {}, root, receipt=True)
    assert len(calls) == 1 and calls[0][0] == "pytest", calls
    invoked = set(calls[0][1:])
    expected = {p.relative_to(root).as_posix() for p in (root / "tests/ci").glob("test_update_ci_*.py")}
    assert expected and expected <= invoked, f"{job_name}: missing replay groups {sorted(expected - invoked)}"
