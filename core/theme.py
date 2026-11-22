"""
Design tokens — two themes:
  • "dark"  : Heritage (current high-contrast dark gold)
  • "light" : Serene Play (warm light, Deep Forest Green ink, Mint accent)

Active theme is read from global_settings.json at import time.
Toggle in Settings → save → restart to apply.
"""
import os, sys, json

# ── Theme dictionaries ────────────────────────────────────────────────────────

DARK_THEME = {
    # Solace Glass, dark — warm charcoal base, the same colour haze painted
    # faintly behind translucent dark cards. Roles are inverted from the light
    # theme: PRIMARY is the off-white pill/ink, ON_PRIMARY the dark text on it.
    # The accent is a lighter orange that keeps >= 4.5:1 on the card colour.
    # 6-digit hex only (several screens append alpha digits).
    "BACKGROUND":               "#12110F",
    "SURFACE":                  "#171614",
    "SURFACE_DIM":              "#0E0D0C",
    "SURFACE_CON_LOW":          "#1F1D1A",   # card base
    "SURFACE_CON":              "#252320",
    "SURFACE_CON_HIGH":         "#2E2B27",
    "SURFACE_CON_HIGH2":        "#38352F",
    "SURFACE_BRIGHT":           "#423F39",
    "PRIMARY":                  "#F4F1EA",
    "PRIMARY_CONTAINER":        "#FF9A4D",
    "PRIMARY_FIXED":            "#FFB26B",
    "ON_PRIMARY":               "#14130F",
    "ON_SURFACE":               "#F1EEE7",
    "ON_SURFACE_VAR":           "#B9B5AB",
    "OUTLINE":                  "#8A877E",
    "OUTLINE_VARIANT":          "#3A3732",
    "ON_PRIMARY_FIXED_VARIANT": "#14130F",
    "SURFACE_VARIANT":          "#2E2B27",
    # App QSS extras
    "SCROLLBAR_BG":             "#12110F",
    "SCROLLBAR_HANDLE":         "#46423C",
}

LIGHT_THEME = {
    # Solace Glass — warm paper background with a soft colour haze behind white
    # frosted cards. Ink is near-black; the accent is a deep orange that keeps
    # >= 4.5:1 contrast on white for text. All values are 6-digit hex because
    # several screens append alpha digits (f"{TOKEN}18").
    "BACKGROUND":               "#F1EFEA",   # base paper; GlassBackground paints the haze over it
    "SURFACE":                  "#F6F4EF",
    "SURFACE_DIM":              "#ECE9E2",
    "SURFACE_CON_LOW":          "#FFFFFF",
    "SURFACE_CON":              "#FFFFFF",
    "SURFACE_CON_HIGH":         "#F7F5F0",
    "SURFACE_CON_HIGH2":        "#EFECE5",
    "SURFACE_BRIGHT":           "#FFFFFF",
    "PRIMARY":                  "#111111",   # black: buttons, active tab, round action buttons
    "PRIMARY_CONTAINER":        "#C2480A",   # deep orange accent for text and outlines
    "PRIMARY_FIXED":            "#FFB26B",   # soft orange for fills and highlights
    "ON_PRIMARY":               "#FFFFFF",
    "ON_SURFACE":               "#14130F",   # main text
    "ON_SURFACE_VAR":           "#5B5A55",   # secondary text, 6.9:1 on white
    "OUTLINE":                  "#8A8880",
    "OUTLINE_VARIANT":          "#E2DFD7",
    "ON_PRIMARY_FIXED_VARIANT": "#111111",
    "SURFACE_VARIANT":          "#ECE9E2",
    # App QSS extras
    "SCROLLBAR_BG":             "#F1EFEA",
    "SCROLLBAR_HANDLE":         "#C9C5BB",
}

# ── Shared settings path helper ──────────────────────────────────────────────

def _settings_path() -> str:
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "global_settings.json")

# ── Load active theme ─────────────────────────────────────────────────────────

def _load_active_theme() -> dict:
    try:
        with open(_settings_path(), "r") as f:
            data = json.load(f)
        return DARK_THEME if data.get("theme") == "dark" else LIGHT_THEME
    except Exception:
        return LIGHT_THEME

