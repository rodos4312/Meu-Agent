"""Driver-neutral notifications emitted by the agent."""
from dataclasses import dataclass
from typing import Optional

@dataclass
class AgentNotice:
    """Driver-agnostic out-of-band notice (``AIAgent.notice_callback`` / ``notice_clear_callback``); each driver
    renders its own way. ``kind``/``ttl_ms`` stay expressive so a future config can switch v1's sticky notices to TTL."""

    text: str
    level: str = "info"            # info | warn | error | success
    kind: str = "sticky"           # sticky | ttl
    ttl_ms: Optional[int] = None   # honored only when kind == "ttl"
    key: Optional[str] = None      # dedupe / fired-once-latch / clear key
    id: Optional[str] = None
