import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from app.library import PhraseLibrary
from app.settings import AppSettings
from app.template_library import TemplateLibrary
from app.ui.library_panel import LibraryPanel
from app.ui.output_panel import OutputPanel
from app.ui.template_panel import TemplatePanel

_BASE = Path(__file__).parent.parent.parent
_DATA_DIR = _BASE / "data"
_WILDCARDS_DIR = _DATA_DIR / "wildcards"
_OUTPUT_DIR = _BASE / "output"


class AppWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self._settings = AppSettings(_DATA_DIR / "settings.json")
        self._settings.load()

        self._library = PhraseLibrary(_WILDCARDS_DIR, _DATA_DIR / "wildcards_meta.json")
        self._library.load()

        self._tpl_library = TemplateLibrary(_DATA_DIR / "templates")
        self._tpl_library.load()

        ctk.set_appearance_mode(self._settings.get("appearance_mode", "dark"))
        ctk.set_default_color_theme("blue")

        self.title("PromptGenie")
        self.minsize(1100, 660)

        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Defer geometry restore so it runs after CTk's internal setup completes.
        # Without after(), CTk overrides the position and the window always opens
        # on the primary monitor.
        saved_geo = self._settings.get("window_geometry", "")
        self.after(1, lambda: self.geometry(saved_geo) if saved_geo else self.geometry("1280x760"))

    def _build_layout(self):
        wildcards_dir = self._settings.get("wildcards_dir", str(_WILDCARDS_DIR))

        self._paned = tk.PanedWindow(
            self, orient=tk.HORIZONTAL,
            sashwidth=6, sashpad=0,
            showhandle=False,
            background="#3d3d3d",
            bd=0, relief="flat",
        )
        self._paned.pack(fill="both", expand=True, padx=8, pady=8)

        self._library_panel = LibraryPanel(
            self._paned,
            library=self._library,
            on_insert=lambda phrase: self._template_panel.insert_at_cursor(phrase),
            get_wildcards_dir=lambda: Path(self._settings.get("wildcards_dir", str(_WILDCARDS_DIR))),
            on_wildcards_changed=lambda: self._template_panel._on_wc_dir_changed(),
        )

        self._template_panel = TemplatePanel(
            self._paned,
            settings=self._settings,
            wildcards_dir=wildcards_dir,
            tpl_library=self._tpl_library,
            on_font_size_change=self._on_font_size_change,
        )

        saved_locks = self._settings.get("last_locks", {})
        saved_seq = self._settings.get("last_sequential", [])
        saved_regen = self._settings.get("last_locks_regen", {})
        if saved_locks:
            self._template_panel.restore_locks(saved_locks)
        if saved_regen:
            self._template_panel.restore_lock_regen(saved_regen)
        if saved_seq:
            self._template_panel.restore_sequential(saved_seq)

        self._output_panel = OutputPanel(
            self._paned,
            settings=self._settings,
            output_dir=_OUTPUT_DIR,
            get_template=self._template_panel.get_template,
            get_count=self._template_panel.get_count,
            get_wildcards_dir=self._template_panel.get_wildcards_dir,
            get_locked_wildcards=self._template_panel.get_locked_wildcards,
            on_locks_resolved=self._template_panel.set_resolved_locks,
            get_sequential_wildcards=self._template_panel.get_sequential_wildcards,
            get_exclusions=self._library.get_all_exclusions,
            get_space_flags=self._library.get_all_space_flags,
            get_negative_template=self._template_panel.get_negative_template,
            get_template_name=self._template_panel.get_template_name,
            get_tpl_library=lambda: self._tpl_library,
        )

        self._paned.add(self._library_panel, minsize=220, width=260, stretch="never")
        self._paned.add(self._template_panel, minsize=360, stretch="always")
        self._paned.add(self._output_panel, minsize=300, width=420, stretch="always")

    def _on_font_size_change(self, size: int):
        self._settings.set("font_size", size)
        self._output_panel.set_font_size(size)
        self._library_panel.set_font_size(size)

    def _on_close(self):
        self._settings.set("last_template", self._template_panel.get_template_for_save())
        self._settings.set("last_template_name", self._template_panel.get_template_name())
        self._settings.set("last_negative_template", self._template_panel.get_negative_template())
        self._settings.set("last_count", self._template_panel.get_count())
        self._settings.set("last_locks", self._template_panel.get_locked_wildcards())
        self._settings.set("last_locks_regen", self._template_panel.get_lock_regen_flags())
        self._settings.set("last_sequential", self._template_panel.get_sequential_wildcards())
        self._settings.set("window_geometry", self.geometry())
        seed_state = self._output_panel.get_seed_state()
        self._settings.set("last_seed", seed_state["seed"])
        self._settings.set("lock_seed", seed_state["locked"])
        self._settings.save()
        self.destroy()
