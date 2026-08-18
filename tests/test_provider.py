import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from freecad_agent.generator import (
    GenerationCancelled,
    codex_auth_status,
    find_codex,
    generate_code,
)


class ProviderTests(unittest.TestCase):
    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_code("box", provider="other")

    def test_codex_executable_can_come_from_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "codex.exe"
            executable.touch()
            with patch.dict(os.environ, {"CODEX_EXE": str(executable)}):
                self.assertEqual(find_codex(), executable.resolve())

    def test_claude_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ANTHROPIC_API_KEY"):
                generate_code("box", provider="claude")

    @patch("freecad_agent.generator.subprocess.run")
    @patch("freecad_agent.generator.find_codex", return_value=Path("codex.exe"))
    def test_codex_auth_status(self, _find_codex, run):
        run.return_value = SimpleNamespace(
            returncode=0, stdout="Logged in using ChatGPT\n", stderr=""
        )
        ready, details = codex_auth_status()
        self.assertTrue(ready)
        self.assertIn("ChatGPT", details)
        run.assert_called_once()

    @patch("freecad_agent.generator.subprocess.Popen")
    @patch("freecad_agent.generator.find_codex", return_value=Path("codex.exe"))
    def test_codex_generation_can_be_cancelled(self, _find_codex, popen):
        cancel_event = threading.Event()
        process = popen.return_value
        process.poll.return_value = None
        process.returncode = -1
        process.wait.return_value = -1

        def log(message: str) -> None:
            if message == "Codex is generating FreeCAD Python...":
                cancel_event.set()

        with self.assertRaises(GenerationCancelled):
            generate_code(
                "Make a box",
                provider="codex",
                cancel_event=cancel_event,
                log=log,
            )
        process.terminate.assert_called_once()

    @patch("freecad_agent.generator.urllib.request.urlopen")
    def test_claude_pipeline_sends_multiple_images_and_returns_code(self, urlopen):
        response = MagicMock()
        response.read.return_value = json.dumps(
            {
                "stop_reason": "end_turn",
                "content": [
                    {"type": "text", "text": json.dumps({"code": "import FreeCAD"})}
                ],
            }
        ).encode("utf-8")
        urlopen.return_value.__enter__.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "front.png"
            second = Path(directory) / "side.jpg"
            first.write_bytes(b"png")
            second.write_bytes(b"jpg")
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                code = generate_code("Make the bracket", [first, second], provider="claude")

        self.assertEqual(code, "import FreeCAD\n")
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "claude-sonnet-5")
        self.assertEqual(
            [item["type"] for item in payload["messages"][0]["content"]],
            ["image", "image", "text"],
        )
        self.assertEqual(payload["output_config"]["format"]["type"], "json_schema")


if __name__ == "__main__":
    unittest.main()
