"""OG image üretici — static/og-image.png oluşturur.
Çalıştır: python scripts/generate_og.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG           = (11,  15,  17)
SURFACE      = (29,  32,  35)
OUTLINE      = (60,  75,  58)
TEXT         = (224, 226, 230)
MUTED        = (186, 203, 182)
GREEN        = (0,   224, 84)
ORANGE       = (255, 128, 0)
BLUE         = (108, 205, 255)

# Font öncelik sırası — ilk bulunan kullanılır
FONT_PATHS = [
    "/System/Library/Fonts/Helvetica.ttc",           # macOS
    "/System/Library/Fonts/SFNSDisplay.ttf",         # macOS alt
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

def load(size):
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

f_title  = load(82)
f_accent = load(50)
f_sub    = load(24)
f_small  = load(13)
f_url    = load(14)

img  = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)

# ── Subtle radial glow (green center) ────────────────────────────────────
glow = Image.new("RGB", (W, H), BG)
gd   = ImageDraw.Draw(glow)
for r in range(260, 0, -1):
    alpha = int(18 * (1 - r / 260))
    c = (max(0, BG[0] + alpha), min(255, BG[1] + alpha + 6), max(0, BG[2] + alpha))
    gd.ellipse([W//2 - r, H//2 - r, W//2 + r, H//2 + r], fill=c)
img = Image.blend(img, glow, 0.6)
draw = ImageDraw.Draw(img)

# ── Film strip sol ────────────────────────────────────────────────────────
for side_x in (42, 1143):
    draw.rectangle([side_x, 0, side_x + 15, H], fill=SURFACE)
    draw.line([(side_x, 0), (side_x, H)], fill=OUTLINE, width=1)
    draw.line([(side_x + 15, 0), (side_x + 15, H)], fill=OUTLINE, width=1)
    for y in range(32, H, 38):
        draw.rounded_rectangle([side_x + 2, y, side_x + 13, y + 20], radius=2, fill=BG)

# ── Badge ─────────────────────────────────────────────────────────────────
badge = "YAPAY ZEKA DESTEKLİ"
bb = draw.textbbox((0, 0), badge, font=f_small)
bw, bh = bb[2] - bb[0] + 44, 30
bx, by = W // 2 - bw // 2, 158
draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=15, fill=SURFACE, outline=OUTLINE)
draw.text((W // 2, by + bh // 2), badge, font=f_small, fill=MUTED, anchor="mm")

# ── Title ─────────────────────────────────────────────────────────────────
draw.text((W // 2, 278), "LETTERBOXD", font=f_title, fill=TEXT, anchor="mm")

# ── AI accent ─────────────────────────────────────────────────────────────
draw.text((W // 2, 348), "· AI ·", font=f_accent, fill=GREEN, anchor="mm")

# ── Divider ───────────────────────────────────────────────────────────────
draw.line([(280, 394), (920, 394)], fill=OUTLINE, width=1)

# ── Tagline ───────────────────────────────────────────────────────────────
draw.text((W // 2, 436), "Watchlist'inden bu akşam ne izlemelisin?", font=f_sub, fill=MUTED, anchor="mm")

# ── Three dots ────────────────────────────────────────────────────────────
cx = W // 2
r  = 7
draw.ellipse([cx - 52 - r, 504 - r, cx - 52 + r, 504 + r], fill=GREEN)
draw.ellipse([cx       - r, 504 - r, cx       + r, 504 + r], fill=ORANGE)
draw.ellipse([cx + 52  - r, 504 - r, cx + 52  + r, 504 + r], fill=BLUE)

# ── URL ───────────────────────────────────────────────────────────────────
draw.text((W // 2, 566), "movie-box-jo3x.onrender.com", font=f_url, fill=OUTLINE, anchor="mm")

out = Path(__file__).parent.parent / "static" / "og-image.png"
img.save(out, "PNG", optimize=True)
print(f"✓ Kaydedildi: {out}  ({out.stat().st_size // 1024} KB)")
