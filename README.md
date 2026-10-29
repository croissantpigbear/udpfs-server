# UDPFS Server

A window for Neutrino's UDPFS server (`udpfs_server.py`), for running PS2
games from a PC or Mac with OPL-RA (the UDPFS build in `../OPL-RA-udpfs`).

- `udpfs_server.py`, `compressed_iso/`: from
  [rickgaiser/neutrino](https://github.com/rickgaiser/neutrino) `pc/` at
  commit 7be8de2, unchanged. Academic Free License 3.0 (`LICENSE.txt`).
- `udpfs_gui.pyw`: the window (Python standard library + tkinter). Windows,
  macOS, Linux.
- `macos/app-template/`: the `UDPFS Server.app` bundle without the server
  files; `build.sh` fills it in.

Run from source:

    python3 udpfs_gui.pyw

Or the server alone:

    python3 udpfs_server.py -d /path/to/OPL-folder     # folder mode
    python3 udpfs_server.py -b opl-disk.img            # disk image

Make the downloads (needs `zip`):

    ./build.sh      # -> dist/udpfs-server.zip, dist/UDPFS-Server-mac.zip
