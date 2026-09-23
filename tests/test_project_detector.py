"""SafeZone Detection tests — the safety-critical logic. Run with: pytest."""

from pathlib import Path

import pytest

import project_detector as pd


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    d = tmp_path / "case"
    d.mkdir()
    return d


def _protected(path: Path, ignore_list=None) -> bool:
    return pd.is_protected_folder(path, ignore_list)[0]


# -- marker directories -----------------------------------------------------

def test_git_folder_is_protected(folder: Path):
    (folder / ".git").mkdir()
    assert _protected(folder)


def test_node_modules_is_protected(folder: Path):
    (folder / "node_modules").mkdir()
    assert _protected(folder)


def test_vscode_is_protected(folder: Path):
    (folder / ".vscode").mkdir()
    assert _protected(folder)


def test_venv_is_protected(folder: Path):
    (folder / "venv").mkdir()
    assert _protected(folder)


def test_dot_venv_is_protected(folder: Path):
    (folder / ".venv").mkdir()
    assert _protected(folder)


# -- marker files ------------------------------------------------------------

def test_package_json_is_protected(folder: Path):
    (folder / "package.json").write_text("{}")
    assert _protected(folder)


def test_requirements_txt_is_protected(folder: Path):
    (folder / "requirements.txt").write_text("requests\n")
    assert _protected(folder)


def test_env_is_protected(folder: Path):
    (folder / ".env").write_text("KEY=value\n")
    assert _protected(folder)


# -- code-mix heuristic -------------------------------------------------------

def test_three_code_files_are_protected(folder: Path):
    for name in ("a.py", "b.py", "c.py"):
        (folder / name).write_text("x = 1\n")
    assert _protected(folder)


def test_two_code_extensions_are_protected(folder: Path):
    (folder / "main.py").write_text("x = 1\n")
    (folder / "app.js").write_text("let x = 1;\n")
    assert _protected(folder)


def test_single_code_file_is_not_protected(folder: Path):
    (folder / "notes.py").write_text("x = 1\n")
    (folder / "photo.png").write_text("not-a-real-png")
    assert not _protected(folder)


# -- negative / false-positive checks ------------------------------------------

def test_plain_images_and_docs_not_protected(folder: Path):
    (folder / "photo.png").write_text("not-a-real-png")
    (folder / "report.pdf").write_text("not-a-real-pdf")
    assert not _protected(folder)


def test_project_like_name_without_markers_not_protected(folder: Path):
    target = folder.parent / "old-project"
    target.mkdir(exist_ok=True)
    (target / "backup-notes.txt").write_text("hello")
    assert not _protected(target)


def test_empty_folder_not_protected(folder: Path):
    assert not _protected(folder)


# -- ignore list -----------------------------------------------------------------

def test_ignore_list_protects_any_folder(folder: Path):
    assert _protected(folder, ignore_list=[folder.name])


# -- fail-safe ---------------------------------------------------------------------

def test_unreadable_folder_is_protected_fail_safe(folder: Path, monkeypatch):
    def _boom(self):
        raise PermissionError("denied")
    monkeypatch.setattr(Path, "iterdir", _boom)
    assert _protected(folder)


def test_reason_is_plain_language(folder: Path):
    (folder / ".git").mkdir()
    protected, reason = pd.is_protected_folder(folder)
    assert protected
    assert reason  # non-technical message for the Activity Feed
    assert ".git" in reason
