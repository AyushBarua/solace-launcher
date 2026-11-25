"""
tests/test_game_scanner.py
Finding installed games from the PC's game stores, and noticing when a game
started through a store closes. Run with: pytest tests/
"""
import json
import struct

from core import game_scanner as gs
from core import process_watch as pw


# ── Fixtures built by hand ────────────────────────────────────────────────────

def _appinfo(path, apps):
    """Write a minimal version-29 appinfo.vdf: {appid: type}."""
    table = ["appinfo", "common", "type", "name", "gameid"]

    def key(name):
        return struct.pack("<i", table.index(name))

    body = b""
    for appid, kind in apps.items():
        kv = (b"\x00" + key("appinfo")
              + b"\x00" + key("common")
              + b"\x01" + key("name") + b"Something\x00"
              + b"\x02" + key("gameid") + struct.pack("<i", appid)
              + b"\x01" + key("type") + kind.encode() + b"\x00"
              + b"\x08" + b"\x08" + b"\x08")
        entry = struct.pack("<IIQ", 2, 0, 0) + b"\x00" * 20 + struct.pack("<I", 1) + b"\x00" * 20 + kv
        body += struct.pack("<II", appid, len(entry)) + entry
    body += struct.pack("<I", 0)
    offset = 16 + len(body)
    strings = struct.pack("<I", len(table)) + b"".join(s.encode() + b"\x00" for s in table)
    path.write_bytes(struct.pack("<IIq", 0x07564429, 1, offset) + body + strings)


def _steam(tmp_path, games, types=None, extra_library=False):
    """A fake Steam folder. games: {appid: (name, installdir, state_flags)}."""
    steam = tmp_path / "Steam"
    libs = [steam]
    if extra_library:
        libs.append(tmp_path / "Library2")
    for lib in libs:
        (lib / "steamapps" / "common").mkdir(parents=True, exist_ok=True)
    lines = ['"libraryfolders"', "{"]
    for i, lib in enumerate(libs):
        escaped = str(lib).replace("\\", "\\\\")
        lines += [f'\t"{i}"', "\t{", f'\t\t"path"\t\t"{escaped}"', "\t}"]
    lines.append("}")
    (steam / "steamapps" / "libraryfolders.vdf").write_text("\n".join(lines), encoding="utf-8")
    for n, (appid, (name, installdir, flags)) in enumerate(games.items()):
        lib = libs[n % len(libs)]
        (lib / "steamapps" / f"appmanifest_{appid}.acf").write_text(
            f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n'
            f'\t"StateFlags"\t\t"{flags}"\n\t"installdir"\t\t"{installdir}"\n}}\n', encoding="utf-8")
        (lib / "steamapps" / "common" / installdir).mkdir(exist_ok=True)
    if types is not None:
        (steam / "appcache").mkdir(exist_ok=True)
        _appinfo(steam / "appcache" / "appinfo.vdf", types)
    return steam


# ── Steam ─────────────────────────────────────────────────────────────────────

def test_appinfo_types_are_read_for_the_requested_apps(tmp_path):
    path = tmp_path / "appinfo.vdf"
    _appinfo(path, {10: "Game", 20: "Tool", 30: "Application"})
    assert gs.parse_appinfo_types(str(path), {10, 30}) == {10: "game", 30: "application"}


def test_appinfo_unreadable_gives_nothing(tmp_path):
    path = tmp_path / "appinfo.vdf"
    path.write_bytes(b"not an appinfo file")
    assert gs.parse_appinfo_types(str(path), {10}) == {}
    assert gs.parse_appinfo_types(str(tmp_path / "missing.vdf"), {10}) == {}


