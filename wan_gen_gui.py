"""WAN Prompt Generator — GUI frontend for wan_gen.py"""

import json
import pathlib
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_AVAILABLE = True
except ImportError:
    TkinterDnD = None
    _DND_AVAILABLE = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

try:
    from PIL import Image as _PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PILImage = None
    _PIL_AVAILABLE = False

# ── re-use core logic from wan_gen ────────────────────────────────────────────
from wan_gen import (
    IMG_EXTS, NEG_PROMPT, LTX_NEG_PROMPT, SYSTEM_PROMPT,
    _extract_scene_info, _img_to_b64, _generate, _clean,
)

_BaseMixin = TkinterDnD.DnDWrapper if _DND_AVAILABLE else object

COMMON_MODELS = [
    "local-model",
    "llava",
    "llava:13b",
    "llava:34b",
    "llava-llama3",
    "llava-v1.6-mistral-7b",
    "llava-phi3",
    "minicpm-v",
    "moondream",
]


class GalleryWindow(ctk.CTkToplevel):
    """Scrollable gallery: thumbnail | original booru prompt | generated prompt (editable)."""

    THUMB_W, THUMB_H = 200, 150

    def __init__(self, parent, folder: pathlib.Path, prefix: str, model_type: str,
                 initial_geometry: str | None = None, on_close=None):
        super().__init__(parent)
        self.title(f"Prompt Gallery — {folder.name}")
        self.minsize(900, 500)
        self._folder = folder
        self._prefix = prefix
        self._model_type = model_type
        self._on_close = on_close
        self._gen_boxes: list[ctk.CTkTextbox] = []
        self._img_refs = []  # prevent GC of CTkImage objects

        if initial_geometry:
            self.geometry(initial_geometry)
        else:
            # Default size, positioned near the parent window
            px, py = parent.winfo_x(), parent.winfo_y()
            self.geometry(f"1300x780+{px + 40}+{py + 40}")

        self.protocol("WM_DELETE_WINDOW", self._handle_close)
        self._build()
        self.after(80, self._start_load)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Top status bar
        top = ctk.CTkFrame(self, fg_color="#1e1e1e", corner_radius=0, height=30)
        top.grid(row=0, column=0, sticky="ew")
        self._status_var = tk.StringVar(value="Loading…")
        ctk.CTkLabel(top, textvariable=self._status_var,
                     text_color="#888888", anchor="w").pack(side="left", padx=10)

        # Scrollable area
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="#1a1a1a")
        self._scroll.grid(row=1, column=0, sticky="nsew")
        self._scroll.grid_columnconfigure(1, weight=1)
        self._scroll.grid_columnconfigure(2, weight=1)

        # Column headers
        for col, text in enumerate(["Image", "Original Prompt (from metadata)", "Generated Prompt (editable)"]):
            ctk.CTkLabel(self._scroll, text=text,
                         font=("Segoe UI", 11, "bold"),
                         text_color="#4a9eff").grid(
                row=0, column=col, padx=8, pady=(8, 4), sticky="w")

        # Bottom bar
        bottom = ctk.CTkFrame(self, fg_color="#1e1e1e", corner_radius=0, height=46)
        bottom.grid(row=2, column=0, sticky="ew")
        ctk.CTkButton(bottom, text="Save Edited Prompts", width=190,
                      command=self._save).pack(side="left", padx=12, pady=8)
        self._save_status = tk.StringVar(value="")
        ctk.CTkLabel(bottom, textvariable=self._save_status,
                     text_color="#88cc88").pack(side="left", padx=6)

    # ── Loading ───────────────────────────────────────────────────────────────

    def _start_load(self):
        self._images = sorted(
            f for f in self._folder.iterdir()
            if f.suffix.lower() in IMG_EXTS
            and (not self._prefix or f.name.startswith(self._prefix))
        )
        suffix = "ltx" if self._model_type == "ltx" else "wan"
        prompt_file = self._folder / f"gen__{suffix}.txt"
        self._gen_prompts = []
        if prompt_file.exists():
            self._gen_prompts = [l for l in
                                 prompt_file.read_text(encoding="utf-8").splitlines()
                                 if l.strip()]
        n = len(self._images)
        self._status_var.set(
            f"Loading {n} images  ·  {prompt_file.name if prompt_file.exists() else 'no prompt file found'}"
        )
        self._load_row(0)

    def _load_row(self, idx: int):
        if idx >= len(self._images):
            self._status_var.set(
                f"{len(self._images)} images  ·  {len(self._gen_prompts)} generated prompts"
            )
            return

        img_path = self._images[idx]
        row = idx + 1

        # ── Thumbnail + filename ──
        cell = ctk.CTkFrame(self._scroll, fg_color="transparent")
        cell.grid(row=row, column=0, padx=8, pady=4, sticky="nw")

        if _PIL_AVAILABLE:
            try:
                pil = _PILImage.open(img_path).convert("RGB")
                pil.thumbnail((self.THUMB_W, self.THUMB_H))
                ctk_img = ctk.CTkImage(light_image=pil, dark_image=pil,
                                       size=(pil.width, pil.height))
                self._img_refs.append(ctk_img)
                ctk.CTkLabel(cell, image=ctk_img, text="").pack()
            except Exception:
                pass
        ctk.CTkLabel(cell, text=f"{idx + 1}. {img_path.name}",
                     font=("Consolas", 9), text_color="#555555",
                     wraplength=self.THUMB_W).pack(pady=(2, 0))

        # ── Original prompt (from metadata) ──
        _, booru = _extract_scene_info(img_path, img_index=idx + 1)
        orig_box = ctk.CTkTextbox(self._scroll, height=self.THUMB_H + 20, width=1,
                                  fg_color="#111111", text_color="#88cc88",
                                  font=("Consolas", 10), wrap="word")
        orig_box.grid(row=row, column=1, padx=4, pady=4, sticky="nsew")
        orig_box.insert("1.0", booru if booru else "(no metadata)")
        orig_box.configure(state="disabled")

        # ── Generated prompt (editable) ──
        gen_text = (self._gen_prompts[idx]
                    if idx < len(self._gen_prompts) else "(not yet generated)")
        gen_box = ctk.CTkTextbox(self._scroll, height=self.THUMB_H + 20, width=1,
                                 fg_color="#111a11", text_color="#cccccc",
                                 font=("Consolas", 10), wrap="word")
        gen_box.grid(row=row, column=2, padx=4, pady=4, sticky="nsew")
        gen_box.insert("1.0", gen_text)
        self._gen_boxes.append(gen_box)

        self.after(5, lambda: self._load_row(idx + 1))

    # ── Close ─────────────────────────────────────────────────────────────────

    def _handle_close(self):
        if self._on_close:
            self._on_close(self.geometry())
        self.destroy()

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save(self):
        suffix = "ltx" if self._model_type == "ltx" else "wan"
        prompt_file = self._folder / f"gen__{suffix}.txt"
        lines = [box.get("1.0", "end").strip() for box in self._gen_boxes]
        prompt_file.write_text("\n".join(lines), encoding="utf-8")
        self._save_status.set(f"Saved {len(lines)} prompts → {prompt_file.name}")


