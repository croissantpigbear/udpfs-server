# UDPFS Server

A window for Neutrino's UDPFS server (`udpfs_server.py`), for running PS2
games from a PC or Mac with OPL-RA (the UDPFS build in `../OPL-RA-udpfs`).

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
- `opl_library.pyw`: OPL Library, the game manager: rename, edit info by
  hand, fetch info (`game_info.py`), compress (`zso_tool.py`). Started from
  UDPFS Server's "OPL Library..." button, `OPL Library.exe`, or
  `OPL Library.app` (which uses UDPFS Server.app's Python).
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

Run from source:

    python3 udpfs_gui.pyw

Or the server alone:

    python3 udpfs_server.py -d /path/to/OPL-folder     # folder mode
    python3 udpfs_server.py -b opl-disk.img            # disk image

Make the downloads (needs `curl`, `tar`, `zip`; `mingw-w64` to rebuild the
launcher):

    ./build.sh      # -> dist/UDPFS-Server-windows.zip, dist/UDPFS-Server-mac.zip
