import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from app.engine.wildcard import generate_batch
from app.settings import AppSettings
from app.ui.utils import tip


class OutputPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        settings: AppSettings,
        output_dir: Path,
        get_template,
        get_count,
        get_wildcards_dir,
        get_locked_wildcards,
        on_locks_resolved,
        get_sequential_wildcards,
        get_exclusions=None,
        get_space_flags=None,
        get_negative_template=None,
        get_template_name=None,
        get_tpl_library=None,
    ):
        super().__init__(master)
        self._settings = settings
        self._output_dir = output_dir
        self._get_template = get_template
        self._get_count = get_count
        self._get_wildcards_dir = get_wildcards_dir
        self._get_locked_wildcards = get_locked_wildcards
        self._on_locks_resolved = on_locks_resolved
        self._get_sequential_wildcards = get_sequential_wildcards
        self._get_exclusions = get_exclusions
        self._get_space_flags = get_space_flags
        self._get_negative_template = get_negative_template
        self._get_template_name = get_template_name
        self._get_tpl_library = get_tpl_library
        self._prompts: list[str] = []
        self._negative_prompts: list[str] = []
        self._wan_prompts: list[str] = []
        self._wan_negative_prompts: list[str] = []
        self._last_seed: int | None = settings.get("last_seed")

        self._build()

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="Generated Prompts", font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, pady=(10, 6), padx=10, sticky="w")

        # Output textbox (read-only)
        self._output_box = ctk.CTkTextbox(
            self, wrap="word", font=("Segoe UI", self._settings.get("font_size", 11)), state="disabled"
        )
        self._output_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))

        # Seed row
        seed_row = ctk.CTkFrame(self, fg_color="transparent")
        seed_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))
        seed_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(seed_row, text="Seed:").grid(row=0, column=0, padx=(0, 6))
        last_seed = self._settings.get("last_seed")
        self._seed_var = tk.StringVar(value=str(last_seed) if last_seed is not None else "")
        self._seed_entry = ctk.CTkEntry(
            seed_row, textvariable=self._seed_var, placeholder_text="lock to reuse a seed",
            state="disabled",
        )
        self._seed_entry.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self._lock_var = tk.BooleanVar(value=self._settings.get("lock_seed", False))
        lock_cb = ctk.CTkCheckBox(
            seed_row, text="Lock", variable=self._lock_var, width=70,
            command=self._on_lock_toggled,
        )
        lock_cb.grid(row=0, column=2)
        tip(lock_cb, "Lock seed to reproduce the exact same batch of prompts")
        # Apply initial state
        self._on_lock_toggled()

        # Action buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 6))

        b = ctk.CTkButton(btn_row, text="⚡ Generate", width=110, command=self._generate)
        b.pack(side="left", padx=(0, 6))
        tip(b, "Generate prompts from the current template")

        b = ctk.CTkButton(btn_row, text="Copy All", width=90, command=self._copy_all)
        b.pack(side="left", padx=(0, 4))
        tip(b, "Copy all positive prompts to clipboard")

        self._copy_neg_btn = ctk.CTkButton(btn_row, text="Copy Neg", width=90, command=self._copy_neg, state="disabled")
        self._copy_neg_btn.pack(side="left", padx=(0, 4))
        tip(self._copy_neg_btn, "Copy all negative prompts to clipboard")

        self._copy_wan_btn = ctk.CTkButton(btn_row, text="Copy WAN", width=90, command=self._copy_wan, state="disabled")
        self._copy_wan_btn.pack(side="left", padx=(0, 6))
        tip(self._copy_wan_btn, "Copy WAN motion prompts to clipboard")

        b = ctk.CTkButton(btn_row, text="Save to File", width=100, command=self._save_to_file)
        b.pack(side="left", padx=(0, 12))
        tip(b, "Save prompts to .txt file (also saves _neg.txt when negative prompts exist)")

        self._number_var = tk.BooleanVar(value=self._settings.get("number_prompts", True))
        cb = ctk.CTkCheckBox(
            btn_row, text="# Prompts", variable=self._number_var, width=100,
            command=self._on_number_toggled,
        )
        cb.pack(side="left")
        tip(cb, "Prefix each prompt with its number")

        # Status label
        self._status_var = tk.StringVar()
        self._status_label = ctk.CTkLabel(
            self,
            textvariable=self._status_var,
            text_color="gray",
            wraplength=320,
            anchor="w",
            justify="left",
        )
        self._status_label.grid(row=4, column=0, padx=10, pady=(0, 10), sticky="ew")

    # ── Core actions ──────────────────────────────────────────────────────────

    def _generate(self):
        template = self._get_template()
        if not template.strip():
            self._status("Template is empty. Add some text first.", error=True)
            return

        count = self._get_count()
        wildcards_dir = self._get_wildcards_dir()
        seed = self._parse_seed()
        locked = self._get_locked_wildcards()
        sequential = self._get_sequential_wildcards()
        exclusions = self._get_exclusions() if self._get_exclusions else None
        space_flags = self._get_space_flags() if self._get_space_flags else None

        neg_template = self._get_negative_template() if self._get_negative_template else ""
        try:
            prompts, seed_used, warnings, resolved_locks, negative_prompts = generate_batch(
                template=template,
                count=count,
                wildcards_dir=wildcards_dir,
                seed=seed,
                locked_overrides=locked if locked else None,
                sequential_wildcards=sequential if sequential else None,
                exclusions=exclusions if exclusions else None,
                space_flags=space_flags if space_flags else None,
                negative_template=neg_template if neg_template.strip() else None,
            )
        except Exception as exc:
            self._status(f"Error: {exc}", error=True)
            return

        self._prompts = prompts
        self._last_seed = seed_used
        self._seed_var.set(str(seed_used))
        self._negative_prompts = negative_prompts
        self._copy_neg_btn.configure(state="normal" if self._negative_prompts else "disabled")

        # Auto-generate matching WAN prompts if a W_<Scene> template exists
        self._wan_prompts = []
        self._wan_negative_prompts = []
        wan_name = self._derive_wan_name()
        if wan_name and self._get_tpl_library:
            lib = self._get_tpl_library()
            if lib.exists(wan_name):
                try:
                    wan_text = lib.get_text(wan_name)
                    wan_prompts, _, _, _, wan_neg = generate_batch(
                        template=wan_text,
                        count=count,
                        wildcards_dir=wildcards_dir,
                        seed=seed_used,
                    )
                    self._wan_prompts = wan_prompts
                    self._wan_negative_prompts = wan_neg
                except Exception:
                    pass
        self._copy_wan_btn.configure(state="normal" if self._wan_prompts else "disabled")

        # Feed resolved lock values back to the template panel so the user can see them
        if resolved_locks:
            self._on_locks_resolved(resolved_locks)

        self._rerender_output()

        msg = f"Generated {len(prompts)} prompt{'s' if len(prompts) != 1 else ''}. Seed: {seed_used}"
        if resolved_locks:
            locked_summary = ", ".join(f"__{n}__={v}" for n, v in resolved_locks.items())
            msg += f"\nLocked: {locked_summary}"
        if sequential:
            msg += f"\nSequential: {', '.join(f'__{n}__' for n in sequential)}"
        if warnings:
            msg += f"\n⚠ {'; '.join(warnings)}"
            self._status(msg, error=True)
        else:
            self._status(msg, error=False)

    def _copy_all(self):
        if not self._prompts:
            self._status("Generate some prompts first.", error=True)
            return
        text = "\n".join(self._prompts)
        self.clipboard_clear()
        self.clipboard_append(text)
        self._status(f"Copied {len(self._prompts)} prompts to clipboard.")

    def _copy_neg(self):
        if not self._negative_prompts:
            self._status("No negative prompts generated.", error=True)
            return
        text = "\n".join(self._negative_prompts)
        self.clipboard_clear()
        self.clipboard_append(text)
        self._status(f"Copied {len(self._negative_prompts)} negative prompts to clipboard.")

    def _copy_wan(self):
        if not self._wan_prompts:
            self._status("No WAN prompts generated.", error=True)
            return
        text = "\n".join(self._wan_prompts)
        self.clipboard_clear()
        self.clipboard_append(text)
        self._status(f"Copied {len(self._wan_prompts)} WAN prompts to clipboard.")

    def _derive_wan_name(self) -> str | None:
        """Derive W_<Scene> from the current template name, or None if not applicable."""
        if not self._get_template_name:
            return None
        name = self._get_template_name().strip()
        if not name or name.upper().startswith("W_"):
            return None
        parts = name.split("_", 1)
        if len(parts) < 2:
            return None
        return f"W_{parts[1]}"

    def _save_to_file(self):
        if not self._prompts:
            self._status("Generate some prompts first.", error=True)
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"prompts_{timestamp}.txt"
        last_dir = self._settings.get("last_output_dir", str(self._output_dir))
        path_str = filedialog.asksaveasfilename(
            title="Save Prompts",
            initialdir=last_dir,
            initialfile=default_name,
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path_str:
            return
        out = Path(path_str)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(self._prompts), encoding="utf-8")
        if self._negative_prompts:
            neg_out = out.with_stem(out.stem + "_neg")
            neg_out.write_text("\n".join(self._negative_prompts), encoding="utf-8")
        if self._wan_prompts:
            wan_out = out.with_stem(out.stem + "_wan")
            wan_out.write_text("\n".join(self._wan_prompts), encoding="utf-8")
            if self._wan_negative_prompts:
                wan_neg_out = out.with_stem(out.stem + "_wan_neg")
                wan_neg_out.write_text("\n".join(self._wan_negative_prompts), encoding="utf-8")
        self._settings.set("last_output_dir", str(out.parent))
        msg = f"Saved → {out.name}"
        if self._negative_prompts:
            msg += f" + _neg.txt"
        if self._wan_prompts:
            msg += f" + _wan.txt"
        self._status(msg)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _rerender_output(self):
        self._output_box.configure(state="normal")
        self._output_box.delete("1.0", tk.END)
        for i, prompt in enumerate(self._prompts, 1):
            line = f"{i}. {prompt}" if self._number_var.get() else prompt
            self._output_box.insert(tk.END, f"{line}\n")
        if self._wan_prompts:
            self._output_box.insert(tk.END, "\n── WAN ────────────────────────────\n\n")
            for i, prompt in enumerate(self._wan_prompts, 1):
                line = f"{i}. {prompt}" if self._number_var.get() else prompt
                self._output_box.insert(tk.END, f"{line}\n")
        if self._negative_prompts:
            self._output_box.insert(tk.END, "\n── Negative ──────────────────────\n\n")
            for i, prompt in enumerate(self._negative_prompts, 1):
                line = f"{i}. {prompt}" if self._number_var.get() else prompt
                self._output_box.insert(tk.END, f"{line}\n")
        self._output_box.configure(state="disabled")

    def _on_number_toggled(self):
        self._settings.set("number_prompts", self._number_var.get())
        if self._prompts:
            self._rerender_output()

    def _on_lock_toggled(self):
        if self._lock_var.get():
            self._seed_entry.configure(state="normal")
        else:
            self._seed_entry.configure(state="disabled")

    def _parse_seed(self) -> int | None:
        if self._lock_var.get() and self._last_seed is not None:
            return self._last_seed
        return None  # always generate a fresh seed when not locked

    def _status(self, message: str, error: bool = False):
        self._status_var.set(message)
        self._status_label.configure(text_color="#ff6b6b" if error else "#4caf50")

    def set_font_size(self, size: int):
        self._output_box.configure(font=("Segoe UI", size))

    def get_seed_state(self) -> dict:
        return {"seed": self._last_seed, "locked": self._lock_var.get()}
