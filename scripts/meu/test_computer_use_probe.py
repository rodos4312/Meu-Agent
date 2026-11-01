"""Behaviour tests for the read-only diagnostic probe."""

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import computer_use_probe as probe


class ProbeTests(unittest.TestCase):
    @patch("computer_use_probe.time.perf_counter", side_effect=[3.0, 3.125])
    @patch("computer_use_probe.subprocess.run")
    def test_only_diagnostics_and_no_command_output_leaks(self, run, _clock):
        run.return_value.returncode = 0
        run.return_value.stdout = "secret=SHOULD_NOT_APPEAR"
        result = probe.probe(("doctor", "computer-use", "doctor"))
        self.assertEqual(result["elapsed_ms"], 125.0)
        self.assertNotIn("SHOULD_NOT_APPEAR", json.dumps(result))
        self.assertEqual(run.call_args.args[0], ["hermes", "computer-use", "doctor"])
        self.assertEqual(run.call_args.kwargs["stdin"], probe.subprocess.DEVNULL)

    @patch("computer_use_probe.shutil.which", return_value=None)
    def test_missing_executable_is_reported_without_spawning(self, _which):
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = probe.main([])
        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(output.getvalue())["measurements"], [])

    @patch("computer_use_probe.time.perf_counter", side_effect=[1.0, 1.5])
    @patch("computer_use_probe.subprocess.run", side_effect=probe.subprocess.TimeoutExpired("hermes", 1))
    def test_timeout(self, _run, _clock):
        self.assertEqual(probe.probe(("status", "computer-use", "status"))["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
