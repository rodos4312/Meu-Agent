"""Phase 7 delegation policy: only separable units, no privileged capability, file leases with
bounded concurrency, read-only investigation in-process, patch candidates as normal tasks."""

import pytest

from meu_coding.delegation import (
    MAX_PARALLEL,
    DelegationKind,
    DelegationRefused,
    DelegationRequest,
    FileLeases,
    investigate,
    plan_delegation,
    run_investigations,
    start_patch_candidate,
)
from meu_coding.intelligence import RepositoryIntelligence
from tests.meu_coding.phase3_support import git, make_git_repo, snapshot

K = DelegationKind
GOAL = "inspect how calc/ops.py is used by the tests and callers"


def _request(kind=K.INSPECT_SUBSYSTEM, files=("calc/ops.py",), **over):
    return DelegationRequest(kind, over.pop("goal", GOAL), tuple(files), **over)


@pytest.mark.parametrize("capability", ["approve", "push", "create_pr", "merge", "write_parent", "install"])
def test_no_privileged_capability_can_be_delegated(capability):
    with pytest.raises(DelegationRefused, match="never"):
        plan_delegation([_request(capabilities=frozenset({capability}))])


def test_vague_or_incomplete_requests_are_refused():
    with pytest.raises(DelegationRefused, match="specific"):
        plan_delegation([_request(goal="look")])
    with pytest.raises(DelegationRefused, match="names the files"):
        plan_delegation([_request(K.PATCH_CANDIDATE, files=())])
    with pytest.raises(DelegationRefused, match="two options"):
        plan_delegation([_request(K.COMPARE_OPTIONS, options=("only one",))])


def test_parallel_only_for_independent_requests_and_bounded():
    assert plan_delegation([_request(files=("a.py",)), _request(files=("b.py",))]).parallel
    overlap = plan_delegation([_request(files=("a.py",)), _request(files=("a.py", "c.py"))])
    assert not overlap.parallel and "overlapping" in overlap.reasons[0]
    many = plan_delegation([_request(files=(f"{i}.py",)) for i in range(MAX_PARALLEL + 1)])
    assert not many.parallel


def test_leases_prevent_overlap_and_cap_concurrency():
    leases = FileLeases(limit=2)
    leases.acquire("one", ["a.py"])
    with pytest.raises(DelegationRefused, match="already held"):
        leases.acquire("two", ["a.py", "b.py"])
    leases.acquire("two", ["b.py"])
    with pytest.raises(DelegationRefused, match="at most 2"):
        leases.acquire("three", ["c.py"])
    leases.release("one")
    leases.acquire("three", ["a.py"])
    assert leases.active == 2


def test_read_only_investigation_touches_nothing(tmp_path):
    repo = make_git_repo(tmp_path)
    before, head = snapshot(repo), git(repo, "rev-parse", "HEAD")
    intel = RepositoryIntelligence(repo)
    intel.analyze_repository()
    result = run_investigations(intel, [_request(), _request(K.INVESTIGATE_TESTS, files=("tests/test_ops.py",),
                                                             goal="why might tests/test_ops.py fail after a change")])
    findings = result["results"][0]["findings"][0]
    assert findings["path"] == "calc/ops.py" and "tests/test_ops.py" in findings["imported_by"]
    assert result["parallel_allowed"]
    compare = investigate(intel, _request(K.COMPARE_OPTIONS, files=(), options=("change sub in calc/ops.py",
                                                                                 "add a new module calc/fast.py")))
    assert len(compare["options"]) == 2
    assert snapshot(repo) == before and git(repo, "rev-parse", "HEAD") == head


def test_patch_candidate_is_a_normal_task_needing_its_own_approval(tmp_path):
    from tests.meu_coding.phase5_support import service_for

    repo = make_git_repo(tmp_path)
    service = service_for(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    view = start_patch_candidate(service, _request(K.PATCH_CANDIDATE, files=("calc/ops.py", "tests/test_ops.py"),
                                                   goal="Add a small function `add` in calc/ops.py and a unit test"),
                                 str(repo), FileLeases())
    assert view["stage"] == "awaiting_approval" and view["approval"]["fingerprint"]
    assert git(repo, "rev-parse", "HEAD") == head  # nothing applied: the user still approves
    with pytest.raises(DelegationRefused, match="coding tasks"):
        investigate(None, _request(K.PATCH_CANDIDATE, files=("calc/ops.py",)))
