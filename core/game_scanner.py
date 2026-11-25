"""
core/game_scanner.py

Finds the games installed on this PC by reading what each game store records
about them. Nothing is sent anywhere and nothing is written.

Stores: Steam, Epic Games, GOG, Ubisoft Connect, Xbox, Amazon Games, itch.io,
Humble, Rockstar, Battle.net. Tools, engines, plugins and add-ons are left out.

Where each store keeps this information follows the library plugins of Playnite
(https://github.com/JosefNemec/PlayniteExtensions, MIT licence, Copyright (c)
2020 Josef Nemec), rewritten here in Python. See CREDITS.txt.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import struct
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote

import vdf

log = logging.getLogger(__name__)

STEAM_FULLY_INSTALLED = 4
STEAM_PLAYABLE_TYPES = {"game", "demo"}
STEAM_NOT_GAMES = {228980}          # redistributables, hidden even without appinfo
APPINFO_V29 = 0x07564429
_ENTRY_HEADER = 60                  # bytes between an entry's size field and its data
_TRADEMARKS = re.compile("[\u2122\u00ae\u00a9]")
_ART_NAMES = ("header.jpg", "library_header.jpg", "library_600x900.jpg")


@dataclass(frozen=True)
class DetectedGame:
    id: str              # "steam:620"
    name: str
    store: str           # shown to the user
    install_dir: str     # used to tell when the game is running
    launch: str          # a store link (contains "://") or a program path
    art_path: str = ""
    args: tuple = ()     # arguments for a program path


def _clean_name(name: str) -> str:
    return " ".join(_TRADEMARKS.sub("", name or "").split())


# ── Steam ─────────────────────────────────────────────────────────────────────

def _read_binary_kv(data: bytes, pos: int, keys: list) -> tuple:
    """Binary KeyValues with keys stored as indexes into a string table."""
    result = {}
    while True:
        kind = data[pos]
        pos += 1
        if kind == 0x08:
            return result, pos
        key = keys[struct.unpack_from("<i", data, pos)[0]]
        pos += 4
        if kind == 0x00:
            value, pos = _read_binary_kv(data, pos, keys)
        elif kind == 0x01:
            end = data.index(b"\x00", pos)
            value, pos = data[pos:end].decode("utf-8", "replace"), end + 1
        elif kind in (0x02, 0x03, 0x04, 0x06):
            value, pos = struct.unpack_from("<i", data, pos)[0], pos + 4
        elif kind in (0x07, 0x0A):
            value, pos = struct.unpack_from("<q", data, pos)[0], pos + 8
        else:
            raise ValueError(f"unknown value type {kind}")
        result[key] = value


def parse_appinfo_types(path: str, app_ids: set) -> dict:
    """{appid: 'game' | 'tool' | ...} for the wanted apps, from appinfo.vdf.

    Gives {} if the file is missing or in a format this does not know."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        magic, _universe, table_at = struct.unpack_from("<IIq", data, 0)
        if magic != APPINFO_V29:
            return {}
        count = struct.unpack_from("<I", data, table_at)[0]
        keys = [k.decode("utf-8", "replace")
                for k in data[table_at + 4:].split(b"\x00", count)[:count]]
        types, pos = {}, 16
        while pos < table_at:
            app_id = struct.unpack_from("<I", data, pos)[0]
            if app_id == 0:
                break
            size = struct.unpack_from("<I", data, pos + 4)[0]
            if app_id in app_ids:
                tree, _ = _read_binary_kv(data, pos + 8 + _ENTRY_HEADER, keys)
                common = (tree.get("appinfo") or {}).get("common") or {}
                if isinstance(common.get("type"), str):
                    types[app_id] = common["type"].lower()
            pos += 8 + size
        return types
    except (OSError, ValueError, IndexError, struct.error) as exc:
        log.warning("could not read %s: %s", path, exc)
        return {}


