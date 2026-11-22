"""
tests/test_milestone_manager.py
Unit tests for milestone detection logic.
"""
import pytest
from unittest.mock import MagicMock, patch


def _make_session_mgr(sessions=0, streak=0, difficulty=0.5,
                      rom_right_pct=0.0, milestones=None):
    """Build a mock SessionManager with the given stats."""
    mgr = MagicMock()
    mgr.get_total_sessions.return_value = sessions
    mgr.get_streak.return_value = streak
    mgr.has_milestone.side_effect = lambda m: m in (milestones or [])
    mgr.award_milestone.return_value = None

    # ROM improvement: return percentage on 'right' axis only for simplicity
    def rom_pct(axis):
        return rom_right_pct if axis in ("right", "up") else 0.0
    mgr.get_rom_improvement_pct.side_effect = rom_pct

    return mgr


def _run_check(session_mgr, session_difficulty=0.5):
    from core.milestone_manager import MilestoneManager
    session = {"difficulty": session_difficulty, "milestones_hit": []}
    mm = MilestoneManager()
    mm.check_and_award(session_mgr, session)
    return session["milestones_hit"]


# ── First session ─────────────────────────────────────────────────────────────

def test_first_session_awarded_on_session_1():
    mgr = _make_session_mgr(sessions=1)
    awarded = _run_check(mgr)
    assert "first_session" in awarded


def test_first_session_not_re_awarded():
    mgr = _make_session_mgr(sessions=5, milestones=["first_session"])
    awarded = _run_check(mgr)
    assert "first_session" not in awarded


# ── Streak milestones ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("streak, milestone", [
    (3,  "streak_3"),
    (7,  "streak_7"),
    (30, "streak_30"),
])
def test_streak_milestone_awarded(streak, milestone):
    mgr = _make_session_mgr(sessions=streak, streak=streak)
    awarded = _run_check(mgr)
    assert milestone in awarded


def test_streak_milestone_not_awarded_below_threshold():
    mgr = _make_session_mgr(sessions=2, streak=2)
    awarded = _run_check(mgr)
    assert "streak_3" not in awarded


# ── Session count milestones ──────────────────────────────────────────────────

@pytest.mark.parametrize("count, milestone", [
    (10, "sessions_10"),
    (30, "sessions_30"),
])
def test_session_count_milestone(count, milestone):
    mgr = _make_session_mgr(sessions=count)
    awarded = _run_check(mgr)
    assert milestone in awarded


# ── ROM milestones ────────────────────────────────────────────────────────────

def test_rom_25_milestone_awarded():
    mgr = _make_session_mgr(sessions=10, rom_right_pct=25.0)
    awarded = _run_check(mgr)
    assert "rom_25" in awarded


def test_rom_50_milestone_awarded():
    mgr = _make_session_mgr(sessions=10, rom_right_pct=50.0)
    awarded = _run_check(mgr)
    assert "rom_25" in awarded
    assert "rom_50" in awarded


def test_rom_milestone_not_awarded_below_threshold():
    mgr = _make_session_mgr(sessions=10, rom_right_pct=20.0)
    awarded = _run_check(mgr)
    assert "rom_25" not in awarded
