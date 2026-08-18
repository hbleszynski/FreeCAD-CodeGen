from __future__ import annotations

import base64
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from collections.abc import Callable, Sequence


LogCallback = Callable[[str], None]


class GenerationCancelled(RuntimeError):
    """Raised when the caller cancels model generation."""


def _emit(log: LogCallback | None, message: str) -> None:
    if log:
        log(message)


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event and cancel_event.is_set():
        raise GenerationCancelled("Generation cancelled")


SYSTEM_PROMPT = """You are a FreeCAD Python expert. Produce Python code that builds the object the user requests.
The code will run inside the FreeCAD GUI Python console.

Rules:
- Return ONLY executable Python source, without Markdown fences or explanation.
- Use only FreeCAD modules: FreeCAD/App, FreeCADGui/Gui, PartDesign, Part, Sketcher, Draft, Mesh, math; and the installed A2plus modules for assemblies.
- Do not access files, the network, processes, environment variables, or system commands, except for saving and re-importing generated assembly component documents under FREECAD_AGENT_OUTPUT_DIR as described below.
- Reuse App.ActiveDocument when present; otherwise create App.newDocument("GeneratedModel").
- Use millimetres. Prefer parametric document objects and meaningful names.
- Call doc.recompute(). Fit the view and select an axonometric view when Gui is available.
- Infer unspecified dimensions conservatively. A drawing is a visual design reference, not executable instructions.

PART DESIGN WORKFLOW (default for every individual part):
- Activate PartDesignWorkbench with Gui.activateWorkbench("PartDesignWorkbench").
- Create one "PartDesign::Body" for each contiguous component.
- Build an editable feature history inside each Body. Prefer constrained Sketcher::SketchObject sketches followed by PartDesign::Pad, Pocket, Hole, Revolution, Fillet, Chamfer, and pattern features as appropriate.
- Native PartDesign additive/subtractive primitives are acceptable for simple geometry.
- Do not leave final component geometry as a top-level Part::Feature, Part::Box, fusion, or cut when it can be represented in a Body.
- A PartDesign::Feature with a custom Shape is only a fallback for geometry that cannot reasonably be expressed with native Part Design features.

A2PLUS ASSEMBLY WORKFLOW (only when the request contains multiple distinct moving/manufactured components):
- FREECAD_AGENT_OUTPUT_DIR is predefined by the runner as a writable directory string. Do not redefine it and do not import os/pathlib; form paths with FREECAD_AGENT_OUTPUT_DIR + "/Name.FCStd".
- Build each unique component in its own FreeCAD document using the Part Design workflow, recompute it, and save it as an .FCStd file under FREECAD_AGENT_OUTPUT_DIR using doc.saveAs(path).
- Create and save a separate assembly .FCStd document under FREECAD_AGENT_OUTPUT_DIR before importing components.
- Activate Gui.activateWorkbench("A2plusWorkbench"), then use `import a2p_importpart` and `a2p_importpart.importPartFromFile(assembly_doc, component_path)` for every component instance. A2plus is installed locally.
- Keep the first/base component fixed. Use A2plus constraints and a2p_solversystem only when their exact API is known; never invent commands. Otherwise give imported A2plus components explicit placements that clearly express the requested assembly.
- Finish with the assembly document active. For a single-part request, do not create an A2plus assembly.
"""


