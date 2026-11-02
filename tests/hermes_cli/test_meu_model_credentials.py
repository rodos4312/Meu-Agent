"""Connected and saved-model provider rows must retain editable credential metadata."""

import pytest

from hermes_cli.inventory import _apply_picker_hints


@pytest.mark.parametrize("authenticated,user_defined", [(True, False), (True, True), (False, False)])
def test_deepseek_key_entry_survives_a_model_catalog(authenticated, user_defined):
    import model_tools  # discover actual provider plugins, as runtime startup does

    rows = [{"slug": "deepseek", "models": ["deepseek-v4-pro"],
             "authenticated": authenticated, "is_user_defined": user_defined}]
    _apply_picker_hints(rows)
    assert rows[0]["auth_type"] == "api_key"
    assert rows[0]["key_env"] == "DEEPSEEK_API_KEY"
    assert rows[0]["authenticated"] is authenticated
    assert rows[0]["automatic_routing"] is True
