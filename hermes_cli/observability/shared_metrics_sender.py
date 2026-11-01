"""Meu has no shared-metrics network transport.

The local consent-window reconciler remains for revoking consent in existing databases.
The sender contract remains callable so agent teardown and old queues cannot break startup.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .shared_metrics import _isoformat, _utc_now

MAX_OBS_ADVANCE_SECONDS = 30 * 24 * 3600
MAX_ATTEMPTS = 3
MAX_PACKAGES_PER_PASS = 20
MAX_SEND_ATTEMPTS = 25
REQUEST_TIMEOUT_SECONDS = 30
GZIP_THRESHOLD_BYTES = 4096


def _parse_stamp(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


@dataclass
class SendOutcome:
    sent: int = 0
    rejected: int = 0
    deferred: int = 0


def _post(endpoint: str, payload: bytes, *, timeout: int):
    """No transport remains, including for callers holding a reference to this function."""
    raise PermissionError("Shared-metrics transmission is disabled in Meu")


def reconcile_send_consent(
    connection: sqlite3.Connection,
    send_enabled: bool,
    *,
    now: datetime | None = None,
) -> None:
    """Reconcile the consent-window table with the observed config state.

    THE ONLY writer of consent state; must run inside a write transaction. Idempotent in
    (config, now, store): call it from anywhere, any number of times, in any order.
    """
    stamp = _isoformat(now or _utc_now())
    raw_stamp = stamp  # pre-cap observation time, used to clamp closes
    previous_obs = connection.execute(
        "SELECT stamp FROM consent_marks WHERE name = 'obs'"
    ).fetchone()
    if previous_obs is not None:
        ceiling = _isoformat(
            _parse_stamp(str(previous_obs[0])) + timedelta(seconds=MAX_OBS_ADVANCE_SECONDS)
        )
        stamp = min(stamp, ceiling)
    connection.execute(
        """
        INSERT INTO consent_marks(name, stamp) VALUES ('obs', ?)
        ON CONFLICT(name) DO UPDATE SET stamp = MAX(stamp, excluded.stamp)
        """,
        (stamp,),
    )
    marks = dict(connection.execute("SELECT name, stamp FROM consent_marks").fetchall())
    obs = marks["obs"]  # >= stamp; immune to clock rollback
    data = marks.get("data")

    open_row = connection.execute(
        "SELECT rowid FROM send_consent_windows WHERE closed_at IS NULL"
    ).fetchone()

    if send_enabled:
        if open_row is None:
            opened = max(x for x in (obs, data) if x is not None)
            connection.execute(
                "INSERT INTO send_consent_windows(opened_at, last_confirmed_at)"
                " VALUES (?, ?)",
                (opened, opened),
            )
        else:
            connection.execute(
                "UPDATE send_consent_windows"
                " SET last_confirmed_at = MAX(last_confirmed_at, ?)"
                " WHERE rowid = ?",
                (obs, open_row[0]),
            )
    elif open_row is not None:
        # Close at the last CONFIRMED moment, never after the closing observation's RAW
        # stamp. Both clamps are load-bearing: last_confirmed_at means an unobserved gap
        # (machine off, hand-edited config) is never asserted as consented; the raw
        # (pre-cap) stamp pulls a glitched-forward last_confirmed_at back to the true
        # revoke moment. A rolled-back clock only closes EARLIER — fail-closed.
        connection.execute(
            "UPDATE send_consent_windows"
            " SET closed_at = MIN(last_confirmed_at, ?)"
            " WHERE rowid = ?",
            (raw_stamp, open_row[0]),
        )


class SharedMetricsSender:
    """Compatibility for lifecycle callers; never reads an outbox or invokes a transport."""

    def __init__(self, store, endpoint: str, *, post=None, sleep=None, now=None,
                 max_attempts: int = 0, consent_check=None) -> None:
        pass

    def send_pending(self) -> SendOutcome:
        return SendOutcome()


# Retained for local database consent queries; it cannot authorize a network transport.
CONSENT_GATE_SQL = """EXISTS (
    SELECT 1 FROM send_consent_windows w
    WHERE package_outbox.period_start >= w.opened_at
      AND package_outbox.period_end <=
          CASE WHEN w.closed_at IS NULL THEN w.last_confirmed_at
               ELSE w.closed_at END
)"""


def _retry_after_seconds(value: str | None, default: int) -> int:
    from agent.retry_utils import parse_retry_after_seconds

    seconds = parse_retry_after_seconds(value)
    return default if seconds is None else max(1, min(int(seconds), 86_400))