def test_steam_lists_games_from_every_library(tmp_path):
    steam = _steam(tmp_path, {10: ("Alpha", "alpha", 4), 20: ("Beta", "beta", 4)},
                   types={10: "Game", 20: "game"}, extra_library=True)
    games = gs.scan_steam(str(steam))
    assert sorted(g.name for g in games) == ["Alpha", "Beta"]
    alpha = next(g for g in games if g.name == "Alpha")
    assert alpha.id == "steam:10" and alpha.store == "Steam"
    assert alpha.launch == "steam://rungameid/10"
    assert alpha.install_dir.endswith("alpha")


def test_steam_leaves_out_tools_and_applications(tmp_path):
    steam = _steam(tmp_path, {10: ("Game", "g", 4), 365670: ("Blender", "Blender", 4),
                              228980: ("Steamworks Common Redistributables", "sw", 4)},
                   types={10: "Game", 365670: "Application", 228980: "Config"})
    assert [g.name for g in gs.scan_steam(str(steam))] == ["Game"]


def test_steam_without_appinfo_still_hides_the_redistributables(tmp_path):
    steam = _steam(tmp_path, {10: ("Game", "g", 4),
                              228980: ("Steamworks Common Redistributables", "sw", 4)})
    assert [g.name for g in gs.scan_steam(str(steam))] == ["Game"]


def test_steam_skips_games_that_are_not_fully_installed(tmp_path):
    steam = _steam(tmp_path, {10: ("Ready", "r", 4), 20: ("Downloading", "d", 1026)},
                   types={10: "game", 20: "game"})
    assert [g.name for g in gs.scan_steam(str(steam))] == ["Ready"]


def test_steam_cleans_trademark_signs_from_names(tmp_path):
    steam = _steam(tmp_path, {10: ("Rocket Thing\u2122 \u00ae", "r", 4)}, types={10: "game"})
    assert gs.scan_steam(str(steam))[0].name == "Rocket Thing"


def test_steam_finds_cached_art(tmp_path):
    steam = _steam(tmp_path, {10: ("Alpha", "alpha", 4)}, types={10: "game"})
    art = steam / "appcache" / "librarycache" / "10" / "abc123"
    art.mkdir(parents=True)
    (art / "header.jpg").write_bytes(b"jpg")
    assert gs.scan_steam(str(steam))[0].art_path.endswith("header.jpg")


def test_steam_missing_gives_empty_list(tmp_path):
    assert gs.scan_steam(str(tmp_path / "nope")) == []
    assert gs.scan_steam("") == []


# ── Epic ──────────────────────────────────────────────────────────────────────

def _epic_item(folder, filename, install, **overrides):
    install.mkdir(parents=True, exist_ok=True)
    data = {"DisplayName": "Some Game", "InstallLocation": str(install), "AppName": "app1",
            "CatalogNamespace": "ns", "CatalogItemId": "item",
            "AppCategories": ["public", "games", "applications"]}
    data.update(overrides)
    folder.mkdir(exist_ok=True)
    (folder / filename).write_text(json.dumps(data), encoding="utf-8")


def test_epic_lists_games_with_a_launch_link(tmp_path):
    folder = tmp_path / "Manifests"
    _epic_item(folder, "a.item", tmp_path / "g1")
    game = gs.scan_epic(str(folder))[0]
    assert game.id == "epic:app1" and game.store == "Epic" and game.name == "Some Game"
    assert game.launch == ("com.epicgames.launcher://apps/ns%3Aitem%3Aapp1"
                           "?action=launch&silent=true")


def test_epic_leaves_out_engines_plugins_addons_and_broken_installs(tmp_path):
    folder = tmp_path / "Manifests"
    _epic_item(folder, "engine.item", tmp_path / "e", AppName="e",
               AppCategories=["engines/ue5", "engines"])
    _epic_item(folder, "plugin.item", tmp_path / "p", AppName="p",
               AppCategories=["plugins/engine", "plugins"])
    _epic_item(folder, "addon.item", tmp_path / "d", AppName="d",
               AppCategories=["games", "addons"])
    _epic_item(folder, "partial.item", tmp_path / "i", AppName="i", bIsIncompleteInstall=True)
    _epic_item(folder, "gone.item", tmp_path / "x", AppName="x",
               InstallLocation=str(tmp_path / "not-there"))
    (folder / "broken.item").write_text("{oops", encoding="utf-8")
    assert gs.scan_epic(str(folder)) == []


