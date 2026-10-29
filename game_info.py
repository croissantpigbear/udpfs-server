#!/usr/bin/env python3
"""
Fill in OPL's game info (CFG/<game ID>.cfg) from the PS2 OPL CFG Database.

The database (github.com/Tom-Bruise/PS2-OPL-CFG-Database, GPL-3.0, game
info from ScreenScraper.fr) has one .cfg per game ID. For every ISO, ZSO or
CSO in DVD/ and CD/ this reads the game ID from the disc's SYSTEM.CNF,
fetches that one file and adds the info lines the game's own .cfg lacks.

Only info keys are copied (Title, Genre, Release, Developer, Publisher,
Description, Players, Rating). OPL settings in the database ($Compatibility,
$VMC_..., anything starting with $) are never copied, and lines already in
your .cfg are kept unless replace=True. Every .cfg that changes is backed
up first to CFG/info-backup/<date-time>/.

Usage:
    python game_info.py E:\\PS2            fill in missing info
    python game_info.py --replace E:\\PS2  also refresh info already there
"""

import os
import re
import shutil
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DB_URL = "https://raw.githubusercontent.com/Tom-Bruise/PS2-OPL-CFG-Database/master/CFG_{lang}/{id}.cfg"
INFO_KEYS = ("Title", "Genre", "Release", "Developer", "Publisher", "Description",
             "Players", "PlayersText", "Rating", "RatingText")
SECTOR = 2048
GAME_EXTS = (".iso", ".zso", ".cso")
ID_RE = re.compile(r"^[A-Z]{4}_\d{3}\.\d{2}$")


# ---------------------------------------------------------------- disc

