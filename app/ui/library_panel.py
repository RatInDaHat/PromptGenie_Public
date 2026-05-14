import tkinter.messagebox as msgbox

import customtkinter as ctk
import tkinter as tk
from app.library import PhraseLibrary
from app.ui.utils import center_input_dialog, make_msgbox_parent, tip

_LB_BG = "#2b2b2b"
_LB_FG = "#dce4ee"
_LB_SEL_BG = "#1f538d"
_LB_EXCL_FG = "#c07070"
_LB_EXCL_SEL_BG = "#5a2f2f"
_LB_EXCL_SEL_FG = "#f0a0a0"


class _EditDialog(ctk.CTkToplevel):
    def __init__(self, master, initial_text: str, title: str = "Edit Phrase", label: str = "Edit phrase:"):
        super().__init__(master)
        self.result: str | None = None
        self.title(title)
        self.geometry("540x130")
        self.resizable(False, False)
        self.grab_set()

        ctk.CTkLabel(self, text=label).pack(padx=16, pady=(14, 4), anchor="w")
        self._entry = ctk.CTkEntry(self, width=508)
        self._entry.pack(padx=16, pady=(0, 10))
        self._entry.insert(0, initial_text)
        self._entry.select_range(0, tk.END)
        self._entry.focus()
        self._entry.bind("<Return>", lambda e: self._ok())
        self._entry.bind("<Escape>", lambda e: self._cancel())

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack()
        ctk.CTkButton(btn_frame, text="OK", width=90, command=self._ok).pack(side="left", padx=4)
        ctk.CTkButton(btn_frame, text="Cancel", width=90, command=self._cancel).pack(side="left", padx=4)

        self.after(50, self._raise_and_center)
        self.wait_window()

    def _raise_and_center(self):
        root = self.master.winfo_toplevel()
        root.update_idletasks()
        rx, ry = root.winfo_x(), root.winfo_y()
        rw, rh = root.winfo_width(), root.winfo_height()
        x = rx + (rw - 540) // 2
        y = ry + (rh - 130) // 2
        self.geometry(f"540x130+{x}+{y}")
        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)
        self.after(100, lambda: self.attributes("-topmost", False))

    def _ok(self):
        self.result = self._entry.get()
        self.destroy()

    def _cancel(self):
        self.destroy()


