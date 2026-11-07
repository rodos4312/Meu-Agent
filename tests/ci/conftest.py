"""Shared positive control for independent workflow-mutation groups."""
import pytest


@pytest.fixture(scope="module")
def valid_update_workflow_consumers():
    # Once per group: the workflow files are immutable; each negative control
    # deep-copies its own workflow data and still executes its mutated script.
    from tests.ci import test_update_ci_routing as routing

    run = routing._ci_run(routing.cc.classify([]))
    for lane in ("desktop_updater", "e2e", "e2e_upgrade", "e2e_desktop_update"):
        reached = routing._consumers_reached(run, lane)
        assert all(reached.values()), f"baseline {lane} is not dispatched: {reached}"
