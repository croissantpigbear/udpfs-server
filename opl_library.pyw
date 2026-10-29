#!/usr/bin/env python3
"""
OPL Library - manage the games in an OPL folder.

  Rename        the name OPL lists a game under (the file name)
  Edit info     title, genre, release, developer, players, rating and
                description in CFG/<game ID>.cfg, for OPL's info screen
  Fetch info    the same fields from the PS2 OPL CFG Database (game_info.py)
  Compress      ISO -> ZSO (zso_tool.py)

Game settings (memory cards, compatibility modes) are never touched; every
.cfg that changes is backed up to CFG/info-backup/ first. Renaming keeps a
game's settings, art and memory cards: OPL keys those by game ID.

Uses only the Python standard library plus lz4 for compressing. The OPL
folder defaults to the one picked in UDPFS Server.
"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import game_info  # noqa: E402

APP_TITLE = "OPL Library"
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
MUTED, GOOD, WARN, BAD = "#888888", "#2e9e44", "#c27c0e", "#d1242f"
NAME_MAX = 160                   # ISO_GAME_NAME_MAX in OPL
BAD_CHARS = '\\/:*?"<>|'
OLD_NAME = re.compile(r"^([A-Z]{4}_\d{3}\.\d{2})\.(.+)$")   # SLUS_202.38.Name.iso
INFO_FIELDS = (("Title", "Title"), ("Genre", "Genre"), ("Release", "Release date"),
               ("Developer", "Developer"), ("Publisher", "Publisher"))
DESC_MAX = 255                   # what OPL Manager and the database keep to


def settings_dir():
    if IS_WINDOWS:
        return os.environ.get("APPDATA") or HERE
    if IS_MAC:
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "UDPFS Server")
    return os.path.join(os.path.expanduser("~"), ".config")


def load_json(name):
    try:
        with open(os.path.join(settings_dir(), name), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(name, data):
    try:
        os.makedirs(settings_dir(), exist_ok=True)
        with open(os.path.join(settings_dir(), name), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024.0


class Game:
    """One game: the files that make it up (an ISO and/or compressed copy)."""

    def __init__(self, root, sub, fname):
        self.root, self.sub = root, sub
        self.stem, ext = os.path.splitext(fname)
        self.files = []          # every file of this game in its folder
        self.refresh_files()
        m = OLD_NAME.match(self.stem)
        self.prefix = m.group(1) + "." if m else ""
        self.name = m.group(2) if m else self.stem
        self.gid = None
        self.info_state = ""

    def refresh_files(self):
        d = os.path.join(self.root, self.sub)
        self.files = [f for f in os.listdir(d)
                      if os.path.splitext(f)[0].lower() == self.stem.lower()
                      and os.path.splitext(f)[1].lower() in game_info.GAME_EXTS]
        self.files.sort(key=lambda f: [".iso", ".zso", ".cso"].index(os.path.splitext(f)[1].lower()))

    @property
    def path(self):
        return os.path.join(self.root, self.sub, self.files[0])

    @property
    def iso(self):
        for f in self.files:
            if f.lower().endswith(".iso"):
                return os.path.join(self.root, self.sub, f)
        return None

    @property
    def fmt(self):
        exts = [os.path.splitext(f)[1][1:].upper() for f in self.files]
        return " + ".join(exts)

    @property
    def size(self):
        return sum(os.path.getsize(os.path.join(self.root, self.sub, f)) for f in self.files)


# --------------------------------------------------------------------------

class Library:
    def __init__(self, root, folder):
        self.root = root
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.job = None
        self.games = {}
        self.id_cache = load_json("opl_library_ids.json")

        root.title(APP_TITLE)
        root.minsize(760, 480)
        root.geometry("900x620")
        outer = ttk.Frame(root, padding=10)
        outer.pack(fill="both", expand=True)

        top = ttk.Frame(outer)
        top.pack(fill="x")
        ttk.Label(top, text="OPL folder:").pack(side="left")
        self.folder = tk.StringVar(value=folder)
        ttk.Entry(top, textvariable=self.folder).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(top, text="Browse...", command=self.browse).pack(side="left")
        ttk.Button(top, text="Reload", command=self.scan).pack(side="left", padx=(8, 0))

        flt = ttk.Frame(outer)
        flt.pack(fill="x", pady=(8, 0))
        ttk.Label(flt, text="Find:").pack(side="left")
        self.find = tk.StringVar()
        self.find.trace_add("write", lambda *_: self.fill_tree())
        ttk.Entry(flt, textvariable=self.find, width=30).pack(side="left", padx=8)
        self.count = ttk.Label(flt, text="", foreground=MUTED)
        self.count.pack(side="left")

        box = ttk.Frame(outer)
        box.pack(fill="both", expand=True, pady=(8, 0))
        cols = ("id", "folder", "fmt", "size", "info")
        self.tree = ttk.Treeview(box, columns=cols, selectmode="extended")
        for c, t, w, a in (("#0", "Name (as OPL lists it)", 330, "w"), ("id", "Game ID", 100, "w"),
                           ("folder", "Folder", 60, "center"), ("fmt", "Format", 80, "center"),
                           ("size", "Size", 80, "e"), ("info", "Info", 140, "w")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=a)
        sb = ttk.Scrollbar(box, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.edit_info())
        self.tree.bind("<F2>", lambda e: self.rename())

        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(8, 0))
        self.btns = []
        for text, cmd in (("Rename...", self.rename), ("Edit info...", self.edit_info)):
            b = ttk.Button(bar, text=text, command=cmd)
            b.pack(side="left", padx=(0, 8))
            self.btns.append(b)
        for text, cmd in (("Compress...", self.compress), ("Fetch info...", self.fetch_info)):
            b = ttk.Button(bar, text=text, command=cmd)
            b.pack(side="right", padx=(8, 0))
            self.btns.append(b)
        self.stop_btn = ttk.Button(bar, text="Stop", command=self.cancel.set, state="disabled")
        self.stop_btn.pack(side="right", padx=(8, 0))

        self.progress = ttk.Progressbar(outer, maximum=1000)
        self.progress.pack(fill="x", pady=(8, 0))
        self.status = ttk.Label(outer, text="", foreground=MUTED, wraplength=860, justify="left")
        self.status.pack(fill="x", pady=(4, 0))

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.pump)
        if folder:
            root.after(200, self.scan)

    # ---- folder and list ----

    def browse(self):
        p = filedialog.askdirectory(title="Your OPL folder (with DVD, CD, CFG, ART)",
                                    initialdir=self.folder.get() or None)
        if p:
            self.folder.set(os.path.normpath(p))
            self.scan()

    def scan(self):
        root = self.folder.get().strip()
        if not os.path.isdir(root):
            self.say("Pick your OPL folder.", WARN)
            return
        self.games = {}
        for sub, fname, _ in game_info.list_games(root):
            g = Game(root, sub, fname)
            self.games[f"{sub}/{g.stem}"] = g
        s = load_json("opl_library.json")
        s["folder"] = root
        save_json("opl_library.json", s)
        self.fill_tree()
        # Game IDs: from the cache when the file is unchanged, else from
        # the disc, in the background (it reads a few sectors per game).
        todo = []
        for key, g in self.games.items():
            st = os.stat(g.path)
            c = self.id_cache.get(g.path)
            if c and c[0] == st.st_size and c[1] == int(st.st_mtime):
                g.gid = c[2]
            else:
                todo.append(key)
        self.refresh_info_states()
        if todo:
            self.run_job(self._read_ids, todo, label="Reading game IDs")

    def _read_ids(self, keys):
        for i, key in enumerate(keys):
            if self.cancel.is_set():
                break
            g = self.games.get(key)
            if g is None:
                continue
            g.gid = game_info.game_id(g.path)
            st = os.stat(g.path)
            self.id_cache[g.path] = [st.st_size, int(st.st_mtime), g.gid]
            self.q.put(("progress", (i + 1) / len(keys), f"Reading game IDs: {g.name}"))
            self.q.put(("row", key))
        save_json("opl_library_ids.json", self.id_cache)
        self.q.put(("refresh_info",))
        return f"{len(self.games)} games."

    def refresh_info_states(self):
        root = self.folder.get().strip()
        for g in self.games.values():
            if not g.gid:
                g.info_state = "no game ID" if g.gid is None and g.path in self.id_cache else ""
                continue
            info = game_info.load_info(root, g.gid)
            have = [k for k in ("Genre", "Developer", "Release", "Description") if info.get(k)]
            g.info_state = "complete" if len(have) == 4 else (f"{len(have)} of 4 fields" if have else "none")
        for key in self.games:
            self.update_row(key)

    def fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        q = self.find.get().strip().lower()
        shown = 0
        for key in sorted(self.games, key=lambda k: self.games[k].name.lower()):
            g = self.games[key]
            if q and q not in g.name.lower() and q not in (g.gid or "").lower():
                continue
            self.tree.insert("", "end", iid=key, text=g.name, values=self.row_values(g))
            shown += 1
        self.count.configure(text=f"{shown} of {len(self.games)} games")

    def row_values(self, g):
        return (g.gid or "", g.sub, g.fmt, human(g.size), g.info_state)

    def update_row(self, key):
        g = self.games.get(key)
        if g is not None and self.tree.exists(key):
            self.tree.item(key, text=g.name, values=self.row_values(g))

    def selected(self):
        return [self.games[k] for k in self.tree.selection() if k in self.games]

    # ---- rename ----

    def rename(self):
        sel = self.selected()
        if len(sel) != 1:
            messagebox.showinfo(APP_TITLE, "Select one game to rename.", parent=self.root)
            return
        if self.job:
            return
        g = sel[0]
        new = RenameDialog(self.root, g.name).result
        if new is None or new == g.name:
            return
        err = self.check_name(g, new)
        if err:
            messagebox.showerror(APP_TITLE, err, parent=self.root)
            return
        d = os.path.join(g.root, g.sub)
        done = []
        try:
            for f in g.files:
                ext = os.path.splitext(f)[1]
                os.rename(os.path.join(d, f), os.path.join(d, g.prefix + new + ext))
                done.append((f, g.prefix + new + ext))
        except OSError as e:
            for old, nw in reversed(done):  # put back what was renamed
                try:
                    os.rename(os.path.join(d, nw), os.path.join(d, old))
                except OSError:
                    pass
            messagebox.showerror(APP_TITLE, f"Could not rename:\n{e}\n\nIs the game running from the "
                                 "server, or the file open elsewhere?", parent=self.root)
            return
        old_key = f"{g.sub}/{g.stem}"
        old_path = g.path
        g.stem, g.name = g.prefix + new, new
        g.refresh_files()
        if old_path in self.id_cache:
            self.id_cache[g.path] = self.id_cache.pop(old_path)
            save_json("opl_library_ids.json", self.id_cache)
        self.games[f"{g.sub}/{g.stem}"] = self.games.pop(old_key)
        self.fill_tree()
        self.tree.selection_set(f"{g.sub}/{g.stem}")
        self.tree.see(f"{g.sub}/{g.stem}")
        self.say(f"Renamed to \"{new}\". In OPL, press Select to refresh the list.", GOOD)

    def check_name(self, g, new):
        if not new.strip():
            return "The name cannot be empty."
        if new != new.strip():
            return "The name cannot start or end with a space."
        if len(g.prefix + new) > NAME_MAX:
            return f"OPL shows names of up to {NAME_MAX} characters."
        bad = [c for c in new if c in BAD_CHARS or ord(c) < 32]
        if bad:
            return "These characters cannot be in a file name: " + " ".join(sorted(set(bad)))
        if new.endswith("."):
            return "The name cannot end with a dot."
        d = os.path.join(g.root, g.sub)
        for f in os.listdir(d):
            stem, ext = os.path.splitext(f)
            if stem.lower() == (g.prefix + new).lower() and stem.lower() != g.stem.lower() \
                    and ext.lower() in game_info.GAME_EXTS:
                return f"There is already a game called \"{new}\" in {g.sub}."
        return None

    # ---- edit info ----

    def edit_info(self):
        sel = self.selected()
        if len(sel) != 1:
            messagebox.showinfo(APP_TITLE, "Select one game to edit.", parent=self.root)
            return
        g = sel[0]
        if not g.gid:
            messagebox.showinfo(APP_TITLE, "This game's ID is not known yet (or the disc has none). "
                                "OPL keeps game info per game ID.", parent=self.root)
            return
        root = self.folder.get().strip()
        dlg = InfoDialog(self.root, g, game_info.load_info(root, g.gid))
        if dlg.result is None:
            return
        try:
            bdir = game_info.save_info(root, g.gid, dlg.result)
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Could not save:\n{e}", parent=self.root)
            return
        self.refresh_info_states()
        note = f" The old file is in {bdir}." if bdir else ""
        self.say(f"Saved the info for {g.name} ({g.gid}).{note}", GOOD)

    # ---- fetch info ----

    def fetch_info(self):
        games = self.selected() or list(self.games.values())
        if not games:
            return
        dlg = FetchDialog(self.root, len(games), bool(self.selected()))
        if dlg.result is None:
            return
        lang, replace = dlg.result
        root = self.folder.get().strip()
        targets = [(g.sub, g.files[0], g.path) for g in games]

        def work(_):
            s = game_info.fill(root, lang, replace, cancel=self.cancel, games=targets,
                               progress=lambda i, n, name, st: self.q.put(("progress", i / n, f"{name}: {st}")))
            self.q.put(("refresh_info",))
            text = f"{s['updated']} updated, {s['complete']} already complete, {s['no_entry']} not in the database"
            if s["no_id"]:
                text += f", {s['no_id']} without a game ID"
            if s["errors"]:
                text += f", {s['errors']} could not be downloaded"
            return text + "."
        self.run_job(work, None, label="Fetching info")

    # ---- compress ----

    def compress(self):
        try:
            import zso_tool
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"The ZSO compressor is not available:\n{e}\n\npip install lz4",
                                 parent=self.root)
            return
        pool = self.selected() or list(self.games.values())
        games = [g for g in pool if g.iso and not any(f.lower().endswith(".zso") for f in g.files)]
        if not games:
            messagebox.showinfo(APP_TITLE, "Nothing to compress: the chosen games are already ZSO.",
                                parent=self.root)
            return
        dlg = CompressDialog(self.root, games, shutil.disk_usage(self.folder.get()).free)
        if dlg.result is None:
            return
        delete = dlg.result
        total = sum(os.path.getsize(g.iso) for g in games) or 1

        def work(_):
            saved, done_bytes, n_ok = 0, 0, 0
            for g in games:
                if self.cancel.is_set():
                    break
                size = os.path.getsize(g.iso)
                if shutil.disk_usage(g.root).free < size + (64 << 20):
                    self.q.put(("msg", "Not enough free space for the next ZSO. Free some space or "
                                       "tick 'Delete each ISO'."))
                    break

                def prog(done, sz, phase, base=done_bytes, g=g):
                    part = done / sz * (0.8 if phase == "compress" else 0.2) + (0.8 if phase == "verify" else 0)
                    self.q.put(("progress", (base + part * sz) / total,
                                f"{'Compressing' if phase == 'compress' else 'Checking'} {g.name}"))
                try:
                    isz, zsz = zso_tool.compress_iso(g.iso, progress=prog, cancel=self.cancel)
                    if delete:
                        try:
                            os.remove(g.iso)
                        except OSError:
                            pass
                    saved += isz - zsz
                    n_ok += 1
                except zso_tool.NotWorthIt:
                    pass
                except zso_tool.Cancelled:
                    break
                except Exception as e:
                    self.q.put(("msg", f"{g.name}: {e}"))
                g.refresh_files()
                self.q.put(("row", f"{g.sub}/{g.stem}"))
                done_bytes += size
            return (f"{n_ok} game(s) compressed, {human(saved)} saved. UDPFS Server serves them with "
                    "'Compressed games' ticked.")
        self.run_job(work, None, label="Compressing")

    # ---- jobs ----

    def run_job(self, fn, arg, label):
        if self.job is not None:
            return
        self.cancel.clear()
        for b in self.btns:
            b.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.say(label + "...", MUTED)
        self.progress["value"] = 0

        def wrap():
            try:
                self.q.put(("done", fn(arg)))
            except Exception as e:
                self.q.put(("done", f"Stopped: {e}"))
        self.job = threading.Thread(target=wrap, daemon=True)
        self.job.start()

    def pump(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "progress":
                    self.progress["value"] = m[1] * 1000
                    self.say(m[2], MUTED)
                elif m[0] == "row":
                    self.update_row(m[1])
                elif m[0] == "refresh_info":
                    self.refresh_info_states()
                elif m[0] == "msg":
                    messagebox.showwarning(APP_TITLE, m[1], parent=self.root)
                elif m[0] == "done":
                    self.job = None
                    for b in self.btns:
                        b.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.progress["value"] = 0
                    self.say(m[1] + (" (stopped)" if self.cancel.is_set() else ""), GOOD)
        except queue.Empty:
            pass
        self.root.after(120, self.pump)

    def say(self, text, color):
        self.status.configure(text=text, foreground=color)

    def on_close(self):
        if self.job is not None:
            if not messagebox.askyesno(APP_TITLE, "Stop the running job and close?", parent=self.root):
                return
            self.cancel.set()
        self.root.destroy()


# ---------------------------------------------------------------- dialogs

class Dialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())

    def buttons(self, ok_text="OK"):
        b = ttk.Frame(self.body)
        b.grid(row=99, column=0, columnspan=4, sticky="e", pady=(12, 0))
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text=ok_text, command=self.ok).pack(side="right", padx=(0, 8))

    def show(self):
        self.grab_set()
        self.wait_window(self)


class RenameDialog(Dialog):
    def __init__(self, parent, name):
        super().__init__(parent, "Rename game")
        ttk.Label(self.body, text="Name in OPL's game list:").grid(row=0, column=0, sticky="w")
        self.var = tk.StringVar(value=name)
        e = ttk.Entry(self.body, textvariable=self.var, width=60)
        e.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        e.focus_set()
        e.select_range(0, "end")
        self.n = ttk.Label(self.body, text="", foreground=MUTED)
        self.n.grid(row=2, column=0, sticky="w")
        self.var.trace_add("write", lambda *_: self.n.configure(text=f"{len(self.var.get())} / {NAME_MAX}"))
        self.var.set(name)
        self.bind("<Return>", lambda e: self.ok())
        self.buttons("Rename")
        self.show()

    def ok(self):
        self.result = self.var.get()
        self.destroy()


class InfoDialog(Dialog):
    def __init__(self, parent, game, info):
        super().__init__(parent, f"Game info - {game.name}")
        ttk.Label(self.body, text=f"{game.gid}  -  saved to CFG\\{game.gid}.cfg",
                  foreground=MUTED).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self.vars = {}
        for r, (key, label) in enumerate(INFO_FIELDS, start=1):
            ttk.Label(self.body, text=label + ":").grid(row=r, column=0, sticky="w", pady=2)
            v = tk.StringVar(value=info.get(key, ""))
            ttk.Entry(self.body, textvariable=v, width=56).grid(row=r, column=1, columnspan=3, sticky="ew", pady=2)
            self.vars[key] = v
        r = len(INFO_FIELDS) + 1
        ttk.Label(self.body, text="(release date as MM-DD-YYYY, like the database)", foreground=MUTED).grid(
            row=r, column=1, columnspan=3, sticky="w")
        r += 1
        ttk.Label(self.body, text="Players:").grid(row=r, column=0, sticky="w", pady=2)
        self.players = tk.StringVar(value=info.get("PlayersText", ""))
        ttk.Spinbox(self.body, from_=1, to=8, textvariable=self.players, width=5).grid(row=r, column=1, sticky="w")
        ttk.Label(self.body, text="Rating (0-5):").grid(row=r, column=2, sticky="e", padx=(12, 4))
        self.rating = tk.StringVar(value=info.get("RatingText", ""))
        ttk.Spinbox(self.body, from_=0, to=5, textvariable=self.rating, width=5).grid(row=r, column=3, sticky="w")
        r += 1
        ttk.Label(self.body, text="Description:").grid(row=r, column=0, sticky="nw", pady=(6, 0))
        self.desc = tk.Text(self.body, width=56, height=6, wrap="word")
        self.desc.insert("1.0", info.get("Description", ""))
        self.desc.grid(row=r, column=1, columnspan=3, sticky="ew", pady=(6, 0))
        r += 1
        self.dn = ttk.Label(self.body, text="", foreground=MUTED)
        self.dn.grid(row=r, column=1, columnspan=3, sticky="w")
        self.desc.bind("<KeyRelease>", lambda e: self.count())
        self.count()
        self.buttons("Save")
        self.show()

    def count(self):
        n = len(" ".join(self.desc.get("1.0", "end").split()))
        self.dn.configure(text=f"{n} / {DESC_MAX} characters" + (" - OPL may cut the rest" if n > DESC_MAX else ""),
                          foreground=WARN if n > DESC_MAX else MUTED)

    def ok(self):
        values = {k: v.get().strip() for k, v in self.vars.items()}
        for key, var, hi in (("Players", self.players, 8), ("Rating", self.rating, 5)):
            t = var.get().strip()
            if t and (not t.isdigit() or not (0 <= int(t) <= hi)):
                messagebox.showerror(APP_TITLE, f"{key}: a number from {0 if key == 'Rating' else 1} to {hi}.",
                                     parent=self)
                return
            values[key] = f"{key.lower()}/{t}" if t else ""
            values[key + "Text"] = t
        values["Description"] = self.desc.get("1.0", "end").strip()
        self.result = values
        self.destroy()


class FetchDialog(Dialog):
    def __init__(self, parent, n, selection):
        super().__init__(parent, "Fetch game info")
        ttk.Label(self.body, wraplength=440, justify="left", text=(
            f"Fetch info for {'the ' + str(n) + ' selected' if selection else 'all ' + str(n)} game(s) from the "
            "PS2 OPL CFG Database on GitHub (game info from ScreenScraper.fr). Only missing fields are "
            "added; your own settings are never changed.")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(self.body, text="Language:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.lang = tk.StringVar(value="English")
        ttk.Combobox(self.body, textvariable=self.lang, values=["English", "French"], state="readonly",
                     width=10).grid(row=1, column=1, sticky="w", pady=(10, 0))
        self.replace = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body, text="Also replace info that is already there",
                        variable=self.replace).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.buttons("Fetch")
        self.show()

    def ok(self):
        self.result = ("fr" if self.lang.get() == "French" else "en", self.replace.get())
        self.destroy()


class CompressDialog(Dialog):
    def __init__(self, parent, games, free):
        super().__init__(parent, "Compress to ZSO")
        total = sum(os.path.getsize(g.iso) for g in games)
        ttk.Label(self.body, wraplength=440, justify="left", text=(
            f"Compress {len(games)} game(s), {human(total)} of ISOs, to ZSO. Each file is checked against "
            f"its ISO before it counts as done. Free on this drive: {human(free)}.")).grid(
            row=0, column=0, sticky="w")
        self.delete = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body, text="Delete each ISO once its ZSO has been checked",
                        variable=self.delete).grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.buttons("Compress")
        self.show()

    def ok(self):
        if self.delete.get() and not messagebox.askyesno(
                APP_TITLE, "Each ISO is deleted for good once its ZSO has been checked. Go ahead?", parent=self):
            return
        self.result = self.delete.get()
        self.destroy()


def main():
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UDPFS.Library")
        except Exception:
            pass
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if IS_WINDOWS else ("aqua" if IS_MAC else "clam"))
    except Exception:
        pass
    icon = os.path.join(HERE, "icon.png")
    if os.path.isfile(icon):
        try:
            root._icon = tk.PhotoImage(file=icon)
            root.iconphoto(True, root._icon)
        except Exception:
            pass
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    folder = args[0] if args else (load_json("opl_library.json").get("folder")
                                   or load_json("udpfs_gui.json").get("folder", ""))
    Library(root, folder)
    root.mainloop()


if __name__ == "__main__":
    main()
