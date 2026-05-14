"""Shared UI helpers."""
import tkinter as tk
import customtkinter as ctk


class Tooltip:
    """Dark-themed hover tooltip for any tkinter/CTk widget."""

    def __init__(self, widget: tk.BaseWidget, text: str, delay: int = 500):
        self._widget = widget
        self._text = text
        self._delay = delay
        self._tip: tk.Toplevel | None = None
        self._after_id: str | None = None

        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, _=None):
        self._cancel()
        self._after_id = self._widget.after(self._delay, self._show)

    def _on_leave(self, _=None):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._after_id:
            self._widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        if self._tip:
            return
        x = self._widget.winfo_rootx() + self._widget.winfo_width() // 2
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 6
        self._tip = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        tk.Label(
            tw, text=self._text,
            background="#1c1c2e", foreground="#dce4ee",
            relief="flat", borderwidth=0,
            font=("Segoe UI", 9),
            padx=8, pady=4,
            wraplength=260,
            justify="left",
        ).pack()

    def _hide(self):
        if self._tip:
            self._tip.destroy()
            self._tip = None


def tip(widget: tk.BaseWidget, text: str, delay: int = 500) -> Tooltip:
    """Attach a hover tooltip to widget and return it."""
    return Tooltip(widget, text, delay)


def center_on_root(widget: tk.BaseWidget, w: int, h: int) -> None:
    """Position `widget` (w×h) centered over its root window.

    Sets geometry immediately so CTk's internal after() calls can't override it,
    then re-applies after a short delay and brings the window to the front.
    """
    try:
        root = widget.master.winfo_toplevel()
    except AttributeError:
        root = widget.winfo_toplevel()

    def _apply():
        try:
            root.update_idletasks()
            rx, ry = root.winfo_x(), root.winfo_y()
            rw, rh = root.winfo_width(), root.winfo_height()
            x = rx + (rw - w) // 2
            y = ry + (rh - h) // 2
            widget.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _raise():
        try:
            widget.lift()
            widget.focus_force()
            widget.attributes("-topmost", True)
            widget.after(100, lambda: widget.attributes("-topmost", False))
        except Exception:
            pass

    _apply()                         # set immediately
    widget.after(50, _apply)         # re-apply after CTk's internal after() fires
    widget.after(150, _raise)        # then bring to front


def center_input_dialog(dialog: ctk.CTkInputDialog, master: tk.BaseWidget) -> None:
    """Center a CTkInputDialog over master's root window."""
    root = master.winfo_toplevel()

    def _do_center():
        try:
            root.update_idletasks()
            dialog.update_idletasks()
            dw = dialog.winfo_reqwidth() or 300
            dh = dialog.winfo_reqheight() or 150
            rx, ry = root.winfo_x(), root.winfo_y()
            rw, rh = root.winfo_width(), root.winfo_height()
            x = rx + (rw - dw) // 2
            y = ry + (rh - dh) // 2
            dialog.geometry(f"+{x}+{y}")
            dialog.lift()
            dialog.focus_force()
            dialog.attributes("-topmost", True)
            dialog.after(100, lambda: dialog.attributes("-topmost", False))
        except Exception:
            pass

    dialog.after(50, _do_center)


def make_msgbox_parent(master: tk.BaseWidget) -> tk.Toplevel:
    """Return a hidden Toplevel positioned at the center of master's root.

    Pass this as `parent=` to tkinter messagebox calls so the dialog
    appears centered over the main window. Call .destroy() afterward.
    """
    root = master.winfo_toplevel()
    root.update_idletasks()
    rx, ry = root.winfo_x(), root.winfo_y()
    rw, rh = root.winfo_width(), root.winfo_height()
    helper = tk.Toplevel(root)
    helper.withdraw()
    helper.geometry(f"+{rx + rw // 2}+{ry + rh // 2}")
    return helper
