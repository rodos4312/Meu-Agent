"""Known Nous-dependent pins are retired; the ordinary catalog remains available."""
import pytest

from hermes_cli.plugin_catalog import find_removed, get_catalog_entry, load_catalog

@pytest.mark.parametrize("name,repo,blocked_repo", [
    ("kfchow-llm-value-router", "https://github.com/kfchow-ai/kfchow-llm-value-router", True),
    ("catalogo-it", "https://github.com/Lazzdaycod/hermes-lang-it", False),
])
def test_retired_pin_is_not_loadable_and_unrelated_monorepo_plugins_remain_available(name,repo,blocked_repo):
    assert get_catalog_entry(name) is None
    assert find_removed(name) is not None
    assert (find_removed(repo) is not None) == blocked_repo
    assert load_catalog()  # independent plugins remain discoverable
