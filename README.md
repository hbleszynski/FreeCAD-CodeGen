# FreeCAD Text + Drawing Agent

This command-line agent turns a plain-English description and/or a drawing image into FreeCAD Python, validates it, displays it for review, and submits it to the FreeCAD GUI through `Gui.doCommand`. The generated source is retained under `.freecad_agent/runs/` for auditing.

Individual components are modeled in the **Part Design** workbench as Bodies with editable feature histories. Multi-component requests create separate Part Design component files and assemble them through the installed **A2plus** workbench. Generated component and assembly files are kept inside that run's timestamped `.freecad_agent/runs/` directory.

## Download

Open [GitHub Releases](../../releases) and download one of these Windows x64 packages:

- **FreeCAD-Agent-Setup-Windows-x64.exe** — recommended installer. It installs the app for the current user, adds **FreeCAD Agent** to the Start menu, includes an uninstaller, and optionally creates a desktop shortcut.
- **FreeCAD-Agent-Portable-Windows-x64.zip** — portable copy that can be extracted and launched without installation.

Neither package requires Python. Windows 11 on Arm can run the x64 build through Windows emulation. FreeCAD must still be installed separately, and model generation requires either a Codex/ChatGPT sign-in or an Anthropic API key.

## Setup (Windows / PowerShell)

Install FreeCAD 0.21+ from the official FreeCAD distribution and Python 3.10+ from python.org. The Microsoft Store `python.exe` placeholder is not sufficient.

The PowerShell wrapper automatically finds normal per-user Python installations even when the Windows Store alias appears first on `PATH`. You can also set `PYTHON_EXE` to the full interpreter path.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

The default provider reuses Codex authentication from the OpenAI VS Code extension or Codex CLI. The GUI checks this automatically and opens a **Sign in with ChatGPT** page when needed. You can also sign in from PowerShell:

```powershell
.\freecad-agent.ps1 -Login
```

No API key is needed for this mode.

FreeCAD versions installed under the standard per-user or Program Files folders are discovered automatically. If FreeCAD is elsewhere:

```powershell
$env:FREECAD_EXE = "C:\Program Files\FreeCAD 1.0\bin\FreeCAD.exe"
```

## Use

### Standalone Windows app

The ready-to-launch desktop application is:

```text
dist\FreeCAD Agent.exe
```

Double-click it in File Explorer. It runs without a terminal window and does not require a separate Python installation. FreeCAD and either the Codex CLI/VS Code extension or an Anthropic API key are still required for their respective workflows.

To rebuild the executable after changing the source:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-app.ps1
```

The build script installs the build-only dependency, creates a single-file Windows executable, and replaces the existing copy under `dist`.

The executable and application-window icon come from `assets\freecad-agent.png`. Replace that PNG and rebuild to change the artwork in the future.

### Publishing a GitHub release

The `Build Windows release` GitHub Actions workflow tests the project and creates both download packages. A manual workflow run stores them as an Actions artifact. Pushing a version tag publishes them on the repository's Releases page:

```powershell
git tag v0.1.0
git push origin v0.1.0
```

Each release also includes `SHA256SUMS.txt` so downloaded files can be verified.

Build from text and immediately send it to the FreeCAD Python console:

```powershell
freecad-agent "Create a 60 x 40 x 8 mm plate with four 4 mm corner holes"
```

Build from a sketch or technical drawing, with optional clarification:

```powershell
freecad-agent "The annotated dimensions are millimetres; make the part parametric" --image .\bracket.png
```

Attach multiple drawings by repeating `--image`:

```powershell
freecad-agent "Use all views to reconstruct this part" --image .\front.png --image .\side.png --image .\top.png
```

Open the minimal black-and-white GUI:

```powershell
.\freecad-agent.ps1 -Gui
```

The GUI accepts multiple files from the picker or from files copied in Windows Explorer via **Paste Files** or `Ctrl+V`. Choose **Codex** or **Claude** at the top. Codex uses the browser sign-in flow; Claude opens a masked API-key page if `ANTHROPIC_API_KEY` is not already set.

The live **Console Log** shows provider startup, generation, validation, saved-code location, FreeCAD startup, bridge confirmation, cancellation, and errors. **Cancel Preview** stops the current Codex preview (or discards an in-flight API response), while **Cancel Run** also stops a FreeCAD process that is still starting.

Use **Dark Mode** in the provider bar to invert the complete black-and-white interface. The button changes to **Light Mode** so the original palette can be restored.

Review code without starting FreeCAD:

```powershell
freecad-agent "Create a 20 mm cube" --dry-run
```

You can also run it without installing the command alias:

```powershell
python -m freecad_agent "Create a 20 mm cube"
```

Or use the included PowerShell wrapper, which checks the common setup mistakes first:

```powershell
.\freecad-agent.ps1 "Create a 20 mm cube"
```

### Claude pipeline

Claude uses the Anthropic Messages API, including multi-image input and a structured response containing the generated Python. Select **Claude** in the GUI and enter an Anthropic Console API key when prompted. The GUI keeps it only in the current process and does not save it to disk.

For command-line use:

```powershell
$env:ANTHROPIC_API_KEY = "your-anthropic-api-key"
freecad-agent "Create a 20 mm cube" --provider claude
```

You can override the default Claude model with `--model`. An embedded Claude.ai Pro/Max subscription sign-in is intentionally not provided: Anthropic requires third-party tools to use API-key authentication rather than forwarding Claude subscription credentials.

### Optional OpenAI API-key mode

The API is not required. If you specifically want usage-based API access instead, install the optional dependency and select it explicitly:

```powershell
python -m pip install -e ".[api]"
$env:OPENAI_API_KEY = "your-api-key"
freecad-agent "Create a 20 mm cube" --provider api
```

## Safety and limitations

Model-generated code is untrusted. The default validator permits only FreeCAD-related modules and `math`, and blocks file access, dynamic execution, system/process imports, and dunder access. Generated code is printed before execution. `--allow-unsafe` exists for reviewed advanced scripts, but removes this protection.

A single image cannot fully specify hidden geometry or missing dimensions. Add those details in the text prompt. The launcher starts a FreeCAD GUI process; it does not attach to an already-running FreeCAD instance.

Run local tests with:

```powershell
python -m unittest discover -s tests -v
```
