"""CustomTkinter UI: first-run onboarding (3 steps) + main dashboard (4 zones).

Dashboard zones:
  1. Status bar (top): Live / Paused / Error with color coding.
  2. Folders list: one card per watched folder (file count + options menu).
  3. Activity feed: real-time scrolling log, capped at last 15 entries.
  4. Quick actions (bottom): Organize Now, Undo, Settings.

Design: minimal palette (action blue + success green + protected yellow),
large type (>=14px), icon-first buttons, friendly empty states, follows the
OS light/dark theme automatically (no manual toggle).
"""

from __future__ import annotations
import json
import os

import queue
import subprocess
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
    _CTK_AVAILABLE = True
except ImportError:
    ctk = None  # type: ignore
    _CTK_AVAILABLE = False

import organizer as org
from project_detector import scan_watched_folder
import settings as app_settings
from watcher import FolderWatcherManager, watchdog_available

FEED_CAP = 15
FONT_NORMAL = ("Segoe UI", 14)
FONT_SMALL = ("Segoe UI", 12)
FONT_TITLE = ("Segoe UI", 20, "bold")
FONT_SECTION = ("Segoe UI", 15, "bold")

STATUS_COLORS = {
    "Live": "#2E9E5B",    # success green
    "Paused": "#8A8A8A",  # neutral grey
    "Error": "#D64545",   # error red
}
PROTECTED_COLOR = "#B98A1D"  # protected / warning yellow (dark-mode readable)


def _require_ctk() -> None:
    if not _CTK_AVAILABLE:
        raise RuntimeError(
            "CustomTkinter is not installed. Run: pip install -r requirements.txt")


def feed_text(result: dict) -> tuple[str, str]:
    """(message, tag) for an organizer result dict. Plain, jargon-free."""
    status = result.get("status")
    if status == "moved":
        cat = org.display_name(result.get("reason", "Others"))
        src = Path(result.get("src", "?")).name
        return f"\u2705 {src} moved to {cat}", "moved"
    if status == "protected":
        name = result.get("name") or Path(result.get("src", "?")).name
        return f"\U0001F6E1\uFE0F {name} skipped (protected)", "protected"
    if status == "protected-check":
        # Checking-in-progress, not a result: never present this as a
        # "skipped (protected)" verdict. Genuine protected folders arrive
        # separately with status "protected" (branch above), which does
        # reflect the real is_protected_folder() outcome.
        return "", "info"
    if status == "skipped":
        reason = result.get("reason", "")
        if reason in ("already organized", "system file",
                       "inside a subfolder", "not a file"):
            return "", "info"  # noise — don't clutter a non-technical feed
        if reason == "download in progress":
            src = Path(result.get("src", "?")).name
            return f"\u23F3 {src} — still downloading, will retry", "info"
        # Any other skip reason from the organizer gets a plain message —
        # transparency beats a quiet feed; nothing falls through to "".
        src = Path(result.get("src", "?")).name
        return f"\u23ED {src} skipped \u2014 {reason}", "info"
    if status == "error":
        src = Path(result.get("src", "?")).name
        return f"\u26A0\uFE0F {src} couldn't be moved", "error"
    return "", "info"


def _settings_fingerprint_now():
    """(mtime, size) of settings.json, or None if unreadable/missing."""
    try:
        st = app_settings.SETTINGS_PATH.stat()
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


