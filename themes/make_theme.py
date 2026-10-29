#!/usr/bin/env python3
"""Builds thm_TrophyNight, an OPL-RA theme, plus a preview of the game list.

Layout is in OPL's 640x448 screen coordinates. Images are drawn at 4x and
scaled down so edges stay smooth on a TV; full-screen images are stored at
1024x512 like OPL's own background, stretched back to the screen by OPL.
"""
import os
import re
import shutil
import sys
from PIL import Image, ImageDraw, ImageFont

OUT = sys.argv[1]
FONTS = sys.argv[2]
THM = os.path.join(OUT, "thm_TrophyNight")

# Palette (from the Trophy Night mockup)
BG = (13, 19, 36)
PANEL = (17, 26, 48)
PANEL2 = (20, 29, 54)
RING = (28, 39, 68)
TEXT = (199, 206, 226)
MUTED = (143, 154, 184)
WHITE = (232, 236, 246)
GOLD = (242, 179, 61)
BLUE = (127, 167, 255)
TEAL = (95, 211, 176)
PINK = (255, 143, 168)
LILAC = (231, 166, 255)
GREEN = (76, 211, 138)

SS = 4  # supersampling
W, H = 640, 448


def hexc(c):
    return "#%02X%02X%02X" % c


def font(name, px):
    return ImageFont.truetype(os.path.join(FONTS, name), px)


def canvas(w, h, fill=(0, 0, 0, 0)):
    im = Image.new("RGBA", (w * SS, h * SS), fill)
    return im, ImageDraw.Draw(im)


def s(*v):
    return [int(round(x * SS)) for x in v]


def finish(im, w, h):
    return im.resize((w, h), Image.LANCZOS)


# OPL refuses a texture over 720*512*4 bytes (textures.c, maxSize), and
# the GS has 4 MB in all. A full-screen 1024x512 image must therefore be
# paletted, as OPL's own background is: 8 bits a pixel, 512 KB.
MAX_TEX = 720 * 512 * 4