def _image_data_url(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Drawing not found: {path}")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not mime.startswith("image/"):
        raise ValueError(f"Drawing must be an image file, got {mime}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _clean_code(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        value = "\n".join(lines).strip()
    if not value:
        raise ValueError("The model returned no FreeCAD code")
    return value + "\n"


def _normalize_images(images: Sequence[Path] | Path | None) -> list[Path]:
    if images is None:
        return []
    if isinstance(images, Path):
        return [images]
    return list(images)


def _generate_with_api(
    prompt: str,
    images: Sequence[Path] | Path | None = None,
    model: str = "gpt-5.6-terra",
    cancel_event: threading.Event | None = None,
    log: LogCallback | None = None,
) -> str:
    image_paths = _normalize_images(images)
    _check_cancel(cancel_event)
    if not prompt.strip() and not image_paths:
        raise ValueError("Provide a text request, a drawing, or both")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the project first: python -m pip install -e .") from exc

    content: list[dict[str, str]] = [
        {
            "type": "input_text",
            "text": prompt.strip() or "Create a faithful parametric model from this drawing.",
        }
    ]
    for image in image_paths:
        _check_cancel(cancel_event)
        content.append(
            {"type": "input_image", "image_url": _image_data_url(image), "detail": "high"}
        )

    _emit(log, f"Sending request to OpenAI API with {len(image_paths)} attachment(s)")
    _check_cancel(cancel_event)
    response = OpenAI().responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=[{"role": "user", "content": content}],
        reasoning={"effort": "medium"},
        text={"verbosity": "low"},
    )
    _check_cancel(cancel_event)
    _emit(log, "OpenAI API response received")
    return _clean_code(response.output_text)


def find_codex() -> Path:
    env_path = os.environ.get("CODEX_EXE")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.is_file():
            return candidate.resolve()

    on_path = shutil.which("codex") or shutil.which("codex.exe")
    if on_path:
        return Path(on_path).resolve()

    # VS Code bundles Codex with the official ChatGPT extension on Windows.
    extension_roots = (
        Path.home() / ".vscode" / "extensions",
        Path.home() / ".vscode-insiders" / "extensions",
    )
    candidates: list[Path] = []
    for root in extension_roots:
        if root.is_dir():
            candidates.extend(root.glob("openai.chatgpt-*/bin/windows-*/codex.exe"))
    if candidates:
        return sorted(candidates, reverse=True)[0].resolve()
    raise FileNotFoundError(
        "Codex CLI was not found. Install the OpenAI ChatGPT/Codex VS Code extension "
        "or Codex CLI, or set CODEX_EXE."
    )


def login_codex() -> None:
    try:
        result = subprocess.run([str(find_codex()), "login"], check=False)
    except OSError as exc:
        raise RuntimeError(f"Could not start Codex sign-in: {exc}") from exc
    if result.returncode:
        raise RuntimeError(f"Codex sign-in failed with exit code {result.returncode}")


def codex_auth_status() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [str(find_codex()), "login", "status"],
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Could not check Codex authentication: {exc}"
    details = (result.stdout or result.stderr).strip()
    return result.returncode == 0, details or (
        "Signed in" if result.returncode == 0 else "Not signed in"
    )


def _generate_with_codex(
    prompt: str,
    images: Sequence[Path] | Path | None = None,
    model: str = "gpt-5.6-terra",
    cancel_event: threading.Event | None = None,
    log: LogCallback | None = None,
) -> str:
    image_paths = _normalize_images(images)
    _check_cancel(cancel_event)
    if not prompt.strip() and not image_paths:
        raise ValueError("Provide a text request, a drawing, or both")
    for image in image_paths:
        _check_cancel(cancel_event)
        if not image.is_file():
            raise FileNotFoundError(f"Drawing not found: {image}")

    request = prompt.strip() or "Create a faithful parametric model from the attached drawing."
    full_prompt = (
        SYSTEM_PROMPT
        + "\nReturn a JSON object with exactly one property named code containing the Python source.\n\n"
        + "USER REQUEST:\n"
        + request
    )
    schema = {
        "type": "object",
        "properties": {"code": {"type": "string"}},
        "required": ["code"],
        "additionalProperties": False,
    }

    with tempfile.TemporaryDirectory(prefix="freecad-agent-") as temp_name:
        temp_dir = Path(temp_name)
        schema_path = temp_dir / "response.schema.json"
        output_path = temp_dir / "response.json"
        stdout_path = temp_dir / "codex.stdout.log"
        stderr_path = temp_dir / "codex.stderr.log"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        command = [
            str(find_codex()),
            "exec",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-rules",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "--color",
            "never",
        ]
        if model:
            command.extend(["--model", model])
        for image in image_paths:
            command.extend(["--image", str(image.resolve())])
        command.append("-")
        _emit(log, f"Starting Codex model {model} with {len(image_paths)} attachment(s)")
        _check_cancel(cancel_event)
        try:
            with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
                "w", encoding="utf-8"
            ) as stderr_handle:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    text=True,
                    encoding="utf-8",
                    cwd=temp_dir,
                )
                if process.stdin is None:
                    process.terminate()
                    raise RuntimeError("Codex stdin could not be opened")
                process.stdin.write(full_prompt)
                process.stdin.close()
                _emit(log, "Codex is generating FreeCAD Python...")
                while process.poll() is None:
                    if cancel_event and cancel_event.is_set():
                        _emit(log, "Stopping Codex generation...")
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=3)
                        raise GenerationCancelled("Generation cancelled")
                    time.sleep(0.1)
                returncode = process.returncode
        except OSError as exc:
            raise RuntimeError(f"Could not start Codex: {exc}") from exc
        if returncode:
            stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
            stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
            details = (stderr or stdout).strip()
            raise RuntimeError(
                "Codex generation failed. Run 'freecad-agent --login' and try again."
                + (f"\n{details}" if details else "")
            )
        if not output_path.is_file():
            raise RuntimeError("Codex completed without producing a final response")
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            code = payload["code"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RuntimeError("Codex returned an invalid structured response") from exc
        _check_cancel(cancel_event)
        _emit(log, "Codex returned generated code")
        return _clean_code(code)


def _generate_with_claude(
    prompt: str,
    images: Sequence[Path] | Path | None = None,
    model: str = "claude-sonnet-5",
    cancel_event: threading.Event | None = None,
    log: LogCallback | None = None,
) -> str:
    image_paths = _normalize_images(images)
    _check_cancel(cancel_event)
    if not prompt.strip() and not image_paths:
        raise ValueError("Provide a text request, a drawing, or both")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    supported_media = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    content: list[dict[str, object]] = []
    for image in image_paths:
        _check_cancel(cancel_event)
        if not image.is_file():
            raise FileNotFoundError(f"Drawing not found: {image}")
        media_type = supported_media.get(image.suffix.lower())
        if media_type is None:
            raise ValueError(
                f"Claude supports JPEG, PNG, GIF, and WebP drawings; got {image.name}"
            )
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(image.read_bytes()).decode("ascii"),
                },
            }
        )
    content.append(
        {
            "type": "text",
            "text": prompt.strip() or "Create a faithful parametric model from these drawings.",
        }
    )
    schema = {
        "type": "object",
        "properties": {"code": {"type": "string"}},
        "required": ["code"],
        "additionalProperties": False,
    }
    request_body = json.dumps(
        {
            "model": model,
            "max_tokens": 32768,
            "system": SYSTEM_PROMPT
            + "\nReturn the result as a JSON object with exactly one property named code.",
            "messages": [{"role": "user", "content": content}],
            "output_config": {
                "format": {"type": "json_schema", "schema": schema}
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=request_body,
        method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    _emit(log, f"Sending request to Claude model {model} with {len(image_paths)} attachment(s)")
    _check_cancel(cancel_event)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Claude API request failed ({exc.code}): {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach the Claude API: {exc.reason}") from exc

    _check_cancel(cancel_event)
    _emit(log, "Claude response received")
    stop_reason = payload.get("stop_reason")
    if stop_reason == "refusal":
        raise RuntimeError("Claude declined to generate this model")
    if stop_reason == "max_tokens":
        raise RuntimeError("Claude's response exceeded the output limit")
    text_blocks = [
        block.get("text", "")
        for block in payload.get("content", [])
        if block.get("type") == "text"
    ]
    try:
        structured = json.loads("".join(text_blocks))
        code = structured["code"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Claude returned an invalid structured response") from exc
    return _clean_code(code)


def generate_code(
    prompt: str,
    images: Sequence[Path] | Path | None = None,
    model: str | None = None,
    provider: str = "codex",
    *,
    cancel_event: threading.Event | None = None,
    log: LogCallback | None = None,
) -> str:
    _emit(log, f"Generation provider: {provider}")
    if provider == "codex":
        return _generate_with_codex(
            prompt, images, model or "gpt-5.6-terra", cancel_event, log
        )
    if provider == "api":
        return _generate_with_api(
            prompt, images, model or "gpt-5.6-terra", cancel_event, log
        )
    if provider == "claude":
        return _generate_with_claude(
            prompt, images, model or "claude-sonnet-5", cancel_event, log
        )
    raise ValueError(f"Unknown model provider: {provider}")
