"""Paid-tier Nous pickers surface every model the gateway is discounting, not only curated ones.

A sale exists only in the live ``/v1/models`` ``pricing.original``; the curated manifest and the
Portal's ``paidRecommendedModels`` can both omit a model while it is heavily discounted, and the
picker then badged discounts on curated rows while hiding the deepest ones.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import hermes_cli.models as models_mod
import hermes_cli.models_pricing as mp
from hermes_cli import model_switch_providers as msp
from hermes_cli.models import union_with_nous_on_sale_models
from hermes_cli.models_pricing import fetch_models_with_pricing

_LIST = {"prompt": "0.000002", "completion": "0.00001"}


def _sale(pct_off: int) -> dict:
    now = 0.000002 * (100 - pct_off) / 100
    return {"prompt": f"{now:.10f}", "completion": "0.00001", "original": dict(_LIST)}


def test_appends_discounted_models_missing_from_list_deepest_first():
    pricing = {"curated/a": _sale(40), "sale/small": _sale(20), "sale/deep": _sale(80), "full/price": dict(_LIST)}

    ids = union_with_nous_on_sale_models(["curated/a"], pricing)

    assert ids[0] == "curated/a"  # curated order preserved, not duplicated
    assert ids.count("curated/a") == 1
    assert ids[1:] == ["sale/deep", "sale/small"]
    assert "full/price" not in ids


def test_skips_tool_less_and_free_rows():
    """Free rows belong to freeRecommendedModels; tool-less rows can't drive the agent loop."""
    pricing = {
        "sale/no-tools": {**_sale(70), "tools": False},
        "free/with-original": {"prompt": "0", "completion": "0", "original": dict(_LIST)},
        "free/native": {"prompt": "0", "completion": "0"},
    }
    assert union_with_nous_on_sale_models(["c"], pricing) == ["c"]


def test_no_pricing_leaves_list_unchanged():
    assert union_with_nous_on_sale_models(["a", "b"], {}) == ["a", "b"]


def _serve(monkeypatch, payload: dict) -> None:
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: False
    monkeypatch.setattr(models_mod, "_urlopen_model_catalog_request", lambda req, timeout=8.0: resp)


def test_nous_fetch_flags_tool_less_rows_so_the_union_can_skip_them(monkeypatch):
    mp._pricing_cache.clear()
    _serve(monkeypatch, {"data": [
        {"id": "t/yes", "supported_parameters": ["tools"], "pricing": _sale(50)},
        {"id": "t/no", "supported_parameters": ["temperature"], "pricing": _sale(50)},
        {"id": "t/unknown", "pricing": _sale(50)},  # absent field is permissive, as elsewhere
    ]})
    fetch = lambda **kw: fetch_models_with_pricing(api_key="sk-test", base_url="https://example.test",
                                                   force_refresh=True, **kw)
    nous = fetch(include_sale_original=True)
    # Equal discounts tie-break by id, so the order is deterministic.
    assert union_with_nous_on_sale_models([], nous) == ["t/unknown", "t/yes"]
    # Other catalogs never carry the Nous-only flag.
    assert all("tools" not in row for row in fetch().values())


def _stub_portal(monkeypatch, *, free_tier: bool, pricing: dict, allowed=None) -> None:
    monkeypatch.setattr(mp, "get_pricing_for_provider", lambda provider, **kw: pricing)
    monkeypatch.setattr("hermes_cli.models.check_nous_free_tier", lambda **kw: free_tier)
    monkeypatch.setattr("hermes_cli.models.fetch_nous_recommended_models", lambda *a, **kw: None)
    monkeypatch.setattr(mp, "nous_policy_allowed_ids", lambda **kw: allowed)


def test_gui_picker_paid_tier_shows_on_sale_model(monkeypatch):
    _stub_portal(monkeypatch, free_tier=False, pricing={"nous/a": dict(_LIST), "sale/x": _sale(80)})
    assert msp._nous_picker_model_ids({"nous": ["nous/a"]}, False) == ["nous/a", "sale/x"]


def test_gui_picker_free_tier_does_not_list_paid_sales(monkeypatch):
    _stub_portal(monkeypatch, free_tier=True, pricing={"nous/a": dict(_LIST), "sale/x": _sale(80)})
    assert "sale/x" not in msp._nous_picker_model_ids({"nous": ["nous/a"]}, False)


def test_gui_picker_org_policy_still_narrows_on_sale_models(monkeypatch):
    _stub_portal(monkeypatch, free_tier=False, pricing={"nous/a": dict(_LIST), "sale/x": _sale(80)},
                 allowed={"nous/a"})
    assert "sale/x" not in msp._nous_picker_model_ids({"nous": ["nous/a"]}, False)


def test_skips_generation_models_on_sale(monkeypatch):
    """Image/video generation rows stay out of the chat picker even when discounted."""
    mp._pricing_cache.clear()
    _serve(monkeypatch, {"data": [
        {"id": "chat/ok", "pricing": _sale(50)},
        {"id": "gen/typed", "capabilities": {"type": "image"}, "pricing": _sale(90)},
        {"id": "vendor/flux-pro", "pricing": _sale(90)},  # generation by name shape alone
    ]})
    nous = fetch_models_with_pricing(api_key="sk-test", base_url="https://example.test",
                                     force_refresh=True, include_sale_original=True)
    assert union_with_nous_on_sale_models([], nous) == ["chat/ok"]


def test_nonzero_sale_rounding_to_full_discount_is_still_paid():
    """A rounded -100% badge does not make a positive-price model free."""
    pricing = {
        "sale/almost-free": {"prompt": "0.000000001", "completion": "0.000000001", "original": dict(_LIST)},
        "free/zero": {"prompt": "0", "completion": "0", "original": dict(_LIST)},
    }
    assert union_with_nous_on_sale_models([], pricing) == ["sale/almost-free"]


def test_zero_prompt_with_missing_or_invalid_completion_is_not_a_paid_sale(monkeypatch):
    """The real parser normalizes absent completion to an empty string."""
    mp._pricing_cache.clear()
    rows = [
        {"id": "free/missing", "pricing": {"prompt": "0", "original": dict(_LIST)}},
        *[{"id": f"free/invalid-{i}",
           "pricing": {"prompt": "0", "completion": value, "original": dict(_LIST)}}
          for i, value in enumerate(("", None, "not-a-price", "NaN", "Infinity", "-1", "0"))],
    ]
    _serve(monkeypatch, {"data": rows})
    pricing = fetch_models_with_pricing(api_key="synthetic", base_url="https://example.test",
                                        force_refresh=True, include_sale_original=True)
    assert union_with_nous_on_sale_models([], pricing) == []