def test_epic_missing_gives_empty_list(tmp_path):
    assert gs.scan_epic(str(tmp_path / "nope")) == []


# ── GOG, Ubisoft, Xbox ────────────────────────────────────────────────────────

def test_gog_lists_games_and_skips_dlc(tmp_path):
    exe = tmp_path / "game.exe"
    exe.write_bytes(b"MZ")
    entries = {"1": {"gameName": "Old Classic", "path": str(tmp_path), "exe": str(exe)},
               "2": {"gameName": "Its DLC", "path": str(tmp_path), "exe": str(exe), "dependsOn": "1"},
               "3": {"gameName": "Gone", "path": str(tmp_path), "exe": str(tmp_path / "no.exe")}}
    games = gs.scan_gog(entries)
    assert [(g.id, g.name, g.launch) for g in games] == [("gog:1", "Old Classic", str(exe))]


def test_ubisoft_uses_the_folder_name(tmp_path):
    folder = tmp_path / "Far Away 3"
    folder.mkdir()
    games = gs.scan_ubisoft({"46": {"InstallDir": str(folder).replace("\\", "/") + "/"},
                             "99": {"InstallDir": str(tmp_path / "gone")}})
    assert [(g.id, g.name, g.launch) for g in games] == [
        ("ubisoft:46", "Far Away 3", "uplay://launch/46/0")]


def test_xbox_reads_the_game_config(tmp_path):
    content = tmp_path / "SkyGame" / "Content"
    content.mkdir(parents=True)
    (content / "MicrosoftGame.config").write_text(
        '<?xml version="1.0"?><Game><ExecutableList><Executable Name="sky.exe"/></ExecutableList>'
        '<ShellVisuals DefaultDisplayName="Sky Game"/></Game>', encoding="utf-8")
    (content / "sky.exe").write_bytes(b"MZ")
    (tmp_path / "GameSave").mkdir()
    games = gs.scan_xbox(str(tmp_path))
    assert [(g.id, g.name) for g in games] == [("xbox:SkyGame", "Sky Game")]
    assert games[0].launch.endswith("sky.exe")


def test_xbox_prefers_the_launch_helper(tmp_path):
    content = tmp_path / "SkyGame" / "Content"
    content.mkdir(parents=True)
    (content / "MicrosoftGame.config").write_text(
        '<Game><ShellVisuals DefaultDisplayName="ms-resource:Name"/></Game>', encoding="utf-8")
    (content / "gamelaunchhelper.exe").write_bytes(b"MZ")
    game = gs.scan_xbox(str(tmp_path))[0]
    assert game.name == "SkyGame" and game.launch.endswith("gamelaunchhelper.exe")


# ── All stores together ───────────────────────────────────────────────────────

def _g(game_id, name):
    return gs.DetectedGame(id=game_id, name=name, store="S", install_dir="d", launch="x")


def test_scan_all_merges_sorts_and_survives_a_failing_store():
    def broken():
        raise OSError("access denied")

    games = gs.scan_all([lambda: [_g("b", "beta")], broken,
                         lambda: [_g("a", "Alpha"), _g("b", "beta again")]])
    assert [g.name for g in games] == ["Alpha", "beta"]


# ── Noticing when a store-launched game closes ────────────────────────────────

def test_paths_under_matches_only_inside_the_folder():
    paths = [r"C:\Games\Alpha\bin\alpha.exe", r"C:\Windows\explorer.exe"]
    assert pw.any_under(paths, r"C:\Games\Alpha")
    assert pw.any_under(paths, "c:/games/alpha/")
    assert not pw.any_under(paths, r"C:\Games\Al")
    assert not pw.any_under(paths, "")


