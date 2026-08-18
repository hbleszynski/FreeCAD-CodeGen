from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, filedialog, messagebox
import tkinter as tk

from .generator import codex_auth_status, generate_code, login_codex
from .runner import launch_freecad
from .safety import validate_code


IMAGE_TYPES = (
    ("Drawing images", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"),
    ("All files", "*.*"),
)

THEME_COLOR_OPTIONS = (
    "background",
    "foreground",
    "activebackground",
    "activeforeground",
    "insertbackground",
    "selectbackground",
    "selectforeground",
    "troughcolor",
    "highlightbackground",
    "highlightcolor",
)


def _opposite_color(value: str) -> str | None:
    normalized = str(value).lower()
    if normalized in {"white", "#ffffff"}:
        return "black"
    if normalized in {"black", "#000000"}:
        return "white"
    return None


def _asset_path(name: str) -> Path:
    """Resolve an asset from source or a PyInstaller one-file bundle."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return bundle_root / "assets" / name


def _clipboard_file_paths_windows() -> list[Path]:
    """Read Explorer's CF_HDROP clipboard format without extra packages."""
    if not hasattr(ctypes, "windll"):
        return []
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_int
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.restype = ctypes.c_int
    shell32.DragQueryFileW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_wchar_p,
        ctypes.c_uint,
    ]
    shell32.DragQueryFileW.restype = ctypes.c_uint
    cf_hdrop = 15
    if not user32.IsClipboardFormatAvailable(cf_hdrop):
        return []
    if not user32.OpenClipboard(None):
        return []
    try:
        handle = user32.GetClipboardData(cf_hdrop)
        if not handle:
            return []
        count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
        paths: list[Path] = []
        for index in range(count):
            length = shell32.DragQueryFileW(handle, index, None, 0)
            buffer = ctypes.create_unicode_buffer(length + 1)
            shell32.DragQueryFileW(handle, index, buffer, length + 1)
            paths.append(Path(buffer.value))
        return paths
    finally:
        user32.CloseClipboard()


class FreeCADAgentGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.attachments: list[Path] = []
        self.busy = False
        self.operation_id = 0
        self.active_execute: bool | None = None
        self.cancel_event: threading.Event | None = None
        self.dark_mode = False
        self.codex_signed_in = False
        self.auth_window: tk.Toplevel | None = None
        self.provider = tk.StringVar(value="codex")

        root.title("FreeCAD Agent")
        icon_path = _asset_path("freecad-agent.png")
        if icon_path.is_file():
            self.app_icon = tk.PhotoImage(file=str(icon_path))
            root.iconphoto(True, self.app_icon)
        root.geometry("820x760")
        root.minsize(680, 620)
        root.configure(bg="white")

        self._label("MODEL PROVIDER").pack(anchor="w", padx=18, pady=(18, 6))
        provider_frame = tk.Frame(root, bg="white")
        provider_frame.pack(fill=X, padx=18)
        for text, value in (("CODEX", "codex"), ("CLAUDE", "claude")):
            tk.Radiobutton(
                provider_frame,
                text=text,
                value=value,
                variable=self.provider,
                command=self.provider_changed,
                bg="white",
                fg="black",
                activebackground="white",
                activeforeground="black",
                selectcolor="white",
                highlightthickness=0,
            ).pack(side=LEFT, padx=(0, 12))
        self.provider_status = tk.Label(
            provider_frame,
            text="CHECKING SIGN-IN...",
            bg="white",
            fg="black",
            anchor="e",
        )
        self.provider_status.pack(side=RIGHT)
        self.theme_button = self._button(provider_frame, "DARK MODE", self.toggle_theme)
        self.theme_button.pack(side=RIGHT, padx=(0, 12))

        self._label("DESCRIBE THE MODEL").pack(anchor="w", padx=18, pady=(14, 6))
        self.prompt = tk.Text(
            root,
            height=8,
            bg="white",
            fg="black",
            insertbackground="black",
            selectbackground="black",
            selectforeground="white",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            wrap="word",
        )
        self.prompt.pack(fill=X, padx=18)

        self._label("ATTACHED DRAWINGS").pack(anchor="w", padx=18, pady=(16, 6))
        list_frame = tk.Frame(root, bg="white")
        list_frame.pack(fill=BOTH, expand=True, padx=18)
        scrollbar = tk.Scrollbar(list_frame, bg="white", troughcolor="white")
        scrollbar.pack(side=RIGHT, fill=Y)
        self.file_list = tk.Listbox(
            list_frame,
            bg="white",
            fg="black",
            selectbackground="black",
            selectforeground="white",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            activestyle="none",
            selectmode="extended",
            yscrollcommand=scrollbar.set,
        )
        self.file_list.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.configure(command=self.file_list.yview)

        file_buttons = tk.Frame(root, bg="white")
        file_buttons.pack(fill=X, padx=18, pady=8)
        self._button(file_buttons, "UPLOAD FILES", self.upload_files).pack(side=LEFT)
        self._button(file_buttons, "PASTE FILES", self.paste_files).pack(side=LEFT, padx=8)
        self._button(file_buttons, "REMOVE", self.remove_files).pack(side=LEFT)

        action_frame = tk.Frame(root, bg="white")
        action_frame.pack(fill=X, padx=18, pady=(8, 6))
        self.preview_button = self._button(action_frame, "PREVIEW CODE", lambda: self.start(False))
        self.preview_button.pack(side=LEFT)
        self.cancel_preview_button = self._button(
            action_frame, "CANCEL PREVIEW", lambda: self.cancel(False)
        )
        self.cancel_preview_button.pack(side=LEFT, padx=8)
        self.cancel_preview_button.configure(state="disabled")
        self.run_button = self._button(action_frame, "GENERATE + RUN", lambda: self.start(True), invert=True)
        self.run_button.pack(side=RIGHT)
        self.cancel_run_button = self._button(
            action_frame, "CANCEL RUN", lambda: self.cancel(True)
        )
        self.cancel_run_button.pack(side=RIGHT, padx=8)
        self.cancel_run_button.configure(state="disabled")

        self._label("CONSOLE LOG").pack(anchor="w", padx=18, pady=(8, 6))
        console_frame = tk.Frame(root, bg="white")
        console_frame.pack(fill=X, padx=18)
        console_scrollbar = tk.Scrollbar(console_frame, bg="white", troughcolor="white")
        console_scrollbar.pack(side=RIGHT, fill=Y)
        self.console = tk.Text(
            console_frame,
            height=8,
            bg="white",
            fg="black",
            insertbackground="black",
            selectbackground="black",
            selectforeground="white",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            wrap="word",
            state="disabled",
            yscrollcommand=console_scrollbar.set,
            font=("Courier New", 9),
        )
        self.console.pack(side=LEFT, fill=X, expand=True)
        console_scrollbar.configure(command=self.console.yview)

        self.status = self._label("READY")
        self.status.pack(anchor="w", padx=18, pady=(2, 14))
        # Keep normal Ctrl+V text pasting in the prompt; paste copied Explorer
        # files when the attachment list has focus.
        self.file_list.bind("<Control-v>", lambda _event: self.paste_files())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.append_log("FreeCAD Agent ready")
        self.root.after(100, lambda: self.check_provider_auth(show_dialog=True))

    def _label(self, text: str) -> tk.Label:
        return tk.Label(self.root, text=text, bg="white", fg="black", anchor="w")

    @staticmethod
    def _button(parent: tk.Misc, text: str, command, invert: bool = False) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg="black" if invert else "white",
            fg="white" if invert else "black",
            activebackground="white" if invert else "black",
            activeforeground="black" if invert else "white",
            relief="solid",
            borderwidth=1,
            padx=12,
            pady=5,
        )

    def toggle_theme(self) -> None:
        self.dark_mode = not self.dark_mode
        self._invert_widget_colors(self.root)
        self._set_dark_boundaries(self.root, self.dark_mode)
        self.theme_button.configure(text="LIGHT MODE" if self.dark_mode else "DARK MODE")
        self.append_log("Dark mode enabled" if self.dark_mode else "Light mode enabled")

    def _invert_widget_colors(self, widget: tk.Misc) -> None:
        available = widget.configure()
        changes: dict[str, str] = {}
        for option in THEME_COLOR_OPTIONS:
            if option not in available:
                continue
            opposite = _opposite_color(widget.cget(option))
            if opposite:
                changes[option] = opposite
        if changes:
            widget.configure(**changes)
        for child in widget.winfo_children():
            self._invert_widget_colors(child)

    def _set_dark_boundaries(self, widget: tk.Misc, enabled: bool) -> None:
        if isinstance(widget, (tk.Text, tk.Entry, tk.Listbox)):
            widget.configure(
                highlightthickness=1 if enabled else 0,
                highlightbackground="white" if enabled else "black",
                highlightcolor="white" if enabled else "black",
            )
        for child in widget.winfo_children():
            self._set_dark_boundaries(child, enabled)

    def upload_files(self) -> None:
        selected = filedialog.askopenfilenames(title="Attach drawings", filetypes=IMAGE_TYPES)
        self.add_files(Path(path) for path in selected)

    def paste_files(self) -> None:
        paths = _clipboard_file_paths_windows()
        if not paths:
            try:
                text = self.root.clipboard_get()
                paths = [Path(value) for value in self.root.tk.splitlist(text)]
            except tk.TclError:
                paths = []
        existing = [path for path in paths if path.is_file()]
        if not existing:
            self.set_status("CLIPBOARD DOES NOT CONTAIN FILES")
            return
        self.add_files(existing)

    def add_files(self, paths) -> None:
        known = {path.resolve() for path in self.attachments}
        added = 0
        for path in paths:
            resolved = Path(path).resolve()
            if resolved.is_file() and resolved not in known:
                self.attachments.append(resolved)
                self.file_list.insert(END, str(resolved))
                known.add(resolved)
                added += 1
        self.set_status(f"{added} FILE(S) ADDED" if added else "NO NEW FILES ADDED")

    def remove_files(self) -> None:
        indexes = list(self.file_list.curselection())
        for index in reversed(indexes):
            self.file_list.delete(index)
            del self.attachments[index]
        self.set_status(f"{len(indexes)} FILE(S) REMOVED")

    def set_status(self, text: str) -> None:
        self.status.configure(text=text.upper())

    def append_log(self, message: str, operation_id: int | None = None) -> None:
        if operation_id is not None and operation_id != self.operation_id:
            return
        timestamp = time.strftime("%H:%M:%S")
        self.console.configure(state="normal")
        self.console.insert(END, f"[{timestamp}] {message}\n")
        self.console.see(END)
        self.console.configure(state="disabled")

    def provider_changed(self) -> None:
        self.append_log(f"Provider changed to {self.provider.get()}")
        self.check_provider_auth(show_dialog=True)

    def check_provider_auth(self, show_dialog: bool = False) -> None:
        if self.provider.get() == "claude":
            ready = bool(os.environ.get("ANTHROPIC_API_KEY"))
            self.provider_status.configure(
                text="CLAUDE: API KEY READY" if ready else "CLAUDE: API KEY REQUIRED"
            )
            if not ready and show_dialog:
                self.show_auth_dialog("claude")
            return

        self.provider_status.configure(text="CODEX: CHECKING SIGN-IN...")

        def check() -> None:
            ready, details = codex_auth_status()
            self.root.after(0, self._codex_auth_checked, ready, details, show_dialog)

        threading.Thread(target=check, daemon=True).start()

    def _codex_auth_checked(
        self, ready: bool, details: str, show_dialog: bool
    ) -> None:
        self.codex_signed_in = ready
        if self.provider.get() != "codex":
            return
        self.provider_status.configure(
            text="CODEX: SIGNED IN" if ready else "CODEX: SIGN IN REQUIRED"
        )
        self.append_log("Codex sign-in confirmed" if ready else f"Codex sign-in required: {details}")
        if not ready and show_dialog:
            self.show_auth_dialog("codex", details)
        elif ready and self.auth_window and self.auth_window.winfo_exists():
            self.auth_window.destroy()
            self.auth_window = None

    def show_auth_dialog(self, provider: str, details: str = "") -> None:
        if self.auth_window and self.auth_window.winfo_exists():
            self.auth_window.destroy()

        window = tk.Toplevel(self.root)
        self.auth_window = window
        window.title("Connect model provider")
        window.geometry("460x260" if provider == "codex" else "460x300")
        window.resizable(False, False)
        window.configure(bg="white")
        window.transient(self.root)
        window.grab_set()
        window.protocol("WM_DELETE_WINDOW", self._close_auth_dialog)

        heading = "SIGN IN TO CODEX" if provider == "codex" else "CONNECT CLAUDE"
        tk.Label(
            window,
            text=heading,
            bg="white",
            fg="black",
            font=("TkDefaultFont", 14, "bold"),
        ).pack(anchor="w", padx=22, pady=(22, 8))

        if provider == "codex":
            tk.Label(
                window,
                text=(
                    "Sign in with your ChatGPT account in the browser. The Codex CLI "
                    "stores the login, so no API key is needed."
                ),
                bg="white",
                fg="black",
                justify=LEFT,
                wraplength=410,
            ).pack(anchor="w", padx=22)
            self.auth_message = tk.Label(
                window,
                text=details or "NOT SIGNED IN",
                bg="white",
                fg="black",
                justify=LEFT,
                wraplength=410,
            )
            self.auth_message.pack(anchor="w", padx=22, pady=(14, 10))
            self.auth_action = self._button(
                window, "SIGN IN WITH CHATGPT", self.start_codex_login, invert=True
            )
            self.auth_action.pack(anchor="w", padx=22)
        else:
            tk.Label(
                window,
                text=(
                    "Claude uses an Anthropic Console API key. The key is kept only "
                    "for this app session and is not written to disk."
                ),
                bg="white",
                fg="black",
                justify=LEFT,
                wraplength=410,
            ).pack(anchor="w", padx=22)
            self.claude_key = tk.Entry(
                window,
                show="*",
                bg="white",
                fg="black",
                insertbackground="black",
                relief="solid",
                borderwidth=1,
            )
            self.claude_key.pack(fill=X, padx=22, pady=(16, 10), ipady=5)
            self.auth_message = tk.Label(
                window,
                text="ENTER ANTHROPIC_API_KEY",
                bg="white",
                fg="black",
                anchor="w",
            )
            self.auth_message.pack(fill=X, padx=22, pady=(0, 8))
            self.auth_action = self._button(
                window, "USE API KEY", self.use_claude_key, invert=True
            )
            self.auth_action.pack(anchor="w", padx=22)
            self.claude_key.focus_set()
            self.claude_key.bind("<Return>", lambda _event: self.use_claude_key())

        if self.dark_mode:
            self._invert_widget_colors(window)
            self._set_dark_boundaries(window, True)

    def _close_auth_dialog(self) -> None:
        if self.auth_window and self.auth_window.winfo_exists():
            self.auth_window.destroy()
        self.auth_window = None

    def start_codex_login(self) -> None:
        self.auth_action.configure(state="disabled")
        self.auth_message.configure(text="OPENING BROWSER — COMPLETE SIGN-IN THERE...")

        def login() -> None:
            try:
                login_codex()
                ready, details = codex_auth_status()
                if not ready:
                    raise RuntimeError(details)
                self.root.after(0, self._codex_login_finished, None)
            except Exception as exc:
                self.root.after(0, self._codex_login_finished, str(exc))

        threading.Thread(target=login, daemon=True).start()

    def _codex_login_finished(self, error: str | None) -> None:
        if error:
            if self.auth_window and self.auth_window.winfo_exists():
                self.auth_action.configure(state="normal")
                self.auth_message.configure(text=error)
            return
        self.codex_signed_in = True
        self.provider_status.configure(text="CODEX: SIGNED IN")
        self._close_auth_dialog()
        self.set_status("CODEX SIGN-IN COMPLETE")
        self.append_log("Codex sign-in completed")

    def use_claude_key(self) -> None:
        key = self.claude_key.get().strip()
        if not key:
            self.auth_message.configure(text="API KEY CANNOT BE EMPTY")
            return
        os.environ["ANTHROPIC_API_KEY"] = key
        self.provider_status.configure(text="CLAUDE: API KEY READY")
        self._close_auth_dialog()
        self.set_status("CLAUDE API KEY READY")
        self.append_log("Claude API key loaded for this session")

    def provider_is_ready(self) -> bool:
        if self.provider.get() == "claude":
            return bool(os.environ.get("ANTHROPIC_API_KEY"))
        return self.codex_signed_in

    def start(self, execute: bool) -> None:
        if self.busy:
            return
        if not self.provider_is_ready():
            self.show_auth_dialog(self.provider.get())
            return
        prompt = self.prompt.get("1.0", END).strip()
        if not prompt and not self.attachments:
            self.set_status("ENTER TEXT OR ATTACH A FILE")
            return
        self.operation_id += 1
        operation_id = self.operation_id
        cancel_event = threading.Event()
        self.cancel_event = cancel_event
        self.active_execute = execute
        self.busy = True
        self.preview_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        self.cancel_preview_button.configure(state="normal" if not execute else "disabled")
        self.cancel_run_button.configure(state="normal" if execute else "disabled")
        self.set_status("GENERATING...")
        action = "Generate + run" if execute else "Preview"
        self.append_log(
            f"{action} started with provider {self.provider.get()} and "
            f"{len(self.attachments)} attachment(s)",
            operation_id,
        )
        threading.Thread(
            target=self._work,
            args=(
                prompt,
                list(self.attachments),
                execute,
                self.provider.get(),
                operation_id,
                cancel_event,
            ),
            daemon=True,
        ).start()

    def _work(
        self,
        prompt: str,
        attachments: list[Path],
        execute: bool,
        provider: str,
        operation_id: int,
        cancel_event: threading.Event,
    ) -> None:
        def log(message: str) -> None:
            self.root.after(0, self.append_log, message, operation_id)

        try:
            code = generate_code(
                prompt,
                attachments,
                provider=provider,
                cancel_event=cancel_event,
                log=log,
            )
            if cancel_event.is_set():
                return
            log("Validating generated Python safety policy...")
            validate_code(code)
            log("Generated Python passed safety validation")
            code_path = None
            if execute:
                code_path, _ = launch_freecad(
                    code,
                    wait_seconds=20,
                    cancel_event=cancel_event,
                    log=log,
                )
            if not cancel_event.is_set():
                self.root.after(0, self._success, operation_id, code, code_path)
        except Exception as exc:
            if not cancel_event.is_set():
                self.root.after(0, self._failure, operation_id, str(exc))

    def cancel(self, execute: bool) -> None:
        if not self.busy or self.active_execute is not execute or not self.cancel_event:
            return
        self.cancel_event.set()
        self.operation_id += 1
        action = "generate + run" if execute else "preview"
        self.append_log(f"Cancellation requested for {action}")
        self._set_idle()
        self.set_status(f"{action} cancelled")

    def _success(
        self, operation_id: int, code: str, code_path: Path | None
    ) -> None:
        if operation_id != self.operation_id:
            return
        self._set_idle()
        if code_path:
            self.set_status(f"SENT TO FREECAD — {code_path.name}")
            self.append_log("Generate + run completed")
        else:
            self.set_status("CODE GENERATED")
            self.append_log("Preview generation completed")
            self.show_code(code)

    def _failure(self, operation_id: int, error: str) -> None:
        if operation_id != self.operation_id:
            return
        self._set_idle()
        self.set_status("ERROR")
        self.append_log(f"ERROR: {error}")
        messagebox.showerror("FreeCAD Agent", error, parent=self.root)

    def _set_idle(self) -> None:
        self.busy = False
        self.active_execute = None
        self.cancel_event = None
        self.preview_button.configure(state="normal")
        self.run_button.configure(state="normal")
        self.cancel_preview_button.configure(state="disabled")
        self.cancel_run_button.configure(state="disabled")

    def close(self) -> None:
        if self.cancel_event:
            self.cancel_event.set()
        self.root.destroy()

    def show_code(self, code: str) -> None:
        window = tk.Toplevel(self.root)
        window.title("Generated FreeCAD Python")
        window.geometry("760x520")
        window.configure(bg="white")
        text = tk.Text(
            window,
            bg="white",
            fg="black",
            insertbackground="black",
            relief="solid",
            borderwidth=1,
            wrap="none",
        )
        text.pack(fill=BOTH, expand=True, padx=12, pady=12)
        text.insert("1.0", code)
        if self.dark_mode:
            self._invert_widget_colors(window)
            self._set_dark_boundaries(window, True)


def main() -> None:
    root = tk.Tk()
    FreeCADAgentGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
