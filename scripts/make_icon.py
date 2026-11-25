"""
Draw the Solace app icon: the "s." of the wordmark on a rounded square.

    python scripts/make_icon.py                 writes assets/solace.ico and solace_icon.png
    python scripts/make_icon.py --sheet FILE    writes a preview of the three colourways

Needs Pillow.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FONT = os.path.join(ROOT, "assets", "fonts", "SchibstedGrotesk-Bold.ttf")
INK, WHITE, ORANGE = "#111111", "#FFFFFF", "#FF8A3D"
COLOURWAYS = {                      # background, letter, dot
    "night": (INK, WHITE, ORANGE),
    "orange": (ORANGE, WHITE, INK),
    "paper": ("#F4F1EA", INK, ORANGE),
}
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
CANVAS = 1024


def draw_icon(colourway: str = "night", size: int = CANVAS) -> Image.Image:
    background, letter, dot = COLOURWAYS[colourway]
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    pen = ImageDraw.Draw(img)
    pen.rounded_rectangle((24, 24, CANVAS - 24, CANVAS - 24), radius=230, fill=background)

    font = ImageFont.truetype(FONT, 820)
    left, top, right, bottom = pen.textbbox((0, 0), "s", font=font)
    width, height = right - left, bottom - top
    dot_size, gap = int(width * 0.38), int(width * 0.12)
    x = (CANVAS - (width + gap + dot_size)) // 2
    y = (CANVAS - height) // 2
    pen.text((x - left, y - top), "s", font=font, fill=letter)
    dot_x, base = x + width + gap, y + height
    pen.ellipse((dot_x, base - dot_size, dot_x + dot_size, base), fill=dot)
    return img.resize((size, size), Image.LANCZOS) if size != CANVAS else img


def write_icon(colourway: str = "night") -> None:
    master = draw_icon(colourway)
    master.resize((512, 512), Image.LANCZOS).save(os.path.join(ROOT, "assets", "solace_icon.png"))
    master.save(os.path.join(ROOT, "assets", "solace.ico"),
                sizes=[(s, s) for s in ICO_SIZES])


def write_sheet(path: str) -> None:
    """The three colourways large, and at taskbar size on a dark strip."""
    sheet = Image.new("RGB", (900, 420), "#D9D6CF")
    ImageDraw.Draw(sheet).rectangle((0, 300, 900, 420), fill="#1F1F1F")
    for i, name in enumerate(COLOURWAYS):
        big, small = draw_icon(name, 240), draw_icon(name, 32)
        sheet.paste(big, (30 + i * 300, 30), big)
        sheet.paste(small, (134 + i * 300, 344), small)
    sheet.save(path)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--sheet":
        write_sheet(sys.argv[2])
    else:
        write_icon(sys.argv[1] if len(sys.argv) == 2 else "night")
