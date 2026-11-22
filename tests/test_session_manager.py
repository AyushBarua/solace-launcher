"""
tests/test_session_manager.py
Unit tests for core session lifecycle, streak, ROM, and schema migration.
Run with: pytest tests/
"""
import json
import os
import pytest
from unittest.mock import patch
from datetime import date, timedelta


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_manager(tmp_path, profile_id="test_profile"):
    """Create a SessionManager backed by a temp directory."""
    with patch("core.paths.get_data_dir", return_value=str(tmp_path)):
        from core.session_manager import SessionManager
        return SessionManager(profile_id)


# ── Schema migration ──────────────────────────────────────────────────────────

def test_migrate_v0_adds_missing_keys(tmp_path):
    """A v0 log (no schema_version) is migrated to v1 without data loss."""
    import importlib
    import core.session_manager as sm
    importlib.reload(sm)  # ensure fresh state

    v0_log = {"profile_id": "abc", "sessions": [{"id": "x"}]}
    result = sm._migrate_log(v0_log)

    assert result["schema_version"] == 1
    assert result["sessions"] == [{"id": "x"}]   # existing data preserved
    assert "baseline_rom" in result
    assert "milestones" in result
    assert "journey" in result
    assert "streak" in result


def test_migrate_v1_is_idempotent(tmp_path):
    """Running migration on a v1 log changes nothing."""
    import core.session_manager as sm
    v1_log = sm._empty_log("abc")
    before = json.dumps(v1_log, sort_keys=True)
    sm._migrate_log(v1_log)
    after = json.dumps(v1_log, sort_keys=True)
    assert before == after


# ── Atomic write / backup recovery ───────────────────────────────────────────

def test_backup_file_created_on_save(tmp_path):
    """After two saves, a .bak file should exist next to the primary."""
    mgr = _make_manager(tmp_path)
    mgr._save()   # first save — no .bak yet (nothing to back up)
    mgr._save()   # second save — should create .bak from first save

    log_path = tmp_path / f"session_log_test_profile.json"
    bak_path = tmp_path / f"session_log_test_profile.json.bak"
    assert log_path.exists()
    assert bak_path.exists()


def test_recovery_from_backup_when_primary_corrupt(tmp_path):
    """If the primary log is corrupt, the manager recovers from .bak."""
    mgr = _make_manager(tmp_path)
    # Record something meaningful
    session = mgr.start_session("game1", 0.5)
    mgr.end_session(session)
    # Two saves so .bak is written
    mgr._save()

    # Corrupt the primary
    log_path = tmp_path / "session_log_test_profile.json"
    log_path.write_text("CORRUPT JSON {{{{")

    # Re-load — should recover from .bak
    mgr2 = _make_manager(tmp_path)
    assert mgr2.get_total_sessions() == 1


# ── Streak logic ──────────────────────────────────────────────────────────────

def test_streak_starts_at_one(tmp_path):
    mgr = _make_manager(tmp_path)
    session = mgr.start_session("g1", 0.5)
    mgr.end_session(session)
    assert mgr.get_streak() == 1


def test_streak_increments_on_consecutive_days(tmp_path):
    mgr = _make_manager(tmp_path)
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # Manually plant a streak entry for yesterday
    mgr._log["streak"]["current"] = 1
    mgr._log["streak"]["last_session_date"] = yesterday

    session = mgr.start_session("g1", 0.5)
    mgr.end_session(session)

    assert mgr.get_streak() == 2


def test_streak_resets_after_missed_day(tmp_path):
    mgr = _make_manager(tmp_path)
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()

    mgr._log["streak"]["current"] = 5
    mgr._log["streak"]["last_session_date"] = two_days_ago

    session = mgr.start_session("g1", 0.5)
    mgr.end_session(session)

    assert mgr.get_streak() == 1


def test_multiple_sessions_same_day_dont_double_streak(tmp_path):
    mgr = _make_manager(tmp_path)
    s1 = mgr.start_session("g1", 0.5)
    mgr.end_session(s1)
    s2 = mgr.start_session("g1", 0.5)
    mgr.end_session(s2)
    assert mgr.get_streak() == 1


def test_longest_streak_tracked(tmp_path):
    mgr = _make_manager(tmp_path)
    mgr._log["streak"]["longest"] = 10
    session = mgr.start_session("g1", 0.5)
    mgr.end_session(session)
    assert mgr.get_longest_streak() == 10  # 1-day session doesn't beat 10


# ── ROM improvement ───────────────────────────────────────────────────────────

def test_rom_improvement_returns_none_without_baseline(tmp_path):
    mgr = _make_manager(tmp_path)
    assert mgr.get_rom_improvement_pct("right") is None


def test_rom_improvement_positive(tmp_path):
    mgr = _make_manager(tmp_path)
    mgr.save_baseline_rom(10.0, 20.0, 15.0, 5.0)

    session = mgr.start_session("g1", 0.5)
    mgr.record_warmup_rom(session, 10.0, 30.0, 15.0, 5.0)  # right improved 50%
    mgr.end_session(session)

    pct = mgr.get_rom_improvement_pct("right")
    assert pct == pytest.approx(50.0)


def test_rom_improvement_zero_baseline_returns_none(tmp_path):
    mgr = _make_manager(tmp_path)
    mgr.save_baseline_rom(0.0, 0.0, 0.0, 0.0)  # zero baseline

    session = mgr.start_session("g1", 0.5)
    mgr.record_warmup_rom(session, 0.0, 10.0, 0.0, 0.0)
    mgr.end_session(session)

    # Zero baseline → division by zero → return None
    assert mgr.get_rom_improvement_pct("right") is None


# ── Milestone idempotency ─────────────────────────────────────────────────────

def test_milestone_awarded_only_once(tmp_path):
    mgr = _make_manager(tmp_path)
    session = mgr.start_session("g1", 0.5)
    mgr.award_milestone("first_session", session)
    mgr.award_milestone("first_session", session)  # duplicate
    mgr.end_session(session)

    assert mgr.get_milestones().count("first_session") == 1


# ── Session difficulty fields (A9) ────────────────────────────────────────────

def test_session_stores_suggested_and_actual_difficulty(tmp_path):
    mgr = _make_manager(tmp_path)
    session = mgr.start_session("g1", suggested := 0.75, actual_difficulty=0.5)
    assert session["suggested_difficulty"] == 0.75
    assert session["difficulty"] == 0.5


def test_session_uses_suggested_when_actual_not_provided(tmp_path):
    mgr = _make_manager(tmp_path)
    session = mgr.start_session("g1", 0.75)
    assert session["suggested_difficulty"] == 0.75
    assert session["difficulty"] == 0.75