class ToolTip:
    """Minimal hover tooltip (plain-language explanations for protected items)."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        if self.tip is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + 20
            self.tip = tw = ctk.CTkToplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            ctk.CTkLabel(tw, text=self.text, font=FONT_SMALL,
                          wraplength=260).pack(padx=10, pady=8)
        except Exception as exc:
            org.log_activity(f"ERROR: ToolTip._show: {exc}")

    def _hide(self, _event=None):
        if self.tip is not None:
            try:
                self.tip.destroy()
            except Exception as exc:
                org.log_activity(f"ERROR: ToolTip._hide: {exc}")
            self.tip = None


class App(ctk.CTk if _CTK_AVAILABLE else object):  # type: ignore
    def __init__(self, tray_controller=None):
        _require_ctk()
        super().__init__()
        self.tray_controller = tray_controller
        self.settings = app_settings.load_settings()
        self._settings_fingerprint = _settings_fingerprint_now()
        self.watcher = FolderWatcherManager(
            on_result=self._on_watcher_result_threadsafe,
            get_ignore_list=lambda: self.settings.get("ignore_list", []))
        self._feed_queue: queue.Queue = queue.Queue()
        self._feed_items: list[tuple[str, str]] = []

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")
        self.title("Auto File Organizer")
        self.geometry("760x620")
        self.minsize(640, 520)

        self.protocol("WM_DELETE_WINDOW", self._on_close_window)

        if not self.settings.get("onboarding_done"):
            self._show_onboarding()
        else:
            self._show_dashboard()
            self._apply_live_mode(initial=True)
        self._poll_feed_queue()

    # ------------------------------------------------------------------
    # Onboarding (3 steps, first launch only)
    # ------------------------------------------------------------------
    def _clear(self):
        for child in self.winfo_children():
            child.destroy()

    def _show_onboarding(self):
        self._clear()
        self.onboard_step = 1
        self.onboard_choice: str | None = None
        self._render_onboard_step()

    def _render_onboard_step(self):
        self._clear()
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(expand=True, fill="both", padx=40, pady=40)

        if self.onboard_step == 1:
            ctk.CTkLabel(wrap, text="\U0001F4C1", font=("Segoe UI", 56)).pack(pady=(30, 10))
            ctk.CTkLabel(wrap, text="Welcome to Auto File Organizer",
                         font=FONT_TITLE).pack(pady=6)
            ctk.CTkLabel(
                wrap,
                text="The only auto-organizer that knows what NOT to touch.\n"
                     "Your coding projects stay exactly as they are —\n"
                     "everything else tidies itself.",
                font=FONT_NORMAL, justify="center").pack(pady=10)
            ctk.CTkButton(wrap, text="Get Started  \u2192", font=FONT_NORMAL,
                          height=44,
                          command=self._onboard_next).pack(pady=24)

        elif self.onboard_step == 2:
            ctk.CTkLabel(wrap, text="Which folder should I keep tidy?",
                         font=FONT_SECTION).pack(pady=(20, 4))
            ctk.CTkLabel(wrap, text="Pick one — you can add more later.",
                         font=FONT_SMALL).pack(pady=(0, 16))
            downloads = app_settings.default_downloads_folder()
            desktop = str(Path.home() / "Desktop")
            for label, path in (("\U0001F4E5  Downloads", downloads),
                                ("\U0001F5A5\uFE0F  Desktop", desktop)):
                exists = Path(path).is_dir()
                btn = ctk.CTkButton(
                    wrap, text=f"{label}\n{path}" if exists else f"{label} (not found)",
                    font=FONT_NORMAL, height=56,
                    state="normal" if exists else "disabled",
                    command=lambda p=path: self._onboard_pick(p))
                btn.pack(fill="x", pady=6)
            ctk.CTkButton(wrap, text="\U0001F4C2  Choose Different Folder…",
                          font=FONT_NORMAL, height=44, fg_color="transparent",
                          border_width=1,
                          command=self._onboard_browse).pack(fill="x", pady=6)
            if self.onboard_choice:
                ctk.CTkLabel(wrap, text=f"Selected: {self.onboard_choice}",
                             font=FONT_SMALL).pack(pady=8)

        elif self.onboard_step == 3:
            ctk.CTkLabel(wrap, text="\U0001F6E1\uFE0F SafeZone Detection is on",
                         font=FONT_SECTION).pack(pady=(20, 4))
            folder = self.onboard_choice or app_settings.default_downloads_folder()
            ctk.CTkLabel(
                wrap,
                text=f"We'll watch:\n{folder}\n\n"
                     "Coding folders (like ones with .git or package.json)\n"
                     "are auto-protected and never touched.\n"
                     "You can undo anything with one click.",
                font=FONT_NORMAL, justify="center").pack(pady=10)
            ctk.CTkButton(wrap, text="\u2728  Start Organizing", font=FONT_NORMAL,
                          height=48,
                          command=self._onboard_finish).pack(pady=20)
            ctk.CTkButton(wrap, text="\u2190 Back", font=FONT_SMALL,
                          fg_color="transparent",
                          command=self._onboard_back).pack()

    def _onboard_next(self):
        self.onboard_step = 2
        self._render_onboard_step()

    def _onboard_back(self):
        self.onboard_step = 2
        self._render_onboard_step()

    def _onboard_pick(self, path: str):
        self.onboard_choice = path
        self.onboard_step = 3
        self._render_onboard_step()

    def _onboard_browse(self):
        picked = filedialog.askdirectory(title="Choose a folder to organize")
        if picked:
            self._onboard_pick(picked)

    def _onboard_finish(self):
        folder = self.onboard_choice or app_settings.default_downloads_folder()
        watched = self.settings.get("watched_folders", [])
        if folder not in watched:
            watched.append(folder)
        self.settings["watched_folders"] = watched
        self.settings["onboarding_done"] = True
        app_settings.save_settings(self.settings)
        self._show_dashboard()
        self._apply_live_mode(initial=True)
        # First run: organize immediately so users see value, then toast.
        self.organize_now()

    # ------------------------------------------------------------------
    # Dashboard (4 zones)
    # ------------------------------------------------------------------
    def _show_dashboard(self):
        self._clear()

        # Zone 1 — status bar ------------------------------------------------
        self.status_bar = ctk.CTkFrame(self, height=44, corner_radius=0)
        self.status_bar.pack(fill="x")
        self.status_dot = ctk.CTkLabel(self.status_bar, text="\u25CF",
                                       font=("Segoe UI", 18))
        self.status_dot.pack(side="left", padx=(14, 4))
        self.status_label = ctk.CTkLabel(self.status_bar, text="Live",
                                         font=FONT_SECTION)
        self.status_label.pack(side="left")
        self.live_switch = ctk.CTkSwitch(
            self.status_bar, text="Live Auto-Organize", font=FONT_SMALL,
            command=self._on_live_toggle)
        self.live_switch.pack(side="right", padx=14)
        if self.settings.get("live_mode", True):
            self.live_switch.select()
        else:
            self.live_switch.deselect()

        # Zone 2 — folders list ----------------------------------------------
        ctk.CTkLabel(self, text="\U0001F4C1  Watched Folders",
                     font=FONT_SECTION).pack(anchor="w", padx=16, pady=(12, 4))
        list_wrap = ctk.CTkFrame(self, fg_color="transparent")
        list_wrap.pack(fill="both", expand=False, padx=12)
        self.folders_frame = ctk.CTkScrollableFrame(list_wrap, height=190)
        self.folders_frame.pack(fill="x")
        ctk.CTkButton(list_wrap, text="+  Add Folder", font=FONT_NORMAL,
                      height=38, command=self.add_folder_dialog).pack(
                          fill="x", pady=(8, 0))
        self._refresh_folder_cards()

        # Zone 3 — activity feed ----------------------------------------------
        feed_head = ctk.CTkFrame(self, fg_color="transparent")
        feed_head.pack(fill="x", padx=16, pady=(12, 0))
        ctk.CTkLabel(feed_head, text="\U0001F4DC  Activity",
                     font=FONT_SECTION).pack(side="left")
        ctk.CTkLabel(feed_head, text="coding folders show as Protected \U0001F6E1\uFE0F",
                     font=FONT_SMALL).pack(side="right")
        self.feed_box = ctk.CTkTextbox(self, height=150, font=FONT_SMALL,
                                       state="disabled", wrap="word")
        self.feed_box.pack(fill="both", expand=True, padx=12, pady=6)

        # Zone 4 — quick actions -----------------------------------------------
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(0, 14))
        self.organize_btn = ctk.CTkButton(
            actions, text="\u2728  Organize Now", font=FONT_NORMAL, height=44,
            command=self.organize_now)
        self.organize_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))
        self.undo_btn = ctk.CTkButton(
            actions, text="\u21A9  Undo", font=FONT_NORMAL, height=44,
            fg_color="transparent", border_width=1,
            command=self.undo_last)
        self.undo_btn.pack(side="left", expand=True, fill="x", padx=(6, 6))
        settings_btn = ctk.CTkButton(actions, text="\u2699", font=(FONT_NORMAL[0], 22),
                                     width=56, height=44, fg_color="transparent",
                                     border_width=1, command=self.open_settings)
        settings_btn.pack(side="left", padx=(6, 0))
        ToolTip(settings_btn, "Settings: Ignore List and categories")
        self._refresh_undo_state()
        self._update_status_ui(initial=True)

    # -- Zone 1: status -------------------------------------------------------
    def _current_status(self) -> str:
        if not watchdog_available():
            return "Error"
        if not self.settings.get("live_mode", True):
            return "Paused"
        folders = [f for f in self.settings.get("watched_folders", [])
                   if Path(f).is_dir()]
        if not folders:
            return "Paused"
        return "Live"

    def _update_status_ui(self, initial: bool = False):
        status = self._current_status()
        color = STATUS_COLORS.get(status, "#8A8A8A")
        try:
            self.status_dot.configure(text_color=color)
            self.status_label.configure(
                text=status if status != "Error"
                 else "Error — monitoring unavailable (pip install watchdog)")
        except Exception as exc:
            org.log_activity(f"ERROR: App._update_status_ui: {exc}")
        if not initial:
            self.push_feed(f"Status: {status}", "info")

    def _on_live_toggle(self):
        self.settings["live_mode"] = bool(self.live_switch.get())
        app_settings.save_settings(self.settings)
        self._apply_live_mode()

    def _apply_live_mode(self, initial: bool = False):
        live = self.settings.get("live_mode", True)
        folders = [f for f in self.settings.get("watched_folders", [])
                   if Path(f).is_dir()]
        self.watcher.pause_all()
        if live and watchdog_available():
            # resume_all() unpauses AND starts observers; add_folder() alone
            # refuses to start anything while paused, so this call is what
            # actually begins watching.
            self.watcher.resume_all(folders)
        try:
            if live:
                self.live_switch.select()
            else:
                self.live_switch.deselect()
        except Exception as exc:
            org.log_activity(f"ERROR: App._apply_live_mode: {exc}")
        self._update_status_ui(initial=initial)

    # -- Zone 2: folder cards ---------------------------------------------------
    def _refresh_folder_cards(self):
        try:
            for child in self.folders_frame.winfo_children():
                child.destroy()
        except Exception as exc:
            org.log_activity(f"ERROR: App._refresh_folder_cards: {exc}")
            return
        folders = self.settings.get("watched_folders", [])
        if not folders:
            ctk.CTkLabel(
                self.folders_frame,
                text="\U0001F4AD Add your first folder to get started",
                font=FONT_NORMAL).pack(pady=24)
            return
        ignore = self.settings.get("ignore_list", [])
        for folder in folders:
            self._make_folder_card(folder, ignore)

    def _make_folder_card(self, folder: str, ignore: list):
        card = ctk.CTkFrame(self.folders_frame)
        card.pack(fill="x", pady=4, padx=4)
        path = Path(folder)
        try:
            loose = sum(1 for e in path.iterdir() if e.is_file()) \
                if path.is_dir() else 0
        except OSError:
            loose = 0
        try:
            protected = [s for s in scan_watched_folder(path, ignore)
                          if s["protected"]]
        except Exception as exc:
            org.log_activity(f"ERROR: App._make_folder_card protected scan: {exc}")
            protected = []

        title = ctk.CTkLabel(card, text=f"\U0001F4C1  {path.name or folder}",
                             font=FONT_NORMAL)
        title.pack(anchor="w", padx=10, pady=(8, 0))
        sub = f"{folder}  •  {loose} loose file(s)"
        if protected:
            sub += f"  •  \U0001F6E1\uFE0F {len(protected)} protected"
        sub_label = ctk.CTkLabel(card, text=sub, font=FONT_SMALL)
        sub_label.pack(anchor="w", padx=10)
        if protected:
            names = ", ".join(s["name"] for s in protected[:3])
            more = "" if len(protected) <= 3 else f" +{len(protected) - 3} more"
            prot = ctk.CTkLabel(card, text=f"\U0001F6E1\uFE0F Protected: {names}{more}",
                                font=FONT_SMALL, text_color=PROTECTED_COLOR)
            prot.pack(anchor="w", padx=10)
            ToolTip(prot, "SafeZone Detection: coding projects are never touched. "
                          "Hover reason: " + "; ".join(
                              f"{s['name']}: {s['reason']}" for s in protected[:3]))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(anchor="e", padx=8, pady=6)
        ctk.CTkButton(btn_row, text="\U0001F4C2 Open", font=FONT_SMALL, width=80,
                      fg_color="transparent", border_width=1,
                      command=lambda f=folder: self._open_in_explorer(f)).pack(side="left", padx=3)
        ctk.CTkButton(btn_row, text="Organize", font=FONT_SMALL, width=90,
                      command=lambda f=folder: self._organize_single(f)).pack(side="left", padx=3)
        ctk.CTkButton(btn_row, text="\u2715", font=FONT_SMALL, width=40,
                      fg_color="transparent", border_width=1,
                      command=lambda f=folder: self.remove_folder(f)).pack(side="left", padx=3)

    def add_folder_dialog(self):
        picked = filedialog.askdirectory(title="Choose a folder to organize")
        if not picked:
            return
        folders = self.settings.get("watched_folders", [])
        if picked in folders:
            messagebox.showinfo("Already watched",
                                "That folder is already being organized.")
            return
        folders.append(picked)
        self.settings["watched_folders"] = folders
        app_settings.save_settings(self.settings)
        self._refresh_folder_cards()
        self._apply_live_mode()
        self.push_feed(f"\U0001F4C1 Now watching {Path(picked).name}", "info")

    def remove_folder(self, folder: str):
        if not messagebox.askyesno("Remove folder?",
                                   f"Stop organizing:\n{folder}\n\n"
                                   "Files already organized stay where they are."):
            return
        folders = [f for f in self.settings.get("watched_folders", []) if f != folder]
        self.settings["watched_folders"] = folders
        app_settings.save_settings(self.settings)
        self.watcher.remove_folder(folder)
        self._refresh_folder_cards()
        self._update_status_ui()

    @staticmethod
    def _open_in_explorer(folder: str):
        try:
            os.startfile(folder)  # type: ignore[attr-defined]  # Windows
        except OSError:
            try:
                subprocess.Popen(["explorer", folder])
            except OSError:
                pass

    # -- Zone 3: activity feed ---------------------------------------------------
    def push_feed(self, message: str, tag: str = "info"):
        if not message:
            return
        self._feed_items.append((message, tag))
        del self._feed_items[:-FEED_CAP]
        try:
            self.feed_box.configure(state="normal")
            self.feed_box.delete("1.0", "end")
            for msg, _t in self._feed_items:
                self.feed_box.insert("end", msg + "\n")
            self.feed_box.see("end")
            self.feed_box.configure(state="disabled")
        except Exception as exc:
            org.log_activity(f"ERROR: App.push_feed: {exc}")

    def _poll_feed_queue(self):
        try:
            while True:
                result = self._feed_queue.get_nowait()
                msg, tag = feed_text(result)
                self.push_feed(msg, tag)
                if result.get("status") == "moved":
                    self._refresh_undo_state()
        except queue.Empty:
            pass
        try:
            self.after(200, self._poll_feed_queue)
        except Exception as exc:
            org.log_activity(f"ERROR: App._poll_feed_queue reschedule: {exc}")

    def _on_watcher_result_threadsafe(self, result: dict):
        self._feed_queue.put(result)

    # -- Zone 4: quick actions ----------------------------------------------------
    def organize_now(self):
        self._maybe_reload_settings()
        folders = [f for f in self.settings.get("watched_folders", [])
                    if Path(f).is_dir()]
        if not folders:
            messagebox.showinfo("No folders",
                                "Add a folder first, then press Organize Now.")
            return
        ignore = self.settings.get("ignore_list", [])
        self.organize_btn.configure(state="disabled", text="\u23F3  Organizing…")

        def _work():
            total_moved, total_prot = 0, 0
            for folder in folders:
                for r in org.organize_folder(folder, ignore):
                    self._feed_queue.put(r)
                    if r.get("status") == "moved":
                        total_moved += 1
                    elif r.get("status") == "protected":
                        total_prot += 1
            self.after(0, lambda: self._on_organize_done(total_moved, total_prot))

        threading.Thread(target=_work, daemon=True).start()

    def _on_organize_done(self, moved: int, protected: int):
        try:
            self.organize_btn.configure(state="normal", text="\u2728  Organize Now")
        except Exception as exc:
            org.log_activity(f"ERROR: App._on_organize_done: {exc}")
        self._refresh_folder_cards()
        self._refresh_undo_state()
        extra = f" ({protected} protected skipped)" if protected else ""
        self._toast(f"{moved} file(s) organized{extra}")

    def _organize_single(self, folder: str):
        ignore = self.settings.get("ignore_list", [])

        def _work():
            moved = 0
            for r in org.organize_folder(folder, ignore):
                self._feed_queue.put(r)
                if r.get("status") == "moved":
                    moved += 1
            self.after(0, lambda: (self._refresh_folder_cards(),
                                   self._refresh_undo_state(),
                                   self._toast(f"{moved} file(s) organized")))

        threading.Thread(target=_work, daemon=True).start()

    def undo_last(self):
        result = org.undo_last_action()
        self.push_feed(f"\u21A9 {result.get('message', '')}", "info")
        self._refresh_undo_state()
        self._refresh_folder_cards()

    def _refresh_undo_state(self):
        try:
            state = "normal" if org.has_undo_available() else "disabled"
            self.undo_btn.configure(state=state)
        except Exception as exc:
            org.log_activity(f"ERROR: App._refresh_undo_state: {exc}")

    def _toast(self, message: str):
        self.push_feed(message, "info")
        try:
            toast = ctk.CTkToplevel(self)
            toast.wm_overrideredirect(True)
            toast.wm_geometry(f"+{self.winfo_rootx() + 120}+{self.winfo_rooty() + 120}")
            ctk.CTkLabel(toast, text=message, font=FONT_NORMAL).pack(padx=20, pady=14)
            toast.after(2200, toast.destroy)
        except Exception as exc:
            org.log_activity(f"ERROR: App._toast: {exc}")

    # -- Settings ------------------------------------------------------------------
    def _maybe_reload_settings(self):
        """Re-read settings.json if it changed on disk since our last load.

        Boundary choice (deliberate): reload happens only at user-action
        boundaries (opening Settings, Organize Now) — never from a timer —
        so the snapshot can't change under running code mid-flight. The
        watcher's ignore-list lambda reads self.settings dynamically, so it
        picks up the reloaded dict with no extra wiring. Our own saves also
        bump the fingerprint; the follow-up reload then just re-parses
        identical content (harmless no-op). A changed-but-corrupt file keeps
        the running snapshot (and is logged) instead of adopting
        load_settings()' reset-to-defaults.
        """
        try:
            current = _settings_fingerprint_now()
        except Exception as exc:
            org.log_activity(f"ERROR: App._maybe_reload_settings stat: {exc}")
            return
        if current is None or current == self._settings_fingerprint:
            return
        try:
            json.loads(app_settings.SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            org.log_activity(
                "ERROR: App._maybe_reload_settings: settings.json changed "
                f"but unreadable ({exc}); keeping running settings")
            self._settings_fingerprint = current
            return
        self.settings = app_settings.load_settings()
        self._settings_fingerprint = current

    def open_settings(self):
        self._maybe_reload_settings()
        win = ctk.CTkToplevel(self)
        win.title("Settings")
        win.geometry("520x480")
        win.grab_set()

        ctk.CTkLabel(win, text="\U0001F6E1\uFE0F SafeZone Ignore List",
                     font=FONT_SECTION).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(win, text="Folder names that are always skipped, e.g. my-game-mod",
                     font=FONT_SMALL).pack(anchor="w", padx=16)
        ignore_box = ctk.CTkTextbox(win, height=110, font=FONT_NORMAL)
        ignore_box.pack(fill="x", padx=16, pady=8)
        ignore_box.insert("1.0", "\n".join(self.settings.get("ignore_list", [])))

        add_row = ctk.CTkFrame(win, fg_color="transparent")
        add_row.pack(fill="x", padx=16)
        entry = ctk.CTkEntry(add_row, placeholder_text="Add folder name…",
                             font=FONT_NORMAL)
        entry.pack(side="left", expand=True, fill="x", padx=(0, 8))

        def _add_name():
            name = entry.get().strip()
            if not name:
                return
            current = ignore_box.get("1.0", "end").strip().splitlines()
            if name.lower() not in {c.strip().lower() for c in current}:
                ignore_box.insert("end", ("" if not current else "\n") + name)
            entry.delete(0, "end")

        ctk.CTkButton(add_row, text="Add", font=FONT_NORMAL, width=80,
                      command=_add_name).pack(side="left")

        ctk.CTkLabel(win, text="\U0001F4C2 Categories (managed automatically)",
                     font=FONT_SECTION).pack(anchor="w", padx=16, pady=(14, 2))
        try:
            cats = org.get_managed_category_dir_names()
            ctk.CTkLabel(win, text=", ".join(org.display_name(c) for c in cats),
                          font=FONT_SMALL, wraplength=460).pack(anchor="w", padx=16)
        except Exception as exc:
            org.log_activity(f"ERROR: App.open_settings category list: {exc}")
        ctk.CTkLabel(win, text="Category rules live in the app files — no setup needed.",
                     font=FONT_SMALL).pack(anchor="w", padx=16, pady=(0, 8))

        def _save():
            names = [n.strip() for n in ignore_box.get("1.0", "end").strip().splitlines()
                     if n.strip()]
            self.settings["ignore_list"] = names
            app_settings.save_settings(self.settings)
            self._refresh_folder_cards()
            self.push_feed("\U0001F6E1\uFE0F Ignore List updated", "info")
            win.destroy()

        ctk.CTkButton(win, text="Save", font=FONT_NORMAL, height=42,
                      command=_save).pack(fill="x", padx=16, pady=12)

    # -- close => minimize to tray ---------------------------------------------------
    def _on_close_window(self):
        if self.tray_controller is not None:
            self.withdraw()  # keep running in the tray
            self.push_feed("Running in the background (tray icon)", "info")
        else:
            self._quit_app()

    def show_window(self):
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception as exc:
            org.log_activity(f"ERROR: App.show_window: {exc}")

    def _quit_app(self):
        try:
            self.watcher.stop_all()
        except Exception as exc:
            org.log_activity(f"ERROR: App._quit_app watcher stop: {exc}")
        try:
            self.destroy()
        except Exception as exc:
            org.log_activity(f"ERROR: App._quit_app destroy: {exc}")


def launch(tray_controller=None):
    """Entry point used by main.py (manual double-click path)."""
    _require_ctk()
    app = App(tray_controller=tray_controller)
    app.mainloop()
    return app
