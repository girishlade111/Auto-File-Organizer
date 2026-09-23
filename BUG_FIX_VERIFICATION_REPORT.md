# Auto File Organizer — Structural + State Report (Second Fix-Pass Verification)

Repo state: `main` @ `66d028b` ("Improve undo reporting, already-organized detection, and GUI skip feed messages"), working tree clean. Prior commits: `f4b010f` (first fix pass), `2f7b733` (baseline project import).

---

## 1. TECH STACK

| Item | Value |
|---|---|
| Language | Python (runtime on this machine: 3.14.6) |
| GUI framework | CustomTkinter (Tkinter-based) |
| File watching | watchdog |
| Tray | pystray + Pillow |
| Tests | pytest |
| Build | PyInstaller `--onedir --windowed` |
| Installer | Inno Setup (`installer/FileOrganizer.iss`) |
| Package manager | pip |
| Lockfile | **None** (no poetry.lock / uv.lock / Pipfile.lock / requirements.lock) |

**requirements.txt** (unchanged since baseline):
```
customtkinter>=5.2.2
watchdog>=4.0.0
pystray>=0.19.5
Pillow>=10.0.0
```

**requirements-dev.txt** (added in first pass `f4b010f`):
```
-r requirements.txt
pytest>=8.0.0
```

Bundler: PyInstaller (per README:48). No JS toolchain, no package.json, no node_modules.

---

## 2. FOLDER / FILE STRUCTURE

```
Auto File Organizer/
├── .gitignore                  # ignores logs/, settings.json, undo_history.json, dist/, build/, *.spec, venvs
├── README.md                   # user + dev docs, build/test commands
├── config.json                 # backend category map (ext → folder) + display_names
├── gui.py                      # CustomTkinter onboarding (3 steps) + dashboard (4 zones) + feed_text()
├── main.py                     # entry point; --tray = headless background mode
├── organizer.py                # file-moving core, undo stack, activity log, category cache
├── project_detector.py         # SafeZone Detection (is_protected_folder, scan_watched_folder)
├── requirements.txt            # runtime deps
├── requirements-dev.txt        # runtime + pytest            [NEW in pass 1]
├── settings.py                 # settings.json persistence (atomic write)
├── tray.py                     # pystray menu controller    [UNCHANGED since baseline]
├── watcher.py                  # watchdog observers + settle-delay handler
├── installer/
│   └── FileOrganizer.iss       # Inno Setup script, Startup-folder autostart (--tray)
└── tests/
    ├── conftest.py             # sys.path bootstrap         [NEW in pass 1]
    └── test_project_detector.py# 17 SafeZone tests          [NEW in pass 1]
```

**Not present:** `assets/` (no `assets/icon.ico`), `settings.json`, `undo_history.json`, `logs/` (all created at runtime; the first three are gitignored / absent).

**Files modified since the last fix pass** (pass 2 = `66d028b`, vs. pass 1 = `f4b010f`): only **`gui.py`** (+8/−3) and **`organizer.py`** (+44/−14) changed. Against the full baseline list: `tray.py` and `project_detector.py` have never been modified since `2f7b733`; `main.py`, `settings.py`, `watcher.py`, `README.md`, `tests/test_project_detector.py` were changed only in pass 1; new files are `requirements-dev.txt`, `tests/conftest.py`, `tests/test_project_detector.py`.

---

## 3. ARCHITECTURE

### Entry points
- `main.py:176 main()` → `parse_args()` (`--tray`) → `_run_gui_with_tray()` (`main.py:26`). Foreground path instantiates `gui.App(tray_controller=...)` at `main.py:158` and calls `app.mainloop()` at `main.py:161`. Background path (`main.py:134-152`) applies headless watchers and blocks on `tray.start_blocking()`.
- `gui.launch()` (`gui.py:657`) exists but is **not called by anything** — `main.py` imports `gui` and constructs `App` directly.
- Installer/Startup shortcut passes `--tray` (`installer/FileOrganizer.iss:47`).

