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

Games the database lacks, and fields it leaves empty, are filled from the
libretro database (metadat/developer: psxdatacenter.com's game info, about
4,700 PS2 games), and as a last resort the title from Redump's disc list.

Redump check: redump_check() reads a whole disc image (ISO, or ZSO/CSO
decompressed) and compares its SHA-1 with Redump's list of good dumps
(libretro-database metadat/redump). The two libretro files (about 4 MB
each) are downloaded once and kept for a week.

Usage:
    python game_info.py E:\\PS2            fill in missing info
    python game_info.py --replace E:\\PS2  also refresh info already there
    python game_info.py --redump E:\\PS2   check every game against Redump
"""

import hashlib
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
LIBRETRO = "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/{}/Sony%20-%20PlayStation%202.dat"
LIBRETRO_INFO = LIBRETRO.format("developer")
LIBRETRO_REDUMP = LIBRETRO.format("redump")
SOURCES = ("opl", "libretro", "redump")   # in the order they are asked
SOURCE_NAMES = {"opl": "PS2 OPL CFG Database", "libretro": "libretro database",
                "redump": "Redump (title only)"}
DESC_MAX = 255


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


def download(url, timeout=15):
    """The text at url, None for a 404. Raises OSError when it cannot be
    reached."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            text = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
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
            return None
        if res.returncode != 0:
            raise OSError(res.stderr.decode("utf-8", "replace").strip() or "download failed")
        text = body.rsplit("\n", 1)[0]
    return text


def fetch(gid, lang="en", timeout=15):
    """The database's entry for gid as {key: value}, {} if it has none.
    Raises OSError when GitHub cannot be reached."""
    text = download(DB_URL.format(lang=lang, id=gid), timeout)
    if text is None:
        return {}
    info = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith("$"):
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info


# ---------------------------------------------------------------- libretro

def default_cache_dir():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "UDPFS Server", "cache")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Caches", "UDPFS Server")
    return os.path.join(os.path.expanduser("~"), ".cache", "udpfs-server")


def cached_download(url, name, cache_dir=None, max_age=7 * 86400):
    """A big file kept in the cache folder and fetched again after a week.
    When GitHub cannot be reached an older copy is used; with none, OSError."""
    cache_dir = cache_dir or default_cache_dir()
    path = os.path.join(cache_dir, name)
    try:
        fresh = time.time() - os.path.getmtime(path) < max_age
    except OSError:
        fresh = False
    if not fresh:
        try:
            text = download(url, timeout=60)
            if text:
                os.makedirs(cache_dir, exist_ok=True)
                with open(path + ".tmp", "w", encoding="utf-8") as f:
                    f.write(text)
                os.replace(path + ".tmp", path)
        except OSError:
            if not os.path.exists(path):
                raise
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