def _load_vdf(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return vdf.load(f)
    except (OSError, SyntaxError, ValueError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return {}


def _lower_keys(mapping: dict) -> dict:
    return {str(k).lower(): v for k, v in (mapping or {}).items()}


def _steam_libraries(steam_dir: str) -> list:
    libraries = [steam_dir]
    root = _load_vdf(os.path.join(steam_dir, "steamapps", "libraryfolders.vdf"))
    for value in _lower_keys(root).get("libraryfolders", {}).values():
        path = value.get("path") if isinstance(value, dict) else None
        if path and os.path.isdir(path):
            libraries.append(path)
    unique = {os.path.normcase(os.path.normpath(p)): p for p in libraries}
    return list(unique.values())


def _steam_manifest(path: str, library: str) -> dict | None:
    state = _lower_keys(_lower_keys(_load_vdf(path)).get("appstate", {}))
    try:
        app_id, flags = int(state["appid"]), int(state["stateflags"])
    except (KeyError, TypeError, ValueError):
        return None
    if not flags & STEAM_FULLY_INSTALLED:
        return None
    install_dir = os.path.join(library, "steamapps", "common", str(state.get("installdir", "")))
    name = _clean_name(str(state.get("name", "")))
    if not name or not state.get("installdir") or not os.path.isdir(install_dir):
        return None
    return {"app_id": app_id, "name": name, "install_dir": os.path.normpath(install_dir)}


def _steam_art(steam_dir: str, app_id: int) -> str:
    cache = os.path.join(steam_dir, "appcache", "librarycache")
    found = {}
    for folder, _dirs, files in os.walk(os.path.join(cache, str(app_id))):
        for name in files:
            if name in _ART_NAMES:
                found.setdefault(name, os.path.join(folder, name))
    for name in _ART_NAMES:
        if name in found:
            return found[name]
    flat = os.path.join(cache, f"{app_id}_header.jpg")
    return flat if os.path.isfile(flat) else ""


def scan_steam(steam_dir: str) -> list:
    if not steam_dir or not os.path.isdir(os.path.join(steam_dir, "steamapps")):
        return []
    manifests = []
    for library in _steam_libraries(steam_dir):
        apps = os.path.join(library, "steamapps")
        if not os.path.isdir(apps):
            continue
        for name in os.listdir(apps):
            if name.startswith("appmanifest_") and name.endswith(".acf"):
                found = _steam_manifest(os.path.join(apps, name), library)
                if found:
                    manifests.append(found)
    types = parse_appinfo_types(os.path.join(steam_dir, "appcache", "appinfo.vdf"),
                                {m["app_id"] for m in manifests})
    games = []
    for m in manifests:
        app_id = m["app_id"]
        kind = types.get(app_id)
        if app_id in STEAM_NOT_GAMES or (kind is not None and kind not in STEAM_PLAYABLE_TYPES):
            continue
        games.append(DetectedGame(
            id=f"steam:{app_id}", name=m["name"], store="Steam", install_dir=m["install_dir"],
            launch=f"steam://rungameid/{app_id}", art_path=_steam_art(steam_dir, app_id)))
    return games


# ── Epic Games ────────────────────────────────────────────────────────────────

def _epic_is_game(item: dict) -> bool:
    categories = {str(c).lower() for c in item.get("AppCategories") or []}
    if "games" not in categories or item.get("bIsIncompleteInstall"):
        return False
    if "addons" in categories and "addons/launchable" not in categories:
        return False
    return not categories & {"plugins", "plugins/engine"}


def scan_epic(manifest_dir: str) -> list:
    if not manifest_dir or not os.path.isdir(manifest_dir):
        return []
    games = []
    for filename in os.listdir(manifest_dir):
        if not filename.endswith(".item"):
            continue
        try:
            with open(os.path.join(manifest_dir, filename), "r", encoding="utf-8-sig") as f:
                item = json.load(f)
        except (OSError, ValueError) as exc:
            log.warning("could not read %s: %s", filename, exc)
            continue
        install_dir = item.get("InstallLocation") or ""
        app = item.get("AppName") or ""
        if not (_epic_is_game(item) and app and os.path.isdir(install_dir)):
            continue
        target = ":".join([item.get("CatalogNamespace", ""), item.get("CatalogItemId", ""), app])
        games.append(DetectedGame(
            id=f"epic:{app}", name=_clean_name(item.get("DisplayName") or app), store="Epic",
            install_dir=os.path.normpath(install_dir),
            launch=f"com.epicgames.launcher://apps/{quote(target, safe='')}"
                   "?action=launch&silent=true"))
    return games


# ── GOG, Ubisoft Connect, Xbox ────────────────────────────────────────────────

def scan_gog(entries: dict) -> list:
    """entries: {game id: registry values} from SOFTWARE\\GOG.com\\Games."""
    games = []
    for game_id, values in entries.items():
        exe, name = values.get("exe") or "", _clean_name(values.get("gameName") or "")
        if values.get("dependsOn") or not name or not os.path.isfile(exe):
            continue                                  # DLC, or the game is gone
        games.append(DetectedGame(
            id=f"gog:{game_id}", name=name, store="GOG",
            install_dir=os.path.normpath(values.get("path") or os.path.dirname(exe)),
            launch=exe))
    return games


def scan_ubisoft(entries: dict) -> list:
    """entries: {game id: registry values} from SOFTWARE\\Ubisoft\\Launcher\\Installs."""
    games = []
    for game_id, values in entries.items():
        folder = values.get("InstallDir") or ""
        if not folder or not os.path.isdir(folder):
            continue
        folder = os.path.normpath(folder)
        games.append(DetectedGame(
            id=f"ubisoft:{game_id}", name=_clean_name(os.path.basename(folder)),
            store="Ubisoft Connect", install_dir=folder, launch=f"uplay://launch/{game_id}/0"))
    return games


def _xbox_game(root: str, folder: str) -> DetectedGame | None:
    content = os.path.join(root, folder, "Content")
    config = os.path.join(content, "MicrosoftGame.config")
    if not os.path.isfile(config):
        return None
    try:
        tree = ET.parse(config).getroot()
    except (OSError, ET.ParseError) as exc:
        log.warning("could not read %s: %s", config, exc)
        return None
    visuals = tree.find(".//ShellVisuals")
    name = visuals.get("DefaultDisplayName", "") if visuals is not None else ""
    if not name or name.startswith("ms-resource:"):
        name = folder
    launch = os.path.join(content, "gamelaunchhelper.exe")
    if not os.path.isfile(launch):
        exe = tree.find(".//Executable")
        launch = os.path.join(content, exe.get("Name", "")) if exe is not None else ""
    if not os.path.isfile(launch):
        return None
    return DetectedGame(id=f"xbox:{folder}", name=_clean_name(name), store="Xbox",
                        install_dir=os.path.normpath(content), launch=launch)


def scan_xbox(root: str) -> list:
    if not root or not os.path.isdir(root):
        return []
    found = (_xbox_game(root, folder) for folder in os.listdir(root))
    return [game for game in found if game]


# ── Amazon Games, itch.io, Humble ─────────────────────────────────────────────

def _query(db_path: str, sql: str) -> list:
    """Rows from a store's database, opened read-only. [] if absent or unreadable."""
    if not db_path or not os.path.isfile(db_path):
        return []
    try:
        db = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            return db.execute(sql).fetchall()
        finally:
            db.close()
    except (sqlite3.Error, OSError, ValueError) as exc:
        log.warning("could not read %s: %s", db_path, exc)
        return []


def scan_amazon(db_path: str) -> list:
    rows = _query(db_path, "SELECT Id, InstallDirectory, ProductTitle FROM DbSet WHERE Installed = 1")
    games = []
    for game_id, folder, title in rows:
        if game_id and title and folder and os.path.isdir(folder):
            games.append(DetectedGame(
                id=f"amazon:{game_id}", name=_clean_name(title), store="Amazon Games",
                install_dir=os.path.normpath(folder), launch=f"amazon-games://play/{game_id}"))
    return games


def _itch_program(verdict: str) -> tuple:
    """(install folder, program) from the record itch keeps of what it can start."""
    try:
        data = json.loads(verdict)
        base = data["basePath"]
        return base, os.path.normpath(os.path.join(base, data["candidates"][0]["path"]))
    except (TypeError, ValueError, KeyError, IndexError):
        return "", ""


def scan_itch(db_path: str) -> list:
    rows = _query(db_path, "SELECT games.id, games.title, caves.verdict FROM caves "
                           "JOIN games ON games.id = caves.game_id "
                           "WHERE games.classification = 'game'")
    games = []
    for game_id, title, verdict in rows:
        folder, program = _itch_program(verdict)
        if title and program.lower().endswith(".exe") and os.path.isfile(program):
            games.append(DetectedGame(
                id=f"itch:{game_id}", name=_clean_name(title), store="itch.io",
                install_dir=os.path.normpath(folder), launch=program))
    return games


def scan_humble(config_path: str) -> list:
    if not config_path or not os.path.isfile(config_path):
        return []
    try:
        with open(config_path, "r", encoding="utf-8-sig") as f:
            entries = json.load(f).get("game-collection-4") or []
    except (OSError, ValueError, AttributeError) as exc:
        log.warning("could not read %s: %s", config_path, exc)
        return []
    games = []
    for item in entries:
        folder, program = item.get("filePath") or "", item.get("executablePath") or ""
        name, key = _clean_name(item.get("gameName") or ""), item.get("machineName")
        target = os.path.normpath(os.path.join(folder, program))
        if (item.get("status") in ("downloaded", "installed") and key and name
                and folder and program and os.path.isfile(target)):
            games.append(DetectedGame(
                id=f"humble:{key}", name=name, store="Humble",
                install_dir=os.path.normpath(folder), launch=target))
    return games


# ── Rockstar and Battle.net, from Windows' list of installed programs ─────────

_ROCKSTAR_ID = re.compile(r"uninstall=(\S+)\s*$", re.IGNORECASE)
_ROCKSTAR_NOT_GAMES = {"Rockstar Games Launcher", "Rockstar Games Social Club"}
_BATTLENET_UID = re.compile(r"Battle\.net.*--uid=([\w.]+)", re.IGNORECASE)
_BATTLENET_CODES = {   # Blizzard's install id -> the code Battle.net launches
    "wow": "WoW", "diablo3": "D3", "s2": "S2", "s1": "S1", "hs_beta": "WTCG",
    "heroes": "Hero", "prometheus": "Pro", "w3": "W3", "viper": "VIPR", "odin": "ODIN",
    "lazarus": "LAZR", "zeus": "ZEUS", "wlby": "WLBY", "osi": "OSI", "rtro": "RTRO",
    "fore": "FORE", "anbs": "ANBS", "auks": "AUKS", "fen": "Fen", "w1r": "W1R", "w2r": "W2R",
}


def _program_in(entries: dict, display_name: str, filename: str) -> str:
    """Path of a store's own launcher, found through its uninstall entry."""
    for values in entries.values():
        if values.get("DisplayName") == display_name:
            path = os.path.join((values.get("InstallLocation") or "").strip('"'), filename)
            if os.path.isfile(path):
                return os.path.normpath(path)
    return ""


def _installed_folder(values: dict) -> str:
    folder = (values.get("InstallLocation") or "").strip('"')
    return os.path.normpath(folder) if folder and os.path.isdir(folder) else ""


def scan_rockstar(entries: dict) -> list:
    """entries: the uninstall keys {key: values}."""
    client = _program_in(entries, "Rockstar Games Launcher", "Launcher.exe")
    games = []
    for values in entries.values():
        match = _ROCKSTAR_ID.search(values.get("UninstallString") or "")
        folder = _installed_folder(values)
        name = _clean_name(values.get("DisplayName") or "")
        if name in _ROCKSTAR_NOT_GAMES:
            continue
        if client and match and folder and name and values.get("Publisher") == "Rockstar Games":
            games.append(DetectedGame(
                id=f"rockstar:{match.group(1)}", name=name, store="Rockstar",
                install_dir=folder, launch=client, args=("-launchTitleInFolder", folder)))
    return games


def scan_battlenet(entries: dict) -> list:
    """entries: the uninstall keys {key: values}. Games with an unknown id are skipped."""
    client = _program_in(entries, "Battle.net", "Battle.net.exe")
    games = []
    for values in entries.values():
        match = _BATTLENET_UID.search(values.get("UninstallString") or "")
        uid = match.group(1).lower() if match else ""
        folder = _installed_folder(values)
        name = _clean_name(values.get("DisplayName") or "")
        if client and uid in _BATTLENET_CODES and folder and name:
            games.append(DetectedGame(
                id=f"battlenet:{uid}", name=name, store="Battle.net", install_dir=folder,
                launch=client, args=(f"--exec=launch {_BATTLENET_CODES[uid]}",)))
    return games


# ── This PC ───────────────────────────────────────────────────────────────────

def _registry_values(hive, path: str) -> dict:
    """{subkey: {value name: value}} from both the 32 and 64 bit views."""
    import winreg
    result = {}
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as root:
                for i in range(winreg.QueryInfoKey(root)[0]):
                    name = winreg.EnumKey(root, i)
                    with winreg.OpenKey(root, name, 0, winreg.KEY_READ | view) as key:
                        count = winreg.QueryInfoKey(key)[1]
                        result[name] = dict(winreg.EnumValue(key, v)[:2] for v in range(count))
        except OSError:
            continue
    return result


def _steam_dir() -> str:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            return os.path.normpath(winreg.QueryValueEx(key, "SteamPath")[0])
    except OSError:
        return ""


def _this_pc() -> list:
    if sys.platform != "win32":
        return []
    import winreg
    hklm = winreg.HKEY_LOCAL_MACHINE
    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    drive = os.environ.get("SystemDrive", "C:") + os.sep
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    uninstall = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"

    def installed_programs() -> dict:
        return {**_registry_values(hklm, uninstall),
                **_registry_values(winreg.HKEY_CURRENT_USER, uninstall)}

    return [
        lambda: scan_amazon(os.path.join(local, "Amazon Games", "Data", "Games", "Sql",
                                         "GameInstallInfo.sqlite")),
        lambda: scan_itch(os.path.join(roaming, "itch", "db", "butler.db")),
        lambda: scan_humble(os.path.join(roaming, "Humble App", "config.json")),
        lambda: scan_rockstar(installed_programs()),
        lambda: scan_battlenet(installed_programs()),
        lambda: scan_steam(_steam_dir()),
        lambda: scan_epic(os.path.join(program_data, "Epic", "EpicGamesLauncher",
                                       "Data", "Manifests")),
        lambda: scan_gog(_registry_values(hklm, r"SOFTWARE\GOG.com\Games")),
        lambda: scan_ubisoft(_registry_values(hklm, r"SOFTWARE\Ubisoft\Launcher\Installs")),
        lambda: scan_xbox(os.path.join(drive, "XboxGames")),
    ]


def scan_all(scanners: Iterable[Callable[[], list]] | None = None) -> list:
    """Every installed game, sorted by name. A store that fails is skipped."""
    games = {}
    for scan in (_this_pc() if scanners is None else scanners):
        try:
            for game in scan():
                games.setdefault(game.id, game)
        except Exception as exc:        # one odd store file must not hide the others
            log.warning("a game store could not be scanned: %s", exc)
    return sorted(games.values(), key=lambda g: g.name.lower())
