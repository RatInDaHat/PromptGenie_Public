import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_AVAILABLE = True
except ImportError:
    TkinterDnD = None
    _DND_AVAILABLE = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_PREVIEW_MAX = (860, 640)


def _load_lines(path: Path) -> list[str]:
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _save_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines), encoding="utf-8")


def _fit(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    return img


_BaseMixin = TkinterDnD.DnDWrapper if _DND_AVAILABLE else object


class WanCurator(ctk.CTk, _BaseMixin):
    def __init__(self):
        super().__init__()
        if _DND_AVAILABLE:
            self.TkdndVersion = TkinterDnD._require(self)

        self.title("WAN Curator")
        self.minsize(1100, 680)
        self.geometry("1300x780")

        self._images: list[Path] = []
        self._wan_lines: list[str] = []
        self._wan_neg_lines: list[str] = []
        self._wan_file: Path | None = None
        self._wan_neg_file: Path | None = None
        self._idx: int = 0
        self._tk_image = None  # keep reference

        self._build()

        if _DND_AVAILABLE:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)

        self.bind("<Left>", lambda e: self._prev())
        self.bind("<Right>", lambda e: self._next())
        self.bind("<Delete>", lambda e: self._delete())

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # ── Top toolbar ──
        toolbar = ctk.CTkFrame(self, height=44, fg_color="#2b2b2b", corner_radius=0)
        toolbar.grid(row=0, column=0, columnspan=3, sticky="ew")
        toolbar.grid_columnconfigure(10, weight=1)

        ctk.CTkButton(toolbar, text="Load Images", width=110,
                      command=self._load_folder).pack(side="left", padx=(8, 4), pady=6)
        ctk.CTkButton(toolbar, text="Load WAN File", width=120,
                      command=self._load_wan).pack(side="left", padx=4, pady=6)
        ctk.CTkButton(toolbar, text="Load WAN Neg", width=120,
                      command=self._load_wan_neg).pack(side="left", padx=4, pady=6)

        hint = "Drag a folder here, or use Load Images above."
        self._status_var = tk.StringVar(value=hint)
        ctk.CTkLabel(toolbar, textvariable=self._status_var,
                     text_color="gray", anchor="w").pack(side="left", padx=12)

        # ── Left: file list ──
        left = ctk.CTkFrame(self, width=210, fg_color="#1e1e1e", corner_radius=0)
        left.grid(row=1, column=0, sticky="nsew")
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self._listbox = tk.Listbox(
            left, bg="#1e1e1e", fg="#cccccc", selectbackground="#1f6aa5",
            font=("Segoe UI", 10), borderwidth=0, highlightthickness=0,
            activestyle="none", relief="flat",
        )
        self._listbox.grid(row=0, column=0, sticky="nsew")
        sb = tk.Scrollbar(left, orient="vertical", command=self._listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._listbox.configure(yscrollcommand=sb.set)
        self._listbox.bind("<<ListboxSelect>>", self._on_list_select)

        # ── Center: image preview ──
        center = ctk.CTkFrame(self, fg_color="#121212", corner_radius=0)
        center.grid(row=1, column=1, sticky="nsew")
        center.grid_rowconfigure(0, weight=1)
        center.grid_columnconfigure(0, weight=1)

        self._img_label = tk.Label(center, bg="#121212")
        self._img_label.grid(row=0, column=0, sticky="nsew")

        self._caption_var = tk.StringVar()
        ctk.CTkLabel(center, textvariable=self._caption_var,
                     text_color="#888888", font=("Segoe UI", 10)
                     ).grid(row=1, column=0, pady=(0, 4))

        # ── Right: WAN prompts ──
        right = ctk.CTkFrame(self, width=320, fg_color="#1a1a1a", corner_radius=0)
        right.grid(row=1, column=2, sticky="nsew")
        right.grid_rowconfigure(1, weight=2)
        right.grid_rowconfigure(3, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="WAN Prompt",
                     font=ctk.CTkFont(weight="bold"), anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        self._wan_box = ctk.CTkTextbox(right, wrap="word", font=("Segoe UI", 11),
                                       state="disabled", fg_color="#222222")
        self._wan_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 6))

        ctk.CTkLabel(right, text="WAN Negative",
                     font=ctk.CTkFont(weight="bold"), anchor="w",
                     text_color="#888888"
                     ).grid(row=2, column=0, sticky="w", padx=10, pady=(4, 2))
        self._neg_box = ctk.CTkTextbox(right, wrap="word", font=("Segoe UI", 11),
                                       state="disabled", fg_color="#222222")
        self._neg_box.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))

        # ── Bottom bar ──
        bottom = ctk.CTkFrame(self, height=48, fg_color="#2b2b2b", corner_radius=0)
        bottom.grid(row=2, column=0, columnspan=3, sticky="ew")

        self._prev_btn = ctk.CTkButton(bottom, text="← Prev", width=90,
                                       command=self._prev, state="disabled")
        self._prev_btn.pack(side="left", padx=(12, 4), pady=8)

        self._counter_var = tk.StringVar(value="—")
        ctk.CTkLabel(bottom, textvariable=self._counter_var,
                     width=90, anchor="center").pack(side="left", padx=4)

        self._next_btn = ctk.CTkButton(bottom, text="Next →", width=90,
                                       command=self._next, state="disabled")
        self._next_btn.pack(side="left", padx=4)

        self._del_btn = ctk.CTkButton(bottom, text="🗑  Delete", width=110,
                                      fg_color="#8b1a1a", hover_color="#b22222",
                                      command=self._delete, state="disabled")
        self._del_btn.pack(side="left", padx=(20, 4))

        ctk.CTkLabel(bottom, text="← → to navigate  |  Del to delete  |  Drag folder to load",
                     text_color="#555555", font=("Segoe UI", 10)).pack(side="right", padx=12)

    # ── Load actions ─────────────────────────────────────────────────────────

    def _on_drop(self, event):
        raw = event.data.strip()
        # Windows DnD wraps paths with spaces in {braces}; multiple items are space-separated
        paths = []
        i = 0
        while i < len(raw):
            if raw[i] == "{":
                end = raw.find("}", i)
                paths.append(raw[i + 1:end])
                i = end + 2
            else:
                end = raw.find(" ", i)
                if end == -1:
                    paths.append(raw[i:])
                    break
                paths.append(raw[i:end])
                i = end + 1
        for path_str in paths:
            p = Path(path_str)
            if p.is_dir():
                self._load_folder_path(p)
                return
            if p.suffix.lower() == ".txt":
                if "_neg" in p.name:
                    self._wan_neg_file = p
                    self._wan_neg_lines = _load_lines(p)
                    self._show()
                    self._status(f"WAN neg loaded: {p.name} ({len(self._wan_neg_lines)} lines)")
                else:
                    self._load_wan_from(p)
                return

    def _load_folder(self):
        folder = filedialog.askdirectory(title="Select image folder")
        if not folder:
            return
        self._load_folder_path(Path(folder))

    def _load_folder_path(self, p: Path):
        files = sorted(f for f in p.iterdir() if f.suffix.lower() in _IMG_EXTS)
        if not files:
            self._status("No images found in that folder.", error=True)
            return
        self._images = files
        self._rebuild_list()
        self._idx = 0
        self._show()

        # Auto-detect WAN file
        wan_candidates = list(p.glob("*_wan.txt")) + list(p.glob("wan*.txt")) + list(p.glob("wan.txt"))
        wan_candidates = [f for f in wan_candidates if "_neg" not in f.name]
        if wan_candidates:
            self._load_wan_from(wan_candidates[0])

        self._status(f"Loaded {len(files)} images from {p.name}/ — drag a folder or .txt to load")

    def _load_wan(self):
        path = filedialog.askopenfilename(
            title="Select WAN prompts file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self._load_wan_from(Path(path))

    def _load_wan_neg(self):
        path = filedialog.askopenfilename(
            title="Select WAN negative prompts file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        p = Path(path)
        self._wan_neg_file = p
        self._wan_neg_lines = _load_lines(p)
        self._show()
        self._status(f"WAN neg loaded: {p.name} ({len(self._wan_neg_lines)} lines)")

    def _load_wan_from(self, p: Path):
        self._wan_file = p
        self._wan_lines = _load_lines(p)
        # Auto-detect matching neg file
        neg_candidate = p.with_stem(p.stem + "_neg")
        if neg_candidate.exists():
            self._wan_neg_file = neg_candidate
            self._wan_neg_lines = _load_lines(neg_candidate)
        self._show()
        n = len(self._wan_lines)
        img_n = len(self._images)
        msg = f"WAN loaded: {p.name} ({n} lines)"
        if img_n and n != img_n:
            msg += f"  ⚠ {n} prompts vs {img_n} images — counts don't match"
            self._status(msg, error=True)
        else:
            self._status(msg)

    # ── Navigation ───────────────────────────────────────────────────────────

    def _prev(self):
        if self._images and self._idx > 0:
            self._idx -= 1
            self._show()

    def _next(self):
        if self._images and self._idx < len(self._images) - 1:
            self._idx += 1
            self._show()

    def _on_list_select(self, _event=None):
        sel = self._listbox.curselection()
        if sel:
            self._idx = sel[0]
            self._show(update_list=False)

    # ── Display ──────────────────────────────────────────────────────────────

    def _show(self, update_list: bool = True):
        if not self._images:
            return

        self._idx = max(0, min(self._idx, len(self._images) - 1))
        img_path = self._images[self._idx]

        # Image
        try:
            img = Image.open(img_path).convert("RGB")
            w, h = self.winfo_width() - 540, self.winfo_height() - 120
            max_w = max(w, 400)
            max_h = max(h, 300)
            img = _fit(img, max_w, max_h)
            self._tk_image = ImageTk.PhotoImage(img)
            self._img_label.configure(image=self._tk_image)
        except Exception as e:
            self._img_label.configure(image="", text=f"Cannot load image: {e}")

        # Caption
        total = len(self._images)
        self._caption_var.set(f"{img_path.name}  ({self._idx + 1} / {total})")
        self._counter_var.set(f"{self._idx + 1} / {total}")

        # WAN prompt
        wan = self._wan_lines[self._idx] if self._idx < len(self._wan_lines) else ""
        self._set_textbox(self._wan_box, wan)

        # WAN neg prompt
        neg = self._wan_neg_lines[self._idx] if self._idx < len(self._wan_neg_lines) else ""
        self._set_textbox(self._neg_box, neg)

        # Sync list selection
        if update_list:
            self._listbox.selection_clear(0, tk.END)
            self._listbox.selection_set(self._idx)
            self._listbox.see(self._idx)

        # Button states
        has = bool(self._images)
        self._prev_btn.configure(state="normal" if self._idx > 0 else "disabled")
        self._next_btn.configure(state="normal" if self._idx < len(self._images) - 1 else "disabled")
        self._del_btn.configure(state="normal" if has else "disabled")

    def _set_textbox(self, box: ctk.CTkTextbox, text: str):
        box.configure(state="normal")
        box.delete("1.0", tk.END)
        box.insert("1.0", text)
        box.configure(state="disabled")

    def _rebuild_list(self):
        self._listbox.delete(0, tk.END)
        for f in self._images:
            self._listbox.insert(tk.END, f"  {f.name}")

    # ── Delete ───────────────────────────────────────────────────────────────

    def _delete(self):
        if not self._images:
            return

        img_path = self._images[self._idx]

        # Remove image file
        try:
            img_path.unlink()
        except Exception as e:
            messagebox.showerror("Delete failed", str(e))
            return

        # Drop matching WAN lines
        if self._idx < len(self._wan_lines):
            self._wan_lines.pop(self._idx)
        if self._idx < len(self._wan_neg_lines):
            self._wan_neg_lines.pop(self._idx)

        # Save updated WAN files
        if self._wan_file and self._wan_file.exists():
            _save_lines(self._wan_file, self._wan_lines)
        if self._wan_neg_file and self._wan_neg_file.exists():
            _save_lines(self._wan_neg_file, self._wan_neg_lines)

        # Remove from in-memory list and listbox
        self._images.pop(self._idx)
        self._listbox.delete(self._idx)

        # Clamp index and show
        if not self._images:
            self._img_label.configure(image="", text="No images remaining.")
            self._caption_var.set("")
            self._counter_var.set("—")
            self._set_textbox(self._wan_box, "")
            self._set_textbox(self._neg_box, "")
            self._del_btn.configure(state="disabled")
            self._prev_btn.configure(state="disabled")
            self._next_btn.configure(state="disabled")
            self._status("All images deleted.")
            return

        self._idx = min(self._idx, len(self._images) - 1)
        self._show()
        self._status(f"Deleted {img_path.name}. {len(self._images)} remaining.")

    # ── Status ───────────────────────────────────────────────────────────────

    def _status(self, msg: str, error: bool = False):
        self._status_var.set(msg)


if __name__ == "__main__":
    app = WanCurator()
    app.mainloop()