### Module connections / data flow
- `gui.py:30-33` imports `organizer as org`, `project_detector.scan_watched_folder`, `settings`, `watcher.FolderWatcherManager`.
- Manual organize: `App.organize_now()` (`gui.py:502`) → worker thread (`gui.py:523`) → `org.organize_folder()` (`gui.py:515`) → per-file `organize_file()` (`organizer.py:373`) → result dicts pushed to `self._feed_queue` (`gui.py:516`) → drained by `_poll_feed_queue()` (`gui.py:483-488`) on the Tk thread → `feed_text(result)` (`gui.py:55`) → `push_feed()` (`gui.py:468`).
- Live watch: `FolderWatcherManager.resume_all()` (`watcher.py:177`) starts one `Observer` per folder → `OrganizerEventHandler.on_created/on_moved` (`watcher.py:48,55`) → `_schedule()` debounce (`watcher.py:62`, `threading.Timer`, `SETTLE_DELAY=1.5`) → `_handle()` (`watcher.py:72`) → **deferred** `from project_detector import is_protected_folder` (`watcher.py:73`) and `import organizer` (`watcher.py:74`) → `org.organize_file(src, self.root, wait_for_stable=True)` (`watcher.py:97`) → `_emit()` → `on_result` → `gui._on_watcher_result_threadsafe()` (`gui.py:498`) → feed queue.
- Undo: `App.undo_last()` (`gui.py:550`) → `org.undo_last_action()` (`organizer.py:201`) → message pushed to feed (`gui.py:552`).
- Tray: `main.py:87-89` wires `TrayController(on_open/on_organize/on_undo/on_toggle_live/on_exit/is_live)`; callbacks route to the GUI app if alive (`holder` dict, `main.py:30`) else headless fallbacks (`main.py:40-85`).
- Circular-dependency workaround (both directions still deferred): `organizer.py:341 from project_detector import is_protected_folder  # deferred: avoids cycle`; `project_detector.py:143 from organizer import get_managed_category_dir_names  # deferred: avoids cycle`.

### State ownership table

| State | Owner | Persistence |
|---|---|---|
| `watched_folders`, `ignore_list`, `live_mode`, `onboarding_done` | `App.self.settings` in-memory snapshot (`gui.py:124`); headless path re-reads disk per action (`main.py:72,85,96,99,110`) | `settings.json` via `settings.save_settings()` (`settings.py:70`, atomic write `settings.py:26-36`) |
| Undo stack (`src/dst/batch/time`) | `organizer` module functions `_load_undo_stack` / `_save_undo_stack` (`organizer.py:171,183`) | `undo_history.json` (`UNDO_FILE`, `organizer.py:29`), capped `stack[-200:]` (`organizer.py:185`) |
| Category cache (`_category_map`, `_category_dirs`, `_display_names`) | `organizer` module globals (`organizer.py:43-45`), guarded by `_lock` (`organizer.py:42`) | `config.json` (read-only at runtime) |
| Observers (`_observers`, `_paused`) | `FolderWatcherManager` (`watcher.py:118-120`), guarded by `self._lock` (`watcher.py:119`) | in-memory only |
| Debounce timers | `OrganizerEventHandler._timers` (`watcher.py:44`), guarded by `_timers_lock` (`watcher.py:45`) | in-memory only |
| Activity feed (`_feed_items`, `_feed_queue`) | `App` (`gui.py:128-129`); queue drained on Tk thread every 200 ms (`gui.py:494`) | in-memory, capped at `FEED_CAP=15` (`gui.py:35,472`) |
| Onboarding step / choice | `App.onboard_step`, `App.onboard_choice` (`gui.py:155-156`) | in-memory |
| Tray icon/thread | `TrayController._icon`, `._thread` (`tray.py:63-64`) | in-memory |
| Activity log | `organizer.log_activity()` (`organizer.py:142`) | `logs/activity.log` append-only |