def save(im, name, palette=False, colors=256):
    opts = {}
    if palette:
        if colors <= 16:
            opts["bits"] = 4  # 4-bit texture (T4): half the memory of 8-bit
        if im.mode == "RGBA" and im.getextrema()[3][0] < 255:
            im = im.quantize(colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        else:
            im = im.convert("RGB").quantize(colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
    bpp = {"P": 0.5 if opts.get("bits") == 4 else 1, "RGB": 3, "RGBA": 4}.get(im.mode, 4)
    if im.size[0] * im.size[1] * bpp > MAX_TEX or max(im.size) > 1024:
        raise SystemExit(f"{name}: {im.size} {im.mode} is too big for OPL")
    im.save(os.path.join(THM, name), optimize=True, **opts)


# ---------------------------------------------------------------- layout
LIST = dict(x=40, y=92, w=244, rows=16)           # ItemsList, 19 px rows
COVER = dict(x=324, y=88, w=118, h=166)           # ItemCover
SIDE_X = 456                                      # text column next to cover
CARD = (324, 276, 612, 392)                       # RetroAchievements card
FOOT_Y = 410


def draw_background(info=False):
    im, d = canvas(W, H, BG + (255,))
    # Rings top right (wide strokes: thin lines shimmer on interlaced TVs)
    for r in (300, 220):
        cx, cy = 600, -40
        d.ellipse(s(cx - r, cy - r, cx + r, cy + r), outline=RING + (255,), width=2 * SS)
    # Header icon tile
    d.rounded_rectangle(s(28, 22, 60, 54), radius=8 * SS, fill=(23, 33, 61, 255))
    d.rounded_rectangle(s(36, 30, 52, 42), radius=2 * SS, outline=GOLD + (255,), width=2 * SS)
    d.line(s(40, 47, 48, 47), fill=GOLD + (255,), width=2 * SS)
    d.line(s(44, 42, 44, 47), fill=GOLD + (255,), width=2 * SS)
    if not info:
        # Game list panel
        d.rounded_rectangle(s(28, 80, 304, 400), radius=12 * SS, fill=PANEL + (255,))
        # Cover shadow
        d.rounded_rectangle(s(COVER["x"] + 4, COVER["y"] + 8, COVER["x"] + COVER["w"] + 4, COVER["y"] + COVER["h"] + 10),
                            radius=8 * SS, fill=(6, 9, 18, 255))
        # RetroAchievements card
        d.rounded_rectangle(s(*CARD), radius=10 * SS, fill=PANEL2 + (255,))
        d.rounded_rectangle(s(CARD[0] + 14, CARD[1] + 16, CARD[0] + 38, CARD[1] + 40), radius=5 * SS, fill=GOLD + (255,))
        f = font("ChakraPetch-Bold.ttf", 11 * SS)
        d.text(s(CARD[0] + 26, CARD[1] + 28), "RA", font=f, fill=BG + (255,), anchor="mm")
        # divider between the card title and its lines
        d.line(s(CARD[0] + 14, CARD[1] + 48, CARD[2] - 14, CARD[1] + 48), fill=RING + (255,), width=2 * SS)
    # Footer rule
    d.line(s(28, FOOT_Y, 612, FOOT_Y), fill=RING + (255,), width=2 * SS)
    return finish(im, W, H).resize((1024, 512), Image.LANCZOS)


def draw_info_overlay():
    im, d = canvas(W, H)
    d.rounded_rectangle(s(28, 76, 612, 228), radius=12 * SS, fill=PANEL + (255,))
    # divider: details on the left, description on the right
    d.line(s(286, 90, 286, 214), fill=RING + (255,), width=2 * SS)
    d.rounded_rectangle(s(28, 240, 312, 400), radius=12 * SS, fill=PANEL2 + (255,))
    d.rounded_rectangle(s(328, 240, 612, 400), radius=12 * SS, fill=PANEL2 + (255,))
    return finish(im, W, H).resize((1024, 512), Image.LANCZOS)


def glyph(kind, color, size=32):
    im, d = canvas(size, size)
    c = color + (255,)
    w = 3 * SS
    if kind == "cross":
        d.line(s(9, 9, 23, 23), fill=c, width=w)
        d.line(s(23, 9, 9, 23), fill=c, width=w)
    elif kind == "circle":
        d.ellipse(s(7, 7, 25, 25), outline=c, width=w)
    elif kind == "square":
        d.rectangle(s(8, 8, 24, 24), outline=c, width=w)
    elif kind == "triangle":
        d.polygon(s(16, 6, 26, 24, 6, 24), outline=c, width=w)
    elif kind in ("select", "start"):
        d.rounded_rectangle(s(3, 9, 29, 23), radius=7 * SS, outline=c, width=2 * SS)
        f = font("ChakraPetch-Bold.ttf", 8 * SS)
        d.text(s(16, 16), "SEL" if kind == "select" else "STA", font=f, fill=c, anchor="mm")
    elif kind == "left":
        d.line(s(20, 6, 10, 16, 20, 26), fill=c, width=w, joint="curve")
    elif kind == "right":
        d.line(s(12, 6, 22, 16, 12, 26), fill=c, width=w, joint="curve")
    elif kind == "up":
        d.line(s(6, 20, 16, 10, 26, 20), fill=c, width=w, joint="curve")
    elif kind == "down":
        d.line(s(6, 12, 16, 22, 26, 12), fill=c, width=w, joint="curve")
    return finish(im, size, size)


def shoulder(label, color):
    im, d = canvas(32, 32)
    d.rounded_rectangle(s(2, 9, 30, 23), radius=4 * SS, outline=color + (255,), width=2 * SS)
    f = font("ChakraPetch-Bold.ttf", 10 * SS)
    d.text(s(16, 16), label, font=f, fill=color + (255,), anchor="mm")
    return finish(im, 32, 32)


def chip(label, fg, bg):
    im, d = canvas(64, 32)
    d.rounded_rectangle(s(2, 4, 62, 28), radius=7 * SS, fill=bg + (255,))
    f = font("ChakraPetch-Bold.ttf", 15 * SS)
    d.text(s(32, 16), label, font=f, fill=fg + (255,), anchor="mm")
    return finish(im, 64, 32)


def ra_mark():
    im, d = canvas(64, 64)
    d.rounded_rectangle(s(2, 2, 62, 62), radius=14 * SS, fill=GOLD + (255,))
    f = font("ChakraPetch-Bold.ttf", 30 * SS)
    d.text(s(32, 33), "RA", font=f, fill=BG + (255,), anchor="mm")
    return finish(im, 64, 64)


def default_cover():
    im, d = canvas(140, 200, (36, 49, 84, 255))
    d.rectangle(s(0, 0, 140, 200), outline=(52, 68, 110, 255), width=3 * SS)
    f = font("ChakraPetch-Bold.ttf", 16 * SS)
    d.text(s(70, 100), "NO COVER", font=f, fill=MUTED + (255,), anchor="mm")
    return finish(im, 140, 200)


def default_screen():
    im, d = canvas(256, 136, (24, 34, 62, 255))
    f = font("ChakraPetch-Bold.ttf", 14 * SS)
    d.text(s(128, 68), "NO SCREENSHOT", font=f, fill=MUTED + (255,), anchor="mm")
    return finish(im, 256, 136).convert("RGB")


def loading(frame):
    im, d = canvas(32, 32)
    for i in range(8):
        a = (i - frame) % 8
        col = GOLD if a == 0 else ((90, 104, 140) if a < 3 else (40, 52, 84))
        import math
        ang = i * math.pi / 4
        x, y = 16 + 10 * math.cos(ang), 16 + 10 * math.sin(ang)
        d.ellipse(s(x - 3, y - 3, x + 3, y + 3), fill=col + (255,))
    return finish(im, 32, 32)


CFG = f"""# Trophy Night - an OPL-RA theme. 640x448 layout.
# Fonts: Inter (SIL OFL, rsms/inter), Chakra Petch (SIL OFL, Cadson Demak).
use_default=0
bg_color={hexc(BG)}
text_color={hexc(TEXT)}
ui_text_color={hexc(WHITE)}
sel_text_color={hexc(GOLD)}
default_font=Inter-Medium.ttf
default_font_size=16
font1=ChakraPetch-Bold.ttf
font1_size=22
font2=ChakraPetch-SemiBold.ttf
font2_size=19
font3=Inter-Medium.ttf
font3_size=13

main0:
	type=Background
	default=background
	aligned=0
	scaled=0
	width=DIM_INF
	height=DIM_INF
main1:
	type=ItemsList
	x={LIST['x']}
	y={LIST['y']}
	width={LIST['w']}
	height={LIST['rows'] * 19}
main2:
	type=MenuText
	aligned=0
	x=72
	y=24
	font=1
	color={hexc(WHITE)}
main3:
	type=GameCountText
	aligned=0
	x=72
	y=50
	font=3
	color={hexc(MUTED)}
main4:
	type=ItemCover
	default=cover
	aligned=0
	x={COVER['x']}
	y={COVER['y']}
	width={COVER['w']}
	height={COVER['h']}
main5:
	type=AttributeText
	attribute=#Name
	display=2
	aligned=0
	x={SIDE_X}
	y=88
	width={612 - SIDE_X}
	height=66
	wrap=1
	font=2
	color={hexc(WHITE)}
main6:
	type=ItemText
	aligned=0
	x={SIDE_X}
	y=164
	font=3
	color={hexc(MUTED)}
main7:
	type=AttributeText
	attribute=#Size
	display=2
	aligned=0
	x={SIDE_X}
	y=184
	font=3
	color={hexc(MUTED)}
main8:
	type=AttributeImage
	attribute=#Format
	aligned=0
	x={SIDE_X}
	y=210
	width=48
	height=24
main9:
	type=AttributeImage
	attribute=#Media
	aligned=0
	x={SIDE_X + 54}
	y=210
	width=48
	height=24
main10:
	type=StaticText
	value=RetroAchievements
	aligned=0
	x={CARD[0] + 46}
	y={CARD[1] + 18}
	font=2
	color={hexc(WHITE)}
main11:
	type=StaticText
	value=RA mark on a cover: game is tracked
	aligned=0
	x={CARD[0] + 14}
	y={CARD[1] + 60}
	font=3
	color={hexc(TEXT)}
main12:
	type=StaticText
	value=Triangle > RA: check game support
	aligned=0
	x={CARD[0] + 14}
	y={CARD[1] + 80}
	font=3
	color={hexc(MUTED)}
main13:
	type=HintText
	aligned=0
	x=28
	y=420
	width=18
	color={hexc(MUTED)}
main14:
	type=BdmIndex
	aligned=0
	x=-130
	y=34
	width=64
	height=8
main15:
	type=LoadingIcon
	x=-44
	y=26
	width=24
	height=24

info0:
	type=Background
info1:
	type=StaticImage
	default=info
	aligned=0
	scaled=0
	width=DIM_INF
	height=DIM_INF
info2:
	type=AttributeText
	attribute=#LongName
	display=2
	aligned=0
	x=44
	y=22
	width=560
	height=50
	wrap=1
	font=2
	color={hexc(WHITE)}
info3:
	type=AttributeText
	attribute=Genre
	display=1
	aligned=0
	x=44
	y=142
	font=3
info4:
	type=AttributeText
	attribute=Release
	display=1
	aligned=0
	x=44
	y=160
	font=3
info5:
	type=AttributeText
	attribute=Developer
	display=1
	aligned=0
	x=44
	y=178
	font=3
info6:
	type=AttributeText
	attribute=#Size
	display=0
	aligned=0
	x=44
	y=90
	font=3
info7:
	type=AttributeText
	attribute=Description
	display=2
	aligned=0
	x=300
	y=90
	width=296
	height=128
	wrap=1
	font=3
info8:
	type=AttributeImage
	attribute=#Media
	aligned=0
	x=44
	y=112
	width=48
	height=24
info9:
	type=AttributeImage
	attribute=#Format
	aligned=0
	x=98
	y=112
	width=48
	height=24
info10:
	type=GameImage
	pattern=SCR
	default=screen
	aligned=0
	x=40
	y=252
	width=260
	height=136
info11:
	type=GameImage
	pattern=SCR2
	default=screen
	aligned=0
	x=340
	y=252
	width=260
	height=136
info12:
	type=InfoHintText
	aligned=0
	x=28
	y=420
	width=18
	color={hexc(MUTED)}
info13:
	type=AttributeText
	attribute=PlayersText
	title=Players
	display=1
	aligned=0
	x=44
	y=196
	font=3
"""


# OPL places theme elements on a virtual 640x480 screen (rmGetScreenExtents)
# and scales that to the TV: 448 lines on NTSC, 512 on PAL. The background
# is stretched to the whole screen either way. The layout here is drawn on
# 640x448, so every y and height is converted to the 480-line space when
# the config is written; x is the same in both.
THEME_H = 480


def ty(v):
    return int(round(v * THEME_H / H))


def to_theme_space(cfg):
    def fix(m):
        key, val = m.group(1), m.group(2)
        if val in ("DIM_INF", "POS_MID"):
            return m.group(0)
        return f"\t{key}={ty(int(val))}"
    return re.sub(r"^\t(y|height)=(-?\d+|DIM_INF|POS_MID)$", fix, cfg, flags=re.M)


def build():
    if os.path.exists(THM):
        shutil.rmtree(THM)
    os.makedirs(THM)
    with open(os.path.join(THM, "conf_theme.cfg"), "w", newline="\n") as f:
        f.write(to_theme_space(CFG))
    save(draw_background(), "background.png", palette=True)
    save(draw_info_overlay(), "info.png", palette=True, colors=16)
    save(ra_mark(), "ra_mark.png")
    save(default_cover(), "cover.png")
    save(default_screen(), "screen.png")
    for k, c in (("cross", BLUE), ("circle", PINK), ("square", LILAC), ("triangle", TEAL),
                 ("select", MUTED), ("start", MUTED), ("left", GOLD), ("right", GOLD),
                 ("up", MUTED), ("down", MUTED)):
        save(glyph(k, c), f"{k}.png")
    for k in ("L1", "L2", "R1", "R2"):
        save(shoulder(k, MUTED), f"{k}.png")
    # A theme's attribute images are looked up as <value>_<attribute>.png
    # (themes.c, drawAttributeImage), e.g. ZSO_#Format.png, DVD_#Media.png.
    for label, attr, fg, bg in (("ISO", "#Format", BG, TEXT), ("ZSO", "#Format", BG, GOLD), ("CSO", "#Format", BG, GOLD),
                                ("UL", "#Format", BG, TEXT), ("HDL", "#Format", BG, TEXT),
                                ("ELF", "#Format", BG, TEXT), ("DVD", "#Media", WHITE, (36, 48, 79)),
                                ("CD", "#Media", WHITE, (36, 48, 79)), ("APP", "#Media", WHITE, (36, 48, 79))):
        save(chip(label, fg, bg), f"{label}_{attr}.png")
    for i in range(8):
        save(loading(i), f"load{i}.png")
    for name in ("Inter-Medium.ttf", "ChakraPetch-Bold.ttf", "ChakraPetch-SemiBold.ttf",
                 "Inter-LICENSE.txt", "ChakraPetch-OFL.txt"):
        shutil.copy(os.path.join(FONTS, name), THM)
    # OPL keeps an image slot for a default it cannot load and then draws
    # from it: the screen goes black. Every default= must be a file here.
    for name in re.findall(r"^\tdefault=(\S+)", CFG, flags=re.M):
        if not os.path.isfile(os.path.join(THM, name + ".png")):
            raise SystemExit(f"default image {name}.png is missing from the theme")
    elems = re.findall(r"^(main|info)(\d+):", CFG, flags=re.M)
    for kind in ("main", "info"):
        nums = [int(n) for k, n in elems if k == kind]
        if nums != list(range(len(nums))):
            raise SystemExit(f"{kind} elements must be numbered 0..N without gaps: {nums}")
    with open(os.path.join(THM, "README.txt"), "w", newline="\r\n") as f:
        f.write("Trophy Night - a theme for OPL-RA\n\n"
                "Install: copy this folder (thm_TrophyNight) into the THM folder of your OPL\n"
                "device, e.g. E:\\PS2\\THM\\thm_TrophyNight. In OPL: Settings > Display settings\n"
                "> Theme > TrophyNight, then save settings.\n\n"
                "Tip: Display settings > RA mark in game list > Suffix keeps the list A-Z.\n\n"
                "Needs the OPL-RA-udpfs build of 29 Oct 2026 or newer. Older OPL builds\n"
                "have a bug in the 'Files found' counter (GameCountText) that makes a\n"
                "game launch hang at 'Loading config' with this theme.\n\n"
                "Fonts: Inter and Chakra Petch, both under the SIL Open Font License\n"
                "(Inter-LICENSE.txt, ChakraPetch-OFL.txt).\n")


def preview(path):
    """What the game list looks like, drawn from the same layout (sample data)."""
    bg = Image.open(os.path.join(THM, "background.png")).convert("RGBA").resize((W * 2, H * 2), Image.LANCZOS)
    d = ImageDraw.Draw(bg)
    k = 2
    fi = font("Inter-Medium.ttf", 16 * k)
    f1 = font("ChakraPetch-Bold.ttf", 22 * k)
    f2 = font("ChakraPetch-SemiBold.ttf", 19 * k)
    f3 = font("Inter-Medium.ttf", 13 * k)
    d.text((72 * k, 24 * k), "UDPFS Games", font=f1, fill=WHITE)
    d.text((72 * k, 50 * k), "Files found: 1243", font=f3, fill=MUTED)
    games = ["Ace Combat 04 [RA]", "Burnout 3: Takedown [RA]", "007 - Nightfire [RA]", "Gran Turismo 4",
             "Jak and Daxter [RA]", "Kingdom Hearts [RA]", "Okami", "Ratchet & Clank [RA]",
             "Rayman 2: Revolution [RA]", "Shadow of the Colossus [RA]", "Silent Hill 2", "SSX 3 [RA]",
             "Tekken 5 [RA]", "Timesplitters 2", "Tony Hawk's Pro Skater 4", "Zone of the Enders"]
    rows = ty(LIST["rows"] * 19) // 19
    for i, g in enumerate((games + ["Aeon Flux", "Agent Hugo"])[:rows]):
        d.text((LIST["x"] * k, (LIST["y"] + 19 * i * H / THEME_H) * k), g, font=fi, fill=GOLD if i == 2 else TEXT)
    cx, cy = COVER["x"] * k, COVER["y"] * k
    d.rounded_rectangle((cx, cy, cx + COVER["w"] * k, cy + COVER["h"] * k), radius=6 * k, fill=(43, 58, 98))
    d.text((cx + 12 * k, cy + COVER["h"] * k - 30 * k), "[cover art]", font=f3, fill=MUTED)
    m = Image.open(os.path.join(THM, "ra_mark.png")).resize((26 * k, 26 * k), Image.LANCZOS)
    bg.alpha_composite(m, (cx + (COVER["w"] - 30) * k, cy + 4 * k))
    d.text((SIDE_X * k, 88 * k), "007 - Nightfire", font=f2, fill=WHITE)
    d.text((SIDE_X * k, 164 * k), "SLUS_205.79", font=f3, fill=MUTED)
    d.text((SIDE_X * k, 184 * k), "2324 MiB", font=f3, fill=MUTED)
    for j, n in enumerate(("ZSO", "DVD")):
        c = Image.open(os.path.join(THM, f"{n}_{'#Format' if n == 'ZSO' else '#Media'}.png")).resize((48 * k, 24 * k), Image.LANCZOS)
        bg.alpha_composite(c, ((SIDE_X + 54 * j) * k, 210 * k))
    d.text(((CARD[0] + 46) * k, (CARD[1] + 18) * k), "RetroAchievements", font=f2, fill=WHITE)
    d.text(((CARD[0] + 14) * k, (CARD[1] + 60) * k), "RA mark on a cover: game is tracked", font=f3, fill=TEXT)
    d.text(((CARD[0] + 14) * k, (CARD[1] + 80) * k), "Triangle > RA: check game support", font=f3, fill=MUTED)
    x = 28 * k
    for icon, label in (("cross", "Start"), ("triangle", "Game menu"), ("circle", "Back"), ("square", "Info"), ("select", "Settings")):
        ic = Image.open(os.path.join(THM, f"{icon}.png")).resize((20 * k, 20 * k), Image.LANCZOS)
        bg.alpha_composite(ic, (x, 418 * k))
        x += 24 * k
        d.text((x, 420 * k), label, font=f3, fill=MUTED)
        x += int(d.textlength(label, font=f3)) + 18 * k
    bg.convert("RGB").save(path)


if __name__ == "__main__":
    build()
    preview(os.path.join(OUT, "preview_TrophyNight.png"))
    print("built", THM)
