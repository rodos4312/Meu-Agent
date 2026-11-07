"""Every update dispatch combination with the Python lane enabled."""
import itertools

import pytest

from tests.ci import test_update_ci_routing as routing


@pytest.mark.platforms("linux", "windows")
@routing._EMULATED_BASH
@pytest.mark.parametrize("rest", list(itertools.product((False, True), repeat=len(routing._GATED) - 1)))
def test_every_set_lane_reaches_its_consumer_with_python(rest):
    routing.assert_dispatch_combination((True, *rest))
