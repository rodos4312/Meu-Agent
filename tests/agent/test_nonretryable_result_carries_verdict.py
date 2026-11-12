"""A non-retryable 4xx (rejected OAuth token, bad key) must reach UI clients with the
classifier's verdict: without ``failure_reason`` the desktop error card read a 401 as a
retryable "Provider error" and offered Retry instead of a re-login."""
from __future__ import annotations

from agent.error_classifier import classify_api_error
from agent.error_surface import LAYER_AUTH, build_error_surface_from_result
from agent.turn_recovery import nonretryable_client_error_result


class _Rejected(Exception):
    status_code = 401

    def __init__(self) -> None:
        super().__init__("HTTP 401: User not found.")


class _Agent:
    log_prefix = ""
    verbose = False

    def _summarize_api_error(self, error):
        return str(error)

    def __getattr__(self, name):  # status/persist/print helpers the terminal path calls
        return lambda *args, **kwargs: None