def _processes(*snapshots):
    calls = iter(snapshots)
    last = snapshots[-1]
    return lambda: next(calls, last)


def test_wait_for_game_returns_true_after_the_game_closes():
    game = [r"C:\G\x\game.exe"]
    slept = []
    ran = pw.wait_for_game(r"C:\G\x", _processes([], [], game, game, [], [], []),
                           sleep=slept.append, start_timeout=60, poll=1)
    assert ran is True and len(slept) >= 4


def test_wait_for_game_ignores_a_short_gap_between_launcher_and_game():
    game = [r"C:\G\x\game.exe"]
    seen = []
    procs = _processes(game, [], game, game, [], [], [])

    def listing():
        value = procs()
        seen.append(bool(value))
        return value

    assert pw.wait_for_game(r"C:\G\x", listing, sleep=lambda s: None, start_timeout=60, poll=1)
    assert seen.count(True) == 3


def test_wait_for_game_gives_up_if_it_never_starts():
    ran = pw.wait_for_game(r"C:\G\x", lambda: [], sleep=lambda s: None, start_timeout=5, poll=1)
    assert ran is False


def test_list_process_paths_sees_this_python():
    import os
    import sys
    paths = [os.path.normcase(p) for p in pw.list_process_paths()]
    if sys.platform == "win32":
        assert any(p.endswith(("python.exe", "pythonw.exe")) for p in paths)


# ── Amazon, itch.io, Humble ───────────────────────────────────────────────────

def _sqlite(path, script):
    import sqlite3
    db = sqlite3.connect(path)
    db.executescript(script)
    db.commit()
    db.close()


def test_amazon_lists_installed_games(tmp_path):
    folder = tmp_path / "Cave"
    folder.mkdir()
    db = tmp_path / "GameInstallInfo.sqlite"
    _sqlite(db, f"""CREATE TABLE DbSet (Id TEXT, InstallDirectory TEXT, ProductTitle TEXT, Installed INTEGER);
        INSERT INTO DbSet VALUES ('abc', '{folder}', 'Cave Game', 1);
        INSERT INTO DbSet VALUES ('def', '{folder}', 'Not Installed', 0);
        INSERT INTO DbSet VALUES ('ghi', '{tmp_path / "gone"}', 'Gone', 1);""")
    games = gs.scan_amazon(str(db))
    assert [(g.id, g.name, g.launch) for g in games] == [
        ("amazon:abc", "Cave Game", "amazon-games://play/abc")]
    assert gs.scan_amazon(str(tmp_path / "missing.sqlite")) == []


def test_itch_lists_installed_games_only(tmp_path):
    folder = tmp_path / "jam"
    folder.mkdir()
    (folder / "jam.exe").write_bytes(b"MZ")
    verdict = json.dumps({"basePath": str(folder), "candidates": [{"path": "jam.exe"}]})
    db = tmp_path / "butler.db"
    _sqlite(db, f"""CREATE TABLE games (id INTEGER, title TEXT, classification TEXT);
        CREATE TABLE caves (id TEXT, game_id INTEGER, verdict TEXT);
        INSERT INTO games VALUES (1, 'Jam Game', 'game');
        INSERT INTO games VALUES (2, 'A Tool', 'tool');
        INSERT INTO caves VALUES ('c1', 1, '{verdict}');
        INSERT INTO caves VALUES ('c2', 2, '{verdict}');
        INSERT INTO caves VALUES ('c3', 1, 'not json');""")
    games = gs.scan_itch(str(db))
    assert [(g.id, g.name) for g in games] == [("itch:1", "Jam Game")]
    assert games[0].launch.endswith("jam.exe")


