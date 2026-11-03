"""An upgrade rehearsal can exercise signed installers without publishing a release."""
from pathlib import Path

import pytest
import hermes_yaml as yaml
from tests.ci import _gha_expr as gha


@pytest.mark.parametrize("verify,prepare", [(True, False), (False, True), (False, False)])
def test_rehearsal_and_release_dispatch_have_separate_publication_gates(verify, prepare):
    flow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/meu-windows-validation.yml").read_text(encoding="utf-8"))
    context = {"inputs": {"verify_upgrade": verify, "prepare_release": prepare}, "github": {
        "repository": "rodos4312/Meu-Agent", "ref": "refs/heads/dev/meu-foundation",
        "event": {"head_commit": {"message": "Verify installer consolidation"}},
    }}
    assert gha.truthy(gha.render(flow["env"]["MEU_RELEASE_REQUEST"], context)) == (verify or prepare)
    assert gha.condition(flow["jobs"]["native-upgrade"]["if"], context) == (verify or prepare)
    assert gha.condition(flow["jobs"]["release-draft"]["if"], context) == prepare