### Threading / concurrency model
- **Tk main thread**: GUI, `_poll_feed_queue` (200 ms poll).
- **Daemon worker threads**: `organize_now` / `_organize_single` (`gui.py:523,548`) — only marshal results via `_feed_queue`.
- **watchdog Observer threads** → **`threading.Timer` daemon threads** for per-file settle delay (`watcher.py:67-70`); each `_handle` runs independently.
- **Tray thread**: daemon via `start_detached()` (`tray.py:73`), or blocking on main thread in `--tray` mode (`tray.py:77-79`).
- **Headless no-tray fallback**: `time.sleep(3600)` loop (`main.py:141-146`).
- **Locks present**: `organizer._lock` (category cache), `FolderWatcherManager._lock` (observer dict + paused flag, incl. race-guard in `add_folder` at `watcher.py:148-158` — added in pass 1), `OrganizerEventHandler._timers_lock`.
- **No lock around `undo_history.json` writes.** `_save_undo_stack` uses atomic write (`_atomic_write_json`, `organizer.py:152-164`, added pass 1 — prevents torn/corrupt files), but `record_move` (`organizer.py:190-198`) does load→append→save with **no mutex**, and watcher callbacks run on concurrent timer threads. Two simultaneous moves can lose one undo entry (lost-update race). No new lock was added for this in either pass.
- **No new locks added in pass 2** — pass 2 touched only message-building and branch ordering.

### Backend / frontend split
Single desktop process; no server. "Backend" = `organizer.py`, `project_detector.py`, `settings.py`, `watcher.py`, `config.json`. "Frontend" = `gui.py` (CustomTkinter) + `tray.py` (pystray). Coupling is direct in-process imports; the only async boundary is the `_feed_queue` + `after()` polling bridge, plus `TrayController` callables injected from `main.py`.

### Database / storage layer
None. Three JSON files (`config.json` category map, `settings.json` user state, `undo_history.json` undo stack — all atomic-write for the latter two) + append-only `logs/activity.log`. Corrupt JSON in settings/undo is caught and reset with a logged warning (`settings.py:55-57`, `organizer.py:176-178`).

---

## 4. BUG FIX VERIFICATION

### 4.1 Undo restore-to-occupied-path reporting — **FIXED**

`organizer.py:201-244`. Current message-building code:

```python
# organizer.py:211-244
restored, renamed, skipped, failed = 0, [], [], []
for move in reversed(to_undo):
    dst, src = Path(move["dst"]), Path(move["src"])
    try:
        if not dst.exists():
            skipped.append(dst.name)          # vanished organized file
            continue
        src.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            target = _unique_destination(src.parent, src.name)
            shutil.move(str(dst), str(target))
            renamed.append(f"{src.name} restored as {target.name}")
        else:
            shutil.move(str(dst), str(src))
            restored += 1
    except (OSError, shutil.Error):
        failed.append(dst.name)
_save_undo_stack(remaining)
total = len(to_undo)
msg = f"Restored {restored} of {total} file(s)."
if renamed:
    msg += f" {len(renamed)} restored under a new name (original spot taken): " \
           f"{', '.join(renamed)}."
if skipped:
    msg += f" {len(skipped)} skipped (already gone): {', '.join(skipped)}."
if failed:
    msg += f" Could not restore: {', '.join(failed)}."
```

The three cases (restored / renamed-due-to-conflict / skipped-because-dst-missing) are distinct buckets, plus `failed`. Counts add up: every iteration lands in exactly one bucket (`skipped` uses `continue`; `renamed`/`restored`/`failed` are mutually exclusive), so `restored + len(renamed) + len(skipped) + len(failed) == len(to_undo) == total`. Empty-stack response also returns all four keys (`organizer.py:205-206`). Minor wording nit: with conflicts, the lead sentence can read "Restored 0 of 3 file(s). 3 restored under a new name…" — accurate but slightly awkward.

### 4.2 "protected-check" feed message — **FIXED**