def test_humble_lists_downloaded_games(tmp_path):
    folder = tmp_path / "humble"
    folder.mkdir()
    (folder / "run.exe").write_bytes(b"MZ")
    entry = {"machineName": "thing", "gameName": "Humble Thing", "status": "installed",
             "filePath": str(folder), "executablePath": "run.exe"}
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"game-collection-4": [
        entry, {**entry, "machineName": "other", "status": "available"}]}), encoding="utf-8")
    games = gs.scan_humble(str(config))
    assert [(g.id, g.name) for g in games] == [("humble:thing", "Humble Thing")]
    assert games[0].launch.endswith("run.exe")
    assert gs.scan_humble(str(tmp_path / "missing.json")) == []


# ── Rockstar and Battle.net, from Windows' uninstall list ─────────────────────

def test_rockstar_games_start_through_the_rockstar_launcher(tmp_path):
    client = tmp_path / "Rockstar" / "Launcher.exe"
    client.parent.mkdir()
    client.write_bytes(b"MZ")
    game_dir = tmp_path / "Open World"
    game_dir.mkdir()
    entries = {
        "Rockstar Games Launcher": {"DisplayName": "Rockstar Games Launcher",
                                    "Publisher": "Rockstar Games",
                                    "InstallLocation": str(client.parent)},
        "{a}": {"DisplayName": "Open World", "Publisher": "Rockstar Games",
                "InstallLocation": str(game_dir),
                "UninstallString": "Launcher.exe -enableFullMode uninstall=openworld"},
        "{b}": {"DisplayName": "Social Club", "Publisher": "Rockstar Games",
                "InstallLocation": str(game_dir), "UninstallString": "x.exe /S"},
    }
    games = gs.scan_rockstar(entries)
    assert [(g.id, g.name) for g in games] == [("rockstar:openworld", "Open World")]
    assert games[0].launch == str(client)
    assert games[0].args == ("-launchTitleInFolder", str(game_dir))


def test_battlenet_games_start_by_product_code(tmp_path):
    client = tmp_path / "Battle.net" / "Battle.net.exe"
    client.parent.mkdir()
    client.write_bytes(b"MZ")
    game_dir = tmp_path / "Overwatch"
    game_dir.mkdir()
    uninstall = r'"C:\ProgramData\Battle.net\Agent\Blizzard Uninstaller.exe" --lang=enUS --uid='
    entries = {
        "Battle.net": {"DisplayName": "Battle.net", "InstallLocation": str(client.parent),
                       "UninstallString": uninstall + "battle.net"},
        "Overwatch": {"DisplayName": "Overwatch", "InstallLocation": str(game_dir),
                      "UninstallString": uninstall + "prometheus"},
        "Unknown": {"DisplayName": "New Thing", "InstallLocation": str(game_dir),
                    "UninstallString": uninstall + "something_new"},
    }
    games = gs.scan_battlenet(entries)
    assert [(g.id, g.name) for g in games] == [("battlenet:prometheus", "Overwatch")]
    assert games[0].launch == str(client) and games[0].args == ("--exec=launch Pro",)


def test_launcher_based_stores_give_nothing_without_their_launcher(tmp_path):
    entries = {"{a}": {"DisplayName": "Open World", "Publisher": "Rockstar Games",
                       "InstallLocation": str(tmp_path), "UninstallString": "uninstall.exe uninstall=x"}}
    assert gs.scan_rockstar(entries) == []
    assert gs.scan_battlenet(entries) == []


def test_rockstar_leaves_out_its_own_launcher_and_social_club(tmp_path):
    client = tmp_path / "Launcher" / "Launcher.exe"
    client.parent.mkdir()
    client.write_bytes(b"MZ")
    entry = {"Publisher": "Rockstar Games", "InstallLocation": str(client.parent),
             "UninstallString": "uninstall.exe uninstall=launcher"}
    entries = {"a": {**entry, "DisplayName": "Rockstar Games Launcher"},
               "b": {**entry, "DisplayName": "Rockstar Games Social Club",
                     "UninstallString": "uninstall.exe uninstall=socialclub"}}
    assert gs.scan_rockstar(entries) == []
