#!/usr/bin/env python3
"""Builds thm_Shelf, an OPL-RA theme with the games as a row of covers.

Needs the OPL-RA-udpfs build with the CoverRow element and horizontal_list
(left/right step through the games, up/down change the device page).

The image helpers and the info screen come from make_theme.py (Trophy
Night), loaded as a library with this theme's palette and fonts swapped in.
Layout is drawn on 640x448 and written to OPL's 640x480 theme space.

Usage: make_shelf.py OUT_DIR FONTS_DIR
"""
import os
import re
import shutil
import sys
from PIL import Image, ImageDraw

OUT, FONTS = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))

# Trophy Night's helpers, as a library (its __main__ block does not run)
lib = {"__name__": "make_theme_lib", "__file__": os.path.join(HERE, "make_theme.py")}
_argv = sys.argv
sys.argv = [lib["__file__"], OUT, FONTS]
exec(compile(open(lib["__file__"], encoding="utf-8").read(), lib["__file__"], "exec"), lib)
sys.argv = _argv

THM = os.path.join(OUT, "thm_Shelf")

# Palette (mockup C)
BG = (22, 22, 22)
PANEL = (31, 31, 30)
PANEL2 = (36, 36, 34)
RING = (52, 52, 50)
TEXT = (226, 226, 222)
MUTED = (163, 163, 158)
WHITE = (242, 242, 240)
ACCENT = (95, 211, 176)
lib.update(THM=THM, BG=BG, PANEL=PANEL, PANEL2=PANEL2, RING=RING, TEXT=TEXT, MUTED=MUTED,
           WHITE=WHITE, GOLD=ACCENT)

canvas, s, finish, save, font, hexc, ty = (lib[k] for k in ("canvas", "s", "finish", "save", "font", "hexc", "ty"))
SS, W, H = lib["SS"], lib["W"], lib["H"]

# Fonts: the helpers draw badges with ChakraPetch-Bold.ttf; point that name
# at Barlow Condensed so every image uses this theme's type.
_font = lib["font"]


def shelf_font(name, px):
    return _font({"ChakraPetch-Bold.ttf": "BarlowCondensed-Bold.ttf",
                  "ChakraPetch-SemiBold.ttf": "BarlowCondensed-SemiBold.ttf",
                  "Inter-Medium.ttf": "Barlow-Medium.ttf"}.get(name, name), px)


lib["font"] = shelf_font
font = shelf_font

