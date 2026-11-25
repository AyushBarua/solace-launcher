"""
GameManager — reads games catalog and handles subprocess game launching.
Hides the launcher window while a game runs, restores it when the game exits.

Data files:
  games_catalog.json    — read-only static metadata (name, desc, art, url).
                          Can be replaced on updates without touching installs.
  games_install_state.json — runtime install state {game_id: {is_installed, path}}.
                             Saved atomically; never overwritten by catalog updates.
"""
import os
import sys
import json
import threading
import subprocess
import urllib.request
import zipfile
import shutil
from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal
from core.injector import inject_controller_into_game
from core.game_scanner import DetectedGame, scan_all
from core.process_watch import wait_for_game

_HERE = os.path.dirname(os.path.abspath(__file__))
GAMES_DB = os.path.join(_HERE, "..", "games_db.json")  # kept for legacy compat


def open_link(link: str) -> None:
    """Hand a store link (steam://...) to Windows. Raises OSError if nothing handles it."""
    os.startfile(link)


def _detected_entry(game: DetectedGame) -> dict:
    """A game found on this PC, in the shape the Play page expects."""
    return {
        "id": game.id,
        "name": game.name,
        "description": f"Installed from {game.store}. It uses its own controls; "
                       "the Solace controller is not mapped to it yet.",
        "genre": game.store,
        "category": game.store,
        "body_parts": [],
        "difficulty_tag": "",
        "emoji": game.name[:1].upper(),          # shown when there is no cover art
        "art_url": game.art_path,
        "is_installed": True,
        "path": "",
        "exe_path": "",
        "game_config": {"type": "store"},
        "detected": True,
        "launch": game.launch,
        "launch_args": list(game.args),
        "install_dir": game.install_dir,
    }


def _get_catalog_path() -> str:
    """Bundled / dev path for the static game catalog."""
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "games_catalog.json")


def _get_install_state_path() -> str:
    """Writable runtime install-state file."""
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "games_install_state.json")


def _load_install_state() -> dict:
    """Returns {game_id: {is_installed, path, exe_path}} dict."""
    path = _get_install_state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_install_state(state: dict):
    """Atomically write install state so a crash can never corrupt it."""
    path = _get_install_state_path()
    tmp  = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