class LibraryPanel(ctk.CTkFrame):
    def __init__(self, master, library: PhraseLibrary, on_insert, get_wildcards_dir=None, on_wildcards_changed=None):
        super().__init__(master)
        self.library = library
        self.on_insert = on_insert
        self._get_wildcards_dir = get_wildcards_dir
        self._on_wildcards_changed = on_wildcards_changed
        self._last_deleted: tuple | None = None

        self._build()
        self._refresh_categories()

    def _build(self):
        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Header row
        header_row = ctk.CTkFrame(self, fg_color="transparent")
        header_row.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 6))
        header_row.grid_columnconfigure(1, weight=1)

        self._expand_btn = ctk.CTkButton(
            header_row, text="▶", width=26, height=26,
            command=self._toggle_category_list,
            fg_color="transparent", hover_color="#3d3d3d",
            font=ctk.CTkFont(size=11),
        )
        self._expand_btn.grid(row=0, column=0, padx=(0, 6))
        ctk.CTkLabel(
            header_row, text="Wildcard Library", font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=1, sticky="w")

        reload_btn = ctk.CTkButton(header_row, text="↺", width=32, height=26, command=self._reload_library)
        reload_btn.grid(row=0, column=2, padx=(6, 0))
        tip(reload_btn, "Reload wildcard files from disk — picks up new .txt files without restarting")

        # Collapsible category list (hidden by default)
        self._cat_list_expanded = False
        self._cat_list_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._cat_list_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 4))
        self._cat_list_frame.grid_rowconfigure(0, weight=1)
        self._cat_list_frame.grid_columnconfigure(0, weight=1)

        self._cat_listbox = tk.Listbox(
            self._cat_list_frame,
            bg=_LB_BG, fg=_LB_FG, selectbackground=_LB_SEL_BG, selectforeground="#ffffff",
            relief="flat", borderwidth=0, highlightthickness=1, highlightbackground="#3d3d3d",
            activestyle="none", font=("Segoe UI", 10), height=8,
        )
        cat_scroll = tk.Scrollbar(self._cat_list_frame, orient="vertical", command=self._cat_listbox.yview)
        self._cat_listbox.configure(yscrollcommand=cat_scroll.set)
        self._cat_listbox.grid(row=0, column=0, sticky="nsew")
        cat_scroll.grid(row=0, column=1, sticky="ns")
        self._cat_listbox.bind("<<ListboxSelect>>", self._on_cat_list_select)
        self._cat_list_frame.grid_remove()

        # Category selector row
        cat_row = ctk.CTkFrame(self, fg_color="transparent")
        cat_row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 4))
        cat_row.grid_columnconfigure(0, weight=1)

        self._cat_var = tk.StringVar()
        self._cat_menu = ctk.CTkOptionMenu(
            cat_row, variable=self._cat_var, command=self._on_category_change, dynamic_resizing=False
        )
        self._cat_menu.grid(row=0, column=0, sticky="ew")
        b = ctk.CTkButton(cat_row, text="+Cat", width=50, command=self._add_category)
        b.grid(row=0, column=1, padx=(4, 0))
        tip(b, "Create a new wildcard category (.txt file)")

        b = ctk.CTkButton(cat_row, text="Ren", width=42, command=self._rename_category)
        b.grid(row=0, column=2, padx=(4, 0))
        tip(b, "Rename the current wildcard file")

        b = ctk.CTkButton(cat_row, text="Del", width=42, fg_color="#6b3535", hover_color="#8b4545", command=self._delete_category)
        b.grid(row=0, column=3, padx=(4, 0))
        tip(b, "Delete the current wildcard .txt file")

        self._space_btn = ctk.CTkButton(cat_row, text="⎵", width=34, command=self._toggle_space_flag, fg_color="#3a3a3a", hover_color="#4a4a4a")
        self._space_btn.grid(row=0, column=4, padx=(4, 0))
        tip(self._space_btn, "Append a trailing space to all resolved values from this wildcard — useful when concatenating wildcards without a separator")

        # Phrase listbox with scrollbar
        lb_frame = ctk.CTkFrame(self, fg_color="transparent")
        lb_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 4))
        lb_frame.grid_rowconfigure(0, weight=1)
        lb_frame.grid_columnconfigure(0, weight=1)

        self._listbox = tk.Listbox(
            lb_frame,
            bg=_LB_BG,
            fg=_LB_FG,
            selectbackground=_LB_SEL_BG,
            selectforeground="#ffffff",
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#3d3d3d",
            activestyle="none",
            font=("Segoe UI", 10),
        )
        scrollbar = tk.Scrollbar(lb_frame, orient="vertical", command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=scrollbar.set)
        self._listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self._listbox.bind("<Double-Button-1>", self._on_double_click)
        self._listbox.bind("<Delete>", lambda e: self._delete_phrase())
        self._listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        self._listbox.bind("<Button-3>", self._on_right_click)
        self._listbox.bind("<Button-2>", self._on_middle_click)
        self._menu_after_id = None
        self._listbox.bind("<Button-1>", self._on_drag_start)
        self._listbox.bind("<B1-Motion>", self._on_drag_motion)
        self._listbox.bind("<ButtonRelease-1>", self._on_drag_release)
        self._drag_idx: int | None = None

        # Add entry row
        add_row = ctk.CTkFrame(self, fg_color="transparent")
        add_row.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 4))
        add_row.grid_columnconfigure(0, weight=1)

        self._add_entry = ctk.CTkEntry(add_row, placeholder_text="New entry...")
        self._add_entry.grid(row=0, column=0, sticky="ew")
        self._add_entry.bind("<Return>", lambda e: self._add_phrase())
        b = ctk.CTkButton(add_row, text="Add", width=52, command=self._add_phrase)
        b.grid(row=0, column=1, padx=(4, 0))
        tip(b, "Add entry to the current wildcard file")

        b = ctk.CTkButton(add_row, text="+ Blank", width=68, fg_color="#3a3a3a", hover_color="#4a4a4a", command=self._add_blank)
        b.grid(row=0, column=2, padx=(4, 0))
        tip(b, "Add a [blank] entry — resolves to empty string in sequential mode")

        # Edit / Delete / Undo / Move row
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=5, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))

        b = ctk.CTkButton(btn_row, text="↑", width=34, command=lambda: self._move_phrase(-1))
        b.pack(side="left", padx=(0, 2))
        tip(b, "Move entry up")

        b = ctk.CTkButton(btn_row, text="↓", width=34, command=lambda: self._move_phrase(1))
        b.pack(side="left", padx=(0, 8))
        tip(b, "Move entry down")

        b = ctk.CTkButton(btn_row, text="Edit", width=56, command=self._edit_phrase)
        b.pack(side="left", padx=(0, 4))
        tip(b, "Edit the selected entry")

        b = ctk.CTkButton(btn_row, text="Delete", width=60, command=self._delete_phrase)
        b.pack(side="left", padx=(0, 4))
        tip(b, "Delete the selected entry")

        self._undo_btn = ctk.CTkButton(btn_row, text="Undo", width=56, state="disabled", command=self._undo_delete)
        self._undo_btn.pack(side="left")
        tip(self._undo_btn, "Undo last delete")

        self._excl_btn = ctk.CTkButton(btn_row, text="Excl", width=52, command=self._toggle_exclude, fg_color="#4a3a1a", hover_color="#6a5a2a")
        self._excl_btn.pack(side="left", padx=(8, 0))
        tip(self._excl_btn, "Exclude/include selected entry from random and locked selection")

    def _reload_library(self):
        self._refresh_categories()

    def set_font_size(self, size: int):
        self._listbox.configure(font=("Segoe UI", size))
        self._cat_listbox.configure(font=("Segoe UI", size))

    # ── Category helpers ──────────────────────────────────────────────────────

    def _toggle_category_list(self):
        if self._cat_list_expanded:
            self._cat_list_frame.grid_remove()
            self._expand_btn.configure(text="▶")
            self._cat_list_expanded = False
        else:
            self._refresh_cat_listbox()
            self._cat_list_frame.grid()
            self._expand_btn.configure(text="▼")
            self._cat_list_expanded = True

    def _refresh_cat_listbox(self):
        self._cat_listbox.delete(0, tk.END)
        cats = self.library.get_categories()
        for cat in cats:
            self._cat_listbox.insert(tk.END, cat)
        current = self._cat_var.get()
        if current in cats:
            idx = cats.index(current)
            self._cat_listbox.selection_set(idx)
            self._cat_listbox.see(idx)

    def _on_cat_list_select(self, _=None):
        sel = self._cat_listbox.curselection()
        if sel:
            cat = self._cat_listbox.get(sel[0])
            self._cat_var.set(cat)
            self._refresh_phrases()

    def _refresh_categories(self):
        cats = self.library.get_categories()
        self._cat_menu.configure(values=cats if cats else [""])
        if cats:
            current = self._cat_var.get()
            if current not in cats:
                self._cat_var.set(cats[0])
            self._refresh_phrases()
        self._update_space_btn()
        if self._cat_list_expanded:
            self._refresh_cat_listbox()

    def _on_category_change(self, _=None):
        self._refresh_phrases()
        self._update_space_btn()
        if self._cat_list_expanded:
            self._refresh_cat_listbox()

    def _update_space_btn(self):
        if not hasattr(self, "_space_btn"):
            return
        cat = self._cat_var.get()
        active = self.library.get_space_flag(cat)
        self._space_btn.configure(
            fg_color="#1f538d" if active else "#3a3a3a",
            hover_color="#2d6bbf" if active else "#4a4a4a",
        )

    def _toggle_space_flag(self):
        cat = self._cat_var.get()
        if not cat:
            return
        self.library.set_space_flag(cat, not self.library.get_space_flag(cat))
        self._update_space_btn()

    def _add_category(self):
        dialog = ctk.CTkInputDialog(text="Category name:", title="New Category")
        center_input_dialog(dialog, self)
        name = dialog.get_input()
        if name and name.strip():
            name = name.strip()
            if self.library.add_category(name):
                self._refresh_categories()
                self._cat_var.set(name)
                self._refresh_phrases()
                if self._on_wildcards_changed:
                    self._on_wildcards_changed()

    def _delete_category(self):
        cat = self._cat_var.get()
        if not cat:
            return
        phrases = self.library.get_phrases(cat)
        msg = f"Delete '{cat}.txt' and all {len(phrases)} entries?" if phrases else f"Delete '{cat}.txt'?"
        parent = make_msgbox_parent(self)
        confirmed = msgbox.askyesno("Delete Wildcard File", msg, parent=parent)
        parent.destroy()
        if confirmed:
            self.library.delete_category(cat)
            self._refresh_categories()
            if self._on_wildcards_changed:
                self._on_wildcards_changed()

    def _rename_category(self):
        cat = self._cat_var.get()
        if not cat:
            return
        dialog = _EditDialog(self, cat, title="Rename Wildcard File", label="New name (without .txt):")
        if dialog.result and dialog.result.strip():
            new_name = dialog.result.strip()
            if self.library.rename_category(cat, new_name):
                self._refresh_categories()
                self._cat_var.set(new_name)
                self._refresh_phrases()
                if self._cat_list_expanded:
                    self._refresh_cat_listbox()
                if self._on_wildcards_changed:
                    self._on_wildcards_changed()

    # ── Phrase helpers ────────────────────────────────────────────────────────

    def _move_phrase(self, delta: int):
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        new_idx = idx + delta
        count = self._listbox.size()
        if 0 <= new_idx < count:
            self.library.move_phrase(self._cat_var.get(), idx, new_idx)
            self._refresh_phrases()
            self._listbox.selection_set(new_idx)
            self._listbox.see(new_idx)

    def _on_drag_start(self, event):
        self._drag_idx = self._listbox.nearest(event.y)
        self._listbox.configure(cursor="fleur")

    def _on_drag_motion(self, event):
        if self._drag_idx is None:
            return
        target = self._listbox.nearest(event.y)
        if target != self._drag_idx:
            self.library.move_phrase(self._cat_var.get(), self._drag_idx, target, save=False)
            self._refresh_phrases()
            self._listbox.selection_clear(0, tk.END)
            self._listbox.selection_set(target)
            self._drag_idx = target

    def _on_drag_release(self, event):
        if self._drag_idx is not None:
            self.library.save()
        self._drag_idx = None
        self._listbox.configure(cursor="")

    def _on_listbox_select(self, _=None):
        sel = self._listbox.curselection()
        if not sel:
            self._excl_btn.configure(text="Excl")
            return
        phrase = self._listbox.get(sel[0])
        is_excl = self.library.is_excluded(self._cat_var.get(), phrase)
        self._excl_btn.configure(text="Incl" if is_excl else "Excl")

    def _exclude_all(self):
        cat = self._cat_var.get()
        self.library.exclude_all(cat)
        self._refresh_phrases()
        self._on_listbox_select()

    def _exclude_none(self):
        cat = self._cat_var.get()
        self.library.exclude_none(cat)
        self._refresh_phrases()
        self._on_listbox_select()

    def _toggle_exclude(self):
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        phrase = self._listbox.get(idx)
        cat = self._cat_var.get()
        now_excluded = self.library.toggle_exclusion(cat, phrase)
        if now_excluded:
            self._listbox.itemconfig(idx, fg=_LB_EXCL_FG, selectbackground=_LB_EXCL_SEL_BG, selectforeground=_LB_EXCL_SEL_FG)
        else:
            self._listbox.itemconfig(idx, fg=_LB_FG, selectbackground=_LB_SEL_BG, selectforeground="#ffffff")
        self._excl_btn.configure(text="Incl" if now_excluded else "Excl")

    def _on_middle_click(self, event):
        idx = self._listbox.nearest(event.y)
        if idx < 0 or idx >= self._listbox.size():
            return
        self._listbox.selection_clear(0, tk.END)
        self._listbox.selection_set(idx)
        self._listbox.activate(idx)
        self._on_listbox_select()
        self._toggle_exclude()

    def _on_right_click(self, event):
        idx = self._listbox.nearest(event.y)
        if idx < 0 or idx >= self._listbox.size():
            return
        self._listbox.selection_clear(0, tk.END)
        self._listbox.selection_set(idx)
        self._listbox.activate(idx)
        self._on_listbox_select()

        if self._menu_after_id is not None:
            self.after_cancel(self._menu_after_id)
            self._menu_after_id = None
            self._toggle_exclude()
            return

        self._menu_after_id = self.after(300, lambda e=event: self._show_context_menu(e))

    def _show_context_menu(self, event):
        self._menu_after_id = None
        sel = self._listbox.curselection()
        if not sel:
            return
        phrase = self._listbox.get(sel[0])
        cat = self._cat_var.get()
        is_excl = self.library.is_excluded(cat, phrase)
        label = "Include" if is_excl else "Exclude"

        menu = tk.Menu(self, tearoff=0, bg="#2b2b2b", fg="#dce4ee",
                       activebackground="#1f538d", activeforeground="#ffffff",
                       bd=0, relief="flat")
        menu.add_command(label=label, command=self._toggle_exclude)
        menu.add_command(label="Exclude All", command=self._exclude_all)
        menu.add_command(label="Exclude None", command=self._exclude_none)
        menu.add_separator()
        menu.add_command(label="Insert into template", command=lambda: self.on_insert(phrase))
        menu.add_command(label="Edit", command=self._edit_phrase)
        menu.add_command(label="Delete", command=self._delete_phrase)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _refresh_phrases(self):
        self._listbox.delete(0, tk.END)
        cat = self._cat_var.get()
        excluded = self.library.get_excluded(cat)
        for i, phrase in enumerate(self.library.get_phrases(cat)):
            self._listbox.insert(tk.END, phrase)
            if phrase in excluded:
                self._listbox.itemconfig(i, fg=_LB_EXCL_FG, selectbackground=_LB_EXCL_SEL_BG, selectforeground=_LB_EXCL_SEL_FG)

    def _on_double_click(self, _=None):
        sel = self._listbox.curselection()
        if sel:
            self.on_insert(self._listbox.get(sel[0]))

    def _add_phrase(self):
        phrase = self._add_entry.get().strip()
        if not phrase:
            return
        category = self._cat_var.get()
        if not category:
            return
        self.library.add_phrase(category, phrase)
        self._add_entry.delete(0, tk.END)
        self._refresh_phrases()

    def _add_blank(self):
        category = self._cat_var.get()
        if not category:
            return
        self.library.add_phrase(category, "[blank]")
        self._refresh_phrases()

    def _delete_phrase(self):
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        category = self._cat_var.get()
        removed = self.library.delete_phrase(category, idx)
        if removed is not None:
            self._last_deleted = (category, removed)
            self._undo_btn.configure(state="normal")
        self._refresh_phrases()

    def _undo_delete(self):
        if self._last_deleted is None:
            return
        category, phrase = self._last_deleted
        if category in self.library.get_categories():
            self.library.add_phrase(category, phrase)
        self._last_deleted = None
        self._undo_btn.configure(state="disabled")
        self._refresh_phrases()

    def _edit_phrase(self):
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        category = self._cat_var.get()
        current_text = self._listbox.get(idx)
        dialog = _EditDialog(self, current_text)
        if dialog.result and dialog.result.strip():
            self.library.edit_phrase(category, idx, dialog.result.strip())
            self._refresh_phrases()
