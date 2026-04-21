#!/usr/bin/env python3
from __future__ import annotations

import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from stems_injector_core import build_sidecar, report_to_json

APP_TITLE = "Custom Stems UI"
APP_SUBTITLE = "Standalone Serato Stems Builder"
APP_VERSION = "desktop-ui-2026-02-11"


def _normalize(path_text: str) -> Path:
    text = (path_text or "").strip()
    if not text:
        return Path("")
    return Path(text).expanduser()


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_TITLE} ({APP_VERSION})")
        self.root.geometry("1060x760")
        self.root.minsize(920, 660)
        self.root.configure(bg="#0d121b")

        self.mode = tk.StringVar(value="four")
        self.base = tk.StringVar()
        self.vocals = tk.StringVar()
        self.bass = tk.StringVar()
        self.drums = tk.StringVar()
        self.melody = tk.StringVar()
        self.instrumental = tk.StringVar()
        self.copy_to = tk.StringVar()
        self.status = tk.StringVar(value="Ready")

        self._build_style()
        self._build_layout()
        self._apply_mode_visibility()

    def _build_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("Root.TFrame", background="#0d121b")
        style.configure("Card.TFrame", background="#17202f", relief="flat")
        style.configure(
            "Headline.TLabel",
            background="#0d121b",
            foreground="#f5f8ff",
            font=("Avenir Next", 26, "bold"),
        )
        style.configure(
            "Sub.TLabel",
            background="#0d121b",
            foreground="#9ab0cf",
            font=("Avenir Next", 12),
        )
        style.configure(
            "Label.TLabel",
            background="#17202f",
            foreground="#dce6f8",
            font=("Avenir Next", 11, "bold"),
        )
        style.configure(
            "Hint.TLabel",
            background="#17202f",
            foreground="#96a8c6",
            font=("Avenir Next", 10),
        )
        style.configure(
            "Mode.TRadiobutton",
            background="#17202f",
            foreground="#dce6f8",
            font=("Avenir Next", 11, "bold"),
        )
        style.map(
            "Mode.TRadiobutton",
            background=[("active", "#1f2a3f")],
            foreground=[("active", "#f4f7ff")],
        )
        style.configure(
            "Build.TButton",
            font=("Avenir Next", 12, "bold"),
            padding=(16, 12),
        )
        style.configure(
            "Quiet.TButton",
            font=("Avenir Next", 10, "bold"),
            padding=(10, 7),
        )

    def _build_layout(self):
        root_frame = ttk.Frame(self.root, style="Root.TFrame", padding=20)
        root_frame.pack(fill="both", expand=True)

        header = ttk.Frame(root_frame, style="Root.TFrame")
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text=APP_TITLE, style="Headline.TLabel").pack(anchor="w")
        ttk.Label(header, text=APP_SUBTITLE, style="Sub.TLabel").pack(anchor="w", pady=(2, 0))

        mode_card = ttk.Frame(root_frame, style="Card.TFrame", padding=14)
        mode_card.pack(fill="x", pady=(0, 12))
        ttk.Radiobutton(
            mode_card,
            text="4 stems (vocals, bass, drums, melody)",
            variable=self.mode,
            value="four",
            style="Mode.TRadiobutton",
            command=self._apply_mode_visibility,
        ).grid(row=0, column=0, sticky="w", padx=(0, 20))
        ttk.Radiobutton(
            mode_card,
            text="2 stems (vocals + instrumental)",
            variable=self.mode,
            value="two",
            style="Mode.TRadiobutton",
            command=self._apply_mode_visibility,
        ).grid(row=0, column=1, sticky="w")

        form_card = ttk.Frame(root_frame, style="Card.TFrame", padding=14)
        form_card.pack(fill="x", pady=(0, 12))
        form_card.columnconfigure(1, weight=1)

        row = 0
        self._make_file_row(form_card, row, "Base audio file", self.base, "audio"); row += 1
        self._make_file_row(form_card, row, "Vocals MP3", self.vocals, "mp3"); row += 1
        self.bass_row = self._make_file_row(form_card, row, "Bass MP3 (4-stem)", self.bass, "mp3"); row += 1
        self.drums_row = self._make_file_row(form_card, row, "Drums MP3 (4-stem)", self.drums, "mp3"); row += 1
        self.melody_row = self._make_file_row(form_card, row, "Melody MP3 (4-stem)", self.melody, "mp3"); row += 1
        self.instrumental_row = self._make_file_row(
            form_card,
            row,
            "Instrumental MP3 (2-stem)",
            self.instrumental,
            "mp3",
        ); row += 1

        self._make_target_row(form_card, row); row += 1

        button_row = ttk.Frame(form_card, style="Card.TFrame")
        button_row.grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 2))
        self.build_button = ttk.Button(button_row, text="Build Stem File", style="Build.TButton", command=self._start_build)
        self.build_button.pack(side="left")
        ttk.Button(button_row, text="Clear", style="Quiet.TButton", command=self._clear_fields).pack(side="left", padx=(10, 0))

        output_card = ttk.Frame(root_frame, style="Card.TFrame", padding=14)
        output_card.pack(fill="both", expand=True)

        status_row = ttk.Frame(output_card, style="Card.TFrame")
        status_row.pack(fill="x", pady=(0, 8))
        ttk.Label(status_row, text="Status:", style="Label.TLabel").pack(side="left")
        ttk.Label(status_row, textvariable=self.status, style="Hint.TLabel").pack(side="left", padx=(8, 0))

        self.output = ScrolledText(
            output_card,
            wrap="word",
            height=16,
            bg="#0d1422",
            fg="#edf4ff",
            insertbackground="#edf4ff",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#31415f",
            font=("Menlo", 11),
            padx=10,
            pady=10,
        )
        self.output.pack(fill="both", expand=True)
        self.output.insert("1.0", "Build output will appear here.\n")
        self.output.configure(state="disabled")

    def _make_file_row(self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, kind: str):
        ttk.Label(parent, text=label, style="Label.TLabel").grid(row=row, column=0, sticky="w", pady=6, padx=(0, 10))
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", pady=6)

        actions = ttk.Frame(parent, style="Card.TFrame")
        actions.grid(row=row, column=2, sticky="e", pady=6, padx=(10, 0))
        ttk.Button(
            actions,
            text="Browse",
            style="Quiet.TButton",
            command=lambda: self._pick_file(var, kind),
        ).pack(side="left")

        return {
            "label": label,
            "entry": entry,
            "actions": actions,
        }

    def _make_target_row(self, parent: ttk.Frame, row: int):
        ttk.Label(parent, text="Copy output to (optional)", style="Label.TLabel").grid(row=row, column=0, sticky="w", pady=(12, 6), padx=(0, 10))
        ttk.Entry(parent, textvariable=self.copy_to).grid(row=row, column=1, sticky="ew", pady=(12, 6))
        actions = ttk.Frame(parent, style="Card.TFrame")
        actions.grid(row=row, column=2, sticky="e", pady=(12, 6), padx=(10, 0))
        ttk.Button(actions, text="Folder", style="Quiet.TButton", command=self._pick_copy_folder).pack(side="left")
        ttk.Button(actions, text="File", style="Quiet.TButton", command=self._pick_copy_file).pack(side="left", padx=(8, 0))

    def _pick_file(self, var: tk.StringVar, kind: str):
        filetypes = [("All files", "*")]
        if kind == "audio":
            filetypes = [
                ("Audio files", "*.mp3 *.wav *.aif *.aiff *.m4a *.flac *.serato-stems"),
                ("All files", "*"),
            ]
        elif kind == "mp3":
            filetypes = [("MP3 files", "*.mp3"), ("All files", "*")]

        path = filedialog.askopenfilename(parent=self.root, title="Choose file", filetypes=filetypes)
        if path:
            var.set(path)

    def _pick_copy_folder(self):
        path = filedialog.askdirectory(parent=self.root, title="Choose output folder")
        if path:
            self.copy_to.set(path)

    def _pick_copy_file(self):
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Choose output file",
            defaultextension=".serato-stems",
            filetypes=[("Serato stems", "*.serato-stems"), ("All files", "*")],
        )
        if path:
            self.copy_to.set(path)

    def _clear_fields(self):
        for var in (self.base, self.vocals, self.bass, self.drums, self.melody, self.instrumental, self.copy_to):
            var.set("")
        self.status.set("Ready")
        self._set_output("Build output will appear here.\n")
        self._apply_mode_visibility()

    def _apply_mode_visibility(self):
        is_two = self.mode.get() == "two"
        self._toggle_row(self.bass_row, not is_two)
        self._toggle_row(self.drums_row, not is_two)
        self._toggle_row(self.melody_row, not is_two)
        self._toggle_row(self.instrumental_row, is_two)

    @staticmethod
    def _toggle_row(row_widgets: dict, visible: bool):
        for widget in (row_widgets["entry"], row_widgets["actions"]):
            if visible:
                widget.grid()
            else:
                widget.grid_remove()
        parent = row_widgets["entry"].master
        for child in parent.grid_slaves(row=row_widgets["entry"].grid_info()["row"], column=0):
            if visible:
                child.grid()
            else:
                child.grid_remove()

    def _start_build(self):
        error = self._validate_inputs()
        if error:
            messagebox.showerror("Missing input", error, parent=self.root)
            return

        self.build_button.state(["disabled"])
        self.status.set("Building stems file...")
        self._set_output("Running build...\n")

        thread = threading.Thread(target=self._run_build, daemon=True)
        thread.start()

    def _validate_inputs(self) -> str | None:
        base = _normalize(self.base.get())
        vocals = _normalize(self.vocals.get())

        if not base:
            return "Base audio file is required."
        if not base.exists():
            return f"Base audio file not found:\n{base}"
        if not vocals:
            return "Vocals MP3 is required."
        if not vocals.exists():
            return f"Vocals MP3 not found:\n{vocals}"

        if self.mode.get() == "two":
            inst = _normalize(self.instrumental.get())
            if not inst:
                return "Instrumental MP3 is required in 2-stem mode."
            if not inst.exists():
                return f"Instrumental MP3 not found:\n{inst}"
        else:
            bass = _normalize(self.bass.get())
            drums = _normalize(self.drums.get())
            melody = _normalize(self.melody.get())
            for label, path in (("Bass MP3", bass), ("Drums MP3", drums), ("Melody MP3", melody)):
                if not path:
                    return f"{label} is required in 4-stem mode."
                if not path.exists():
                    return f"{label} not found:\n{path}"

        return None

    def _run_build(self):
        try:
            mode = self.mode.get()
            base = _normalize(self.base.get())
            vocals = _normalize(self.vocals.get())
            copy_to_raw = self.copy_to.get().strip()

            if mode == "two":
                report = build_sidecar(
                    base_audio=base,
                    vocals=vocals,
                    bass=None,
                    drums=None,
                    melody=None,
                    instrumental=_normalize(self.instrumental.get()),
                    two_stem_strategy="mute",
                    overwrite=True,
                )
            else:
                report = build_sidecar(
                    base_audio=base,
                    vocals=vocals,
                    bass=_normalize(self.bass.get()),
                    drums=_normalize(self.drums.get()),
                    melody=_normalize(self.melody.get()),
                    instrumental=None,
                    two_stem_strategy="compat",
                    overwrite=True,
                )

            if copy_to_raw:
                out = Path(report["output_sidecar"])
                target = _normalize(copy_to_raw)
                if target.exists() and target.is_dir():
                    dest = target / out.name
                elif str(target).endswith(".serato-stems"):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    dest = target
                else:
                    target.mkdir(parents=True, exist_ok=True)
                    dest = target / out.name
                dest.write_bytes(out.read_bytes())
                report["copied_to"] = str(dest)

            result_json = report_to_json(report)
            self.root.after(0, lambda: self._finish_build(True, result_json))
        except Exception as exc:
            message = f"{exc}\n\n{json.dumps({'mode': self.mode.get()}, indent=2)}"
            self.root.after(0, lambda: self._finish_build(False, message))

    def _finish_build(self, ok: bool, text: str):
        self.build_button.state(["!disabled"])
        if ok:
            self.status.set("Build finished successfully")
            self._set_output(text)
        else:
            self.status.set("Build failed")
            self._set_output(text)
            messagebox.showerror("Build failed", text, parent=self.root)

    def _set_output(self, text: str):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")


def main() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
