import tkinter as tk
from datetime import datetime

import customtkinter as ctk

from app.template_library import TemplateLibrary
from app.ui.utils import center_input_dialog, center_on_root

_LB_BG = "#2b2b2b"
_LB_FG = "#dce4ee"
_LB_SEL_BG = "#1f538d"


class TemplateManager(ctk.CTkToplevel):
    def __init__(self, master, library: TemplateLibrary, on_load):
        super().__init__(master)
        self.library = library
        self.on_load = on_load
        self._sort = tk.StringVar(value="recent")
        self._selected_name: str | None = None

        self.title("Saved Templates")
        self.minsize(500, 380)
        self._build()
        self._refresh_list()
        center_on_root(self, 680, 520)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=2)
        self.grid_rowconfigure(3, weight=1)

        # Sort toggle + reload
        sort_row = ctk.CTkFrame(self, fg_color="transparent")
        sort_row.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        ctk.CTkLabel(sort_row, text="Sort by:").pack(side="left", padx=(0, 8))
        ctk.CTkSegmentedButton(
            sort_row,
            values=["Recent", "A → Z"],
            variable=self._sort,
            command=lambda _: self._refresh_list(),
        ).pack(side="left")
        ctk.CTkButton(
            sort_row, text="↺ Reload from disk", width=140, height=28,
            command=self._reload_from_disk,
        ).pack(side="right")

        # Template list
        lb_frame = ctk.CTkFrame(self, fg_color="transparent")
        lb_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 6))
        lb_frame.grid_rowconfigure(0, weight=1)
        lb_frame.grid_columnconfigure(0, weight=1)

        self._listbox = tk.Listbox(
            lb_frame,
            bg=_LB_BG, fg=_LB_FG,
            selectbackground=_LB_SEL_BG, selectforeground="#ffffff",
            relief="flat", borderwidth=0,
            highlightthickness=1, highlightbackground="#3d3d3d",
            activestyle="none", font=("Segoe UI", 11),
        )
        sb = tk.Scrollbar(lb_frame, orient="vertical", command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=sb.set)
        self._listbox.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        self._listbox.bind("<<ListboxSelect>>", self._on_select)
        self._listbox.bind("<Double-Button-1>", lambda e: self._load())
        self._listbox.bind("<Delete>", lambda e: self._delete())

        # Preview label + box
        ctk.CTkLabel(self, text="Preview:", anchor="w").grid(
            row=2, column=0, sticky="ew", padx=12, pady=(0, 2)
        )
        self._preview = ctk.CTkTextbox(self, state="disabled", font=("Segoe UI", 10), height=100)
        self._preview.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 8))

        # Action buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 12))

        ctk.CTkButton(btn_row, text="Load", width=90, command=self._load).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Rename", width=90, command=self._rename).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_row, text="Delete", width=90, fg_color="#6b3535", hover_color="#8b4545",
            command=self._delete
        ).pack(side="left")
        ctk.CTkButton(btn_row, text="Close", width=80, command=self.destroy).pack(side="right")

    # ── List management ───────────────────────────────────────────────────────

    def _reload_from_disk(self):
        self.library.load()
        self._refresh_list()

    def _refresh_list(self, keep_selection: str | None = None):
        sort_key = "alpha" if self._sort.get().startswith("A") else "recent"
        templates = self.library.get_templates(sort=sort_key)

        self._listbox.delete(0, tk.END)
        self._names: list[str] = []

        for t in templates:
            name = t["name"]
            date_str = _fmt_date(t.get("last_used") or t.get("created_at", ""))
            self._listbox.insert(tk.END, f"  {name}  —  {date_str}")
            self._names.append(name)

        # Restore selection if possible
        target = keep_selection or self._selected_name
        if target and target in self._names:
            idx = self._names.index(target)
            self._listbox.selection_set(idx)
            self._listbox.see(idx)
            self._selected_name = target
            self._update_preview(target)
        else:
            self._selected_name = None
            self._set_preview("")

    def _on_select(self, _=None):
        sel = self._listbox.curselection()
        if not sel:
            return
        name = self._names[sel[0]]
        self._selected_name = name
        self._update_preview(name)

    def _update_preview(self, name: str):
        text = self.library.get_text(name) or ""
        self._set_preview(text)

    def _set_preview(self, text: str):
        self._preview.configure(state="normal")
        self._preview.delete("1.0", tk.END)
        if text:
            self._preview.insert("1.0", text)
        self._preview.configure(state="disabled")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _load(self):
        if not self._selected_name:
            return
        text = self.library.get_text(self._selected_name)
        if text is not None:
            self.library.touch_last_used(self._selected_name)
            self.on_load(self._selected_name, text)
            self.destroy()

    def _rename(self):
        if not self._selected_name:
            return
        dialog = ctk.CTkInputDialog(text="New name:", title="Rename Template")
        center_input_dialog(dialog, self)
        new_name = dialog.get_input()
        if not new_name or not new_name.strip():
            return
        new_name = new_name.strip()
        if self.library.rename_template(self._selected_name, new_name):
            self._refresh_list(keep_selection=new_name)
        else:
            ctk.CTkMessagebox(title="Error", message=f'A template named "{new_name}" already exists.')

    def _delete(self):
        if not self._selected_name:
            return
        name = self._selected_name
        self.library.delete_template(name)
        self._selected_name = None
        self._refresh_list()


def _fmt_date(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso
