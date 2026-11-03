"""Browser Use cloud browser provider using the profile's own BROWSER_USE_API_KEY."""

from __future__ import annotations

import logging
from typing import Any

from agent.secret_scope import get_secret
from plugins.browser._common import CloudBrowserProvider

logger = logging.getLogger(__name__)
_BASE_URL = "https://api.browser-use.com/api/v3"


class BrowserUseBrowserProvider(CloudBrowserProvider):
    """Browser Use (https://browser-use.com) cloud browser backend."""

    provider_id = "browser-use"
    label = "Browser Use"
    release_method = "patch"
    release_path = "/browsers/{session_id}"
    setup_tag = "Cloud browser using your own Browser Use account"
    setup_env_vars = [
        {"key": "BROWSER_USE_API_KEY", "prompt": "Browser Use API key", "url": "https://browser-use.com"},
    ]

    def _get_config_or_none(self) -> dict[str, Any] | None:
        from tools.tool_backend_helpers import read_selection

        # A saved retired selection must not silently start billing the user's direct account.
        if read_selection("browser") == "nous":
            return None
        api_key = get_secret("BROWSER_USE_API_KEY")
        return {"api_key": api_key, "base_url": _BASE_URL} if api_key else None

    def _get_config(self) -> dict[str, Any]:
        from tools.tool_backend_helpers import read_selection, selection_error

        config = self._get_config_or_none()
        if config is not None:
            return config
        selected = read_selection("browser")
        if selected == "nous":
            raise ValueError("Nous-managed browsing has been removed. Select a local browser or configure "
                             "your own browser provider in settings.")
        if selected is not None:
            raise ValueError(selection_error("browser", selected, "BROWSER_USE_API_KEY is not set"))
        raise ValueError("Browser Use requires a direct BROWSER_USE_API_KEY credential.")

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Content-Type": "application/json", "X-Browser-Use-API-Key": config["api_key"]}

    def _release_body(self, config: dict[str, Any]) -> dict[str, object]:
        return {"action": "stop"}

    def create_session(self, task_id: str) -> dict[str, object]:
        config = self._get_config()
        response = self._post_create(f"{config['base_url']}/browsers", self._headers(config), {})
        self._check_created(response)
        session_data = response.json()
        session_name = self._session_name(task_id)
        logger.info("Created Browser Use session %s", session_name)
        return {
            "session_name": session_name,
            "bb_session_id": session_data["id"],
            "cdp_url": session_data.get("cdpUrl") or session_data.get("connectUrl") or "",
            "expires_at": session_data.get("timeoutAt"),
            "features": {"browser_use": True},
        }
