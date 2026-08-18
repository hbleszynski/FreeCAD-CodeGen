from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .generator import generate_code, login_codex
from .runner import launch_freecad
from .safety import UnsafeCodeError, validate_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="freecad-agent",
        description="Generate FreeCAD Python from text/drawings and run it in the GUI console.",
    )
    parser.add_argument("prompt", nargs="?", default="", help="Description of the model to build")
    parser.add_argument(
        "--image",
        type=Path,
        action="append",
        default=[],
        help="Sketch, drawing, or reference image; repeat for multiple files",
    )
    parser.add_argument("--model", help="Provider-specific model override")
    parser.add_argument(
        "--provider",
        choices=("codex", "claude", "api"),
        default="codex",
        help="Use ChatGPT sign-in through Codex (default), Claude API, or OpenAI API",
    )
    parser.add_argument("--login", action="store_true", help="Sign in to Codex with ChatGPT, then exit")
    parser.add_argument("--gui", action="store_true", help="Open the black-and-white desktop interface")
    parser.add_argument("--freecad-exe", type=Path, help="Path to FreeCAD.exe")
    parser.add_argument("--dry-run", action="store_true", help="Print validated code without running FreeCAD")
    parser.add_argument(
        "--allow-unsafe",
        action="store_true",
        help="Skip the generated-code safety policy (review the printed code first)",
    )
    parser.add_argument("--wait", type=float, default=20, help="Seconds to wait for bridge startup")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    def console_log(message: str) -> None:
        print(f"[freecad-agent] {message}", file=sys.stderr)

    try:
        if args.gui:
            from .gui import main as gui_main

            gui_main()
            return 0
        if args.login:
            login_codex()
            print("Codex sign-in completed.")
            return 0
        code = generate_code(
            args.prompt,
            args.image,
            args.model,
            args.provider,
            log=console_log,
        )
        if not args.allow_unsafe:
            console_log("Validating generated Python safety policy...")
            validate_code(code)
            console_log("Generated Python passed safety validation")
        print("\n--- Generated FreeCAD Python ---\n")
        print(code, end="")
        if args.dry_run:
            return 0
        code_path, _ = launch_freecad(
            code,
            args.freecad_exe,
            wait_seconds=args.wait,
            log=console_log,
        )
        print(f"\nSent to the FreeCAD Python console. Saved: {code_path}")
        return 0
    except (FileNotFoundError, RuntimeError, UnsafeCodeError, ValueError) as exc:
        print(f"freecad-agent: {exc}", file=sys.stderr)
        return 2
