"""Test doubles for which activity counts as work for the local Desktop (``process_identity``)."""

from __future__ import annotations


def as_local_desktop_backend(monkeypatch) -> None:
    """Every activity in this test is work for the local Desktop (``process_identity.serving_local_desktop``),
    threads included."""
    from contextvars import ContextVar
    from hermes_cli import process_identity
    monkeypatch.setattr(process_identity, "_SERVING_LOCAL_DESKTOP", ContextVar("serving_local_desktop_test", default=True))