`gui.py:65-67`:
```python
if status == "protected-check":
    name = Path(result.get("src", "?")).name
    return f"\U0001F6E1\uFE0F {name} skipped (protected project folder)", "protected"
```
No longer `""`. Delivery path: `_poll_feed_queue` calls `feed_text` then `push_feed` (`gui.py:487-488`); `push_feed` only drops empty messages (`gui.py:469: if not message: return`). The producer is `watcher.py:50-51` (`on_created` directory branch). **Caveat (new issue, see §6):** `watcher.py:50-51` emits `protected-check` for *every* new folder unconditionally (reason field "new folder — checking SafeZone" is ignored by `feed_text`), so non-protected folders now display "skipped (protected project folder)" — a claim that isn't verified for that folder.

### 4.3 "already organized" branch — **PARTIALLY FIXED**

The checks were reordered as claimed. Current code:

```python
# organizer.py:286-298
category = get_category(src.name)
try:
    # Already sitting in its correct category folder ...
    # Checked BEFORE the subfolder short-circuit below ...
    if (src.parent.name == category
            and src.parent.parent.resolve() == root.resolve()):
        return {"status": "skipped", "reason": "already organized", ...}   # lines 291-294
    # Only direct children of the watched folder — never touch subfolders.
    if src.parent.resolve() != root.resolve():
        return {"status": "skipped", "reason": "inside a subfolder", ...}  # lines 296-298
```

Previously the already-organized check sat *after* the move/`dest_dir` logic and was shadowed by the subfolder short-circuit; now it precedes it, so for a direct `organize_file("root/Documents/a.pdf", "root")` call it fires. **However, no in-app caller ever passes such a path:**
- `organize_folder` only iterates top-level entries and calls `organize_file` for `entry.is_file()` at the root level (`organizer.py:358-373`); for those, `src.parent == root`, so `src.parent.parent.resolve() == root.resolve()` is false.
- `watcher._handle` returns early unless `src.parent.resolve() == self.root.resolve()` (`watcher.py:82-94`) before calling `organize_file` (`watcher.py:97`); files inside category folders are therefore never passed in.

So through the app's actual flows the branch remains unreachable; it's only reachable via direct/test invocation. Also note the comparison `src.parent.name == category` is case-sensitive (matters on Windows).

### 4.4 "file is still changing" vs vanished-file mislabeling — **FIXED**

`organizer.py:310-316`:
```python
if wait_for_stable and not wait_until_stable(src):
    # wait_until_stable() only returns False on OSError — i.e. the file
    # vanished mid-check — so label it accurately. (A genuine timeout
    # proceeds as stable by design, so "still changing" is unreachable.)
    return {"status": "skipped",
            "reason": "file was moved or deleted before it could be organized",
            "src": str(src), "dst": None}
```
The string `"file is still changing"` no longer exists as a returned reason (only in the comment at `organizer.py:313`); `wait_until_stable` returns `False` only on `OSError` (`organizer.py:261-268`) — timeouts return `True` (`organizer.py:272`).

`feed_text` surfaces unknown skip reasons (`gui.py:76-79`):
```python
# Any other skip reason from the organizer gets a plain message —
# transparency beats a quiet feed; nothing falls through to "".
src = Path(result.get("src", "?")).name
return f"\u23ED {src} skipped \u2014 {reason}", "info"
```
Only four noise reasons return `""` (`gui.py:70-72`: "already organized", "system file", "inside a subfolder", "not a file").

### 4.5 Bare except / silent exception swallowing — **NOT FIXED** (tray.py exit specifically unchanged)

**Totals across the five named files: 49 `except` blocks; 0 call `log_activity`/logging.** (`log_activity` is only invoked from `organizer.py` and `settings.py` — grep confirms no usages in the five files.) No bare `except:` (type-less) remain anywhere; all are typed, but most broad `except Exception: pass` blocks are still silent.

