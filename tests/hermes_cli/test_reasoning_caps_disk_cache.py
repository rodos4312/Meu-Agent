"""The reasoning-capability disk mirror.

Every consumer of these capabilities sits on a per-request hot path that must
never block on HTTP, so a process whose in-memory cache is cold answers
"unknown" — and on that answer the Nous profile drops a "thinking off" disable
rather than risk a 400. A short-lived process (``hermes -p``, a cron job, a
freshly booted gateway) is ALWAYS cold, so without a disk copy that fallback is
the only behavior those runs ever get and the user keeps paying for reasoning
they turned off.

These tests pin the mirror that makes every run after the first correct from
its first turn.
"""

import json

import pytest

import hermes_cli.models as models_mod
from hermes_cli import models_pricing
from hermes_cli import models_reasoning_caps


_CATALOG = json.dumps({
    "data": [
        {
            "id": "deepseek/deepseek-v4-pro",
            "supported_parameters": ["reasoning", "tools"],
            "reasoning": {"mandatory": False},
        },
        {
            "id": "arcee-ai/trinity-large-thinking",
            "supported_parameters": ["reasoning"],
            "reasoning": {"mandatory": True},
        },
    ]
}).encode()


def _response(body: bytes):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return body

    return _Resp()


@pytest.fixture
def cold_process(monkeypatch):
    """Put the module in the state a freshly started process would be in."""

    def _reset():
        for name in (
            "_nous_reasoning_caps_cache",
            "_nous_reasoning_caps_failed_at",
            "_openrouter_reasoning_caps_cache",
            "_openrouter_reasoning_caps_failed_at",
        ):
            monkeypatch.setattr(models_mod, name, None)
        for name in (
            "_nous_caps_disk_checked",
            "_nous_caps_warm_started",
            "_openrouter_caps_disk_checked",
            "_openrouter_caps_warm_started",
        ):
            monkeypatch.setattr(models_mod, name, False)

    _reset()
    return _reset


@pytest.fixture
def offline():
    """Fail the test if anything reaches for the network."""

    def _boom(req, *, timeout):
        raise AssertionError(f"must not fetch: {req.full_url}")

    return _boom

