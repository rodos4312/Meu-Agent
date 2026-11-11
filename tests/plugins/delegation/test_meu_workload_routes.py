"""The General Coordinator obeys the owner's exact multi-provider routes."""
import pytest


@pytest.mark.parametrize("workload,provider,model", [
    ("routine", "zai", "glm-5.3-flash"),
    ("complex", "deepseek", "deepseek-v4-pro"),
    ("standard", "deepseek", "deepseek-v4-pro"),
    ("web", "gemini", "gemini-3.6-flash"),
    ("vision", "zai", "glm-5.3-flash"),
])
def test_coordinator_routes_each_role_without_inheriting_another_provider_key(workload, provider, model):
    from plugins.delegation.meu_coordinator import MeuCoordinator
    routes = {
        "routine": {"provider": "zai", "model": "glm-5.3-flash"},
        "complex": {"provider": "deepseek", "model": "deepseek-v4-pro"},
        "web": {"provider": "gemini", "model": "gemini-3.6-flash"},
        "vision": {"provider": "zai", "model": "glm-5.3-flash"},
    }
    parent = {"provider": "deepseek", "model": "deepseek-v4-pro",
              "workload_policy": {"enabled": True, "provider": "deepseek", "routes": routes}}
    task = {"workload": workload, "write_paths": [], "acceptance": "Return evidence"}
    route = MeuCoordinator(general=True).route_task(task, {"parent_route": parent})
    assert (route["provider"], route["model"]) == (provider, model)
    assert "api_key" not in route
    assert route["fallback_providers"] == []
    if workload == "web":
        assert "web_search" in route["allowed_tools"]
        assert "write_file" not in route["allowed_tools"]