# ---------------------------------------------------------------- layout
CX, CY = 320, 186                 # centre of the selected cover
SEL = dict(w=136, h=192)          # selected cover (ItemCover)
NB = dict(w=96, h=136, gap=SEL["w"] // 2 + 20, spacing=14, side=3)
TITLE_Y = 306
FOOT_Y = 410


def draw_background():
    im, d = canvas(W, H, BG + (255,))
    # the shelf the covers stand on
    d.rectangle(s(0, 96, W, 288), fill=(27, 27, 26, 255))
    d.line(s(0, 288, W, 288), fill=RING + (255,), width=2 * SS)
    # frame around the selected slot (the selected game is always here)
    x0, y0 = CX - SEL["w"] // 2, CY - SEL["h"] // 2
    d.rounded_rectangle(s(x0 - 8, y0 - 8, x0 + SEL["w"] + 8, y0 + SEL["h"] + 8), radius=12 * SS,
                        outline=ACCENT + (255,), width=3 * SS)
    # shadow under the selected cover
    d.rounded_rectangle(s(x0 + 4, y0 + 10, x0 + SEL["w"] + 4, y0 + SEL["h"] + 12), radius=6 * SS,
                        fill=(8, 8, 8, 255))
    # details panel
    d.rounded_rectangle(s(28, 298, 612, 398), radius=12 * SS, fill=PANEL + (255,))
    d.line(s(336, 312, 336, 384), fill=RING + (255,), width=2 * SS)
    # footer rule
    d.line(s(28, FOOT_Y, 612, FOOT_Y), fill=RING + (255,), width=2 * SS)
    return finish(im, W, H).resize((1024, 512), Image.LANCZOS)


lib["draw_background"] = draw_background

MAIN = f"""# Shelf - an OPL-RA theme. Needs OPL-RA-udpfs with CoverRow.
use_default=0
horizontal_list=1
bg_color={hexc(BG)}
text_color={hexc(TEXT)}
ui_text_color={hexc(WHITE)}
sel_text_color={hexc(ACCENT)}
default_font=Barlow-Medium.ttf
default_font_size=16
font1=BarlowCondensed-Bold.ttf
font1_size=26
font2=BarlowCondensed-SemiBold.ttf
font2_size=22
font3=Barlow-Medium.ttf
font3_size=14

main0:
	type=Background
	default=background
	aligned=0
	scaled=0
	width=DIM_INF
	height=DIM_INF
main1:
	type=CoverRow
	x={CX}
	y={CY}
	side={NB['side']}
	cover_width={NB['w']}
	cover_height={ty(NB['h'])}
	spacing={NB['spacing']}
	gap={NB['gap']}
main2:
	type=ItemCover
	default=cover
	aligned=1
	x={CX}
	y={CY}
	width={SEL['w']}
	height={SEL['h']}
	count={2 * NB['side'] + 1}
main3:
	type=MenuText
	aligned=0
	x=36
	y=28
	font=1
	color={hexc(WHITE)}
main4:
	type=GameCountText
	aligned=0
	x=36
	y=60
	font=3
	color={hexc(MUTED)}
main5:
	type=AttributeText
	attribute=#Name
	display=2
	aligned=0
	x=44
	y={TITLE_Y}
	width=280
	height=52
	wrap=1
	font=2
	color={hexc(WHITE)}
main6:
	type=ItemText
	aligned=0
	x=44
	y=362
	font=3
	color={hexc(MUTED)}
main7:
	type=AttributeText
	attribute=#Size
	display=2
	aligned=0
	x=150
	y=362
	font=3
	color={hexc(MUTED)}
main8:
	type=AttributeImage
	attribute=#Format
	aligned=0
	x=224
	y=360
	width=44
	height=22
main9:
	type=AttributeImage
	attribute=#Media
	aligned=0
	x=274
	y=360
	width=44
	height=22
main10:
	type=AttributeText
	attribute=Description
	display=2
	aligned=0
	x=350
	y=310
	width=250
	height=66
	wrap=1
	font=3
	color={hexc(TEXT)}
main11:
	type=HintText
	aligned=0
	x=28
	y=420
	width=18
	color={hexc(MUTED)}
main12:
	type=BdmIndex
	aligned=0
	x=-130
	y=38
	width=64
	height=8
main13:
	type=LoadingIcon
	x=-44
	y=30
	width=24
	height=24
"""

# The info screen: Trophy Night's, in this palette
INFO = lib["CFG"][lib["CFG"].index("info0:"):]
for old, new in ((lib["hexc"](lib_c), hexc(c)) for lib_c, c in (((232, 236, 246), WHITE), ((143, 154, 184), MUTED))):
    INFO = INFO.replace(old, new)
CFG = MAIN + "\n" + INFO
lib["CFG"] = CFG


def build():
    if os.path.exists(THM):
        shutil.rmtree(THM)
    os.makedirs(THM)
    with open(os.path.join(THM, "conf_theme.cfg"), "w", newline="\n") as f:
        f.write(lib["to_theme_space"](CFG))
    save(draw_background(), "background.png", palette=True)
    save(lib["draw_info_overlay"](), "info.png", palette=True, colors=16)
    save(lib["ra_mark"](), "ra_mark.png")
    save(lib["default_cover"](), "cover.png")
    save(lib["default_screen"](), "screen.png")
    glyph, chip, shoulder = lib["glyph"], lib["chip"], lib["shoulder"]
    for k, c in (("cross", lib["BLUE"]), ("circle", lib["PINK"]), ("square", lib["LILAC"]), ("triangle", ACCENT),
                 ("select", MUTED), ("start", MUTED),
                 ("up", MUTED), ("down", MUTED)):
        save(glyph(k, c), f"{k}.png")
    # MenuText draws left.png/right.png beside the device name for the
    # previous/next device. With horizontal_list those are up/down.
    save(glyph("up", ACCENT), "left.png")
    save(glyph("down", ACCENT), "right.png")
    for k in ("L1", "L2", "R1", "R2"):
        save(shoulder(k, MUTED), f"{k}.png")
    dark = (48, 48, 46)
    for label, attr, fg, bg in (("ISO", "#Format", BG, TEXT), ("ZSO", "#Format", BG, ACCENT),
                                ("CSO", "#Format", BG, ACCENT), ("UL", "#Format", BG, TEXT),
                                ("HDL", "#Format", BG, TEXT), ("ELF", "#Format", BG, TEXT),
                                ("DVD", "#Media", WHITE, dark), ("CD", "#Media", WHITE, dark),
                                ("APP", "#Media", WHITE, dark)):
        save(chip(label, fg, bg), f"{label}_{attr}.png")
    for i in range(8):
        save(lib["loading"](i), f"load{i}.png")
    for name in ("Barlow-Medium.ttf", "BarlowCondensed-Bold.ttf", "BarlowCondensed-SemiBold.ttf", "Barlow-OFL.txt"):
        shutil.copy(os.path.join(FONTS, name), THM)

    # the checks Trophy Night taught us
    for name in re.findall(r"^\tdefault=(\S+)", CFG, flags=re.M):
        if not os.path.isfile(os.path.join(THM, name + ".png")):
            raise SystemExit(f"default image {name}.png is missing from the theme")
    elems = re.findall(r"^(main|info)(\d+):", CFG, flags=re.M)
    for kind in ("main", "info"):
        nums = [int(n) for k, n in elems if k == kind]
        if nums != list(range(len(nums))):
            raise SystemExit(f"{kind} elements must be numbered 0..N without gaps: {nums}")

    with open(os.path.join(THM, "README.txt"), "w", newline="\r\n") as f:
        f.write("Shelf - a theme for OPL-RA\n\n"
                "Needs the OPL-RA-udpfs build of 29 Oct 2026 or newer: it uses the CoverRow\n"
                "element and horizontal_list, which other OPL builds do not have.\n\n"
                "Controls with this theme: LEFT/RIGHT choose a game, UP/DOWN change the\n"
                "device page, L1/R1 jump a page of games.\n\n"
                "Install: copy this folder (thm_Shelf) into the THM folder of your OPL device,\n"
                "e.g. E:\\PS2\\THM\\thm_Shelf. In OPL: Settings > Display settings > Theme > Shelf,\n"
                "then save settings and restart OPL.\n\n"
                "Fonts: Barlow and Barlow Condensed, SIL Open Font License (Barlow-OFL.txt).\n")


def preview(path):
    """The main screen drawn from the same layout, with sample games."""
    k = 2
    bg = Image.open(os.path.join(THM, "background.png")).convert("RGBA").resize((W * k, H * k), Image.LANCZOS)
    d = ImageDraw.Draw(bg)
    f1, f2, f3 = font("BarlowCondensed-Bold.ttf", 26 * k), font("BarlowCondensed-SemiBold.ttf", 22 * k), font("Barlow-Medium.ttf", 14 * k)
    d.text((36 * k, 28 * k), "UDPFS Games", font=f1, fill=WHITE)
    d.text((36 * k, 60 * k), "Files found: 155", font=f3, fill=MUTED)
    tints = [(70, 60, 90), (90, 60, 55), (55, 80, 70), (60, 70, 100), (95, 85, 55), (55, 90, 95)]
    mark = Image.open(os.path.join(THM, "ra_mark.png")).convert("RGBA")
    for dirn in (-1, 1):
        for dd in range(1, NB["side"] + 1):
            x = CX + dirn * (NB["gap"] + (dd - 1) * (NB["w"] + NB["spacing"]) + NB["w"] // 2)
            shade = (0x80 - dd * (0x80 // (NB["side"] + 2))) / 0x80
            t = tints[(dd * 2 + (dirn > 0)) % len(tints)]
            c = tuple(int(v * shade) for v in t)
            box = ((x - NB["w"] // 2) * k, (CY - NB["h"] // 2) * k, (x + NB["w"] // 2) * k, (CY + NB["h"] // 2) * k)
            d.rectangle(box, fill=c)
            if (dd + dirn) % 2:
                m = mark.resize((24 * k, 24 * k))
                bg.alpha_composite(m, (box[2] - 27 * k, box[1] + 3 * k))
    x0, y0 = CX - SEL["w"] // 2, CY - SEL["h"] // 2
    d.rectangle((x0 * k, y0 * k, (x0 + SEL["w"]) * k, (y0 + SEL["h"]) * k), fill=(56, 82, 70))
    d.text(((x0 + 10) * k, (y0 + SEL["h"] - 26) * k), "[cover art]", font=f3, fill=MUTED)
    bg.alpha_composite(mark.resize((32 * k, 32 * k)), ((x0 + SEL["w"] - 36) * k, (y0 + 4) * k))
    d.text((44 * k, TITLE_Y * k), "Burnout 3: Takedown", font=f2, fill=WHITE)
    d.text((44 * k, 362 * k), "SLES_525.84", font=f3, fill=MUTED)
    d.text((150 * k, 362 * k), "3327 MiB", font=f3, fill=MUTED)
    for j, n in enumerate(("ZSO_#Format", "DVD_#Media")):
        c = Image.open(os.path.join(THM, n + ".png")).convert("RGBA").resize((44 * k, 22 * k))
        bg.alpha_composite(c, ((224 + 50 * j) * k, 360 * k))
    desc = ("Burnout 3: Takedown is a racing game which encourages aggressive driving and lets you use "
            "your vehicle to smash your way to the finish line.")
    words, lines, cur = desc.split(), [], ""
    for w_ in words:
        if d.textlength((cur + " " + w_).strip(), font=f3) > 250 * k:
            lines.append(cur)
            cur = w_
        else:
            cur = (cur + " " + w_).strip()
    lines.append(cur)
    for i, l in enumerate(lines[:4]):
        d.text((350 * k, (310 + i * 18) * k), l, font=f3, fill=TEXT)
    x = 28 * k
    for icon, label in (("start", "Menu"), ("cross", "Run"), ("square", "Info"), ("triangle", "Options"), ("select", "Refresh")):
        ic = Image.open(os.path.join(THM, f"{icon}.png")).convert("RGBA").resize((20 * k, 20 * k))
        bg.alpha_composite(ic, (x, 418 * k))
        x += 24 * k
        d.text((x, 419 * k), label, font=f3, fill=MUTED)
        x += int(d.textlength(label, font=f3)) + 18 * k
    bg.convert("RGB").save(path)


if __name__ == "__main__":
    build()
    preview(os.path.join(OUT, "preview_Shelf.png"))
    print("built", THM)