| File | except blocks | logging | silent / fallback | intentional control-flow |
|---|---|---|---|---|
| gui.py | 20 (lines 26,107,114,338,363,372,392,397,461,464,480,491,495,528,560,571,613,643,649,653) | 0 | ~15 `pass`/default fallbacks (107,114,338,363,372,397,464,480,495,528,560,571,613,643,649,653) | ImportError(26), queue.Empty(491), OSError fallbacks(392,461) |
| main.py | 12 (37,45,55,70,83,119,125,129,145,150,172,180) | 0 | 9 broad `pass`/default (37,45,55,70,83,119,125,129,150) | KeyboardInterrupt(145,180), ImportError(172) |
| tray.py | 9 (22,85,92,102,133,137,142,152,158) | 0 | 8 (85,92,102,133,137,142,152,158) | ImportError(22) |
| watcher.py | 5 (24,92,99,107,146) | 0 (1 emits to feed) | 2 (92,107) | ImportError(24); 99 emits error dict to feed; 146 returns False |
| project_detector.py | 3 (87,152,160) | 0 | 1 (152 `managed = set()`) | 87/160 return meaningful values |

**tray.py exit-confirmation — NOT FIXED.** Current code `tray.py:116-134` is byte-identical in behavior to the baseline (`2f7b733`); `tray.py` was never touched in either pass:
```python
# tray.py:133-134
except Exception:
    pass  # no display — treat click as confirmed exit
```
Dialog failure still falls through to `icon.stop()` + `on_exit()` — i.e., **defaults to confirmed exit**.

### 4.6 GUI settings snapshot vs disk — **NOT FIXED**

Neither a periodic/on-action re-read nor a documented safety comment/guard exists in `gui.py`. The GUI loads settings exactly once:
```python
# gui.py:124
self.settings = app_settings.load_settings()
```
and every subsequent read uses the snapshot: `self.settings.get("ignore_list", ...)` at `gui.py:127,381,509,536`, `watched_folders` at `gui.py:240,324,350,374,433,450,503`. The watcher's ignore-list lambda closes over the snapshot: `get_ignore_list=lambda: self.settings.get("ignore_list", [])` (`gui.py:127`). No comment in `gui.py` discusses snapshot staleness. (Contrast: the **headless** path in `main.py` does re-read from disk per action — `main.py:72,85,96,99,110` — but that does not fix the GUI.) External edits to `settings.json` while the GUI runs are invisible until restart.

### 4.7 watched_folders / ignore_list entry-level validation — **NOT FIXED**

`settings.py:60-66` only type-checks that the *containers* are lists; no per-entry checks, no dropping, no logging:
```python
# settings.py:60-66
# Normalize types (guard against hand-edited / corrupt files).
if not isinstance(defaults.get("watched_folders"), list):
    defaults["watched_folders"] = [default_downloads_folder()]
if not isinstance(defaults.get("ignore_list"), list):
    defaults["ignore_list"] = []
defaults["live_mode"] = bool(defaults.get("live_mode", True))
defaults["onboarding_done"] = bool(defaults.get("onboarding_done", False))
```
A list like `["", 123, null]` passes straight through. (Note: `project_detector._normalise_ignore_list` at `project_detector.py:63-67` filters empty/non-string entries at *use* time for protection checks only — that is pre-existing behavior, not settings-load validation, and does not clean `watched_folders`.)

### 4.8 Dead code — **NOT FIXED** (all three still present, neither deleted nor wired)

| Claim | Current state |
|---|---|
| `import time` removed from watcher.py? | **Still present** at `watcher.py:16`. Grep for `time.sleep/time.time/time.monotonic` in watcher.py: **zero usages** — it is a dead import. (Used time calls exist only in `organizer.py:258,263,264` and `main.py:144`.) |
| `gui.launch()` deleted or wired? | **Still present** at `gui.py:657-662`. Not called anywhere: `main.py:157-158` does `import gui; app = gui.App(...)`. Dead code. |
| `organizer.reload_category_map()` deleted or wired? | **Still present** at `organizer.py:76-83`. Grep finds zero callers in app or tests (docstring says "tests / future settings use" but no test imports it). Dead code. |

### 4.9 assets/icon.ico — **NOT FIXED**

- `assets/icon.ico` does **not** exist (glob `**/*.ico` → no files; `assets/` directory itself absent; `Test-Path assets\icon.ico` → False).
- README was **not** changed to drop the flag — `README.md:48` still reads:
  ```
  pyinstaller --onedir --windowed --name FileOrganizer --icon assets\icon.ico main.py
  ```
