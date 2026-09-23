"""Core file-moving logic.

Rules (safety-critical, read before changing):
  * Only loose, top-level FILES in the watched folder are ever moved.
  * Subfolders are NEVER descended into. Protected project folders
    (see project_detector.SafeZone Detection) are reported as skipped.
  * Category destination folders created by the organizer are skipped so
    already-organized files are never re-moved.
  * Incomplete downloads (.crdownload, .part, .tmp, ...) and OS files
    (desktop.ini, Thumbs.db, ...) are skipped, not moved.
  * Name collisions are resolved with "name (1).ext" suffixing — never overwrite.
  * Every move is recorded for Undo and appended to logs/activity.log.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
LOGS_DIR = APP_DIR / "logs"
ACTIVITY_LOG = LOGS_DIR / "activity.log"
UNDO_FILE = APP_DIR / "undo_history.json"

# Extensions that mean "download still in progress — leave the file alone".
INCOMPLETE_SUFFIXES = frozenset({
    ".crdownload", ".part", ".tmp", ".download",
    ".opdownload", ".!ut", ".pending",
})

# OS / app bookkeeping files that must never be organized.
SYSTEM_FILES = frozenset({
    "desktop.ini", "thumbs.db", ".ds_store",
})

_lock = threading.Lock()
_category_map: dict[str, str] | None = None   # ext (".pdf") -> folder name ("Documents")
_category_dirs: set[str] | None = None        # lower-cased managed folder names
_display_names: dict[str, str] | None = None


def _ensure_logs_dir() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def load_category_map(config_path: str | Path = CONFIG_PATH) -> dict[str, str]:
    """Load extension -> category-folder mapping from config.json (cached)."""
    global _category_map, _category_dirs, _display_names
    with _lock:
        if _category_map is not None:
            return dict(_category_map)
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        data = {}
    mapping: dict[str, str] = {}
    display: dict[str, str] = {}
    for category, exts in (data.get("categories") or {}).items():
        display[category] = (data.get("display_names") or {}).get(category, category)
        for ext in exts or []:
            mapping[str(ext).lower()] = category
    with _lock:
        _category_map = mapping
        _category_dirs = {c.lower() for c in (data.get("categories") or {}).keys()}
        _display_names = display
    return dict(mapping)


def reload_category_map() -> dict[str, str]:
    """Force re-read of config.json (tests / future settings use)."""
    global _category_map, _category_dirs, _display_names
    with _lock:
        _category_map = None
        _category_dirs = None
        _display_names = None
    return load_category_map()


def get_managed_category_dir_names() -> list[str]:
    """Folder names the organizer itself creates (skipped during scans)."""
    load_category_map()
    with _lock:
        source = _category_dirs or set()
    # Recover original casing from config for display / mkdir.
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cats = list((json.load(fh).get("categories") or {}).keys())
        return cats
    except (OSError, json.JSONDecodeError):
        return sorted(source)


def display_name(category: str) -> str:
    load_category_map()
    with _lock:
        return (_display_names or {}).get(category, category)


def get_category(filename: str) -> str:
    """Category folder name for a filename; 'Others' when unrecognized."""
    load_category_map()
    with _lock:
        mapping = dict(_category_map or {})
    ext = Path(filename).suffix.lower()
    if not ext:
        return "Others"
    return mapping.get(ext, "Others")


def is_incomplete_download(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() in INCOMPLETE_SUFFIXES:
        return True
    return name.endswith((".crdownload", ".part", ".tmp", ".download"))


def is_system_file(path: Path) -> bool:
    return path.name.lower() in SYSTEM_FILES


def _unique_destination(dest_dir: Path, filename: str) -> Path:
    """Collision-safe destination; never overwrites an existing file."""
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem, suffix = Path(filename).stem, Path(filename).suffix
    i = 1
    while True:
        candidate = dest_dir / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def log_activity(message: str) -> None:
    _ensure_logs_dir()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ACTIVITY_LOG, "a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {message}\n")


# ---------------------------------------------------------------------------
# Undo — every move pushes {"src", "dst", "batch"}; undo pops the last batch.
# ---------------------------------------------------------------------------

def _load_undo_stack() -> list[dict]:
    try:
        with open(UNDO_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_undo_stack(stack: list[dict]) -> None:
    try:
        with open(UNDO_FILE, "w", encoding="utf-8") as fh:
            json.dump(stack[-200:], fh, indent=2)  # cap: last 200 moves
    except OSError:
        pass


def record_move(original: Path, moved_to: Path, batch_id: str | None = None) -> None:
    stack = _load_undo_stack()
    stack.append({
        "src": str(original),
        "dst": str(moved_to),
        "batch": batch_id or uuid.uuid4().hex[:8],
        "time": datetime.now().isoformat(timespec="seconds"),
    })
    _save_undo_stack(stack)


def undo_last_action() -> dict:
    """Undo the most recent organize batch. Returns a result dict for the UI."""
    stack = _load_undo_stack()
    if not stack:
        return {"status": "empty", "restored": 0, "message": "Nothing to undo."}
    batch = stack[-1]["batch"]
    to_undo = [m for m in stack if m["batch"] == batch]
    remaining = [m for m in stack if m["batch"] != batch]

    restored, failed = 0, []
    for move in reversed(to_undo):
        dst, src = Path(move["dst"]), Path(move["src"])
        try:
            if dst.exists():
                src.parent.mkdir(parents=True, exist_ok=True)
                target = _unique_destination(src.parent, src.name) \
                    if src.exists() else src
                shutil.move(str(dst), str(target))
                restored += 1
        except (OSError, shutil.Error):
            failed.append(dst.name)
    _save_undo_stack(remaining)
    msg = f"Restored {restored} file(s)."
    if failed:
        msg += f" Could not restore: {', '.join(failed)}."
    log_activity(f"UNDO: {msg}")
    return {"status": "ok", "restored": restored,
            "failed": failed, "message": msg}


def has_undo_available() -> bool:
    return bool(_load_undo_stack())


# ---------------------------------------------------------------------------
# Organizing
# ---------------------------------------------------------------------------

def wait_until_stable(path: Path, timeout: float = 10.0,
                       interval: float = 0.5) -> bool:
    """Wait until file size stops changing (download finished)."""
    deadline = time.time() + timeout
    try:
        last = path.stat().st_size
    except OSError:
        return False
    while time.time() < deadline:
        time.sleep(interval)
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == last:
            return True
        last = size
    return True  # timed out but file exists — proceed rather than stall live mode


def organize_file(file_path: str | Path, watched_root: str | Path,
                  batch_id: str | None = None,
                  wait_for_stable: bool = False) -> dict:
    """Organize a single file. Never raises for expected skip conditions."""
    src = Path(file_path)
    root = Path(watched_root)
    batch_id = batch_id or uuid.uuid4().hex[:8]

    if not src.is_file():
        return {"status": "skipped", "reason": "not a file",
                "src": str(src), "dst": None}
    try:
        # Only direct children of the watched folder — never touch subfolders.
        if src.parent.resolve() != root.resolve():
            return {"status": "skipped", "reason": "inside a subfolder",
                    "src": str(src), "dst": None}
    except OSError:
        return {"status": "error", "reason": "unreadable path",
                "src": str(src), "dst": None}

    if is_system_file(src):
        return {"status": "skipped", "reason": "system file",
                "src": str(src), "dst": None}
    if is_incomplete_download(src):
        return {"status": "skipped", "reason": "download in progress",
                "src": str(src), "dst": None}

    if wait_for_stable and not wait_until_stable(src):
        return {"status": "skipped", "reason": "file is still changing",
                "src": str(src), "dst": None}

    category = get_category(src.name)
    dest_dir = root / category
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Already where it belongs (e.g. re-scan after a move).
        if src.parent.resolve() == dest_dir.resolve():
            return {"status": "skipped", "reason": "already organized",
                    "src": str(src), "dst": None}
        dest = _unique_destination(dest_dir, src.name)
        shutil.move(str(src), str(dest))
    except (OSError, shutil.Error) as exc:
        log_activity(f"ERROR: could not move {src.name}: {exc}")
        return {"status": "error", "reason": str(exc),
                "src": str(src), "dst": None}

    record_move(src, dest, batch_id)
    log_activity(f"MOVED: {src.name} -> {category}/")
    return {"status": "moved", "reason": category,
            "src": str(src), "dst": str(dest), "batch": batch_id}


def organize_folder(watched: str | Path, ignore_list=None) -> list[dict]:
    """Organize all loose top-level files; report protected folders as skipped.

    Returns a flat list of result dicts — one per loose file plus one
    {"status": "protected", ...} entry per protected subfolder so the
    Activity Feed can show "X skipped (protected)" transparently.
    """
    from project_detector import is_protected_folder  # deferred: avoids cycle

    root = Path(watched)
    results: list[dict] = []
    if not root.is_dir():
        return results

    load_category_map()
    with _lock:
        managed = set(_category_dirs or set())
    batch_id = uuid.uuid4().hex[:8]

    try:
        entries = sorted(root.iterdir(), key=lambda e: e.name.lower())
    except (OSError, PermissionError):
        return results

    for entry in entries:
        try:
            if entry.is_dir():
                if entry.name.lower() in managed:
                    continue  # organizer's own output folder
                protected, reason = is_protected_folder(entry, ignore_list)
                if protected:
                    results.append({"status": "protected", "reason": reason,
                                    "src": str(entry), "dst": None,
                                    "name": entry.name})
                    log_activity(f"SKIPPED (protected): {entry.name} — {reason}")
                # Non-protected regular subfolders are left alone too:
                # only loose files are organized, never folder contents.
                continue
            if entry.is_file():
                results.append(organize_file(entry, root, batch_id))
        except (OSError, PermissionError):
            results.append({"status": "error", "reason": "unreadable",
                            "src": str(entry), "dst": None})
    return results
