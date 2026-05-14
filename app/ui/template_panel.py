import random
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from app.engine.wildcard import build_template_directives, parse_template_directives
from app.settings import AppSettings
from app.template_library import TemplateLibrary
from app.ui.utils import center_input_dialog, tip


class TemplatePanel(ctk.CTkFrame):
    def __init__(self, master, settings: AppSettings, wildcards_dir: str, tpl_library: TemplateLibrary, on_font_size_change=None):
        super().__init__(master)
        self._settings = settings
        self._tpl_library = tpl_library
        self._locks: list[tuple[str, tk.StringVar, tk.BooleanVar]] = []
        self._lock_row_frames: list[ctk.CTkFrame] = []
        self._seq_wildcards: list[str] = []
        self._seq_row_frames: list[ctk.CTkFrame] = []
        self._font_size: int = settings.get("font_size", 11)
        self._on_font_size_change = on_font_size_change
        self._build(settings, wildcards_dir)

    def _build(self, settings: AppSettings, wildcards_dir: str):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._neg_expanded = False

        # Initialized early so _get_wildcard_names() works before the dir row is built
        self._wc_var = tk.StringVar(value=wildcards_dir)
        self._wc_var.trace_add("write", self._on_wc_dir_changed)

        # ── Header row: title + save/load controls ───────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            hdr, text="Prompt Template", font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))

        self._tpl_name_var = tk.StringVar()
        ctk.CTkEntry(
            hdr, textvariable=self._tpl_name_var, placeholder_text="template name...", height=28
        ).grid(row=0, column=1, sticky="ew", padx=(0, 4))

        save_btn = ctk.CTkButton(hdr, text="Save", width=55, height=28, command=self._save_template)
        save_btn.grid(row=0, column=2, padx=(0, 4))
        tip(save_btn, "Save template with current lock/sequential settings")

        mgr_btn = ctk.CTkButton(hdr, text="Templates…", width=96, height=28, command=self._open_manager)
        mgr_btn.grid(row=0, column=3, padx=(0, 12))
        tip(mgr_btn, "Browse, load, rename or delete saved templates")

        a_minus = ctk.CTkButton(hdr, text="A−", width=30, height=28, command=lambda: self._change_font_size(-1))
        a_minus.grid(row=0, column=4, padx=(0, 2))
        tip(a_minus, "Decrease font size")

        self._font_size_label = ctk.CTkLabel(hdr, text=str(self._font_size), width=26, anchor="center")
        self._font_size_label.grid(row=0, column=5)

        a_plus = ctk.CTkButton(hdr, text="A+", width=30, height=28, command=lambda: self._change_font_size(1))
        a_plus.grid(row=0, column=6, padx=(2, 0))
        tip(a_plus, "Increase font size")

        # ── Template textbox ─────────────────────────────────────────────────
        self._textbox = ctk.CTkTextbox(self, wrap="word", font=("Segoe UI", self._font_size))
        self._textbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 4))

        # ── Negative template (collapsible) ───────────────────────────────────
        neg_hdr = ctk.CTkFrame(self, fg_color="transparent")
        neg_hdr.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 2))
        neg_hdr.grid_columnconfigure(1, weight=1)

        self._neg_toggle_btn = ctk.CTkButton(
            neg_hdr, text="▶", width=26, height=22,
            command=self._toggle_neg_template,
            fg_color="transparent", hover_color="#3d3d3d",
            font=ctk.CTkFont(size=11),
        )
        self._neg_toggle_btn.grid(row=0, column=0, padx=(0, 6))
        ctk.CTkLabel(
            neg_hdr, text="Negative Template", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=1, sticky="w")

        self._neg_textbox = ctk.CTkTextbox(self, wrap="word", font=("Segoe UI", self._font_size), height=80)
        self._neg_textbox.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 4))
        self._neg_textbox.grid_remove()

        # ── Quick-insert buttons ──────────────────────────────────────────────
        qrow = ctk.CTkFrame(self, fg_color="transparent")
        qrow.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 6))
        ctk.CTkLabel(qrow, text="Insert:").pack(side="left", padx=(0, 6))
        b = ctk.CTkButton(qrow, text="{a|b|c}", width=80, command=lambda: self._insert("{option1|option2|option3}"))
        b.pack(side="left", padx=(0, 4))
        tip(b, "Insert inline choice — pick one option randomly per prompt")

        b = ctk.CTkButton(qrow, text="__wc__", width=72, command=lambda: self._insert("__wildcard__"))
        b.pack(side="left", padx=(0, 4))
        tip(b, "Insert file wildcard — loads a .txt file and picks a random line")

        b = ctk.CTkButton(qrow, text="[@1-3:]", width=76, command=lambda: self._insert("[@1-3: ]"))
        b.pack(side="left", padx=(0, 8))
        tip(b, "Insert conditional block — content only included on specified prompt numbers")

        ctk.CTkLabel(qrow, text="|", text_color="gray").pack(side="left", padx=(0, 8))
        self._insert_wc_combo = self._make_ac_combo(qrow, self._insert_wc_from_combo)
        self._insert_wc_combo.configure(width=150)
        self._insert_wc_combo.pack(side="left", padx=(0, 4))

        b = ctk.CTkButton(qrow, text="↩", width=36, command=self._insert_wc_from_combo)
        b.pack(side="left", padx=(0, 4))
        tip(b, "Insert selected wildcard into template at cursor")

        b = ctk.CTkButton(qrow, text="Clear", width=60, fg_color="#6b3535", hover_color="#8b4545", command=self._clear_template)
        b.pack(side="right")
        tip(b, "Clear the template editor")

        # ── Count spinner ─────────────────────────────────────────────────────
        count_row = ctk.CTkFrame(self, fg_color="transparent")
        count_row.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 6))
        ctk.CTkLabel(count_row, text="Prompts to generate:").pack(side="left", padx=(0, 8))
        self._count_var = tk.IntVar(value=settings.get("last_count", 10))
        ctk.CTkButton(
            count_row, text="−", width=30,
            command=lambda: self._count_var.set(max(1, self._count_var.get() - 1))
        ).pack(side="left")
        ctk.CTkEntry(
            count_row, textvariable=self._count_var, width=52, justify="center"
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            count_row, text="+", width=30,
            command=lambda: self._count_var.set(min(200, self._count_var.get() + 1))
        ).pack(side="left")

        # ── Wildcards dir ─────────────────────────────────────────────────────
        wc_row = ctk.CTkFrame(self, fg_color="transparent")
        wc_row.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 8))
        wc_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(wc_row, text="Wildcards dir:").grid(row=0, column=0, padx=(0, 6))
        ctk.CTkEntry(wc_row, textvariable=self._wc_var).grid(
            row=0, column=1, sticky="ew", padx=(0, 4)
        )
        ctk.CTkButton(wc_row, text="Browse", width=70, command=self._browse).grid(row=0, column=2)

        self._build_locks_section()
        self._build_seq_section()

        saved_name = settings.get("last_template_name", "")
        if saved_name:
            self._tpl_name_var.set(saved_name)

        initial = settings.get("last_template", "")
        if initial:
            self._init_from_saved_template(initial)

        neg_initial = settings.get("last_negative_template", "")
        if neg_initial:
            self._neg_textbox.insert("1.0", neg_initial)
            self._toggle_neg_template()

    def _toggle_neg_template(self):
        if self._neg_expanded:
            self._neg_textbox.grid_remove()
            self._neg_toggle_btn.configure(text="▶")
            self._neg_expanded = False
        else:
            self._neg_textbox.grid()
            self._neg_toggle_btn.configure(text="▼")
            self._neg_expanded = True

    # ── Save / Load ───────────────────────────────────────────────────────────

    def _save_template(self):
        text = self.get_template()
        if not text.strip():
            return
        name = self._tpl_name_var.get().strip()
        if not name:
            dialog = ctk.CTkInputDialog(text="Template name:", title="Save Template")
            center_input_dialog(dialog, self)
            name = dialog.get_input()
            if not name or not name.strip():
                return
            name = name.strip()
            self._tpl_name_var.set(name)
        self._tpl_library.save_template(name, self.get_template_for_save())

    def _open_manager(self):
        from app.ui.template_manager import TemplateManager
        TemplateManager(self, library=self._tpl_library, on_load=self._load_template)

    def _load_template(self, name: str, text: str):
        self._tpl_name_var.set(name)
        self._init_from_saved_template(text, clear_first=True)

    def _init_from_saved_template(self, text: str, clear_first: bool = False):
        """Parse directives from text and populate editor + lock/seq panels."""
        clean, lock_names, seq_names, regen_flags, negative_text = parse_template_directives(text)
        self._textbox.delete("1.0", tk.END)
        if clean:
            self._textbox.insert("1.0", clean)
        if negative_text:
            self._neg_textbox.delete("1.0", tk.END)
            self._neg_textbox.insert("1.0", negative_text)
            if not self._neg_expanded:
                self._toggle_neg_template()
        if clear_first or lock_names:
            if clear_first:
                self._locks.clear()
            for name in lock_names:
                if name not in [n for n, _, _ in self._locks]:
                    regen = regen_flags.get(name.lower(), False)
                    self._locks.append((name, tk.StringVar(value=""), tk.BooleanVar(value=regen)))
            self._rebuild_lock_rows()
        if clear_first or seq_names:
            if clear_first:
                self._seq_wildcards.clear()
            existing = {n for n, _, _ in self._locks}
            for name in seq_names:
                if name not in self._seq_wildcards and name not in existing:
                    self._seq_wildcards.append(name)
            self._rebuild_seq_rows()

    # ── Wildcard name helpers ─────────────────────────────────────────────────

    def _get_wildcard_names(self) -> list[str]:
        wc_dir = self.get_wildcards_dir()
        if not wc_dir.is_dir():
            return []
        return sorted(p.stem for p in wc_dir.glob("*.txt"))

    def _make_ac_combo(self, parent: ctk.CTkFrame, add_fn) -> ctk.CTkComboBox:
        names = self._get_wildcard_names()
        combo = ctk.CTkComboBox(
            parent, values=names, height=28,
            command=lambda val: add_fn(),
        )
        combo.set("")

        def _filter(event=None):
            if event and event.keysym in ("Return", "KP_Enter", "Escape", "Tab"):
                return
            typed = combo.get().strip()
            all_names = self._get_wildcard_names()
            filtered = [v for v in all_names if typed.lower() in v.lower()] if typed else all_names
            combo.configure(values=filtered if filtered else all_names)

        try:
            combo._entry.bind("<KeyRelease>", _filter)
            combo._entry.bind("<Return>", lambda e: add_fn())
        except AttributeError:
            pass

        return combo

    def _insert_wc_from_combo(self):
        raw = self._insert_wc_combo.get().strip().strip("_")
        if raw:
            self._insert(f"__{raw}__")
            self._insert_wc_combo.set("")
            self._insert_wc_combo.configure(values=self._get_wildcard_names())

    def _on_wc_dir_changed(self, *_):
        names = self._get_wildcard_names()
        if hasattr(self, "_insert_wc_combo"):
            self._insert_wc_combo.configure(values=names)
        if hasattr(self, "_lock_combo"):
            self._lock_combo.configure(values=names)
        if hasattr(self, "_seq_combo"):
            self._seq_combo.configure(values=names)

    # ── Locked wildcards section ──────────────────────────────────────────────

    def _build_locks_section(self):
        lock_section = ctk.CTkFrame(self, fg_color="transparent")
        lock_section.grid(row=7, column=0, sticky="ew", padx=10, pady=(0, 6))
        lock_section.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(lock_section, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header, text="Locked Wildcards", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self._lock_combo = self._make_ac_combo(header, self._add_lock)
        self._lock_combo.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        b = ctk.CTkButton(header, text="+ Lock", width=62, height=28, command=self._add_lock)
        b.grid(row=0, column=2)
        tip(b, "Lock selected wildcard to the same value across all prompts in the batch")

        self._lock_rows_container = ctk.CTkFrame(lock_section, fg_color="transparent")
        self._lock_rows_container.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self._lock_rows_container.grid_columnconfigure(0, weight=1)

    # ── Sequential wildcards section ──────────────────────────────────────────

    def _build_seq_section(self):
        seq_section = ctk.CTkFrame(self, fg_color="transparent")
        seq_section.grid(row=8, column=0, sticky="ew", padx=10, pady=(0, 10))
        seq_section.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(seq_section, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header, text="Sequential Wildcards", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self._seq_combo = self._make_ac_combo(header, self._add_seq)
        self._seq_combo.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        b = ctk.CTkButton(header, text="+ Seq", width=62, height=28, command=self._add_seq)
        b.grid(row=0, column=2)
        tip(b, "Step through wildcard values in order — prompt 1 gets line 1, prompt 2 gets line 2, etc.")

        self._seq_rows_container = ctk.CTkFrame(seq_section, fg_color="transparent")
        self._seq_rows_container.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self._seq_rows_container.grid_columnconfigure(0, weight=1)

    # ── Public API ────────────────────────────────────────────────────────────

    def insert_at_cursor(self, text: str):
        self._insert(text)

    def set_font_size(self, size: int):
        self._font_size = max(8, min(20, size))
        self._textbox.configure(font=("Segoe UI", self._font_size))
        if hasattr(self, "_neg_textbox"):
            self._neg_textbox.configure(font=("Segoe UI", self._font_size))
        if hasattr(self, "_font_size_label"):
            self._font_size_label.configure(text=str(self._font_size))

    def _change_font_size(self, delta: int):
        new_size = max(8, min(20, self._font_size + delta))
        if new_size == self._font_size:
            return
        self.set_font_size(new_size)
        if self._on_font_size_change:
            self._on_font_size_change(new_size)

    def get_template_name(self) -> str:
        return self._tpl_name_var.get().strip()

    def get_template(self) -> str:
        return self._textbox.get("1.0", "end-1c")

    def get_negative_template(self) -> str:
        return self._neg_textbox.get("1.0", "end-1c")

    def get_template_for_save(self) -> str:
        """Return template text with [@lock:] / [@seq:] directives and [NEG] block prepended."""
        raw = self.get_template()
        lock_names = [n for n, _, _ in self._locks]
        regen_flags = {n: r.get() for n, _, r in self._locks}
        seq_names = list(self._seq_wildcards)
        neg_text = self.get_negative_template()
        directives = build_template_directives(lock_names, seq_names, regen_flags, neg_text)
        return (directives + "\n" + raw) if directives else raw

    def get_count(self) -> int:
        try:
            return max(1, min(200, int(self._count_var.get())))
        except (ValueError, tk.TclError):
            return 10

    def get_wildcards_dir(self) -> Path:
        return Path(self._wc_var.get())

    def get_locked_wildcards(self) -> dict[str, str]:
        return {
            name: ("" if regen.get() else var.get().strip())
            for name, var, regen in self._locks
        }

    def set_resolved_locks(self, resolved: dict[str, str]) -> None:
        for name, var, regen in self._locks:
            if name in resolved:
                var.set(resolved[name])

    def get_sequential_wildcards(self) -> list[str]:
        return list(self._seq_wildcards)

    def get_lock_regen_flags(self) -> dict[str, bool]:
        return {name: regen.get() for name, _, regen in self._locks}

    def restore_locks(self, locks: dict[str, str]):
        existing = {n: (v, r) for n, v, r in self._locks}
        seq_names = set(self._seq_wildcards)
        for name, value in locks.items():
            if name in existing:
                var, regen = existing[name]
                if not regen.get():
                    var.set(value)
            elif name not in seq_names:
                self._locks.append((name, tk.StringVar(value=value), tk.BooleanVar(value=False)))
        self._rebuild_lock_rows()

    def restore_lock_regen(self, flags: dict[str, bool]):
        for name, _, regen in self._locks:
            if name in flags:
                regen.set(flags[name])
        self._rebuild_lock_rows()

    def restore_sequential(self, names: list[str]):
        existing_names = set(self._seq_wildcards) | {n for n, _, _ in self._locks}
        for name in names:
            if name not in existing_names:
                self._seq_wildcards.append(name)
                existing_names.add(name)
        self._rebuild_seq_rows()

    # ── Lock management ───────────────────────────────────────────────────────

    def _add_lock(self):
        raw = self._lock_combo.get().strip().strip("_")
        if not raw:
            return
        if raw in [n for n, _, _ in self._locks] or raw in self._seq_wildcards:
            self._lock_combo.set("")
            return
        self._locks.append((raw, tk.StringVar(value=""), tk.BooleanVar(value=False)))
        self._lock_combo.set("")
        self._lock_combo.configure(values=self._get_wildcard_names())
        self._rebuild_lock_rows()

    def _remove_lock(self, name: str):
        self._locks = [(n, v, r) for n, v, r in self._locks if n != name]
        self._rebuild_lock_rows()

    def _roll_lock(self, name: str, var: tk.StringVar):
        wc_file = self.get_wildcards_dir() / f"{name}.txt"
        if wc_file.exists():
            lines = [
                l.strip() for l in wc_file.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.strip().startswith("#")
            ]
            if lines:
                var.set(random.choice(lines))

    def _rebuild_lock_rows(self):
        for frame in self._lock_row_frames:
            frame.destroy()
        self._lock_row_frames.clear()

        for row_idx, (name, var, regen) in enumerate(self._locks):
            wc_file = self.get_wildcards_dir() / f"{name}.txt"
            options = []
            if wc_file.exists():
                options = [
                    l.strip() for l in wc_file.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.strip().startswith("#")
                ]

            frame = ctk.CTkFrame(self._lock_rows_container, fg_color="transparent")
            frame.grid(row=row_idx, column=0, sticky="ew", pady=(2, 0))
            frame.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                frame, text=f"__{name}__", font=("Courier New", 10), width=120, anchor="w"
            ).grid(row=0, column=0, padx=(0, 6))

            combo = ctk.CTkComboBox(frame, variable=var, values=options, height=28)
            combo.grid(row=0, column=1, sticky="ew", padx=(0, 4))
            if not var.get():
                combo.set("")

            def _filter(event=None, c=combo, opts=options):
                if event and event.keysym in ("Return", "KP_Enter", "Escape", "Tab"):
                    return
                typed = c.get().strip()
                filtered = [v for v in opts if typed.lower() in v.lower()] if typed else opts
                c.configure(values=filtered if filtered else opts)

            try:
                combo._entry.bind("<KeyRelease>", _filter)
            except AttributeError:
                pass

            roll_btn = ctk.CTkButton(
                frame, text="↺", width=30, height=28,
                command=lambda n=name, v=var: self._roll_lock(n, v)
            )
            roll_btn.grid(row=0, column=2, padx=(0, 4))
            tip(roll_btn, "Pick a random value from this wildcard file")

            def _on_regen_toggle(c=combo, rb=roll_btn, rv=regen):
                state = "disabled" if rv.get() else "normal"
                c.configure(state=state)
                rb.configure(state=state)

            regen_cb = ctk.CTkCheckBox(
                frame, text="Regen", width=64, height=28,
                variable=regen, command=_on_regen_toggle,
            )
            regen_cb.grid(row=0, column=3, padx=(0, 4))
            tip(regen_cb, "Re-pick from file on every Generate click instead of using a fixed value")

            rm_btn = ctk.CTkButton(
                frame, text="✕", width=30, height=28, fg_color="#6b3535", hover_color="#8b4545",
                command=lambda n=name: self._remove_lock(n)
            )
            rm_btn.grid(row=0, column=4)
            tip(rm_btn, "Remove this lock")

            # Apply initial state
            _on_regen_toggle()

            self._lock_row_frames.append(frame)

    # ── Sequential management ─────────────────────────────────────────────────

    def _add_seq(self):
        raw = self._seq_combo.get().strip().strip("_")
        if not raw:
            return
        if raw in self._seq_wildcards or raw in [n for n, _, _ in self._locks]:
            self._seq_combo.set("")
            return
        self._seq_wildcards.append(raw)
        self._seq_combo.set("")
        self._seq_combo.configure(values=self._get_wildcard_names())
        self._rebuild_seq_rows()

    def _remove_seq(self, name: str):
        self._seq_wildcards = [n for n in self._seq_wildcards if n != name]
        self._rebuild_seq_rows()

    def _rebuild_seq_rows(self):
        for frame in self._seq_row_frames:
            frame.destroy()
        self._seq_row_frames.clear()

        for row_idx, name in enumerate(self._seq_wildcards):
            preview = self._seq_preview(name)
            frame = ctk.CTkFrame(self._seq_rows_container, fg_color="transparent")
            frame.grid(row=row_idx, column=0, sticky="ew", pady=(2, 0))
            frame.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                frame, text=f"__{name}__", font=("Courier New", 10), width=120, anchor="w"
            ).grid(row=0, column=0, padx=(0, 6))
            ctk.CTkLabel(
                frame, text=preview, anchor="w", text_color="gray", font=("Segoe UI", 10)
            ).grid(row=0, column=1, sticky="ew", padx=(0, 4))
            ctk.CTkButton(
                frame, text="✕", width=30, height=28, fg_color="#6b3535", hover_color="#8b4545",
                command=lambda n=name: self._remove_seq(n)
            ).grid(row=0, column=2)

            self._seq_row_frames.append(frame)

    def _seq_preview(self, name: str) -> str:
        wc_file = self.get_wildcards_dir() / f"{name}.txt"
        if not wc_file.exists():
            return "(file not found)"
        lines = [
            l.strip() for l in wc_file.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
        if not lines:
            return "(empty file)"
        snippets = [f'"{v[:28]}…"' if len(v) > 28 else f'"{v}"' for v in lines[:3]]
        preview = " → ".join(snippets)
        if len(lines) > 3:
            preview += f" … (+{len(lines) - 3} more)"
        return f"{len(lines)} values: {preview}"

    # ── Internals ─────────────────────────────────────────────────────────────

    def _insert(self, text: str):
        try:
            idx = self._textbox.index(tk.INSERT)
            self._textbox.insert(idx, text)
        except Exception:
            self._textbox.insert("end", text)
        self._textbox.focus()

    def _clear_template(self):
        self._textbox.delete("1.0", tk.END)

    def _browse(self):
        path = filedialog.askdirectory(title="Select Wildcards Directory")
        if path:
            self._wc_var.set(path)