- `tray.py:146-153` does gracefully fall back to a programmatic icon if the file is missing, but the **PyInstaller build command references a nonexistent file and will fail** (see §9).

### 4.10 Onboarding Back/Next step logic — **NOT FIXED**

`gui.py:220-226` — both handlers still hardcode step 2, identical to baseline `2f7b733`:
```python
def _onboard_next(self):
    self.onboard_step = 2
    self._render_onboard_step()

def _onboard_back(self):
    self.onboard_step = 2
    self._render_onboard_step()
```
No increment/decrement, no bounds. Navigation graph as rendered: step 1 has only "Get Started" → `_onboard_next` → 2 (`gui.py:174-176`); step 2 has pick/browse buttons → 3 (`gui.py:228-231`) and **no Back button at all** (step-2 block `gui.py:178-200` renders no Back); step 3 has Back → `_onboard_back` → 2 (`gui.py:216-218`). **Step 2 → step 1 (Welcome) cannot be performed.**

### Verification summary table

| # | Item | Verdict |
|---|---|---|
| 1 | Undo restore-to-occupied-path reporting | **FIXED** |
| 2 | "protected-check" feed message | **FIXED** (reaches feed; message wording over-claims protection — see §6) |
| 3 | "already organized" branch reachability | **PARTIALLY FIXED** (reordered, but unreachable via app call paths) |
| 4 | "still changing" vs vanished-file mislabeling | **FIXED** |
| 5 | Bare except / silent swallowing (+ tray exit default) | **NOT FIXED** (0 of 49 blocks log in the 5 files; tray exit still defaults to confirmed) |
| 6 | GUI settings snapshot vs disk | **NOT FIXED** (neither re-read nor documented guard) |
| 7 | watched_folders / ignore_list entry validation | **NOT FIXED** (list-type checks only) |
| 8 | Dead code (`time` import, `launch()`, `reload_category_map()`) | **NOT FIXED** (all three still present, unwired) |
| 9 | assets/icon.ico | **NOT EXISTS; README unchanged** → build command broken |
| 10 | Onboarding Back/Next step logic | **NOT FIXED** (both hardcode `step = 2`; 2→1 impossible) |

---

## 5. FEATURES — CURRENT STATE

### Fully implemented and working (re-verified from current code)
- **SafeZone Detection** — `project_detector.is_protected_folder` (marker dirs/files, code-mix heuristic, ignore list, fail-safe unreadable→protected). 17/17 tests pass.
- **Category-based organizing of loose top-level files** — `organizer.organize_file` / `organize_folder`; only top-level files moved; subfolders never descended.
- **Collision-safe naming** — `_unique_destination` (`organizer.py:128-139`), never overwrites.
- **Undo with batch semantics + full reporting** — `undo_last_action` distinguishes restored / renamed / skipped / failed; counts sum to batch size (pass 2); corrupt-history reset logging (pass 1); 200-entry cap.
- **Atomic JSON persistence** — `_atomic_write_json` for both `settings.json` (`settings.py:26`) and `undo_history.json` (`organizer.py:152`), with fsync + os.replace; failure paths log (pass 1).
- **Real-time watching** — one watchdog Observer per folder, 1.5 s settle delay, per-path debounce timers, directory events reported to feed.
- **Live-mode pause/resume that actually starts observers** — `resume_all` wiring in `gui.py:348-357` and `main.py:93-106` (pass 1); race-guarded `add_folder` (`watcher.py:123-159`, pass 1).
- **GUI**: 3-step onboarding, 4-zone dashboard (status bar, folder cards with protected counts/tooltips, activity feed capped at 15, quick actions), settings window with ignore-list editor, add/remove folder, per-folder Organize button, toasts, minimize-to-tray on close.
- **Activity feed routing** — `feed_text` covers moved / protected / protected-check / skipped (4 noise reasons suppressed, download-in-progress special-cased, everything else surfaced) / error (pass 2).
- **Tray menu** — Open / Organize now / Undo / Pause-Resume / Exit-with-confirmation; programmatic Pillow icon with `assets/icon.ico` fallback.
- **Headless `--tray` mode** — tray + disk-re-reading watchers/organizers without a window; no-tray sleep-loop fallback.
- **Activity log** — `logs/activity.log` for moves, protected skips, undo summaries, corrupt-state warnings, write errors.
- **Installer** — Inno Setup with Startup-folder `--tray` shortcut (no registry Run key), optional desktop icon, post-install launch.