def _open_image(path):
    """A file-like object reading the uncompressed image."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".zso", ".cso"):
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        from compressed_iso import ZsoFileWrapper, CsoFileWrapper
        return (ZsoFileWrapper if ext == ".zso" else CsoFileWrapper)(path, 8)
    return open(path, "rb")


def _read(f, lba, length):
    f.seek(lba * SECTOR)
    return f.read(length)


def game_id(path):
    """The game ID OPL names its files by (SLUS_202.38), from BOOT2 in the
    disc's SYSTEM.CNF, or None."""
    try:
        f = _open_image(path)
    except Exception:
        return None
    try:
        pvd = _read(f, 16, SECTOR)
        if len(pvd) < 190 or pvd[1:6] != b"CD001":
            return None
        root = pvd[156:190]
        lba, size = struct.unpack("<I", root[2:6])[0], struct.unpack("<I", root[10:14])[0]
        data = _read(f, lba, min(size, 64 * SECTOR))
        pos = 0
        while pos < len(data):
            n = data[pos]
            if n == 0:
                pos = (pos // SECTOR + 1) * SECTOR  # records never cross a sector
                continue
            rec = data[pos:pos + n]
            name = rec[33:33 + rec[32]].decode("ascii", "replace").split(";")[0].upper()
            if name == "SYSTEM.CNF":
                flba, fsize = struct.unpack("<I", rec[2:6])[0], struct.unpack("<I", rec[10:14])[0]
                cnf = _read(f, flba, min(fsize, 4096)).decode("ascii", "replace")
                m = re.search(r"BOOT2?\s*=\s*cdrom0?:\\?([A-Za-z]{4}[_-]\d{3}\.\d{2})", cnf, re.I)
                if m:
                    gid = m.group(1).upper().replace("-", "_")
                    return gid if ID_RE.match(gid) else None
                return None
            pos += n
    except Exception:
        return None
    finally:
        try:
            f.close()
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- cfg

def read_cfg(path):
    """[(key, value)] in file order; blank and odd lines kept as (line, None)."""
    out = []
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except FileNotFoundError:
        return out
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out.append((k, v))
        elif line.strip():
            out.append((line, None))
    return out


def write_cfg(path, items):
    lines = [k if v is None else f"{k}={v}" for k, v in items]
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    os.replace(tmp, path)


def merge(items, info, replace=False):
    """Add (or with replace, refresh) info keys. Returns the keys changed."""
    have = {k: i for i, (k, v) in enumerate(items) if v is not None}
    changed = []
    for k in INFO_KEYS:
        if k not in info or not info[k].strip():
            continue
        if k in have:
            if replace and items[have[k]][1] != info[k]:
                items[have[k]] = (k, info[k])
                changed.append(k)
        else:
            items.append((k, info[k]))
            changed.append(k)
    return changed


def fetch(gid, lang="en", timeout=15):
    """The database's entry for gid as {key: value}, {} if it has none.
    Raises OSError when GitHub cannot be reached."""
    url = DB_URL.format(lang=lang, id=gid)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            text = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise OSError(f"HTTP {e.code}")
    except urllib.error.URLError as e:
        # Python's TLS may lack a certificate store (some Mac installs):
        # the system curl has one.
        curl = shutil.which("curl")
        if not curl:
            raise OSError(str(e.reason))
        kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
        res = __import__("subprocess").run([curl, "-fsSL", "-w", "\n%{http_code}", url],
                                           capture_output=True, **kw)
        body = res.stdout.decode("utf-8", "replace")
        if body.rstrip().endswith("404"):
            return {}
        if res.returncode != 0:
            raise OSError(res.stderr.decode("utf-8", "replace").strip() or "download failed")
        text = body.rsplit("\n", 1)[0]
    info = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith("$"):
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info


# ---------------------------------------------------------------- run

def list_games(root):
    """(folder, file name, path) of every game image in DVD/ and CD/.
    A compressed copy beside an ISO of the same name is the same game."""
    games, seen = [], set()
    for sub in ("DVD", "CD"):
        d = os.path.join(root, sub)
        try:
            names = sorted(os.listdir(d), key=str.lower)
        except OSError:
            continue
        for n in names:
            stem, ext = os.path.splitext(n)
            if ext.lower() not in GAME_EXTS:
                continue
            key = (sub, stem.lower())
            if key in seen:
                continue
            seen.add(key)
            games.append((sub, n, os.path.join(d, n)))
    return games


def backup_dir_for(root):
    return os.path.join(root, "CFG", "info-backup", time.strftime("%Y-%m-%d_%H%M%S"))


def backup(root, gid, backup_dir=None):
    """Copy CFG/<gid>.cfg into a backup folder before it changes. Returns
    the folder, or None when there was no file to save."""
    cfg = os.path.join(root, "CFG", gid + ".cfg")
    if not os.path.exists(cfg):
        return None
    backup_dir = backup_dir or backup_dir_for(root)
    os.makedirs(backup_dir, exist_ok=True)
    shutil.copy2(cfg, os.path.join(backup_dir, gid + ".cfg"))
    return backup_dir


def load_info(root, gid):
    """The game's .cfg as {key: value} (info and settings alike)."""
    return {k: v for k, v in read_cfg(os.path.join(root, "CFG", gid + ".cfg")) if v is not None}


def save_info(root, gid, values):
    """Set info keys by hand: values maps key -> text, "" removes the key.
    Other lines ($ settings and the rest) stay as they are. Returns the
    backup folder used, if any."""
    cfg = os.path.join(root, "CFG", gid + ".cfg")
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    items = read_cfg(cfg)
    have = {k: i for i, (k, v) in enumerate(items) if v is not None}
    changed = False
    for k, v in values.items():
        v = " ".join(str(v).split())  # one line: OPL reads key=value lines
        if k in have:
            if not v:
                items[have[k]] = None
                changed = True
            elif items[have[k]][1] != v:
                items[have[k]] = (k, v)
                changed = True
        elif v:
            items.append((k, v))
            changed = True
    if not changed:
        return None
    bdir = backup(root, gid)
    write_cfg(cfg, [it for it in items if it is not None])
    return bdir


def fill(root, lang="en", replace=False, progress=None, cancel=None, threads=8, games=None):
    """Fill in the info for every game under root (or the given list from
    list_games). progress(i, total, name, status) is called as each game
    finishes. Returns a summary dict."""
    games = list_games(root) if games is None else games
    cfg_dir = os.path.join(root, "CFG")
    os.makedirs(cfg_dir, exist_ok=True)
    backup_dir = backup_dir_for(root)
    summary = {"games": len(games), "updated": 0, "complete": 0, "no_entry": 0,
               "no_id": 0, "errors": 0, "backup": None}
    lock = threading.Lock()
    done = [0]

    def one(game):
        sub, name, path = game
        if cancel is not None and cancel.is_set():
            return
        gid = game_id(path)
        if gid is None:
            status, key = "no game ID on the disc", "no_id"
        else:
            try:
                info = fetch(gid, lang)
            except OSError as e:
                info, status, key = None, f"{gid}: download failed ({e})", "errors"
            if info is not None:
                if not info:
                    status, key = f"{gid}: not in the database", "no_entry"
                else:
                    cfg = os.path.join(cfg_dir, gid + ".cfg")
                    with lock:  # two images can share an ID
                        items = read_cfg(cfg)
                        changed = merge(items, info, replace)
                        if changed:
                            if os.path.exists(cfg):
                                os.makedirs(backup_dir, exist_ok=True)
                                shutil.copy2(cfg, os.path.join(backup_dir, gid + ".cfg"))
                                summary["backup"] = backup_dir
                            write_cfg(cfg, items)
                    if changed:
                        status, key = f"{gid}: added {', '.join(c for c in changed if not c.endswith('Text'))}", "updated"
                    else:
                        status, key = f"{gid}: already complete", "complete"
        with lock:
            summary[key] += 1
            done[0] += 1
            if progress:
                progress(done[0], len(games), name, status)

    with ThreadPoolExecutor(threads) as pool:
        list(pool.map(one, games))
    return summary


def main(argv):
    replace = "--replace" in argv
    lang = "fr" if "--fr" in argv else "en"
    roots = [a for a in argv if not a.startswith("--")]
    if len(roots) != 1 or not os.path.isdir(roots[0]):
        print(__doc__)
        return 2

    def prog(i, n, name, status):
        print(f"[{i}/{n}] {name}: {status}", flush=True)

    s = fill(roots[0], lang, replace, prog)
    print(f"\n{s['updated']} updated, {s['complete']} already complete, {s['no_entry']} not in the "
          f"database, {s['no_id']} without a game ID, {s['errors']} failed")
    if s["backup"]:
        print(f"previous .cfg files saved in {s['backup']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
