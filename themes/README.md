# OPL themes

Scripts that build the two themes attached to the releases (Python 3 +
Pillow). Both need the UDPFS build of OPL-RA: Shelf uses its CoverRow
element and horizontal list, Trophy Night its `#Format` and `#LongName`.

    python3 make_theme.py OUT_DIR FONTS_DIR    # -> OUT_DIR/thm_TrophyNight
    python3 make_shelf.py OUT_DIR FONTS_DIR    # -> OUT_DIR/thm_Shelf

FONTS_DIR holds Inter-Medium.ttf, ChakraPetch-Bold.ttf and
ChakraPetch-SemiBold.ttf ([Inter](https://github.com/rsms/inter) and
[Chakra Petch](https://github.com/cadsondemak/Chakra-Petch), SIL Open Font
License; the themes carry copies).

Copy a `thm_...` folder to the root of your OPL device (or the UDPFS
folder) and choose it in OPL's Display settings.
