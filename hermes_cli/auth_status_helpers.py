"""Read-only credential status shared by supported OAuth providers."""
from typing import Any, Callable, Optional
from hermes_cli.auth_constants import AuthError

def _pool_first_oauth_status(
    provider_id: str, *, is_expiring: Callable[[str, int], bool], auth_mode: str,
    resolve: Callable[[], dict[str, Any]],
    on_pool_miss: Optional[Callable[[], Optional[dict[str, Any]]]] = None) -> dict[str, Any]:
    """Status snapshot for a store-backed OAuth provider (Codex, xAI).

    Pool first (where `hermes auth` / `hermes model` store device_code tokens), then
    *on_pool_miss* for a pool-derived degraded status, then the legacy state via *resolve*.

    The pool read is an observation (``peek``), not a lease: ``select()`` refreshes an expiring
    single-use token and, when that speculative POST fails transiently, benches the entry with a
    persisted cooldown — every credential-gated listing (``/model`` picker, doctor) then shows the
    provider as unconfigured while the runtime resolver still serves it. Refreshing stays with the
    runtime resolver reached through *resolve*, whose failures persist nothing.
    """
    from hermes_cli.auth import _auth_file_path
    try:
        from agent.credential_pool import load_pool
        pool = load_pool(provider_id)
        if pool and pool.has_credentials():
            entry = pool.peek()
            if entry is not None:
                api_key = (
                    getattr(entry, "runtime_api_key", None) or getattr(entry, "access_token", ""))
                if api_key and not is_expiring(api_key, 0):
                    return {
                        "logged_in": True, "auth_store": str(_auth_file_path()),
                        "last_refresh": getattr(entry, "last_refresh", None),
                        "auth_mode": auth_mode,
                        "source": f"pool:{getattr(entry, 'label', 'unknown')}", "api_key": api_key,
                        # The host this entry's key belongs to, so a caller never pairs it with
                        # another provider default (#121486).
                        "base_url": str(getattr(entry, "runtime_base_url", None)
                                        or getattr(entry, "base_url", None) or "").rstrip("/")}
            if on_pool_miss is not None and (degraded := on_pool_miss()):
                return degraded
    except Exception:
        pass
    try:
        creds = resolve()
        return {
            "logged_in": True, "auth_store": str(_auth_file_path()),
            "last_refresh": creds.get("last_refresh"),
            "auth_mode": creds.get("auth_mode"), "source": creds.get("source"),
            "api_key": creds.get("api_key"), "base_url": creds.get("base_url") or ""}
    except AuthError as exc:
        return {"logged_in": False, "auth_store": str(_auth_file_path()), "error": str(exc)}