### Partially implemented
- **Already-organized skip** — check reordered ahead of subfolder guard (`organizer.py:291-298`) but unreachable from `organize_folder` / watcher call paths (§4.3); also case-sensitive name comparison.
- **Tray exit confirmation** — dialog exists, but any failure (no display, Tk error) silently proceeds with exit (`tray.py:133-134`).
- **Settings freshness in GUI** — in-GUI edits stay synced (`_save` writes both memory+disk, `gui.py:618-625`), but external disk edits are never re-read; headless path re-reads, GUI path doesn't.
- **Settings validation** — container-type + bool coercion only; no entry-level sanitization; no corrupt-file entry logging beyond a generic reset message.
- **Onboarding navigation** — 1→2→3 and 3→2 work; 2→1 impossible; handlers hardcode targets.
- **`protected-check` feed message** — reaches the feed, but emitted for every new folder regardless of actual protection result (§4.2).

### Planned / stubbed, no real implementation
- `organizer.reload_category_map()` — "tests / future settings use" docstring, zero callers.
- `gui.launch()` — docstring claims "Entry point used by main.py", but `main.py` doesn't use it.
- Multi-PC Ignore-List sync and Pro category presets — mentioned in `README.md:77` as "reserved for v1.1"; no code.
- No feature flags, no plugin/extension points.

---

## 6. NEW / REMAINING KNOWN ISSUES

### Regressions / new issues introduced by this fix pass (pass 2, `66d028b`)
1. **Mislabeling of every new folder as protected** — `watcher.py:50-51` has always emitted `protected-check` for *any* directory creation (with reason "new folder — checking SafeZone"), but pass 2's `feed_text` (`gui.py:65-67`) now renders it as "**skipped (protected project folder)**" without consulting the reason or the actual `is_protected_folder` result (that verification only happens later in `_handle`, `watcher.py:84-93`, which emits a *different* `protected` status). Previously this status produced `""` (silent); now every new folder — protected or not — claims it was skipped as a protected project folder. The `reason` field is ignored by `feed_text`.
2. **Undo lead sentence can understate success** — when all restores were conflict-renamed, message reads "Restored 0 of N file(s). N restored under a new name…" (`organizer.py:234-237`). Counts are still correct; wording is confusing, not functional.
3. No functional regressions found in move/undo/watcher behavior; pass 2 touched only message-building and branch order.

### Items from prior rounds not addressed at all
Items 5 (tray exit), 6 (GUI snapshot), 7 (entry validation), 8 (dead code ×3), 9 (icon asset), 10 (onboarding) — **none were touched in pass 2**, and pass 1 also did not address them (`tray.py`, `project_detector.py` unchanged since baseline; `settings.py` pass-1 changes were atomic-write + corrupt logging only; `watcher.py` pass-1 changes were `add_folder` race logic only).

### New hardcoded values / unvalidated input / edge cases in the new fix code
- **Case-sensitive category match** in the new already-organized check: `src.parent.name == category` (`organizer.py:291`) — on Windows, a folder named `documents` vs category `Documents` won't match (and vice versa).
- **No synchronization on undo stack read-modify-write** — `record_move` (`organizer.py:190-198`) and `undo_last_action` (`organizer.py:201-232`) run without `_lock`; concurrent watcher timer threads can interleave load/append/save. Atomic write (pass 1) prevents file corruption but not **lost undo entries**. `organizer._lock` guards only the category cache.
- **`protected-check` message hardcodes "protected project folder"** regardless of outcome (§6.1).
- **Feed noise risk** — the new catch-all skip message (`gui.py:76-79`) will now surface any future organizer reason verbatim (including raw exception strings if ever passed as reasons); currently reasons are curated strings, so low risk.
- Undo message builds unbounded join of names (`organizer.py:236-241`) — a 200-entry batch could produce a very long feed line (feed box wraps; cosmetic only).

