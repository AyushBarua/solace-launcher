"""
setup_bundled_games.py
Run this once from the FlexStoreLauncher directory to download all games
into bundled_games/ so they ship pre-installed with the launcher.

Usage:
    cd E:\Solace\FlexStoreLauncher
    venv\Scripts\python.exe setup_bundled_games.py
"""
import os
import sys
import urllib.request
import zipfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLED = os.path.join(HERE, "bundled_games")

GAMES = [
    {
        "id":  "javascript_racer_v5",
        "url": "https://github.com/lrq3000/javascript-racer/archive/refs/heads/master.zip",
        "entry": "v5.game.html",
    },
    {
        "id":  "archery_game_hassanhaseen",
        "url": "https://github.com/hassanhaseen/ArcheryGame/archive/refs/heads/main.zip",
        "entry": "index.html",
    },
    {
        "id":  "tilting_maze_game",
        "url": "https://github.com/dollpriyanka/Tilting_Maze_Game/archive/refs/heads/main.zip",
        "entry": "index.html",
    },
    {
        "id":  "simon_says",
        "url": "https://github.com/th3alexdev/simonsays/archive/refs/heads/main.zip",
        "entry": "index.html",
    },
    {
        "id":  "classic_pong_game",
        "url": "https://github.com/njoshly/Classic-pong-Game/archive/refs/heads/main.zip",
        "entry": "index.html",
    },
    {
        "id":  "fruit_game",
        "url": "https://github.com/HondaPL/FruitGame/archive/refs/heads/main.zip",
        "entry": None,  # index.html is inside "3. Fruits Game (JQuery)/" subfolder — auto-detected
    },
]


def find_entry(dest_dir, hint=None):
    """Walk dest_dir and return the best HTML entry point."""
    all_html = []
    for root, dirs, files in os.walk(dest_dir):
        depth = root.replace(dest_dir, "").count(os.sep)
        for f in files:
            if f.lower().endswith(".html"):
                all_html.append((depth, os.path.join(root, f), f.lower()))
    all_html.sort(key=lambda x: x[0])

    if hint:
        for _, path, fname in all_html:
            if fname == hint.lower():
                return path
    for _, path, fname in all_html:
        if fname == "index.html":
            return path
    if all_html:
        return all_html[0][1]
    return None


def download_and_extract(game_id, url):
    dest_dir = os.path.join(BUNDLED, game_id)
    os.makedirs(dest_dir, exist_ok=True)

    # Skip if already has files
    if len(os.listdir(dest_dir)) > 0:
        print(f"  [{game_id}] already populated — skipping download")
        return dest_dir

    zip_path = os.path.join(dest_dir, "_dl.zip")
    print(f"  [{game_id}] Downloading...", end=" ", flush=True)
    urllib.request.urlretrieve(url, zip_path)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)
    os.remove(zip_path)

    # Flatten single inner folder (GitHub adds repo-branch/ wrapper)
    items = [i for i in os.listdir(dest_dir) if not i.startswith("_")]
    if len(items) == 1 and os.path.isdir(os.path.join(dest_dir, items[0])):
        inner = os.path.join(dest_dir, items[0])
        for f in os.listdir(inner):
            shutil.move(os.path.join(inner, f), dest_dir)
        os.rmdir(inner)

    print("OK")
    return dest_dir


def main():
    os.makedirs(BUNDLED, exist_ok=True)
    print(f"Bundling games into: {BUNDLED}\n")

    results = {}

    for g in GAMES:
        try:
            dest = download_and_extract(g["id"], g["url"])
            entry = find_entry(dest, g.get("entry"))
            if entry:
                # Store relative path from FlexStoreLauncher root
                rel = os.path.relpath(entry, HERE).replace("\\", "/")
                results[g["id"]] = rel
                print(f"    entry → {rel}")
            else:
                print(f"  [{g['id']}] WARNING: no HTML entry found")
        except Exception as e:
            print(f"  [{g['id']}] FAILED: {e}")

    # Print a summary to paste into games_db.json if needed
    print("\n=== Entry points (for games_db.json) ===")
    for gid, path in results.items():
        print(f'  "{gid}":  "{path}"')

    print("\nDone. Now run the launcher — all games will be pre-installed.")


if __name__ == "__main__":
    main()