class WanGenApp(ctk.CTk, _BaseMixin):
    def __init__(self):
        super().__init__()
        if _DND_AVAILABLE:
            self.TkdndVersion = TkinterDnD._require(self)

        self.title("WAN Prompt Generator")
        self.geometry("900x680")
        self.minsize(760, 520)

        self._stop_event = threading.Event()
        self._q: queue.Queue = queue.Queue()
        self._running = False
        self._gallery_geometry: str | None = None

        self._build()
        self._load_settings()

        if _DND_AVAILABLE:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)

        self.after(100, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        self._save_settings()
        self.destroy()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ── Top: settings ──
        cfg = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=0)
        cfg.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        cfg.grid_columnconfigure(1, weight=1)
        cfg.grid_columnconfigure(3, weight=1)

        row = 0
        # Folder
        ctk.CTkLabel(cfg, text="Folder  ↙ drag", anchor="e", width=90).grid(
            row=row, column=0, padx=(12, 6), pady=(10, 4), sticky="e")
        self._folder_var = tk.StringVar()
        ctk.CTkEntry(cfg, textvariable=self._folder_var).grid(
            row=row, column=1, columnspan=3, padx=(0, 4), pady=(10, 4), sticky="ew")
        ctk.CTkButton(cfg, text="Browse", width=80, command=self._browse_folder).grid(
            row=row, column=4, padx=(0, 12), pady=(10, 4))

        row += 1
        # Host
        ctk.CTkLabel(cfg, text="Host", anchor="e", width=70).grid(
            row=row, column=0, padx=(12, 6), pady=4, sticky="e")
        self._host_var = tk.StringVar(value="http://localhost:1234")
        ctk.CTkEntry(cfg, textvariable=self._host_var, width=240).grid(
            row=row, column=1, padx=(0, 16), pady=4, sticky="w")

        # Model
        ctk.CTkLabel(cfg, text="Model", anchor="e", width=60).grid(
            row=row, column=2, padx=(0, 6), pady=4, sticky="e")
        self._model_var = tk.StringVar(value="local-model")
        model_combo = ctk.CTkComboBox(cfg, variable=self._model_var,
                                      values=COMMON_MODELS, width=260)
        model_combo.grid(row=row, column=3, padx=(0, 4), pady=4, sticky="w")

        row += 1
        # Prefix
        ctk.CTkLabel(cfg, text="Prefix", anchor="e", width=70).grid(
            row=row, column=0, padx=(12, 6), pady=4, sticky="e")
        self._prefix_var = tk.StringVar(value="gen__")
        ctk.CTkEntry(cfg, textvariable=self._prefix_var, width=120).grid(
            row=row, column=1, padx=(0, 16), pady=4, sticky="w")

        # Checkboxes
        checks = ctk.CTkFrame(cfg, fg_color="transparent")
        checks.grid(row=row, column=2, columnspan=3, padx=4, pady=4, sticky="w")

        self._batch_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(checks, text="Batch (process subfolders)",
                        variable=self._batch_var).pack(side="left", padx=(0, 16))

        self._overwrite_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(checks, text="Overwrite existing",
                        variable=self._overwrite_var).pack(side="left", padx=(0, 16))

        self._dryrun_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(checks, text="Dry run",
                        variable=self._dryrun_var).pack(side="left", padx=(0, 16))

        # Video model type selector
        ctk.CTkLabel(checks, text="Output for:", text_color="#888888").pack(side="left", padx=(0, 6))
        self._model_type_var = tk.StringVar(value="wan")
        ctk.CTkSegmentedButton(checks, values=["wan", "ltx"],
                               variable=self._model_type_var,
                               width=120).pack(side="left")

        row += 1
        # Buttons
        btn_row = ctk.CTkFrame(cfg, fg_color="transparent")
        btn_row.grid(row=row, column=0, columnspan=5, padx=12, pady=(4, 10), sticky="w")

        self._go_btn = ctk.CTkButton(btn_row, text="Generate", width=120,
                                     command=self._start)
        self._go_btn.pack(side="left", padx=(0, 8))

        self._stop_btn = ctk.CTkButton(btn_row, text="Stop", width=80,
                                       fg_color="#8b1a1a", hover_color="#b22222",
                                       command=self._stop, state="disabled")
        self._stop_btn.pack(side="left", padx=(0, 16))

        self._gallery_btn = ctk.CTkButton(btn_row, text="View Gallery", width=110,
                                          fg_color="#2a4a2a", hover_color="#3a6a3a",
                                          command=self._open_gallery)
        self._gallery_btn.pack(side="left", padx=(0, 16))

        self._progress_var = tk.StringVar(value="")
        ctk.CTkLabel(btn_row, textvariable=self._progress_var,
                     text_color="#888888").pack(side="left")

        # ── Center: log ──
        log_frame = ctk.CTkFrame(self, fg_color="#111111", corner_radius=0)
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        self._log = tk.Text(
            log_frame, bg="#111111", fg="#cccccc", insertbackground="white",
            font=("Consolas", 10), wrap="word", state="disabled",
            borderwidth=0, highlightthickness=0, relief="flat",
        )
        self._log.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        sb = tk.Scrollbar(log_frame, orient="vertical", command=self._log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._log.configure(yscrollcommand=sb.set)

        # Tags for coloured log lines
        self._log.tag_config("header",  foreground="#4a9eff", font=("Consolas", 10, "bold"))
        self._log.tag_config("prompt",  foreground="#88cc88")
        self._log.tag_config("error",   foreground="#ff6666")
        self._log.tag_config("muted",   foreground="#555555")
        self._log.tag_config("success", foreground="#aaaaaa")

        # ── Bottom: status bar ──
        bottom = ctk.CTkFrame(self, height=28, fg_color="#1e1e1e", corner_radius=0)
        bottom.grid(row=2, column=0, sticky="ew")
        self._status_var = tk.StringVar(value="Ready.")
        ctk.CTkLabel(bottom, textvariable=self._status_var,
                     text_color="#666666", font=("Segoe UI", 10),
                     anchor="w").pack(side="left", padx=10)

    # ── Settings persistence ──────────────────────────────────────────────────

    _SETTINGS = pathlib.Path(__file__).parent / "data" / "wan_gen_settings.json"

    def _load_settings(self):
        try:
            d = json.loads(self._SETTINGS.read_text())
            self._folder_var.set(d.get("folder", ""))
            self._host_var.set(d.get("host", "http://localhost:1234"))
            self._model_var.set(d.get("model", "local-model"))
            self._prefix_var.set(d.get("prefix", "gen__"))
            self._batch_var.set(d.get("batch", False))
            self._overwrite_var.set(d.get("overwrite", False))
            self._model_type_var.set(d.get("model_type", "wan"))
            self._gallery_geometry = d.get("gallery_geometry", None)
            if geo := d.get("geometry"):
                self.geometry(geo)
        except Exception:
            pass

    def _save_settings(self):
        try:
            self._SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            self._SETTINGS.write_text(json.dumps({
                "folder":    self._folder_var.get(),
                "host":      self._host_var.get(),
                "model":     self._model_var.get(),
                "prefix":    self._prefix_var.get(),
                "batch":     self._batch_var.get(),
                "overwrite":        self._overwrite_var.get(),
                "model_type":       self._model_type_var.get(),
                "gallery_geometry": self._gallery_geometry,
                "geometry":         self.geometry(),
            }, indent=2))
        except Exception:
            pass

    # ── Browse / Drop ─────────────────────────────────────────────────────────

    def _open_gallery(self):
        folder_str = self._folder_var.get().strip()
        if not folder_str:
            self._status("No folder selected.", error=True)
            return
        folder = pathlib.Path(folder_str)
        if not folder.is_dir():
            self._status(f"Folder not found: {folder}", error=True)
            return
        GalleryWindow(self, folder,
                      prefix=self._prefix_var.get().strip(),
                      model_type=self._model_type_var.get(),
                      initial_geometry=self._gallery_geometry,
                      on_close=self._on_gallery_close)

    def _on_gallery_close(self, geometry: str):
        self._gallery_geometry = geometry
        self._save_settings()

    def _browse_folder(self):
        p = filedialog.askdirectory(title="Select image folder (or parent for batch)")
        if p:
            self._folder_var.set(p)

    def _on_drop(self, event):
        raw = event.data.strip()
        # Windows DnD wraps paths with spaces in {braces}
        if raw.startswith("{"):
            path_str = raw[1:raw.find("}")]
        else:
            path_str = raw.split()[0]
        p = pathlib.Path(path_str)
        if p.is_dir():
            self._folder_var.set(str(p))
            self._status(f"Folder set: {p.name}")

    # ── Generation ───────────────────────────────────────────────────────────

    def _start(self):
        folder = self._folder_var.get().strip()
        if not folder:
            self._status("No folder selected.", error=True)
            return

        root = pathlib.Path(folder)
        if not root.exists():
            self._status(f"Folder not found: {root}", error=True)
            return

        self._save_settings()
        self._stop_event.clear()
        self._running = True
        self._go_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._log_clear()

        kwargs = dict(
            root=root,
            model=self._model_var.get().strip(),
            host=self._host_var.get().strip(),
            dry_run=self._dryrun_var.get(),
            overwrite=self._overwrite_var.get(),
            prefix=self._prefix_var.get().strip(),
            batch=self._batch_var.get(),
            model_type=self._model_type_var.get(),
        )
        threading.Thread(target=self._worker, kwargs=kwargs, daemon=True).start()

    def _stop(self):
        self._stop_event.set()
        self._status("Stopping after current image…")

    def _worker(self, root, model, host, dry_run, overwrite, prefix, batch, model_type="wan"):
        try:
            if batch:
                folders = sorted(d for d in root.iterdir() if d.is_dir())
                self._q.put(("header", f"Batch mode — {len(folders)} folders\n"))
            else:
                folders = [root]

            total_folders = len(folders)
            for fi, folder in enumerate(folders, 1):
                if self._stop_event.is_set():
                    break

                suffix = "ltx" if model_type == "ltx" else "wan"
                wan_out = folder / f"gen__{suffix}.txt"
                neg_out = folder / f"gen__{suffix}_neg.txt"

                if wan_out.exists() and not overwrite:
                    self._q.put(("muted", f"\nSkipping {folder.name} — already has {suffix.upper()} file\n"))
                    continue

                images = sorted(
                    f for f in folder.iterdir()
                    if f.suffix.lower() in IMG_EXTS
                    and (not prefix or f.name.startswith(prefix))
                )

                if not images:
                    self._q.put(("muted", f"\nNo images in {folder.name}\n"))
                    continue

                self._q.put(("header", f"\n{'─'*50}\n{folder.name}  ({len(images)} images)\n{'─'*50}\n"))

                wan_lines, neg_lines = [], []
                for i, img_path in enumerate(images, 1):
                    if self._stop_event.is_set():
                        break

                    self._q.put(("progress", (i, len(images), fi, total_folders)))
                    self._q.put(("muted", f"  [{i:>3}/{len(images)}] {img_path.name}  "))

                    action, booru = _extract_scene_info(img_path, img_index=i)

                    next_booru = ""
                    if "strip" in action.lower() and i < len(images):
                        next_action, nb = _extract_scene_info(images[i], img_index=i + 1)
                        if "strip" in next_action.lower():
                            next_booru = nb

                    neg = LTX_NEG_PROMPT if model_type == "ltx" else NEG_PROMPT

                    if dry_run:
                        self._q.put(("muted", "(dry-run)\n"))
                        wan_lines.append(f"[dry-run] {img_path.name}")
                        neg_lines.append(neg)
                        continue

                    try:
                        t0 = time.time()
                        b64 = _img_to_b64(img_path)
                        response = _generate(host, model, b64, action, booru,
                                             next_booru=next_booru, model_type=model_type)
                        response = _clean(response)
                        if not response:
                            response = action
                        elapsed = time.time() - t0
                        self._q.put(("muted", f"({elapsed:.1f}s)\n"))
                        self._q.put(("prompt", f"        → {response}\n"))
                        wan_lines.append(response)
                        neg_lines.append(neg)
                    except Exception as e:
                        self._q.put(("error", f"ERROR: {e}\n"))
                        wan_lines.append(f"[error] {img_path.name}")
                        neg_lines.append(neg)

                if not dry_run and wan_lines and not self._stop_event.is_set():
                    wan_out.write_text("\n".join(wan_lines), encoding="utf-8")
                    neg_out.write_text("\n".join(neg_lines), encoding="utf-8")
                    self._q.put(("success", f"  ✓ Written {wan_out.name} ({len(wan_lines)} lines)\n"))
                elif dry_run:
                    self._q.put(("muted", f"  [dry-run] {len(wan_lines)} prompts not written\n"))

        except Exception as e:
            self._q.put(("error", f"\nUnhandled error: {e}\n"))
        finally:
            self._q.put(("done", None))

    # ── Queue polling ─────────────────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                kind, data = self._q.get_nowait()
                if kind == "done":
                    self._on_done()
                elif kind == "progress":
                    img_i, img_n, fold_i, fold_n = data
                    if fold_n > 1:
                        self._progress_var.set(f"Folder {fold_i}/{fold_n}  ·  Image {img_i}/{img_n}")
                    else:
                        self._progress_var.set(f"Image {img_i}/{img_n}")
                else:
                    self._log_append(data, tag=kind)
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def _on_done(self):
        self._running = False
        self._go_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._progress_var.set("")
        if self._stop_event.is_set():
            self._status("Stopped.")
        else:
            self._status("Done.")

    # ── Log helpers ───────────────────────────────────────────────────────────

    def _log_append(self, text: str, tag: str = ""):
        self._log.configure(state="normal")
        if tag:
            self._log.insert(tk.END, text, tag)
        else:
            self._log.insert(tk.END, text)
        self._log.see(tk.END)
        self._log.configure(state="disabled")

    def _log_clear(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", tk.END)
        self._log.configure(state="disabled")

    def _status(self, msg: str, error: bool = False):
        self._status_var.set(msg)


if __name__ == "__main__":
    app = WanGenApp()
    app.mainloop()
