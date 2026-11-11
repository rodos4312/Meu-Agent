"""Shared fixtures for Phase 2 tests: a small repository and deterministic fake models."""

from __future__ import annotations

from dataclasses import dataclass, field

from meu_coding import analyze_repository
from meu_coding.coding_interfaces import (
    CoderOutput,
    CodingRequest,
    EditAction,
    EditOperation,
    EditStrategy,
    ReviewRequest,
)

REPO = {
    "app/__init__.py": "",
    "app/pricing.py": (
        "def apply_discount(price, rate):\n"
        "    return price * (1 - rate)\n"
        "\n\n"
        "def format_price(value):\n"
        "    return f'{value:.2f}'\n"
    ),
    "app/cart.py": (
        "from app.pricing import apply_discount\n\n\n"
        "class Cart:\n"
        "    def total(self, items, rate):\n"
        "        return sum(apply_discount(p, rate) for p in items)\n"
    ),
    "app/auth/tokens.py": "def issue_token(user):\n    return 'secret-' + user\n",
    "web/routes.py": "from app.cart import Cart\n\n\ndef checkout(items):\n    return Cart().total(items, 0.1)\n",
    "tests/test_pricing.py": (
        "from app.pricing import apply_discount\n\n\n"
        "def test_apply_discount():\n"
        "    assert apply_discount(10, 0.5) == 5\n"
    ),
    "pyproject.toml": "[project]\nname = 'shop'\n",
}

TASK = "Clamp the rate in `apply_discount` in app/pricing.py so it stays between 0 and 1"

FIX_EDIT = EditOperation(
    path="app/pricing.py", strategy=EditStrategy.SEARCH_REPLACE,
    description="clamp rate in apply_discount",
    search="    return price * (1 - rate)\n",
    replace="    rate = min(max(rate, 0), 1)\n    return price * (1 - rate)\n",
)


def make_intel(make_repo, files=REPO):
    return analyze_repository(make_repo(files))


@dataclass
class ScriptedCoder:
    """Returns one scripted output per call; records every request it received."""

    outputs: list[CoderOutput]
    requests: list[CodingRequest] = field(default_factory=list)

    def propose(self, request: CodingRequest) -> CoderOutput:
        self.requests.append(request)
        return self.outputs[min(len(self.requests), len(self.outputs)) - 1]


def good_output(**kwargs) -> CoderOutput:
    return CoderOutput((FIX_EDIT,), **kwargs)


def output(*ops: EditOperation) -> CoderOutput:
    return CoderOutput(tuple(ops))


def edit(path: str, strategy=EditStrategy.SEARCH_REPLACE, action=EditAction.UPDATE, **payload) -> EditOperation:
    if strategy == EditStrategy.SEARCH_REPLACE and not payload and action != EditAction.DELETE:
        payload = {"search": "x = 1\n", "replace": "x = 2\n"}
    return EditOperation(path, strategy, f"edit {path}", action, **payload)


@dataclass
class RecordingReviewModel:
    findings: tuple = ()
    requests: list[ReviewRequest] = field(default_factory=list)

    def review(self, request: ReviewRequest):
        self.requests.append(request)
        return self.findings
