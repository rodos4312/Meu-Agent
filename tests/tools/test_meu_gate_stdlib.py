"""Standard-library smoke checks for Meu's process-local execution gate.

Runs on Windows CI before packaging; no pytest or gateway dependencies needed.
"""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from time import sleep
from unittest.mock import patch

from tools.meu_limits import meu_child_slot


class MeuConcurrencyGateTests(unittest.TestCase):
    def test_meu_never_exceeds_two_simultaneous_children(self):
        counter_lock = Lock()
        running = 0
        peak = 0

        def child(_):
            nonlocal running, peak
            with meu_child_slot():
                with counter_lock:
                    running += 1
                    peak = max(peak, running)
                sleep(0.035)
                with counter_lock:
                    running -= 1

        with patch.dict(os.environ, {"MEU_AGENT_MODE": "1"}):
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(child, range(8)))

        self.assertEqual(peak, 2)
        self.assertEqual(running, 0)

    def test_slot_released_after_child_raises(self):
        with patch.dict(os.environ, {"MEU_AGENT_MODE": "1"}):
            with self.assertRaisesRegex(RuntimeError, "intentional"):
                with meu_child_slot():
                    raise RuntimeError("intentional")

            # The next two slots must remain available after an exception.
            with meu_child_slot():
                with meu_child_slot():
                    pass

    def test_upstream_runtime_not_gated(self):
        barrier = Barrier(3)
        counter_lock = Lock()
        running = 0
        peak = 0

        def child(_):
            nonlocal running, peak
            with meu_child_slot():
                with counter_lock:
                    running += 1
                    peak = max(peak, running)
                barrier.wait(timeout=3)

        with patch.dict(os.environ, {"MEU_AGENT_MODE": "0"}):
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(child, range(3)))

        self.assertEqual(peak, 3)


if __name__ == "__main__":
    unittest.main()
