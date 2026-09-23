"""SafeZone Detection — the core safety differentiator.

A folder inside a watched directory is treated as a *protected project folder*
and skipped entirely (including all of its contents) when ANY of these hold:

  1. It contains marker directories: .git, node_modules, .vscode, venv/.venv
  2. It contains marker files: package.json, requirements.txt, .env (+ common
     project roots: pyproject.toml, go.mod, Cargo.toml, pom.xml, build.gradle)
  3. It contains a mix of code files (.py, .js, .java, ...)
  4. Its name is on the user's manual Ignore List (checked here for convenience)

Only loose, top-level *files* in the watched folder are ever organized.
Subfolders are never descended into.

All user-facing reasons are plain-language strings suitable for direct display
in the Activity Feed ("my-react-app skipped (protected)") with no jargon.
"""

from __future__ import annotations

import os
from pathlib import Path

# Directories whose presence means "active dev project — do not touch".
MARKER_DIRS = frozenset({
    ".git",
    "node_modules",
    ".vscode",
    "venv",
    ".venv",
    "__pycache__",
})

# Files whose presence means "project root — do not touch".
# Spec-required: package.json, requirements.txt, .env
# Plus unambiguous equivalents from other ecosystems (same confidence level).
MARKER_FILES = frozenset({
    "package.json",
    "requirements.txt",
    ".env",
    "pyproject.toml",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
})

# Extensions that count as "code" for the mixed-code-files heuristic.
CODE_EXTENSIONS = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java",
    ".c", ".h", ".cpp", ".hpp", ".cc",
    ".cs", ".go", ".rs", ".rb", ".php",
    ".swift", ".kt", ".kts", ".scala",
    ".vue", ".svelte",
})

# Heuristic thresholds: >=3 code files total, OR >=2 distinct code extensions.
CODE_FILE_COUNT_THRESHOLD = 3
CODE_EXT_VARIETY_THRESHOLD = 2


def _normalise_ignore_list(ignore_list) -> set[str]:
    """Lower-cased ignore-list names for case-insensitive Windows matching."""
    if not ignore_list:
        return set()
    return {str(name).strip().lower() for name in ignore_list if str(name).strip()}


def is_protected_folder(folder: str | os.PathLike, ignore_list=None) -> tuple[bool, str]:
    """Return (protected: bool, plain_language_reason: str).

    `reason` is "" when not protected, otherwise a short human sentence
    like "contains a .git folder (code project)".
    """
    path = Path(folder)
    ignored = _normalise_ignore_list(ignore_list)

    if path.name.strip().lower() in ignored:
        return True, "on your Ignore List"

    if not path.is_dir():
        return False, ""

    try:
        entries = list(path.iterdir())
    except (OSError, PermissionError):
        # Unreadable folder: safest option is to leave it alone.
        return True, "couldn't be read safely, so it was left alone"

    names = {e.name for e in entries}
    lower_names = {e.name.lower() for e in entries}

    # 1. Marker directories (.git, node_modules, .vscode, venv, ...)
    for entry in entries:
        if entry.name in MARKER_DIRS and entry.is_dir():
            if entry.name == ".git":
                return True, "contains a .git folder (code project)"
            if entry.name == "node_modules":
                return True, "contains a node_modules folder (code project)"
            if entry.name == ".vscode":
                return True, "contains a .vscode folder (code project)"
            if entry.name in ("venv", ".venv"):
                return True, "contains a Python virtual environment (code project)"
            return True, f"contains a {entry.name} folder (code project)"

    # 2. Marker files (package.json, requirements.txt, .env, ...)
    for marker in MARKER_FILES:
        if marker in names or marker.lower() in lower_names:
            if marker == "package.json":
                return True, "contains a package.json file (code project)"
            if marker == "requirements.txt":
                return True, "contains a requirements.txt file (code project)"
            if marker == ".env":
                return True, "contains a .env file (code project)"
            return True, f"contains a {marker} file (code project)"

    # 3. Mix of code files heuristic (top level only — fast, no recursion).
    code_exts_seen: set[str] = set()
    code_file_count = 0
    for entry in entries:
        if entry.is_file():
            ext = entry.suffix.lower()
            if ext in CODE_EXTENSIONS:
                code_file_count += 1
                code_exts_seen.add(ext)

    if (code_file_count >= CODE_FILE_COUNT_THRESHOLD
            or len(code_exts_seen) >= CODE_EXT_VARIETY_THRESHOLD):
        return True, "looks like a coding project (contains code files)"

    return False, ""


def scan_watched_folder(watched: str | os.PathLike, ignore_list=None) -> list[dict]:
    """List immediate subfolders of `watched` with their protection status.

    Used by the GUI folder cards / activity feed so users always see
    WHAT is being skipped and WHY. Category subfolders created by the
    organizer itself (Images, Documents, ...) are excluded — they are
    organizer output, not user content.
    """
    from organizer import get_managed_category_dir_names  # deferred: avoids cycle

    path = Path(watched)
    result: list[dict] = []
    if not path.is_dir():
        return result

    try:
        managed = {n.lower() for n in get_managed_category_dir_names()}
    except Exception:
        managed = set()

    try:
        subfolders = sorted(
            (e for e in path.iterdir() if e.is_dir()),
            key=lambda e: e.name.lower(),
        )
    except (OSError, PermissionError):
        return result

    for sub in subfolders:
        if sub.name.lower() in managed:
            continue
        protected, reason = is_protected_folder(sub, ignore_list)
        result.append({
            "name": sub.name,
            "path": str(sub),
            "protected": protected,
            "reason": reason,
        })
    return result
