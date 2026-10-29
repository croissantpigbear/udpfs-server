# UDPFS Server

Run PS2 games from a folder on your PC or Mac over the network, with
RetroAchievements, using the UDPFS build of OPL-RA:
[croissantpigbear/Open-PS2-Loader](https://github.com/croissantpigbear/Open-PS2-Loader/tree/udpfs)
(branch `udpfs`).

Two apps, for Windows and macOS, with Python included (nothing to install):

- **UDPFS Server**: pick your OPL folder (DVD, CD, CFG, ART, VMC...) and
  press Start. Serves ISO, ZSO and CSO games, and runs
  [xeRAbora](https://github.com/hacan359/xerabora) for RetroAchievements
  alongside.
- **OPL Library**: rename games, edit or fetch their info for OPL's info
  screen, check them against Redump, compress ISOs to ZSO.

Downloads: see [Releases](https://github.com/croissantpigbear/udpfs-server/releases)
(the OPL ELF and two themes, Trophy Night and Shelf, are attached there too).

## Files

- `udpfs_server.py`, `compressed_iso/`: from
  [rickgaiser/neutrino](https://github.com/rickgaiser/neutrino) `pc/` at
  commit 7be8de2. Changed here: with `-c` a compressed game is listed as
  plain `Game.iso` (not `Game.zso.iso`), hidden while `Game.iso` itself
  exists, and the `ZSO\0` reader masks the stored-block flag. Academic Free License 3.0 (`LICENSE.txt`).
- `zso_tool.py`: ISO -> ZSO compressor (ZISO v1, as maxcso writes it;
  OPL and PCSX2 read it too). Used by OPL Library's Compress, or
  on its own: `python3 zso_tool.py GAME.iso`. Needs `lz4`
  (`vendor/wheels` for the bundles, `pip install lz4` otherwise).
- `game_info.py`: fills `CFG/<game ID>.cfg` with game info (Title, Genre,
  Release, Developer, Publisher, Description, Players, Rating) from the
  [PS2 OPL CFG Database](https://github.com/Tom-Bruise/PS2-OPL-CFG-Database)
  (GPL-3.0; info from ScreenScraper.fr), one file per game ID fetched from
  GitHub. Game IDs come from each disc's SYSTEM.CNF (ISO, ZSO or CSO). Only
  missing info lines are added; `$` settings are never copied; changed files
  are backed up to `CFG/info-backup/`. OPL Library's Fetch info runs it.
  What the database lacks comes from the libretro database
  ([libretro-database](https://github.com/libretro/libretro-database)
  `metadat/developer`, game info from psxdatacenter.com), then the title from
  Redump's list. `--redump` checks each image's SHA-1 against Redump's list
  of good dumps (`metadat/redump`); both files are cached for a week.
- `opl_library.pyw`: OPL Library, the game manager: rename, edit info by
  hand, fetch info (`game_info.py`), compress (`zso_tool.py`). Started from
  UDPFS Server's "OPL Library..." button, `OPL Library.exe`, or
  `OPL Library.app` (which uses UDPFS Server.app's Python).
  Click games to tick them (Shift-click ticks a range; Select all or
  Ctrl+A ticks every game shown, so it works with Find). Fetch info and
  Compress act on the ticked games, or on all of them when none are ticked.
- `udpfs_gui.pyw`: the window (Python standard library + tkinter). Windows,
  macOS, Linux. It also runs [xeRAbora](https://github.com/hacan359/xerabora)
  (found next to the app, in Downloads or on the Desktop, or fetched with
  Download): started with `--server` alongside the UDPFS server, stopped
  with its `POST /quit`, its output in the same log, its status read from
  `GET /state` on 127.0.0.1:18280-18284.
- `macos/app-template/`: the `UDPFS Server.app` bundle without Python or
  the server files; `build.sh` fills it in.
- `windows/`: `UDPFS Server.exe`, a small launcher (`launcher.c`) that starts
  the bundled `python\pythonw.exe` with `app\udpfs_gui.pyw`.
- Both downloads carry their own Python from
  [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
  (3.12, with Tk), so nothing has to be installed.

- `themes/`: the scripts that build the Trophy Night and Shelf themes.

Run from source:

    python3 udpfs_gui.pyw

Or the server alone:

    python3 udpfs_server.py -d /path/to/OPL-folder     # folder mode
    python3 udpfs_server.py -b opl-disk.img            # disk image

Make the downloads (needs `curl`, `tar`, `zip`; `mingw-w64` to rebuild the
launcher):

    ./build.sh      # -> dist/UDPFS-Server-windows.zip, dist/UDPFS-Server-mac.zip

## Credits

- [Open PS2 Loader](https://github.com/ps2homebrew/Open-PS2-Loader), and
  [hacan359's OPL-RA](https://github.com/hacan359/Open-PS2-Loader) with
  RetroAchievements, which the UDPFS build is based on.
- [Neutrino](https://github.com/rickgaiser/neutrino) by Rick Gaiser:
  UDPFS and the original `udpfs_server.py` and `compressed_iso`.
- [xeRAbora](https://github.com/hacan359/xerabora) by hacan359.
- Game info: the [PS2 OPL CFG Database](https://github.com/Tom-Bruise/PS2-OPL-CFG-Database)
  (from ScreenScraper.fr) and [libretro-database](https://github.com/libretro/libretro-database)
  (from psxdatacenter.com); disc checksums from [Redump](http://redump.org)
  via libretro-database. These are downloaded when you use them, not
  included here.
- Theme fonts: [Inter](https://github.com/rsms/inter) and
  [Chakra Petch](https://github.com/cadsondemak/Chakra-Petch) (SIL Open Font License).
- [python-build-standalone](https://github.com/astral-sh/python-build-standalone),
  [lz4](https://github.com/python-lz4/python-lz4).

Licence: Academic Free License 3.0 (`LICENSE.txt`), as OPL and Neutrino.