class GameManager(QObject):
    game_finished      = pyqtSignal()
    download_finished  = pyqtSignal(str)   # emits game_id
    download_failed    = pyqtSignal(str)   # U1: emits game_id on failure
    web_game_requested = pyqtSignal(dict)  # web games — MainWindow opens WebGameWindow
    game_not_started   = pyqtSignal(str)   # a store game never appeared (emits its name)

    def __init__(self, main_window=None):
        super().__init__()
        self.main_window = main_window
        self.is_running  = False
        self._games: list[dict] = []
        self._detected: list[dict] = []     # found on this PC; never in the therapy list
        self._load()
        self.refresh_detected()

    # ── data ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_bundled_path(rel_path: str) -> str:
        """
        Resolve a bundled_games/ relative path to an absolute path.
        Works both from source (relative to FlexStoreLauncher/) and
        from a frozen exe (relative to _internal/).
        """
        base = os.path.normpath(os.path.join(_HERE, ".."))
        return os.path.normpath(os.path.join(base, rel_path))

    def _load(self):
        """Load catalog then overlay install state."""
        from core.paths import get_data_dir
        catalog_dst = _get_catalog_path()

        # Bootstrap: copy bundled catalog to data dir on first run
        if not os.path.exists(catalog_dst):
            for src in [
                os.path.join(_HERE, "..", "games_catalog.json"),
                os.path.join(_HERE, "..", "games_db.json"),   # legacy fallback
            ]:
                if os.path.exists(src):
                    shutil.copy2(src, catalog_dst)
                    break

        if not os.path.exists(catalog_dst):
            return  # nothing to load

        with open(catalog_dst, "r", encoding="utf-8") as f:
            catalog = json.load(f)

        # Overlay bundled_path from the SHIPPED catalog so app updates
        # propagate to existing installs (their data-dir catalog was copied
        # once at first run and would otherwise never learn about newly
        # bundled games).
        shipped_path = os.path.join(_HERE, "..", "games_catalog.json")
        if os.path.exists(shipped_path):
            try:
                with open(shipped_path, "r", encoding="utf-8") as f:
                    shipped = {g["id"]: g for g in json.load(f)}
                for game in catalog:
                    sg = shipped.get(game.get("id"))
                    if sg:
                        if sg.get("bundled_path"):
                            game["bundled_path"] = sg["bundled_path"]
                        if sg.get("game_config"):
                            game["game_config"] = sg["game_config"]
            except Exception as exc:
                print(f"[GameManager] shipped catalog overlay: {exc}")

        # Migrate legacy games_db.json install state on first run
        install_state = _load_install_state()
        if not install_state:
            legacy = os.path.join(get_data_dir(), "games_db.json")
            if os.path.exists(legacy):
                try:
                    with open(legacy, "r", encoding="utf-8") as f:
                        old_games = json.load(f)
                    for g in old_games:
                        if g.get("is_installed"):
                            install_state[g["id"]] = {
                                "is_installed": True,
                                "path": g.get("path", ""),
                                "exe_path": g.get("exe_path", ""),
                            }
                    if install_state:
                        _save_install_state(install_state)
                except Exception:
                    pass

        # Merge catalog + install state
        for game in catalog:
            state = install_state.get(game["id"], {})

            # Bundled games: resolve relative path and mark installed automatically
            bundled_rel = game.get("bundled_path", "")
            if bundled_rel:
                abs_path = self._resolve_bundled_path(bundled_rel)
                if os.path.exists(abs_path):
                    game["is_installed"] = True
                    if abs_path.lower().endswith(".exe"):
                        game["exe_path"] = abs_path
                        game["path"]     = state.get("path", game.get("path", ""))
                    else:
                        game["path"]     = abs_path
                        game["exe_path"] = state.get("exe_path", game.get("exe_path", ""))
                    continue  # skip install_state overlay — bundled takes priority

            game["is_installed"] = state.get("is_installed", False)
            game["path"]         = state.get("path", game.get("path", ""))
            game["exe_path"]     = state.get("exe_path", game.get("exe_path", ""))

        self._games = catalog

    def _save_install_state_for(self, game: dict):
        """Update install state for a single game atomically."""
        state = _load_install_state()
        state[game["id"]] = {
            "is_installed": game.get("is_installed", False),
            "path":         game.get("path", ""),
            "exe_path":     game.get("exe_path", ""),
        }
        _save_install_state(state)

    def get_games(self) -> list[dict]:
        return self._games

    def get_game(self, game_id: str) -> Optional[dict]:
        return next((g for g in self._games + self._detected if g["id"] == game_id), None)

    # ── games found on this PC ────────────────────────────────────────────────
    def get_detected_games(self) -> list[dict]:
        return self._detected

    def refresh_detected(self) -> None:
        """Look through the game stores again."""
        self._detected = [_detected_entry(g) for g in scan_all()]

    def _launch_store_game(self, game: dict) -> None:
        self.is_running = True
        self._current_proc = None
        print(f"[GameManager] Launching installed game: {game['name']}")
        threading.Thread(target=self._run_store_game, args=(game,), daemon=True).start()

    def _run_store_game(self, game: dict) -> None:
        """Start the game and wait for it to close (it is not our child process)."""
        ran = False
        try:
            if "://" in game["launch"]:
                open_link(game["launch"])
            else:
                subprocess.Popen([game["launch"], *game["launch_args"]],
                                 cwd=os.path.dirname(game["launch"]))
            ran = wait_for_game(game["install_dir"])
        except OSError as exc:
            print(f"[GameManager] Could not start {game['name']}: {exc}")
        finally:
            self.is_running = False
        if ran:
            self.game_finished.emit()
        else:
            self.game_not_started.emit(game["name"])

    # ── downloading ───────────────────────────────────────────────────────────
    
    def download_game(self, game_id: str):
        game = self.get_game(game_id)
        if not game: return
        url = game.get("github_url")
        if not url: return

        print(f"[GameManager] Downloading {game['name']} from {url}...")
        
        def _dl():
            try:
                from core.paths import get_data_dir
                # 1. Resolve games_dir first so we can download straight there
                #    (avoids writing to C:\Temp when C drive is low on space)
                games_dir = None
                s_path = os.path.join(get_data_dir(), "global_settings.json")
                try:
                    if os.path.exists(s_path):
                        with open(s_path, "r", encoding="utf-8") as sf:
                            games_dir = json.load(sf).get("games_dir")
                except Exception:
                    pass

                if not games_dir:
                    games_dir = os.path.normpath(
                        os.path.join(os.path.dirname(_HERE), "..", "..", "Games")
                    )

                dest_dir = os.path.join(games_dir, game_id)
                os.makedirs(dest_dir, exist_ok=True)

                # 2. Download zip directly into dest_dir (same drive, no C:\Temp)
                zip_path = os.path.join(dest_dir, f"_download_{game_id}.zip")
                urllib.request.urlretrieve(url, zip_path)

                # 3. Extract in place then delete the zip
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(dest_dir)
                try:
                    os.remove(zip_path)
                except Exception:
                    pass
                    
                # GitHub zips usually extract into a single subfolder (e.g. arkanoid-master)
                extracted_items = os.listdir(dest_dir)
                if len(extracted_items) == 1 and os.path.isdir(os.path.join(dest_dir, extracted_items[0])):
                    inner_dir = os.path.join(dest_dir, extracted_items[0])
                    for item in os.listdir(inner_dir):
                        shutil.move(os.path.join(inner_dir, item), dest_dir)
                    os.rmdir(inner_dir)

                game_type = game.get("game_config", {}).get("type", "mouse")

                if game_type == "web":
                    # 3W. Find the HTML entry point
                    entry_html = self._find_html_entry(dest_dir, game)

                    if entry_html:
                        # 4W. Apply code_patches (if any) and write game_config.json
                        inject_controller_into_game(dest_dir, entry_html, game)

                        # 5W. Persist install state
                        game["path"]         = entry_html
                        game["is_installed"] = True
                        self._save_install_state_for(game)

                        print(f"[GameManager] Successfully installed web game {game['name']}!")
                        self.download_finished.emit(game_id)
                    else:
                        print(f"[GameManager] No HTML entry point found in {dest_dir}. Cleaning up.")
                        shutil.rmtree(dest_dir, ignore_errors=True)
                        self.download_failed.emit(game_id)

                else:
                    # 3P. Find the main Python script
                    main_py = None
                    for root, dirs, files in os.walk(dest_dir):
                        if "main.py" in files:
                            main_py = os.path.join(root, "main.py")
                            break
                        elif "run.py" in files:
                            main_py = os.path.join(root, "run.py")
                            break
                        elif "arkanoid.py" in files:
                            main_py = os.path.join(root, "arkanoid.py")
                            break

                    if main_py:
                        # 4P. Inject pygame controller
                        inject_controller_into_game(dest_dir, main_py, game)

                        # 5P. Persist install state
                        game["path"]         = main_py
                        game["is_installed"] = True
                        self._save_install_state_for(game)

                        print(f"[GameManager] Successfully installed {game['name']}!")
                        self.download_finished.emit(game_id)
                    else:
                        print(f"[GameManager] No entry-point found in {dest_dir}. Cleaning up.")
                        shutil.rmtree(dest_dir, ignore_errors=True)

            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[GameManager] Download error: {e}")
                # P4: clean up partial extraction so no orphaned files remain
                if 'dest_dir' in dir() and os.path.exists(dest_dir):
                    shutil.rmtree(dest_dir, ignore_errors=True)
                # U1: notify UI so the card can show a Retry state
                self.download_failed.emit(game_id)

        threading.Thread(target=_dl, daemon=True).start()

    @staticmethod
    def _find_html_entry(dest_dir: str, game: dict) -> str | None:
        """
        Find the HTML entry point for a web game.
        Priority:
          1. game_config["entry_point"] if specified (e.g. "v5.game.html")
          2. index.html at any depth (shallowest first)
          3. First *.html file at the root level
        """
        entry_point = game.get("game_config", {}).get("entry_point", "")

        # Walk shallowest first
        all_html = []
        for root, dirs, files in os.walk(dest_dir):
            depth = root.replace(dest_dir, "").count(os.sep)
            for f in files:
                if f.lower().endswith(".html"):
                    all_html.append((depth, os.path.join(root, f), f))

        all_html.sort(key=lambda x: x[0])  # shallowest first

        if entry_point:
            for _, path, fname in all_html:
                if fname.lower() == entry_point.lower():
                    return path

        for _, path, fname in all_html:
            if fname.lower() == "index.html":
                return path

        # Fallback: first HTML file found
        if all_html:
            return all_html[0][1]

        return None

    # ── launching ─────────────────────────────────────────────────────────────

    def _effective_difficulty(self) -> float:
        """Per-patient adaptive value if the launcher provided one, otherwise
        the global settings multiplier (legacy fallback for direct launches)."""
        diff = getattr(self, "_launch_difficulty", None)
        if diff is not None:
            return diff
        from core.paths import get_data_dir
        p = os.path.join(get_data_dir(), "global_settings.json")
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    return json.load(f).get("difficulty_multiplier", 1.0)
            except Exception:
                pass
        return 1.0

    def _write_game_config(self, game: dict, cwd: str, diff_mult: float):
        gc = game.get("game_config", {}).copy()
        gc["difficulty_multiplier"] = diff_mult
        cfg_path = os.path.join(cwd, "game_config.json")
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(gc, f, indent=2)
        except Exception as e:
            print(f"[GameManager] Could not update game config: {e}")

    def launch(self, game_id: str, difficulty: float | None = None):
        """
        difficulty: per-patient adaptive value from the SuggestionEngine.
        If given, it is written to the game's game_config.json — otherwise
        the global settings multiplier is used (legacy behaviour).
        """
        self._launch_difficulty = difficulty
        # P1 fix: check if the tracked process is still alive before blocking
        if self.is_running and hasattr(self, '_current_proc'):
            if self._current_proc and self._current_proc.poll() is not None:
                # Process has already exited externally — reset the flag
                self.is_running = False
        if self.is_running:
            print("[GameManager] A game is already running. Ignoring launch request.")
            return

        game = self.get_game(game_id)
        if not game:
            print(f"[GameManager] Unknown game id: {game_id}")
            return

        game_type = game.get("game_config", {}).get("type", "mouse")

        # ── Installed store games: start through the store and watch ───────────
        if game_type == "store":
            self._launch_store_game(game)
            return

        # ── Web game path ──────────────────────────────────────────────────────
        if game_type == "web":
            html_path = game.get("path", "")
            if not html_path or not os.path.exists(html_path):
                print(f"[GameManager] Web game not installed or path missing: {game['name']}")
                return
            self.is_running = True
            print(f"[GameManager] Launching web game: {game['name']}")
            # C2 fix: web games get the difficulty too — both as a config file
            # next to the game (for games that fetch it) and via the game dict
            # (WebGameWindow injects it as window.__solaceGameConfig).
            diff = self._effective_difficulty()
            self._write_game_config(game, os.path.dirname(html_path), diff)
            game = dict(game)
            game["adaptive_difficulty"] = diff
            self.web_game_requested.emit(game)
            return

        # ── Python / EXE path ─────────────────────────────────────────────────
        exe_path = game.get("exe_path", "")
        py_path  = game.get("path", "")

        # When frozen, sys.executable IS Solace.exe which has a runpy intercept
        # to act as a Python interpreter when passed a .py file as first argument.
        python_bin = sys.executable

        if exe_path and os.path.exists(exe_path):
            cmd = [exe_path]
            cwd = os.path.dirname(exe_path)
        elif py_path and os.path.exists(py_path):
            cmd = [python_bin, py_path]
            cwd = os.path.dirname(py_path)
        else:
            print(f"[GameManager] No valid path for: {game['name']}")
            return

        self._write_game_config(game, cwd, self._effective_difficulty())

        self.is_running = True
        print(f"[GameManager] Launching: {game['name']}")

        if self.main_window:
            self.main_window.hide()

        def _run():
            try:
                self._current_proc = subprocess.Popen(cmd, cwd=cwd)
                self._current_proc.wait()
            except Exception as exc:
                print(f"[GameManager] Error running game: {exc}")
            finally:
                self._current_proc = None
                self.is_running = False
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, self._emit_game_finished)

        threading.Thread(target=_run, daemon=True).start()

    def _emit_game_finished(self):
        """Relay game_finished to the GUI thread. Called via invokeMethod."""
        self.game_finished.emit()
