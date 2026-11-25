# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ui', 'ui'),
        ('core', 'core'),
        ('assets', 'assets'),
        ('games_db.json', '.'),
        ('games_catalog.json', '.'),
        ('bundled_games', 'bundled_games'),
        ('CREDITS.txt', '.'),
    ],
    hiddenimports=[
        # reportlab is imported lazily inside core/report_generator.py, so
        # PyInstaller can't auto-detect it — bundle the whole package.
        *collect_submodules('reportlab'),
        # pyserial is imported lazily inside core/device_link.py
        # (re-tare button, per-patient range limits).
        'serial',
        'serial.tools',
        'serial.tools.list_ports',
        'bcrypt',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebChannel',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Solace',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                      # a desktop app: no black window behind it
    icon='assets/solace.ico',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Solace',
)
