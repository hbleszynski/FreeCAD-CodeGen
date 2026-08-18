from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from collections.abc import Callable


LogCallback = Callable[[str], None]


class FreeCADLaunchCancelled(RuntimeError):
    """Raised when the caller cancels while FreeCAD is starting."""


def _emit(log: LogCallback | None, message: str) -> None:
    if log:
        log(message)


def _windows_freecad_candidates() -> list[Path]:
    roots = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    ]
    candidates: list[Path] = []
    for root in roots:
        if root.is_dir():
            candidates.extend(root.glob("FreeCAD*/bin/[Ff]ree[Cc][Aa][Dd].exe"))
    return sorted(
        (path for path in candidates if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def find_freecad(explicit: Path | None = None) -> Path:
    if explicit is not None:
        candidate = explicit.expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"FreeCAD executable not found: {candidate}")
        return candidate

    env_path = os.environ.get("FREECAD_EXE")
    candidates = ([Path(env_path)] if env_path else []) + _windows_freecad_candidates()
    on_path = shutil.which("FreeCAD") or shutil.which("FreeCAD.exe")
    if on_path:
        candidates.insert(0, Path(on_path))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "FreeCAD was not found. Pass --freecad-exe or set the FREECAD_EXE environment variable."
    )


def _bridge_source(code: str, status_path: Path, output_dir: Path) -> str:
    payload = repr(code)
    status = repr(str(status_path))
    generated_output = repr(str(output_dir))
    return f'''# Generated FreeCAD Agent bridge. Runs inside FreeCAD, not system Python.
import json
import traceback
import FreeCAD as App
import FreeCADGui as Gui

try:
    main_window = Gui.getMainWindow()
    # Make the Python console visible when its dock is available. PySide changed
    # module layout between FreeCAD releases, so support both bindings.
    try:
        from PySide import QtGui
        dock_type = QtGui.QDockWidget
    except (ImportError, AttributeError):
        from PySide2 import QtWidgets
        dock_type = QtWidgets.QDockWidget
    for dock in main_window.findChildren(dock_type):
        identity = (dock.objectName() + " " + dock.windowTitle()).lower()
        if "python" in identity and "console" in identity:
            dock.show()
            dock.raise_()
    # Give generated assembly code one controlled location for component files.
    Gui.doCommand("FREECAD_AGENT_OUTPUT_DIR = " + repr({generated_output}))
    # A single exec command preserves multiline generated source in console history.
    Gui.doCommand("exec(" + repr({payload}) + ")")
    with open({status}, "w", encoding="utf-8") as handle:
        json.dump({{"ok": True}}, handle)
except Exception:
    with open({status}, "w", encoding="utf-8") as handle:
        json.dump({{"ok": False, "error": traceback.format_exc()}}, handle)
    raise
'''


def launch_freecad(
    code: str,
    executable: Path | None = None,
    run_dir: Path = Path(".freecad_agent/runs"),
    wait_seconds: float = 0,
    cancel_event: threading.Event | None = None,
    log: LogCallback | None = None,
) -> tuple[Path, subprocess.Popen[bytes]]:
    if cancel_event and cancel_event.is_set():
        raise FreeCADLaunchCancelled("FreeCAD launch cancelled")
    freecad = find_freecad(executable)
    run_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    output_dir = (run_dir / stamp).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    code_path = output_dir / "model.py"
    bridge_path = output_dir / "bridge.py"
    status_path = output_dir / "status.json"
    code_path.write_text(code, encoding="utf-8")
    bridge_path.write_text(_bridge_source(code, status_path, output_dir), encoding="utf-8")
    _emit(log, f"Saved generated code to {code_path}")

    # Provider credentials are needed by this process only. Do not expose them
    # to FreeCAD or to generated console code through the child environment.
    child_environment = os.environ.copy()
    child_environment.pop("ANTHROPIC_API_KEY", None)
    child_environment.pop("OPENAI_API_KEY", None)
    try:
        process = subprocess.Popen(
            [str(freecad), str(bridge_path)], env=child_environment
        )
    except OSError as exc:
        raise RuntimeError(f"Could not start FreeCAD at {freecad}: {exc}") from exc
    _emit(log, f"Started FreeCAD: {freecad}")
    if wait_seconds > 0:
        _emit(log, "Waiting for the FreeCAD Python console bridge...")
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline and not status_path.exists() and process.poll() is None:
            if cancel_event and cancel_event.is_set():
                _emit(log, "Stopping the FreeCAD process...")
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise FreeCADLaunchCancelled("FreeCAD launch cancelled")
            time.sleep(0.1)
        if status_path.exists():
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if not status.get("ok"):
                raise RuntimeError(status.get("error", "FreeCAD bridge failed"))
            _emit(log, "FreeCAD confirmed the console command")
        elif process.poll() is not None:
            raise RuntimeError(f"FreeCAD exited before running the console bridge (exit {process.returncode})")
        else:
            raise RuntimeError(
                f"FreeCAD started, but the console bridge was not confirmed within {wait_seconds:g} seconds"
            )
    return code_path, process
