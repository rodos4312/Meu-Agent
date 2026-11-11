from meu_coding.coding_interfaces import EditAction, EditOperation, EditStrategy
from meu_coding.edit_strategy import (
    SAFE_DEFAULT,
    EditHint,
    EditStrategyRouter,
    ModelProfile,
    format_errors,
    touched_paths,
)


def test_selection_is_deterministic_per_profile():
    router = EditStrategyRouter()
    for _ in range(3):
        assert router.select("deepseek-pro-v4").strategy == EditStrategy.V4A_PATCH
        assert router.select("DeepSeek-Flash").strategy == EditStrategy.SEARCH_REPLACE
    assert router.profile_for("deepseek-pro-v4").architect_mode
    assert not router.profile_for("deepseek-flash").architect_mode
    assert router.profile_for("deepseek-pro").max_context_chars > router.profile_for("deepseek-flash").max_context_chars


def test_unknown_model_gets_the_safe_default():
    router = EditStrategyRouter()
    for model in ("", "some-new-model", "gpt-unknown"):
        choice = router.select(model)
        assert choice.profile == SAFE_DEFAULT.name
        assert choice.strategy == EditStrategy.SEARCH_REPLACE


def test_requested_strategy_is_honoured_only_when_allowed():
    router = EditStrategyRouter()
    assert router.select("deepseek-pro", requested=EditStrategy.UNIFIED_DIFF).strategy == EditStrategy.UNIFIED_DIFF
    refused = router.select("unknown", requested=EditStrategy.V4A_PATCH)
    assert refused.strategy == EditStrategy.SEARCH_REPLACE
    assert "not allowed" in refused.reason


def test_new_and_small_files_route_to_whole_file():
    router = EditStrategyRouter()
    assert router.select("deepseek-pro", EditHint(new_file=True)).strategy == EditStrategy.WHOLE_FILE
    assert router.select("deepseek-pro", EditHint(file_bytes=500)).strategy == EditStrategy.WHOLE_FILE
    assert router.select("deepseek-pro", EditHint(file_bytes=50_000)).strategy == EditStrategy.V4A_PATCH
    assert router.select("unknown", EditHint(file_bytes=500)).strategy == EditStrategy.SEARCH_REPLACE


def test_profiles_are_extensible_and_later_registrations_win():
    router = EditStrategyRouter()
    router.register(ModelProfile("house", ("deepseek-pro-house*",), EditStrategy.UNIFIED_DIFF))
    assert router.select("deepseek-pro-house-1").strategy == EditStrategy.UNIFIED_DIFF
    assert router.select("deepseek-pro-v4").strategy == EditStrategy.V4A_PATCH


def test_touched_paths_include_files_named_inside_patches():
    v4a = EditOperation("a.py", EditStrategy.V4A_PATCH, "d", patch=(
        "*** Begin Patch\n*** Update File: a.py\n@@\n-x\n+y\n*** Update File: secret.py\n+z\n*** End Patch\n"))
    diff = EditOperation("a.py", EditStrategy.UNIFIED_DIFF, "d", patch=(
        "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-x\n+y\n"))
    assert touched_paths(v4a) == ("a.py", "secret.py")
    assert touched_paths(diff) == ("a.py", "b.py")


def test_format_errors_catch_malformed_payloads():
    assert format_errors(EditOperation("a.py", EditStrategy.SEARCH_REPLACE, "d", search="", replace="y"))
    assert format_errors(EditOperation("a.py", EditStrategy.V4A_PATCH, "d", patch="+x\n"))
    assert format_errors(EditOperation("a.py", EditStrategy.WHOLE_FILE, "d", content="x", search="x"))
    assert not format_errors(EditOperation("a.py", EditStrategy.WHOLE_FILE, "d", content=""))
    assert not format_errors(EditOperation("a.py", EditStrategy.SEARCH_REPLACE, "d", EditAction.DELETE))
