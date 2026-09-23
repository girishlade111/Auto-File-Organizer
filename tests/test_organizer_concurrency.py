"""Concurrency regression tests for the undo-stack lock (organizer._undo_lock).

record_move() and undo_last_action() both do load→mutate→save on
undo_history.json. Without serialization, concurrent watcher debounce-timer
threads interleave those sequences and silently lose undo entries. These tests
prove the lock actually serializes writers under real thread load — locking
bugs don't show up in diff review, only here.

Isolation: organizer resolves UNDO_FILE / LOGS_DIR / ACTIVITY_LOG from its own
module constants, so the fixture redirects all three into tmp_path. The real
repo tree (undo_history.json, logs/) is never touched, and monkeypatch
reverts everything after each test.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

import organizer
from organizer import _load_undo_stack, record_move, undo_last_action


@pytest.fixture()
def isolated_undo_state(tmp_path, monkeypatch):
    """Redirect organizer persistence into tmp_path for one test."""
    monkeypatch.setattr(organizer, "UNDO_FILE", tmp_path / "undo_history.json")
    monkeypatch.setattr(organizer, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(organizer, "ACTIVITY_LOG", tmp_path / "logs" / "activity.log")
    organizer._save_undo_stack([])
    yield tmp_path
    # monkeypatch auto-reverts the constants; tmp_path is auto-removed.


def _join_all(threads, timeout=120):
    for t in threads:
        t.join(timeout=timeout)
    assert not any(t.is_alive() for t in threads), \
        "deadlock: worker threads did not finish in time"


def test_concurrent_record_move_loses_no_entries(isolated_undo_state):
    """20 threads x 5 record_move each must persist exactly 100 entries."""
    n_threads, per_thread = 20, 5
    gate = threading.Barrier(n_threads)  # line everyone up: no sleep-sync
    errors: list = []

    def worker(tid):
        try:
            gate.wait(timeout=30)
            for i in range(per_thread):
                record_move(Path(f"/src/t{tid}f{i}"), Path(f"/dst/t{tid}f{i}"))
        except Exception as exc:  # test harness only
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    _join_all(threads)

    assert not errors
    stack = _load_undo_stack()
    assert len(stack) == n_threads * per_thread
    # Uniquely identifiable entries: every dst appears exactly once.
    assert len({e["dst"] for e in stack}) == n_threads * per_thread


def test_concurrent_record_and_undo_stays_consistent(isolated_undo_state):
    """Undo racing with record_move: no crash, no corruption, exact accounting.

    Every record_move gets its own batch id, so each non-empty undo consumes
    exactly one entry: processed_total + len(final_stack) == recorded_total.
    """
    n_recorders, per_recorder, n_undo_calls = 4, 10, 40
    gate = threading.Barrier(n_recorders + 2)
    errors: list = []
    processed: list = []

    def recorder(tid):
        try:
            gate.wait(timeout=30)
            for i in range(per_recorder):
                record_move(Path(f"/s/m{tid}_{i}"), Path(f"/d/m{tid}_{i}"))
        except Exception as exc:
            errors.append(exc)

    def undoer():
        try:
            gate.wait(timeout=30)
            for _ in range(n_undo_calls // 2):
                r = undo_last_action()
                processed.append(r["restored"] + len(r["renamed"])
                                 + len(r["skipped"]) + len(r["failed"]))
        except Exception as exc:
            errors.append(exc)

    threads = ([threading.Thread(target=recorder, args=(t,)) for t in range(n_recorders)]
               + [threading.Thread(target=undoer) for _ in range(2)])
    for t in threads:
        t.start()
    _join_all(threads)

    assert not errors
    final = _load_undo_stack()
    assert isinstance(final, list)
    assert all(set(e) >= {"src", "dst", "batch"} for e in final)
    assert sum(processed) + len(final) == n_recorders * per_recorder