def _read_settings() -> dict:
    try:
        with open(_settings_path()) as f:
            return json.load(f)
    except Exception:
        return {}

def _write_settings(data: dict):
    try:
        with open(_settings_path(), "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def save_theme(theme_name: str):
    """Save theme preference to global_settings.json."""
    d = _read_settings()
    d["theme"] = theme_name
    _write_settings(d)

def get_active_theme_name() -> str:
    return _read_settings().get("theme", "light")

def save_ui_scale(scale: float):
    """Save UI scale factor (1.0 = 100%, 1.5 = 150%) to global_settings.json."""
    d = _read_settings()
    d["ui_scale"] = round(scale, 2)
    _write_settings(d)

def get_ui_scale() -> float:
    """Read UI scale factor from settings. Returns 1.0 if not set."""
    try:
        return float(_read_settings().get("ui_scale", 1.0))
    except Exception:
        return 1.0

def switch_theme_live(theme_name: str):
    """Mutate every module-level color constant to the new theme.

    Widgets that re-import from core.theme INSIDE their refresh_theme() method
    will pick up the new values automatically — no process restart needed.
    Call save_theme() separately if you also want to persist the change.
    """
    import core.theme as _m
    t = DARK_THEME if theme_name == "dark" else LIGHT_THEME
    _m.BACKGROUND               = t["BACKGROUND"]
    _m.SURFACE                  = t["SURFACE"]
    _m.SURFACE_DIM              = t["SURFACE_DIM"]
    _m.SURFACE_CON_LOW          = t["SURFACE_CON_LOW"]
    _m.SURFACE_CON              = t["SURFACE_CON"]
    _m.SURFACE_CON_HIGH         = t["SURFACE_CON_HIGH"]
    _m.SURFACE_CON_HIGH2        = t["SURFACE_CON_HIGH2"]
    _m.SURFACE_BRIGHT           = t["SURFACE_BRIGHT"]
    _m.PRIMARY                  = t["PRIMARY"]
    _m.PRIMARY_CONTAINER        = t["PRIMARY_CONTAINER"]
    _m.PRIMARY_FIXED            = t["PRIMARY_FIXED"]
    _m.ON_PRIMARY               = t["ON_PRIMARY"]
    _m.ON_SURFACE               = t["ON_SURFACE"]
    _m.ON_SURFACE_VAR           = t["ON_SURFACE_VAR"]
    _m.OUTLINE                  = t["OUTLINE"]
    _m.OUTLINE_VARIANT          = t["OUTLINE_VARIANT"]
    _m.ON_PRIMARY_FIXED_VARIANT = t["ON_PRIMARY_FIXED_VARIANT"]
    _m.SURFACE_VARIANT          = t["SURFACE_VARIANT"]
    _m.APP_QSS                  = generate_app_qss(theme_name)


def hex_rgba(hex_color: str, alpha: float) -> str:
    """Return 'rgba(r, g, b, alpha)' from a #RRGGBB hex string.

    Qt QSS 8-digit hex is AARRGGBB, NOT the CSS standard RRGGBBAA.
    Appending '1a' to a hex color gives the wrong colour at ~83% opacity.
    Always use this helper instead of f"{color}XX" for transparent fills.
    """
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


_t = _load_active_theme()

# ── Exported color tokens (used by all UI files) ──────────────────────────────
BACKGROUND               = _t["BACKGROUND"]
SURFACE                  = _t["SURFACE"]
SURFACE_DIM              = _t["SURFACE_DIM"]
SURFACE_CON_LOW          = _t["SURFACE_CON_LOW"]
SURFACE_CON              = _t["SURFACE_CON"]
SURFACE_CON_HIGH         = _t["SURFACE_CON_HIGH"]
SURFACE_CON_HIGH2        = _t["SURFACE_CON_HIGH2"]
SURFACE_BRIGHT           = _t["SURFACE_BRIGHT"]
PRIMARY                  = _t["PRIMARY"]
PRIMARY_CONTAINER        = _t["PRIMARY_CONTAINER"]
PRIMARY_FIXED            = _t["PRIMARY_FIXED"]
ON_PRIMARY               = _t["ON_PRIMARY"]
ON_SURFACE               = _t["ON_SURFACE"]
ON_SURFACE_VAR           = _t["ON_SURFACE_VAR"]
OUTLINE                  = _t["OUTLINE"]
OUTLINE_VARIANT          = _t["OUTLINE_VARIANT"]
ON_PRIMARY_FIXED_VARIANT = _t["ON_PRIMARY_FIXED_VARIANT"]
SURFACE_VARIANT          = _t["SURFACE_VARIANT"]

# ── Font Families (unchanged) ──────────────────────────────────────────────────
FONT_DISPLAY = "Schibsted Grotesk"
FONT_BODY    = "Schibsted Grotesk"
FONT_MONO    = "Schibsted Grotesk"   # no monospace face: JetBrains Mono is not used in this project

# ── Stitch Image URLs ──────────────────────────────────────────────────────────
HERO_IMAGE_URL = (
    "https://lh3.googleusercontent.com/aida-public/"
    "AB6AXuB5pQFoFj8TSV2e0afNMewApLZo6EdfudCJP2dzevRgYrdyDocKJj6UNfCvIn4Sznet"
    "IwHfACyCjo7QHQSuCi09j5x3Pkyd12tAVweKGd1a_i7T5-nYUUN6rUyqKb9LbTaU7Vacl2K-"
    "E9IaEaXSk3LhyaG0vLYoXHhG6bzi6oosB6X06gFcbDkyfD0nXEw58sUOd7sjFEhbHxLk-"
    "yymZQwl8b0d3hyGCYhvljdNh6c-OMQA-KF89qOiYLtQbMRqTqQfEJEnhjAoSgXY"
)
CARD1_IMAGE_URL = "https://images.unsplash.com/photo-1550745165-9bc0b252726f?q=80&w=600&auto=format&fit=crop"
CARD2_IMAGE_URL = "https://images.unsplash.com/photo-1506806732259-39c2d02684ce?q=80&w=600&auto=format&fit=crop"
CARD3_IMAGE_URL = "https://images.unsplash.com/photo-1611078716801-44754d92a14b?q=80&w=600&auto=format&fit=crop"
CARD4_IMAGE_URL = "https://images.unsplash.com/photo-1462331940025-496dfbfc7564?q=80&w=600&auto=format&fit=crop"

# ── App-level QSS ─────────────────────────────────────────────────────────────
def _dialog_qss(t: dict) -> str:
    """Message boxes and dialogs: card background, pill buttons."""
    return f"""
QDialog, QMessageBox {{ background: {t["SURFACE_CON_LOW"]}; }}
QMessageBox QLabel {{ color: {t["ON_SURFACE"]}; font-size: 17px; background: transparent; }}
QMessageBox QPushButton, QDialogButtonBox QPushButton {{
    background: {t["PRIMARY"]}; color: {t["ON_PRIMARY"]}; border: none;
    border-radius: 22px; min-width: 96px; min-height: 44px; padding: 0 22px;
    font-weight: bold; font-size: 16px;
}}
QMessageBox QPushButton:hover, QDialogButtonBox QPushButton:hover {{ background: #2B2A27; }}
"""


APP_QSS = f"""
* {{
    outline: none;
}}
QMainWindow {{
    background: {BACKGROUND};
}}
QWidget {{
    background-color: transparent;
    color: {ON_SURFACE};
    font-family: "{FONT_BODY}";
    font-size: 16px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: {_t["SCROLLBAR_BG"]};
    width: 4px;
    border-radius: 2px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {_t["SCROLLBAR_HANDLE"]};
    border-radius: 2px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    height: 0;
}}
{_dialog_qss(_t)}
"""


def generate_app_qss(theme_name: str) -> str:
    """Return a fresh APP_QSS string for the given theme ('dark' or 'light').
    Used by the live theme-transition animation in settings."""
    t = DARK_THEME if theme_name == "dark" else LIGHT_THEME
    return f"""
* {{ outline: none; }}
QMainWindow {{ background: {t["BACKGROUND"]}; }}
QWidget {{
    background-color: transparent;
    color: {t["ON_SURFACE"]};
    font-family: "{FONT_BODY}";
    font-size: 16px;
}}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: {t["SCROLLBAR_BG"]};
    width: 4px; border-radius: 2px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t["SCROLLBAR_HANDLE"]};
    border-radius: 2px; min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}
{_dialog_qss(t)}
"""
