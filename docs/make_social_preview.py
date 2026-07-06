#!/usr/bin/env python3
"""Generate the GitHub social-preview card (docs/social-preview.png).

This is the image GitHub embeds when the repo URL is shared on Reddit, Hacker
News, X, Slack, etc. Upload the result via the repo's
Settings -> General -> Social preview (there is no API for it).

Inputs (in this directory):  app_icon.png, screenshot.png
Output:                       social-preview.png  (1280x640, GitHub's spec)

Requires Pillow:  pip install Pillow   (already available in the project .venv)
Run:              python docs/make_social_preview.py

Tweak the CONFIG block below to change wording, colours, or layout.
"""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# --------------------------------------------------------------------------
# CONFIG -- edit these to restyle the card
# --------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
ICON_PATH = HERE / "app_icon.png"
SHOT_PATH = HERE / "screenshot.png"
OUT_PATH = HERE / "social-preview.png"

W, H = 1280, 640  # GitHub social preview spec (2:1)

# Brand palette (sampled from the app icon)
BG_TOP = (18, 24, 38)      # top of background gradient (navy)
BG_BOT = (9, 12, 22)       # bottom of background gradient (darker navy)
ACCENT = (70, 99, 235)     # royal blue -- payoff line, links
WHITE = (245, 247, 251)
MUTE = (158, 168, 190)     # secondary text
CHIP_BG = (30, 38, 58)
CHIP_LINE = (52, 64, 92)

# macOS system fonts (Arial ships on every Mac)
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"

LEFT = 72  # left text margin

WORDMARK = "Learn To Play It"          # title case to match learntoplayit.com
DOMAIN = "learntoplayit.com"
# Headline = the app's full tagline; last line is drawn in ACCENT.
HEADLINE = [
    ("Isolate any instrument.", WHITE),
    ("Slow it down.", WHITE),
    ("Learn to play it.", ACCENT),
]
FEATURES = "stem separation · beat detection · pitch-shift · intelligent looping"
CHIPS = ["Free", "Open source", "macOS", "Apple Silicon"]

# Screenshot frame (top-right)
SHOT_W = 520
SHOT_MARGIN_RIGHT = 66
SHOT_TOP = 74
CORNER_RADIUS = 16


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _gradient_background() -> Image.Image:
    """Vertical navy gradient with a soft blue glow in the top-left."""
    column = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / H
        column.putpixel(
            (0, y),
            tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3)),
        )
    bg = column.resize((W, H))

    glow = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse([-200, -260, 380, 320], fill=(30, 45, 110))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    return ImageChops.add(bg, glow).convert("RGBA")


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, *img.size], radius=radius, fill=255)
    img.putalpha(mask)
    return img


def _paste_screenshot(bg: Image.Image) -> None:
    """Screenshot in a rounded, shadowed window frame, pinned top-right."""
    shot = Image.open(SHOT_PATH).convert("RGB")
    h = int(shot.height * SHOT_W / shot.width)
    shot = shot.resize((SHOT_W, h), Image.LANCZOS)
    x = W - SHOT_W - SHOT_MARGIN_RIGHT
    y = SHOT_TOP

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [x, y + 14, x + SHOT_W, y + h + 14], radius=CORNER_RADIUS, fill=(0, 0, 0, 150)
    )
    bg.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(28)))

    ImageDraw.Draw(bg).rounded_rectangle(
        [x - 1, y - 1, x + SHOT_W + 1, y + h + 1],
        radius=CORNER_RADIUS + 1,
        outline=(60, 72, 104),
        width=2,
    )
    frame = _rounded(shot.convert("RGBA"), CORNER_RADIUS)
    bg.alpha_composite(frame, (x, y))


def _chip(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font) -> int:
    w = draw.textlength(text, font=font)
    pad, height = 17, 42
    draw.rounded_rectangle(
        [x, y, x + w + pad * 2, y + height],
        radius=21, fill=CHIP_BG, outline=CHIP_LINE, width=1,
    )
    draw.text((x + pad, y + 9), text, font=font, fill=WHITE)
    return int(x + w + pad * 2 + 13)  # next chip's x


def main() -> None:
    bg = _gradient_background()
    _paste_screenshot(bg)
    draw = ImageDraw.Draw(bg)

    # Icon + wordmark + domain (top-left)
    icon = Image.open(ICON_PATH).convert("RGBA").resize((92, 92), Image.LANCZOS)
    bg.alpha_composite(icon, (LEFT, 66))
    draw.text((LEFT + 110, 74), WORDMARK, font=_font(FONT_BOLD, 26), fill=WHITE)
    draw.text((LEFT + 110, 106), DOMAIN, font=_font(FONT_REG, 21), fill=ACCENT)

    # Headline (three-part tagline)
    title = _font(FONT_BOLD, 50)
    top, line_height = 224, 68
    for i, (text, colour) in enumerate(HEADLINE):
        draw.text((LEFT, top + i * line_height), text, font=title, fill=colour)

    # Feature line
    features_y = top + len(HEADLINE) * line_height + 18
    draw.text((LEFT, features_y), FEATURES, font=_font(FONT_REG, 28), fill=MUTE)

    # Chips
    chip_font = _font(FONT_BOLD, 22)
    x = LEFT
    for label in CHIPS:
        x = _chip(draw, x, features_y + 52, label, chip_font)

    bg.convert("RGB").save(OUT_PATH)
    print(f"wrote {OUT_PATH} ({W}x{H})")


if __name__ == "__main__":
    main()
