"""OPTIONAL live check against the user's configured MEU provider (``-m live``).

Runs only when a coding route is configured (Models by workload, else the main model) and MEU's
resolver finds credentials for it; otherwise it is skipped. It spends a few small requests, prints no
secret, and works in a temporary repository: Architect → Coder → Reviewer must return valid
structured responses, and the change is executed only in an isolated worktree.
"""

import pytest

from meu_coding import analyze_repository
from meu_coding.architect import Architect
from meu_coding.coder import Coder
from meu_coding.coding_session import CodingSession, SessionState
from meu_coding.impact import ImpactAnalyzer
from meu_coding.provider_adapter import ProviderError, provider_has_credentials, provider_models, resolve_coding_routes
from meu_coding.reviewer import Reviewer
from meu_coding.safe_execution import SafeExecutionAdapter
from tests.meu_coding.phase3_support import TASK, git, snapshot, yes

pytestmark = pytest.mark.live


def _routes():
    from hermes_cli.config import load_config_readonly

    try:
        routes = resolve_coding_routes(load_config_readonly()).routes
    except ProviderError as exc:
        pytest.skip(f"no configured coding routes: {exc}")
    if not all(provider_has_credentials(r.provider) for r in (routes.architect, routes.coder, routes.reviewer)):
        pytest.skip("provider credentials are not available")
    return routes


def test_live_provider_completes_a_harmless_task(git_repo):
    routes = _routes()
    before = snapshot(git_repo)
    intel = analyze_repository(git_repo)
    models = provider_models(routes, timeout=180)
    session = CodingSession(intel, Coder(models.coding), Reviewer(models.review),
                            Architect(ImpactAnalyzer(intel.graph), models.planning),
                            adapter=SafeExecutionAdapter())
    state = session.start(TASK)
    calls = [*models.planning.session.calls, *models.coding.session.calls, *models.review.session.calls]
    assert [c.role for c in calls][:1] == ["architect"] and all(c.ok for c in calls), calls
    assert state == SessionState.AWAITING_APPROVAL, (state, session.planning.plan_errors, session.blocked_reason)
    attempt = session.execute(yes(session.pending))
    assert attempt.result.executed, attempt.result.reasons
    assert snapshot(git_repo) == before and attempt.result.commits == 0
    assert not git(git_repo, "remote").strip()
    assert attempt.review.status.value in ("pass", "fix"), attempt.review.rationale