### Test coverage status
- **17 tests, unchanged** (`pytest` collect: `17 tests collected`; run: `17 passed in 0.23s`).
- Single test file: `tests/test_project_detector.py` only. **No new test files** for organizer, undo, settings, watcher, or gui. No test touches the pass-2 changes (undo message building, already-organized branch, `feed_text`). `requirements-dev.txt` added pass 1; no test-count change from 17.

---

## 7. CONFIG / ENV

**Config files:**
- `config.json` — backend category map (`categories`, `display_names`). Read-only at runtime.
- `settings.json` — user state (`watched_folders`, `ignore_list`, `live_mode`, `onboarding_done`); created on first run, gitignored.
- `undo_history.json` — undo stack; created on first move, gitignored.
- `requirements.txt`, `requirements-dev.txt` — dependency pins.
- `.gitignore`
- `installer/FileOrganizer.iss` — Inno Setup definitions (`MyAppVersion "1.0.0"`, `MyAppPublisher "LadeStack"`, `MyAppExeName "FileOrganizer.exe"`, AppId GUID).

**Environment variables referenced in code: none** (grep for `os.environ` / `getenv` / `environ[` → zero matches).

**requirements.txt changes:** none (unchanged since baseline `2f7b733`).
**requirements-dev.txt changes:** file itself is new (pass 1 `f4b010f`); contents `-r requirements.txt` + `pytest>=8.0.0`.

---

## 8. DEPENDENCIES HEALTH

- **New dependencies this pass:** none. Pass 1 added only the *dev requirements file* (`pytest>=8.0.0`); no new runtime packages in either pass.
- **Circular dependency (organizer ↔ project_detector):** workaround **still present and still needed** — neither side was restructured. `organizer.py:341` defers `from project_detector import is_protected_folder`; `project_detector.py:143` defers `from organizer import get_managed_category_dir_names`. Both directions deferred; no top-level cycle.
- **Lockfile:** still absent. No lockfile of any kind in the repo.
- Optional-dep degradation is handled via import guards: `customtkinter` (`gui.py:23-28`, `main.py:168-173`), `pystray`/`PIL` (`tray.py:17-26`), `watchdog` (`watcher.py:20-27`).

---

## 9. HOW TO RUN

**Install / run / test (as they currently stand):**
```powershell
pip install -r requirements.txt
python main.py            # dashboard window
python main.py --tray     # background tray mode (autostart path)

pip install -r requirements-dev.txt
pytest                    # 17 passed (SafeZone suite only)
```

**Documented build command — does NOT work end-to-end:**
```powershell
pyinstaller --onedir --windowed --name FileOrganizer --icon assets\icon.ico main.py
iscc installer\FileOrganizer.iss
```
- `assets\icon.ico` **does not exist** (`assets/` directory absent; zero `.ico` files in repo). PyInstaller's `--icon` points at a missing file and will error out. The command as printed in `README.md:48` fails; nothing in the repo was changed to drop the flag.
- The second step (`iscc`) additionally requires `dist\FileOrganizer\*` from a successful first step (`FileOrganizer.iss:40`), so the full chain is broken until either the icon asset is added or the `--icon` flag is removed.
- Runtime itself is unaffected: `tray.py:146-153` falls back to `make_icon_image()` when the file is missing.

**Bottom line on round-2 fixes:** 3 of 10 items fully verified fixed (undo reporting, protected-check feed text, vanished-file reason + generic skip surfacing), 1 partial (already-organized reorder that still can't fire in practice), and 6 not fixed (except/tray-exit handling, settings re-read, entry validation, dead code, icon asset, onboarding navigation) — the latter six were not modified in pass 2 at all.
