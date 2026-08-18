import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from freecad_agent.runner import FreeCADLaunchCancelled, find_freecad, launch_freecad


class RunnerTests(unittest.TestCase):
    def test_explicit_freecad_path(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "freecad.exe"
            executable.touch()
            self.assertEqual(find_freecad(executable), executable.resolve())

    def test_missing_explicit_path_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            find_freecad(Path("definitely-missing-freecad.exe"))

    @patch("freecad_agent.runner.subprocess.Popen")
    def test_provider_keys_are_not_passed_to_freecad(self, popen):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "freecad.exe"
            executable.touch()
            with patch.dict(
                os.environ,
                {"ANTHROPIC_API_KEY": "anthropic-secret", "OPENAI_API_KEY": "openai-secret"},
            ):
                launch_freecad("import FreeCAD\n", executable, root / "runs")

        child_environment = popen.call_args.kwargs["env"]
        self.assertNotIn("ANTHROPIC_API_KEY", child_environment)
        self.assertNotIn("OPENAI_API_KEY", child_environment)

    @patch("freecad_agent.runner.subprocess.Popen")
    def test_freecad_launch_can_be_cancelled(self, popen):
        process = popen.return_value
        process.poll.return_value = None
        process.wait.return_value = 0
        cancel_event = threading.Event()

        def log(message: str) -> None:
            if message == "Waiting for the FreeCAD Python console bridge...":
                cancel_event.set()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "freecad.exe"
            executable.touch()
            with self.assertRaises(FreeCADLaunchCancelled):
                launch_freecad(
                    "import FreeCAD\n",
                    executable,
                    root / "runs",
                    wait_seconds=2,
                    cancel_event=cancel_event,
                    log=log,
                )
        process.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
