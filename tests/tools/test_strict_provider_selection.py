"""Persisted selections and direct-provider billing boundaries."""
from unittest.mock import patch

import pytest

from tools import tool_backend_helpers as tbh


# ---------------------------------------------------------------------------
# read_selection — the shared helper
# ---------------------------------------------------------------------------


class TestReadSelection:
    def _with_raw(self, raw):
        return patch(
            "hermes_cli.config.read_raw_config_readonly",
            return_value=raw,
        )

    def test_never_configured_returns_none(self):
        with self._with_raw({}):
            assert tbh.read_selection("image_gen") is None

    def test_vendor_provider_returned(self):
        with self._with_raw({"image_gen": {"provider": "fal"}}):
            assert tbh.read_selection("image_gen") == "fal"

    def test_nous_provider_returned(self):
        with self._with_raw({"image_gen": {"provider": "nous"}}):
            assert tbh.read_selection("image_gen") == "nous"

    def test_legacy_use_gateway_true_maps_to_nous(self):
        """Old configs stored use_gateway: true beside a vendor name — only
        the managed picker row ever wrote it, so it means 'nous'."""
        with self._with_raw({"video_gen": {"provider": "fal", "use_gateway": True}}):
            assert tbh.read_selection("video_gen") == "nous"

    def test_legacy_use_gateway_false_keeps_vendor(self):
        with self._with_raw({"tts": {"provider": "openai", "use_gateway": False}}):
            assert tbh.read_selection("tts") == "openai"

    def test_empty_string_backend_is_no_selection(self):
        """DEFAULT_CONFIG's seeded empty strings are not selections."""
        with self._with_raw({"web": {"backend": ""}}):
            assert tbh.read_selection("web") is None

    def test_raw_stt_local_is_a_selection(self):
        """A raw config.yaml ``stt.provider: local`` is a genuine pick: the
        DEFAULT_CONFIG seed never reached disk (save_config strips schema
        defaults), and the current picker's Local Whisper row writes exactly
        this shape (provider only, legacy use_gateway popped). Treating it
        as no-selection would silently discard the user's choice."""
        with self._with_raw({"stt": {"provider": "local"}}):
            assert tbh.read_selection("stt") == "local"

    def test_stt_local_with_use_gateway_key_is_a_selection(self):
        """A picker-written stt section (use_gateway key present) means
        local was a genuine choice."""
        with self._with_raw({"stt": {"provider": "local", "use_gateway": False}}):
            assert tbh.read_selection("stt") == "local"

    def test_browser_backend_key_is_not_the_cloud_selection(self):
        """browser.backend is the driver choice (browser-use CLI vs built-in
        tools), not the cloud provider selection."""
        with self._with_raw({"browser": {"backend": "browser-use"}}):
            assert tbh.read_selection("browser") is None

    def test_web_per_capability_keys_mark_configured(self):
        with self._with_raw({"web": {"search_backend": "searxng"}}):
            assert tbh.read_selection("web") is None
            assert tbh.selection_exists("web") is True


# ---------------------------------------------------------------------------
# Image generation (FAL)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Video generation (FAL plugin)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# STT (OpenAI audio resolver — previously ignored the stored intent entirely)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Browser Use provider
# ---------------------------------------------------------------------------


class TestBrowserUseStrictSelection:
    def _provider(self):
        from plugins.browser.browser_use.provider import BrowserUseBrowserProvider

        return BrowserUseBrowserProvider()

    def test_retired_selection_refuses_direct_key(self):
        provider = self._provider()
        with patch("plugins.browser.browser_use.provider.get_secret", return_value="bu-key"), \
             patch("tools.tool_backend_helpers.read_selection", return_value="nous"):
            assert provider._get_config_or_none() is None
            with pytest.raises(ValueError, match="has been removed"):
                provider._get_config()

    def test_vendor_selection_missing_key_errors_without_managed_call(self):
        provider = self._provider()
        with patch("plugins.browser.browser_use.provider.get_secret", return_value=""), \
             patch("tools.tool_backend_helpers.read_selection", return_value="browser-use"), \
             patch("tools.managed_tool_gateway.resolve_managed_tool_gateway") as gw:
            with pytest.raises(ValueError) as exc:
                provider._get_config()
        gw.assert_not_called()
        assert "browser is configured to use browser-use" in str(exc.value)
        assert "BROWSER_USE_API_KEY" in str(exc.value)

    def test_never_configured_key_still_routes_direct(self):
        provider = self._provider()
        with patch("plugins.browser.browser_use.provider.get_secret", return_value="bu-key"), \
             patch("tools.tool_backend_helpers.read_selection", return_value=None):
            config = provider._get_config_or_none()
        assert config["api_key"] == "bu-key"


# ---------------------------------------------------------------------------
# tools_config writers: one provider string per row, no use_gateway writes
# ---------------------------------------------------------------------------


class TestWriteProviderConfig:

    def test_byok_row_writes_vendor_and_clears_legacy_flag(self):
        from hermes_cli.tools_config import _write_provider_config

        config = {"web": {"backend": "nous", "use_gateway": True}}
        provider = {"name": "Keenable", "web_backend": "keenable"}
        _write_provider_config(provider, config)
        assert config["web"]["backend"] == "keenable"
        assert "use_gateway" not in config["web"]


    def test_plugin_injected_byok_row_clears_stale_use_gateway(self):
        """Plugin-injected rows are not in TOOL_CATEGORIES' hardcoded
        provider lists; the legacy clear-loop skipped them."""
        from hermes_cli.tools_config import _write_provider_config

        config = {"stt": {"provider": "nous", "use_gateway": True}}
        provider = {"name": "Groq Whisper", "stt_provider": "groq"}
        _write_provider_config(provider, config)
        assert config["stt"]["provider"] == "groq"
        assert "use_gateway" not in config["stt"]
