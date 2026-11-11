from meu_coding.coding_interfaces import RiskLevel
from meu_coding.impact import ImpactAnalyzer
from tests.meu_coding.phase2_support import REPO, make_intel


def _analyzer(make_repo, files=REPO):
    intel = make_intel(make_repo, files)
    intel.deep_analyze()
    return ImpactAnalyzer(intel.graph)


def test_direct_and_reverse_dependencies(make_repo):
    report = _analyzer(make_repo).analyze(["app/cart.py"])
    assert "app/pricing.py" in report.direct_dependencies
    assert report.reverse_dependencies == ("web/routes.py",)
    assert report.callers == ("web/routes.py",)


def test_affected_tests_found_through_the_graph(make_repo):
    report = _analyzer(make_repo).analyze(["app/pricing.py"])
    assert "tests/test_pricing.py" in report.affected_tests
    assert "app/cart.py" in report.reverse_dependencies


def test_public_api_change_raises_risk_with_a_reason(make_repo):
    report = _analyzer(make_repo).analyze(["app/pricing.py"], ["apply_discount"])
    assert report.risk == RiskLevel.MEDIUM
    assert any("public API changed: apply_discount" in r.reason for r in report.reasons)


def test_security_code_is_high_risk_and_explained(make_repo):
    report = _analyzer(make_repo).analyze(["app/auth/tokens.py"])
    assert report.risk == RiskLevel.HIGH
    assert any("security-sensitive" in r.reason for r in report.reasons)
    assert any("no tests found" in r.reason for r in report.reasons)
    assert "risk high" in report.explain()


def test_config_touched_is_reported(make_repo):
    report = _analyzer(make_repo).analyze(["pyproject.toml"])
    assert report.affected_config == ("pyproject.toml",)
    assert any("configuration file touched" in r.reason for r in report.reasons)


def test_isolated_tested_change_is_low_risk(make_repo):
    files = {"lib/util.py": "def _helper():\n    return 1\n", "tests/test_util.py": "from lib.util import _helper\n"}
    report = _analyzer(make_repo, files).analyze(["lib/util.py"], ["_helper"])
    assert report.risk == RiskLevel.LOW
    assert report.affected_tests == ("tests/test_util.py",)
