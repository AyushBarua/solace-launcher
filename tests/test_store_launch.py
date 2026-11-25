"""
tests/test_store_launch.py
Games found on this PC: how GameManager lists them and starts them.
Run with: pytest tests/
"""
import time

import pytest
from PyQt6.QtCore import QCoreApplication

from core import game_manager as gm_module
from core.game_scanner import DetectedGame


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def manager(app, tmp_path, monkeypatch):
    monkeypatch.setenv("SOLACE_DATA_DIR", str(tmp_path))
    found = [DetectedGame(id="steam:10", name="Alpha", store="Steam", install_dir=str(tmp_path),
                          launch="steam://rungameid/10", art_path="")]
    monkeypatch.setattr(gm_module, "scan_all", lambda: found)
    return gm_module.GameManager()


def _pump(app, until, seconds=3.0):
    end = time.time() + seconds
    while not until() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return until()


def test_detected_games_are_listed_apart_from_the_therapy_catalogue(manager):
    detected = manager.get_detected_games()
    assert [g["id"] for g in detected] == ["steam:10"]
    entry = detected[0]
    assert entry["name"] == "Alpha" and entry["is_installed"] and entry["detected"]
    assert entry["genre"] == "Steam" and entry["emoji"] == "A"
    assert all(g["id"] != "steam:10" for g in manager.get_games())


def test_get_game_finds_a_detected_game(manager):
    assert manager.get_game("steam:10")["name"] == "Alpha"


def test_store_game_reports_finished_after_it_closes(app, manager, monkeypatch):
    opened, finished, not_started = [], [], []
    monkeypatch.setattr(gm_module, "open_link", opened.append)
    monkeypatch.setattr(gm_module, "wait_for_game", lambda folder: True)
    manager.game_finished.connect(lambda: finished.append(1))
    manager.game_not_started.connect(not_started.append)

    manager.launch("steam:10")

    assert opened == ["steam://rungameid/10"]
    assert _pump(app, lambda: bool(finished))
    assert not not_started and manager.is_running is False


def test_store_game_that_never_starts_is_reported(app, manager, monkeypatch):
    finished, not_started = [], []
    monkeypatch.setattr(gm_module, "open_link", lambda link: None)
    monkeypatch.setattr(gm_module, "wait_for_game", lambda folder: False)
    manager.game_finished.connect(lambda: finished.append(1))
    manager.game_not_started.connect(not_started.append)

    manager.launch("steam:10")

    assert _pump(app, lambda: bool(not_started))
    assert not_started == ["Alpha"] and not finished and manager.is_running is False


def test_store_link_that_cannot_open_is_reported(app, manager, monkeypatch):
    def refuse(link):
        raise OSError("no program handles this link")

    not_started = []
    monkeypatch.setattr(gm_module, "open_link", refuse)
    manager.game_not_started.connect(not_started.append)

    manager.launch("steam:10")

    assert _pump(app, lambda: bool(not_started))
    assert manager.is_running is False


def test_program_launch_passes_the_store_arguments(app, manager, monkeypatch, tmp_path):
    client = tmp_path / "Client.exe"
    client.write_bytes(b"MZ")
    started = []
    monkeypatch.setattr(gm_module.subprocess, "Popen", lambda cmd, cwd=None: started.append((cmd, cwd)))
    monkeypatch.setattr(gm_module, "wait_for_game", lambda folder: True)
    manager._detected = [gm_module._detected_entry(DetectedGame(
        id="x:1", name="X", store="S", install_dir=str(tmp_path), launch=str(client),
        args=("--exec=launch Pro",)))]
    finished = []
    manager.game_finished.connect(lambda: finished.append(1))

    manager.launch("x:1")

    assert _pump(app, lambda: bool(finished))
    assert started == [([str(client), "--exec=launch Pro"], str(tmp_path))]