_DAT_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([()])|([^\s()"]+)')
_SERIAL = re.compile(r"^([A-Z]{4})-(\d{3})(\d{2})")


def parse_dat(text):
    """clrmamepro dat -> [game dict]; each rom ( ... ) becomes a dict in
    game["roms"]."""
    games, stack, key = [], [], None
    for m in _DAT_TOKEN.finditer(text):
        q, paren, word = m.groups()
        if paren == "(":
            d = {}
            if stack:
                if key == "rom":
                    stack[-1].setdefault("roms", []).append(d)
                else:
                    stack[-1][key] = d
            elif key == "game":
                games.append(d)
            stack.append(d)
            key = None
        elif paren == ")":
            if stack:
                stack.pop()
            key = None
        elif not stack:
            key = word
        elif key is None:
            key = word
        else:
            stack[-1][key] = q if q is not None else word
            key = None
    return games


def opl_id(serial):
    """SLUS-20238GH -> SLUS_202.38, or None."""
    m = _SERIAL.match(serial or "")
    return f"{m.group(1)}_{m.group(2)}.{m.group(3)}" if m else None


def clean_title(name):
    """'Crash Bandicoot - The Wrath of Cortex (USA) (v1.00)' -> without the tags."""
    return re.sub(r"(\s*[(\[][^)\]]*[)\]])+\s*$", "", name).strip()


def short_description(text, limit=DESC_MAX):
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= limit // 2:
        return cut[:end + 1]
    cut = cut[:limit - 3]
    return cut[:cut.rfind(" ")].rstrip(",;:") + "..."


_cache = {}
_cache_lock = threading.Lock()


def libretro_info(cache_dir=None):
    """{game ID: {Title, Genre, ...}} in OPL's .cfg keys, from psxdatacenter
    via libretro."""
    with _cache_lock:
        if "info" not in _cache:
            out = {}
            for g in parse_dat(cached_download(LIBRETRO_INFO, "libretro-ps2-info.dat", cache_dir)):
                gid = opl_id(g.get("serial"))
                if not gid or gid in out:
                    continue
                info = {}
                if g.get("name"):
                    info["Title"] = clean_title(g["name"])
                for src, dst in (("genre", "Genre"), ("developer", "Developer"), ("publisher", "Publisher")):
                    if g.get(src, "").strip():
                        info[dst] = g[src].strip()
                y, mo, d = g.get("releaseyear", ""), g.get("releasemonth", ""), g.get("releaseday", "")
                if y.isdigit():
                    info["Release"] = f"{int(mo):02d}-{int(d):02d}-{y}" if mo.isdigit() and d.isdigit() else y
                if g.get("users", "").isdigit() and int(g["users"]) > 0:
                    info["Players"], info["PlayersText"] = f"players/{g['users']}", g["users"]
                if g.get("description", "").strip():
                    info["Description"] = short_description(g["description"].replace("\\'", "'"))
                out[gid] = info
            _cache["info"] = out
        return _cache["info"]


def redump_db(cache_dir=None):
    """{"by_id": {game ID: [disc]}, "by_sha1": {sha1: disc}} where a disc is
    {name, file, size, sha1, crc}."""
    with _cache_lock:
        if "redump" not in _cache:
            by_id, by_sha1 = {}, {}
            for g in parse_dat(cached_download(LIBRETRO_REDUMP, "libretro-ps2-redump.dat", cache_dir)):
                for rom in g.get("roms", []):
                    disc = {"name": g.get("name", ""), "file": rom.get("name", ""),
                            "size": int(rom.get("size", "0") or 0),
                            "sha1": rom.get("sha1", "").lower(), "crc": rom.get("crc", "").lower()}
                    if disc["sha1"]:
                        by_sha1.setdefault(disc["sha1"], disc)
                    gid = opl_id(g.get("serial") or rom.get("serial"))
                    if gid and disc not in by_id.setdefault(gid, []):
                        by_id[gid].append(disc)
            _cache["redump"] = {"by_id": by_id, "by_sha1": by_sha1}
        return _cache["redump"]


def lookup(gid, lang="en", sources=SOURCES, cache_dir=None):
    """Info for gid from each source in turn; a later source only fills the
    keys the earlier ones left out. Returns (info, [sources used]). Raises
    OSError only when no source could be reached at all."""
    info, used, errors = {}, [], []
    for src in sources:
        try:
            if src == "opl":
                got = fetch(gid, lang)
            elif src == "libretro":
                got = libretro_info(cache_dir).get(gid, {})
            elif src == "redump":
                discs = redump_db(cache_dir)["by_id"].get(gid)
                got = {"Title": clean_title(discs[0]["name"])} if discs else {}
            else:
                continue
        except OSError as e:
            errors.append(e)
            continue
        new = {k: v for k, v in got.items() if k in INFO_KEYS and v.strip() and k not in info}
        if new:
            info.update(new)
            used.append(src)
    if not info and errors and len(errors) == len(sources):
        raise errors[0]
    return info, used


# ---------------------------------------------------------------- redump

def image_size(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".zso", ".cso"):
        f = _open_image(path)
        try:
            return f.uncompressed_size
        finally:
            f.close()
    return os.path.getsize(path)


def sha1_image(path, progress=None, cancel=None, chunk=4 << 20):
    """SHA-1 of the disc image (decompressed for ZSO/CSO). progress(done,
    total) as it goes. Returns None when cancelled."""
    total = image_size(path)
    f = _open_image(path)
    h, done = hashlib.sha1(), 0
    try:
        while True:
            if cancel is not None and cancel.is_set():
                return None
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
            done += len(b)
            if progress:
                progress(done, total)
    finally:
        f.close()
    return h.hexdigest()


def redump_check(path, gid, db, progress=None, cancel=None):
    """Compare one disc image with Redump. Returns a dict:
       state   "verified" | "cd-size" | "different" | "unknown" | None (cancelled)
       text    short text for the list
       detail  a sentence
       name    Redump's name for the disc, when known"""
    size = image_size(path)
    discs = db["by_id"].get(gid, []) if gid else []
    isos = [d for d in discs if d["file"].lower().endswith(".iso")]
    bins = [d for d in discs if d["file"].lower().endswith(".bin")]
    if bins and not isos:
        # A CD game: Redump keeps the raw .bin (2352-byte sectors), an ISO
        # holds only the 2048 data bytes of each, so only the size can be
        # compared.
        for d in bins:
            if d["size"] % 2352 == 0 and d["size"] // 2352 * 2048 == size:
                return {"state": "cd-size", "text": "size matches (CD)", "name": d["name"],
                        "detail": f"Same size as Redump's \"{d['name']}\". Redump lists CD games as "
                                  ".bin files, so an ISO's checksum can't be compared; the size matches."}
        return {"state": "different", "text": "size differs (CD)", "name": bins[0]["name"] if bins else "",
                "detail": f"Redump has {gid} as a CD ({bins[0]['name']}) but this image is a different size: "
                          "possibly a bad, trimmed or patched copy."}
    sha1 = sha1_image(path, progress, cancel)
    if sha1 is None:
        return {"state": None, "text": "", "detail": "", "name": ""}
    hit = db["by_sha1"].get(sha1)
    if hit:
        return {"state": "verified", "text": "verified", "name": hit["name"], "sha1": sha1,
                "detail": f"Matches Redump: \"{hit['name']}\"."}
    if discs:
        same = [d for d in isos if d["size"] == size]
        why = ("same size, different contents: modified (patched, undubbed, translated) or damaged"
               if same else "different size: trimmed, modified or a bad dump")
        return {"state": "different", "text": "not a Redump dump", "name": discs[0]["name"], "sha1": sha1,
                "detail": f"Redump lists {gid} as \"{discs[0]['name']}\" but this image differs ({why})."}
    return {"state": "unknown", "text": "not in Redump", "name": "", "sha1": sha1,
            "detail": "Redump has no disc with this game ID or checksum (a prototype, demo, homebrew "
                      "or a modified disc)."}


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


def fill(root, lang="en", replace=False, progress=None, cancel=None, threads=8, games=None,
         sources=SOURCES, cache_dir=None):
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
                info, used = lookup(gid, lang, sources, cache_dir)
            except OSError as e:
                info, status, key = None, f"{gid}: download failed ({e})", "errors"
            if info is not None:
                if not info:
                    status, key = f"{gid}: not in any database", "no_entry"
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
                        names = ", ".join(c for c in changed if not c.endswith("Text"))
                        frm = " + ".join(SOURCE_NAMES[u].split(" (")[0] for u in used)
                        status, key = f"{gid}: added {names} (from {frm})", "updated"
                    else:
                        status, key = f"{gid}: already complete", "complete"
        with lock:
            summary[key] += 1
            done[0] += 1
            if progress:
                progress(done[0], len(games), name, status)

    for src, load in (("libretro", libretro_info), ("redump", redump_db)):
        if src in sources:
            try:
                load(cache_dir)  # once, before the threads ask
            except OSError:
                pass
    with ThreadPoolExecutor(threads) as pool:
        list(pool.map(one, games))
    return summary


def main(argv):
    if "--redump" in argv:
        roots = [a for a in argv if not a.startswith("--")]
        if len(roots) != 1 or not os.path.isdir(roots[0]):
            print(__doc__)
            return 2
        db = redump_db()
        for sub, name, path in list_games(roots[0]):
            res = redump_check(path, game_id(path), db)
            print(f"{sub}/{name}: {res['text']}. {res['detail']}", flush=True)
        return 0
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
