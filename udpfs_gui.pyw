#!/usr/bin/env python3
"""
UDPFS Server - a small window around Neutrino's udpfs_server.py.

Put this file next to udpfs_server.py (and its compressed_iso folder) and
double-click it. Pick your OPL folder (or a disk image), press Start.

Only the Python standard library is used (tkinter ships with the
python.org installers for Windows and macOS). Settings are kept in
%APPDATA%\\udpfs_gui.json on Windows, ~/Library/Application Support/
UDPFS Server/udpfs_gui.json on a Mac, ~/.config/udpfs_gui.json elsewhere.

On a Mac this file normally runs from inside "UDPFS Server.app".

Command line:
    udpfs_gui.pyw --autostart     start the server as soon as the window opens
    udpfs_gui.pyw --minimized     open minimized (used by "Open with Windows/at login")
"""

import json
import plistlib
import shlex
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import shutil
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "UDPFS Server"
DISCOVERY_PORT = 0xF5F6  # 62966
FIREWALL_RULE = "UDPFS Server (PS2)"
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
LAUNCH_AGENT_ID = "local.udpfs.server-gui"
MAC_FIREWALL = "/usr/libexec/ApplicationFirewall/socketfilterfw"
EXAMPLE_FOLDER = "E:\\PS2" if IS_WINDOWS else ("/Volumes/MyDrive/PS2" if IS_MAC else "/media/you/drive/PS2")
THIS_PC = "This Mac" if IS_MAC else "This PC"

# Colours that read on light and dark window backgrounds (macOS dark mode).
MUTED = "#888888"
GOOD = "#2e9e44"
WARN = "#c27c0e"
BAD = "#d1242f"
HERE = os.path.dirname(os.path.abspath(__file__))
LOG_LINES_MAX = 3000
GAME_EXTS = (".iso",)
COMPRESSED_EXTS = (".zso", ".cso", ".chd")
# A console counts as "connected" while requests keep arriving; the menu
# pings the server every 4 s, so 10 s of silence means it has gone.
ACTIVE_TIMEOUT = 10.0


# --------------------------------------------------------------------------
# Settings

def settings_path():
    if IS_WINDOWS:
        base = os.environ.get("APPDATA")
    elif IS_MAC:
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_TITLE)
    else:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base or HERE, "udpfs_gui.json")


DEFAULTS = {
    "mode": "folder",          # "folder" or "image"
    "folder": "",
    "image": "",
    "server": "",              # path to udpfs_server.py; "" = next to this file
    "bind": "",                # "" = all network adapters
    "read_only": False,
    "compression": True,
    "verbose": False,
    "autostart": False,
}


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except Exception:
        pass
    return s


def save_settings(s):
    try:
        os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Helpers

def find_server(configured):
    for p in (configured, os.path.join(HERE, "udpfs_server.py"),
              os.path.join(HERE, "pc", "udpfs_server.py"),
              os.path.join(HERE, "udpfs-server", "udpfs_server.py")):
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return ""


def console_python():
    """The interpreter that runs the server. Under pythonw.exe use the
    python.exe beside it, so the server's output can be read."""
    exe = sys.executable or "python"
    if IS_WINDOWS and os.path.basename(exe).lower() == "pythonw.exe":
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(cand):
            return cand
    return exe


def local_addresses():
    """(label, ip) pairs for the adapter picker."""
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    best = primary_ip()
    if best and best not in ips:
        ips.insert(0, best)
    return ips


def primary_ip():
    """The address this PC uses on the LAN (no packet is sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def scan_opl_folder(path, compression):
    """Count games and say whether this looks like an OPL root."""
    exts = GAME_EXTS + (COMPRESSED_EXTS if compression else ())
    counts = {}
    for sub in ("DVD", "CD"):
        d = os.path.join(path, sub)
        n = 0
        if os.path.isdir(d):
            try:
                n = sum(1 for f in os.listdir(d) if f.lower().endswith(exts))
            except Exception:
                n = 0
            counts[sub] = n
    hint = ""
    if not counts:
        # The OPL folder is often one level down (E:\ instead of E:\PS2).
        try:
            for name in sorted(os.listdir(path)):
                p = os.path.join(path, name)
                if os.path.isdir(os.path.join(p, "DVD")) or os.path.isdir(os.path.join(p, "CD")):
                    hint = p
                    break
        except Exception:
            pass
    compressed = 0
    if not compression:
        for sub in ("DVD", "CD"):
            d = os.path.join(path, sub)
            if os.path.isdir(d):
                try:
                    compressed += sum(1 for f in os.listdir(d) if f.lower().endswith(COMPRESSED_EXTS))
                except Exception:
                    pass
    return counts, hint, compressed


def run_hidden(args):
    kw = {}
    if IS_WINDOWS:
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(args, capture_output=True, text=True, **kw)


def mac_python_binary(python_exe):
    """The binary macOS's firewall sees receive the packets. A python.org
    install runs bin/python3 as Resources/Python.app/Contents/MacOS/Python."""
    app = os.path.join(sys.base_prefix, "Resources", "Python.app", "Contents", "MacOS", "Python")
    if os.path.isfile(app):
        return app
    return os.path.realpath(python_exe)


def firewall_rule_exists():
    """True: allowed. False: not yet. "off": no firewall to pass.
    None: cannot tell (not Windows or macOS)."""
    try:
        if IS_WINDOWS:
            r = run_hidden(["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE}"])
            return r.returncode == 0 and FIREWALL_RULE in r.stdout
        if IS_MAC and os.path.exists(MAC_FIREWALL):
            r = run_hidden([MAC_FIREWALL, "--getglobalstate"])
            if "disabled" in r.stdout.lower() or "state = 0" in r.stdout.lower():
                return "off"
            r = run_hidden([MAC_FIREWALL, "--getappblocked", mac_python_binary(console_python())])
            out = r.stdout.lower()
            if "permitted" in out or "allowed" in out:
                return True
            return False
    except Exception:
        pass
    return None


def add_firewall_rule(python_exe):
    """Ask the OS (UAC prompt / admin password) to let this Python receive
    UDP.

    The rule is for the program, not a port: the server answers discovery
    on 62966 but moves each console to a data port the OS picks at
    random."""
    if IS_MAC:
        b = shlex.quote(mac_python_binary(python_exe))
        sh = f"{MAC_FIREWALL} --add {b}; {MAC_FIREWALL} --unblockapp {b}"
        script = 'do shell script "%s" with administrator privileges' % sh.replace("\\", "\\\\").replace('"', '\\"')
        try:
            return subprocess.run(["osascript", "-e", script], capture_output=True).returncode == 0
        except Exception:
            return False
    import ctypes
    cmd = (f'netsh advfirewall firewall delete rule name="{FIREWALL_RULE}" & '
           f'netsh advfirewall firewall add rule name="{FIREWALL_RULE}" dir=in action=allow '
           f'protocol=UDP program="{python_exe}" profile=any & '
           f'netsh advfirewall firewall add rule name="{FIREWALL_RULE}" dir=in action=allow '
           f'protocol=UDP localport={DISCOVERY_PORT} profile=any')
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", f"/c {cmd}", None, 0)
    return ret > 32


def startup_file():
    if IS_WINDOWS:
        base = os.environ.get("APPDATA", "")
        return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "UDPFS Server.bat")
    if IS_MAC:
        return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", LAUNCH_AGENT_ID + ".plist")
    return ""


def write_startup_entry(path):
    gui = os.path.abspath(__file__)
    if IS_WINDOWS:
        pyw = os.path.join(os.path.dirname(console_python()), "pythonw.exe")
        if not os.path.isfile(pyw):
            pyw = console_python()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f'@start "" "{pyw}" "{gui}" --autostart --minimized\r\n')
    elif IS_MAC:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            plistlib.dump({
                "Label": LAUNCH_AGENT_ID,
                "ProgramArguments": [console_python(), gui, "--autostart", "--minimized"],
                "RunAtLoad": True,
                "ProcessType": "Interactive",
                "LimitLoadToSessionType": "Aqua",
            }, fh)


# --------------------------------------------------------------------------
# The window

class App:
    def __init__(self, root, args):
        self.root = root
        self.s = load_settings()
        self.proc = None
        self.reader = None
        self.q = queue.Queue()
        self.last_activity = 0.0
        self.console_ip = ""
        self.started_at = 0.0
        self.stopping = False

        root.title(APP_TITLE)
        root.minsize(620, 460)

        self._build()
        self._load_into_widgets()
        self.refresh_checks()
        self.refresh_firewall()
        self.root.after(200, self._pump)
        self.root.after(1000, self._tick)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        if "--minimized" in args:
            root.iconify()
        if "--autostart" in args or self.s["autostart"]:
            self.root.after(300, self.start)

    # ---- layout -----------------------------------------------------------

    def _build(self):
        pad = {"padx": 8, "pady": 4}
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        # What to serve
        src = ttk.LabelFrame(outer, text="What to serve", padding=8)
        src.pack(fill="x")
        self.mode = tk.StringVar()
        ttk.Radiobutton(src, text="OPL folder", value="folder", variable=self.mode,
                        command=self.on_mode).grid(row=0, column=0, sticky="w")
        self.folder = tk.StringVar()
        self.folder_entry = ttk.Entry(src, textvariable=self.folder)
        self.folder_entry.grid(row=0, column=1, sticky="ew", **pad)
        self.folder_btn = ttk.Button(src, text="Browse...", command=self.browse_folder)
        self.folder_btn.grid(row=0, column=2)

        ttk.Radiobutton(src, text="Disk image", value="image", variable=self.mode,
                        command=self.on_mode).grid(row=1, column=0, sticky="w")
        self.image = tk.StringVar()
        self.image_entry = ttk.Entry(src, textvariable=self.image)
        self.image_entry.grid(row=1, column=1, sticky="ew", **pad)
        self.image_btn = ttk.Button(src, text="Browse...", command=self.browse_image)
        self.image_btn.grid(row=1, column=2)

        self.check_label = ttk.Label(src, text="", foreground=MUTED)
        self.check_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.hint_btn = ttk.Button(src, text="Use it", command=self.use_hint)
        src.columnconfigure(1, weight=1)
        for v in (self.folder, self.image):
            v.trace_add("write", lambda *_: self.refresh_checks())

        # Options
        opt = ttk.LabelFrame(outer, text="Options", padding=8)
        opt.pack(fill="x", pady=(8, 0))
        ttk.Label(opt, text="Network adapter:").grid(row=0, column=0, sticky="w")
        self.bind = tk.StringVar()
        self.bind_box = ttk.Combobox(opt, textvariable=self.bind, width=22, state="readonly",
                                     values=["All adapters"] + local_addresses())
        self.bind_box.grid(row=0, column=1, sticky="w", padx=8)
        self.ip_label = ttk.Label(opt, text="", foreground=MUTED)
        self.ip_label.grid(row=0, column=2, columnspan=2, sticky="w")

        self.read_only = tk.BooleanVar()
        self.compression = tk.BooleanVar()
        self.verbose = tk.BooleanVar()
        self.autostart = tk.BooleanVar()
        self.startup = tk.BooleanVar(value=bool(startup_file()) and os.path.isfile(startup_file()))
        self.platform_bits(root=self.root)
        ttk.Checkbutton(opt, text="Read-only (the PS2 cannot save configs or VMCs)",
                        variable=self.read_only).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(opt, text="Compressed games (.zso / .cso / .chd)", variable=self.compression,
                        command=self.refresh_checks).grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(opt, text="Log every request (slow, for debugging)",
                        variable=self.verbose).grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(opt, text="Start the server when this window opens",
                        variable=self.autostart).grid(row=4, column=0, columnspan=3, sticky="w")
        if IS_WINDOWS or IS_MAC:
            ttk.Checkbutton(opt, text="Open with Windows (minimized)" if IS_WINDOWS else "Open at login (minimized)",
                            variable=self.startup,
                            command=self.on_startup).grid(row=5, column=0, columnspan=3, sticky="w")

        # Firewall
        fw = ttk.Frame(outer)
        fw.pack(fill="x", pady=(8, 0))
        self.fw_label = ttk.Label(fw, text="")
        self.fw_label.pack(side="left")
        self.fw_btn = ttk.Button(fw, text="Allow through firewall", command=self.on_firewall)
        if IS_WINDOWS or IS_MAC:
            self.fw_btn.pack(side="right")

        # Start / stop and status
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(10, 4))
        self.start_btn = ttk.Button(bar, text="Start", width=12, command=self.toggle)
        self.start_btn.pack(side="left")
        self.dot = tk.Canvas(bar, width=14, height=14, highlightthickness=0, borderwidth=0)
        try:
            self.dot.configure(background=ttk.Style().lookup("TFrame", "background") or self.root.cget("background"))
        except Exception:
            pass
        self.dot.pack(side="left", padx=(12, 4))
        self.dot_id = self.dot.create_oval(2, 2, 12, 12, fill="#999", outline="")
        self.status = ttk.Label(bar, text="Stopped", font=("TkDefaultFont", 13 if IS_MAC else 10, "bold"))
        self.status.pack(side="left")
        ttk.Button(bar, text="Clear log", command=self.clear_log).pack(side="right")
        self.compress_btn = ttk.Button(bar, text="Compress games...", command=self.open_compressor)
        self.compress_btn.pack(side="right", padx=(0, 8))
        self.rate = ttk.Label(outer, text="", foreground=MUTED)
        self.rate.pack(fill="x")

        # Log
        logf = ttk.Frame(outer)
        logf.pack(fill="both", expand=True, pady=(4, 0))
        self.log = tk.Text(logf, height=12, wrap="none", state="disabled",
                           font=("Consolas", 9) if IS_WINDOWS else (("Menlo", 11) if IS_MAC else ("TkFixedFont", 9)),
                           background="#111", foreground="#ddd", insertbackground="#ddd")
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.log.tag_configure("err", foreground="#ff7b72")
        self.log.tag_configure("ok", foreground="#7ee787")
        self.log.tag_configure("me", foreground="#79c0ff")

        self.inputs = [self.folder_entry, self.folder_btn, self.image_entry, self.image_btn, self.bind_box]

    def _load_into_widgets(self):
        s = self.s
        self.mode.set(s["mode"] if s["mode"] in ("folder", "image") else "folder")
        self.folder.set(s["folder"])
        self.image.set(s["image"])
        self.bind.set(s["bind"] or "All adapters")
        self.read_only.set(s["read_only"])
        self.compression.set(s["compression"])
        self.verbose.set(s["verbose"])
        self.autostart.set(s["autostart"])
        self.on_mode()
        ip = primary_ip()
        self.ip_label.configure(text=f"{THIS_PC}: {ip}" if ip else "")

    def _store(self):
        s = self.s
        s["mode"] = self.mode.get()
        s["folder"] = self.folder.get().strip()
        s["image"] = self.image.get().strip()
        b = self.bind.get()
        s["bind"] = "" if b == "All adapters" else b
        s["read_only"] = self.read_only.get()
        s["compression"] = self.compression.get()
        s["verbose"] = self.verbose.get()
        s["autostart"] = self.autostart.get()
        save_settings(s)

    def platform_bits(self, root):
        if IS_MAC:
            try:
                root.createcommand("tk::mac::Quit", self.on_close)
                root.createcommand("tk::mac::ReopenApplication", root.deiconify)
            except Exception:
                pass

    # ---- inputs -----------------------------------------------------------

    def on_mode(self):
        folder = self.mode.get() == "folder"
        running = self.proc is not None
        for w, on in ((self.folder_entry, folder), (self.folder_btn, folder),
                      (self.image_entry, not folder), (self.image_btn, not folder)):
            w.configure(state="normal" if on and not running else "disabled")
        self.refresh_checks()

    def browse_folder(self):
        p = filedialog.askdirectory(title="Your OPL folder (the one with DVD, CD, ART, CFG, VMC)",
                                    initialdir=self.folder.get() or None)
        if p:
            self.folder.set(os.path.normpath(p))

    def browse_image(self):
        p = filedialog.askopenfilename(title="Disk image",
                                       filetypes=[("Disk images", "*.img *.vhd *.bin *.raw"), ("All files", "*.*")])
        if p:
            self.image.set(os.path.normpath(p))

    def use_hint(self):
        if getattr(self, "_hint", ""):
            self.folder.set(self._hint)

    def refresh_checks(self):
        self._hint = ""
        self.hint_btn.grid_forget()
        color = MUTED
        if self.mode.get() == "folder":
            p = self.folder.get().strip()
            if not p:
                text = f"Pick the folder that holds DVD, CD, ART, CFG and VMC (for example {EXAMPLE_FOLDER})."
            elif not os.path.isdir(p):
                text, color = "That folder does not exist.", BAD
            else:
                counts, hint, compressed = scan_opl_folder(p, self.compression.get())
                if counts:
                    parts = [f"{n} {k}" for k, n in counts.items()]
                    text = "OPL folder: " + ", ".join(parts) + " game(s)."
                    if compressed:
                        text += f"  {compressed} compressed file(s) need 'Compressed games'."
                    color = GOOD
                elif hint:
                    text, color = f"No DVD or CD folder here. Did you mean {hint}?", WARN
                    self._hint = hint
                    self.hint_btn.grid(row=2, column=2, sticky="e")
                else:
                    text, color = "No DVD or CD folder here: OPL will find no games.", WARN
        else:
            p = self.image.get().strip()
            if not p:
                text = "Pick a disk image formatted FAT32 or exFAT, laid out like an OPL USB stick."
            elif not os.path.isfile(p):
                text, color = "That file does not exist.", BAD
            else:
                text = f"Disk image, {os.path.getsize(p) / (1 << 30):.1f} GiB."
        self.check_label.configure(text=text, foreground=color)

    def refresh_firewall(self):
        state = firewall_rule_exists()
        if state == "off":
            self.fw_label.configure(text="Firewall: off, nothing to allow", foreground=GOOD)
            self.fw_btn.configure(text="Allow anyway")
        elif state is True:
            self.fw_label.configure(text="Firewall: allowed", foreground=GOOD)
            self.fw_btn.configure(text="Allow again")
        elif state is False:
            self.fw_label.configure(text="Firewall: no rule yet - the PS2 may not find the server",
                                    foreground=WARN)
            self.fw_btn.configure(text="Allow through firewall")
        else:
            self.fw_label.configure(text=f"Allow inbound UDP for Python in your firewall (port {DISCOVERY_PORT}).",
                                    foreground=MUTED)

    def on_firewall(self):
        if not add_firewall_rule(console_python()):
            messagebox.showerror(APP_TITLE, "The firewall rule was not added.")
            return
        self.root.after(2500, self.refresh_firewall)

    def on_startup(self):
        f = startup_file()
        try:
            if self.startup.get():
                if IS_MAC and "/AppTranslocation/" in HERE:
                    messagebox.showwarning(APP_TITLE, "Move UDPFS Server into your Applications folder and "
                                           "open it from there first, then switch this on.")
                    self.startup.set(False)
                    return
                write_startup_entry(f)
            elif os.path.isfile(f):
                os.remove(f)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Could not change the startup entry:\n{e}")
            self.startup.set(os.path.isfile(f))

    # ---- server process ---------------------------------------------------

    def toggle(self):
        if self.proc is None:
            self.start()
        else:
            self.stop()

    def start(self):
        if self.proc is not None:
            return
        self._store()
        server = find_server(self.s["server"])
        if not server:
            if not messagebox.askyesno(APP_TITLE, "udpfs_server.py was not found next to this program.\n\n"
                                       "Find it now?"):
                return
            server = filedialog.askopenfilename(title="udpfs_server.py", filetypes=[("Python", "*.py")])
            if not server:
                return
            self.s["server"] = server
            save_settings(self.s)

        args = [console_python(), "-u", server]
        if self.s["mode"] == "folder":
            if not os.path.isdir(self.s["folder"]):
                messagebox.showerror(APP_TITLE, "Pick your OPL folder first.")
                return
            args += ["-d", self.s["folder"]]
        else:
            if not os.path.isfile(self.s["image"]):
                messagebox.showerror(APP_TITLE, "Pick a disk image first.")
                return
            args += ["-b", self.s["image"]]
        if self.s["bind"]:
            args += ["-i", self.s["bind"]]
        if self.s["read_only"]:
            args.append("-r")
        if self.s["compression"]:
            args.append("-c")
        if self.s["verbose"]:
            args.append("-v")

        kw = {}
        if IS_WINDOWS:
            kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        try:
            self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, cwd=os.path.dirname(server), env=env, **kw)
        except Exception as e:
            self.proc = None
            messagebox.showerror(APP_TITLE, f"Could not start the server:\n{e}")
            return

        self.stopping = False
        self.started_at = time.monotonic()
        self.last_activity = 0.0
        self.console_ip = ""
        self.write_log(f"> {' '.join(args[2:])}", "me")
        self.reader = threading.Thread(target=self._read, args=(self.proc,), daemon=True)
        self.reader.start()
        self.start_btn.configure(text="Stop")
        for w in self.inputs:
            w.configure(state="disabled")
        self._set_status("Waiting for the PS2...", "#d29922")

    def stop(self):
        if self.proc is None:
            return
        self.stopping = True
        try:
            self.proc.terminate()
        except Exception:
            pass

    def _read(self, proc):
        """Split the server's output into log lines (ending in \\n) and its
        live status line (rewritten in place with \\r)."""
        buf = b""
        out = proc.stdout
        while True:
            chunk = out.read1(4096) if hasattr(out, "read1") else out.read(1)
            if not chunk:
                break
            buf += chunk
            while True:
                m = re.search(rb"[\r\n]", buf)
                if not m:
                    break
                if buf[m.start():m.start() + 1] == b"\r":
                    # Windows ends lines with \r\n; a lone \r redraws the
                    # status line. Wait for the byte after a trailing \r.
                    if m.end() == len(buf):
                        break
                    if buf[m.end():m.end() + 1] == b"\n":
                        piece, sep, buf = buf[:m.start()], b"\n", buf[m.end() + 1:]
                        text = piece.decode("utf-8", "replace").rstrip()
                        if text.strip() or not piece:
                            self.q.put(("line", text))
                        continue
                piece, sep, buf = buf[:m.start()], buf[m.start():m.start() + 1], buf[m.end():]
                text = piece.decode("utf-8", "replace").rstrip()
                if sep == b"\r":
                    if text.strip():
                        self.q.put(("status", text.strip()))
                elif text.strip() or not piece:
                    self.q.put(("line", text))
        if buf.strip():
            self.q.put(("line", buf.decode("utf-8", "replace").rstrip()))
        proc.wait()
        self.q.put(("exit", proc.returncode))

    def _pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "line":
                    self._on_line(val)
                elif kind == "status":
                    self.last_activity = time.monotonic()
                    self.rate.configure(text=val)
                elif kind == "exit":
                    self._on_exit(val)
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def _on_line(self, line):
        m = re.match(r"\[(\d+\.\d+\.\d+\.\d+):\d+\]", line)
        if m:
            self.last_activity = time.monotonic()
            if self.console_ip != m.group(1):
                self.console_ip = m.group(1)
        tag = None
        low = line.lower()
        if "error" in low or "warning" in low or "eacces" in low:
            tag = "err"
        elif "discovery ->" in low:
            tag = "ok"
            line = line + "   (PS2 found the server)"
        if line.strip():
            self.write_log(line, tag)
        if "address already in use" in low or "winerror 10048" in low or "errno 98" in low:
            self.write_log("Another server is already using the port. Close it (or the other window) first.", "err")

    def _on_exit(self, code):
        self.proc = None
        self.start_btn.configure(text="Start")
        self.rate.configure(text="")
        self.on_mode()
        self.bind_box.configure(state="readonly")
        if self.stopping:
            self.write_log("Server stopped.", "me")
            self._set_status("Stopped", MUTED)
        else:
            self.write_log(f"Server exited (code {code}).", "err")
            self._set_status("Server exited - see the log", "#da3633")
        self.stopping = False

    def _tick(self):
        if self.proc is not None:
            now = time.monotonic()
            if self.last_activity and now - self.last_activity < ACTIVE_TIMEOUT:
                who = f" ({self.console_ip})" if self.console_ip else ""
                self._set_status(f"PS2 connected{who}", "#2ea043")
            else:
                self._set_status("Running - waiting for the PS2...", "#d29922")
                if self.last_activity:
                    self.rate.configure(text="")
        self.root.after(1000, self._tick)

    def _set_status(self, text, color):
        self.status.configure(text=text)
        self.dot.itemconfigure(self.dot_id, fill=color)

    # ---- log --------------------------------------------------------------

    def write_log(self, text, tag=None):
        self.log.configure(state="normal")
        at_end = self.log.yview()[1] > 0.999
        self.log.insert("end", text + "\n", (tag,) if tag else ())
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > LOG_LINES_MAX:
            self.log.delete("1.0", f"{lines - LOG_LINES_MAX}.0")
        self.log.configure(state="disabled")
        if at_end:
            self.log.see("end")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def open_compressor(self):
        folder = self.folder.get().strip()
        if self.mode.get() != "folder" or not os.path.isdir(folder):
            messagebox.showinfo(APP_TITLE, "Compressing works on an OPL folder. Pick yours first.")
            return
        try:
            import zso_tool  # noqa: F401  (needs lz4)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"The ZSO compressor is not available here:\n{e}\n\n"
                                 "Install it with:  pip install lz4")
            return
        if getattr(self, "_compressor", None) is not None and self._compressor.win.winfo_exists():
            self._compressor.win.lift()
            return
        if not self.compression.get():
            if not messagebox.askyesno(APP_TITLE, "Compressed games is off, so the PS2 would not see the "
                                       "ZSO files this makes.\n\nTurn it on now?"
                                       + ("\n\nThe server restarts; a game running from it will freeze."
                                          if self.proc is not None else "")):
                return
            self.compression.set(True)
            self._store()
            self.refresh_checks()
            if self.proc is not None:
                self.restart_server()
        self._compressor = Compressor(self, folder)

    def restart_server(self):
        if self.proc is None:
            self.start()
            return
        self.stop()

        def again():
            if self.proc is None:
                self.start()
            else:
                self.root.after(200, again)
        self.root.after(200, again)

    def on_close(self):
        self._store()
        if self.proc is not None:
            if not messagebox.askokcancel(APP_TITLE, "Stop the server and close?\n\n"
                                          "A game that is running from it will freeze."):
                return
            self.stop()
            try:
                self.proc.wait(timeout=3)
            except Exception:
                pass
        self.root.destroy()


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024.0


class Compressor:
    """The "Compress games" window: ISOs in DVD and CD become ZSO files,
    one after another on a background thread."""

    def __init__(self, app, folder):
        import zso_tool
        self.zso = zso_tool
        self.app = app
        self.folder = folder
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.thread = None
        self.saved = 0

        w = self.win = tk.Toplevel(app.root)
        w.title("Compress games")
        w.minsize(640, 480)
        w.geometry("720x560")
        w.protocol("WM_DELETE_WINDOW", self.on_close)
        f = ttk.Frame(w, padding=10)
        f.pack(fill="both", expand=True)

        ttk.Label(f, wraplength=600, justify="left", text=(
            "Turns the ISOs in DVD and CD into ZSO files, the compressed format OPL and PCSX2 read. "
            "Each file is decompressed again and checked against its ISO before it counts as done. "
            "Settings, art, memory cards and achievements stay as they are: they follow the game ID, "
            "not the file name.")).pack(fill="x")

        cols = ("folder", "size", "status")
        box = ttk.Frame(f)
        box.pack(fill="both", expand=True, pady=(8, 4))
        tv = self.tree = ttk.Treeview(box, columns=cols, selectmode="extended", height=12)
        tv.heading("#0", text="Game")
        tv.heading("folder", text="Folder")
        tv.heading("size", text="Size")
        tv.heading("status", text="Status")
        tv.column("#0", width=270)
        tv.column("folder", width=60, anchor="center")
        tv.column("size", width=80, anchor="e")
        tv.column("status", width=230)
        sb = ttk.Scrollbar(box, command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.delete = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Delete each ISO once its ZSO has been checked (frees the space)",
                        variable=self.delete).pack(anchor="w")
        self.summary = ttk.Label(f, text="", foreground=MUTED)
        self.summary.pack(fill="x", pady=(4, 0))
        self.now = ttk.Label(f, text="")
        self.now.pack(fill="x", pady=(6, 0))
        self.bar = ttk.Progressbar(f, maximum=1000)
        self.bar.pack(fill="x")
        self.total_bar = ttk.Progressbar(f, maximum=1000)
        self.total_bar.pack(fill="x", pady=(4, 0))

        btns = ttk.Frame(f)
        btns.pack(fill="x", pady=(8, 0))
        self.go_btn = ttk.Button(btns, text="Compress all", command=self.go)
        self.go_btn.pack(side="right")
        self.stop_btn = ttk.Button(btns, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="right", padx=(0, 8))
        ttk.Button(btns, text="Select all", command=lambda: tv.selection_set(self.todo_ids())).pack(side="left")
        tv.bind("<<TreeviewSelect>>", lambda e: self._label_go())

        self.items = {}
        self.scan()
        w.after(100, self.pump)

    # ---- list ----

    def scan(self):
        tv = self.tree
        tv.delete(*tv.get_children())
        self.items.clear()
        total = 0
        count = 0
        for sub in ("DVD", "CD"):
            d = os.path.join(self.folder, sub)
            try:
                names = sorted(os.listdir(d), key=str.lower)
            except OSError:
                continue
            lower = {n.lower() for n in names}
            for n in names:
                stem, ext = os.path.splitext(n)
                if ext.lower() != ".iso":
                    continue
                path = os.path.join(d, n)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                status = "ZSO exists" if (stem + ".zso").lower() in lower else ""
                iid = tv.insert("", "end", text=stem, values=(sub, human(size), status))
                self.items[iid] = {"path": path, "size": size, "done": bool(status)}
                if not status:
                    total += size
                    count += 1
        self.summary.configure(text=f"{count} ISO(s) to compress, {human(total)}. "
                                    f"Free on this drive: {human(self.free())}.")
        self._label_go()

    def free(self):
        try:
            return shutil.disk_usage(self.folder).free
        except OSError:
            return 0

    def todo_ids(self):
        return [i for i, it in self.items.items() if not it["done"]]

    def _label_go(self):
        sel = [i for i in self.tree.selection() if not self.items[i]["done"]]
        if self.thread is None:
            self.go_btn.configure(text=f"Compress {len(sel)} selected" if sel else "Compress all")

    # ---- work ----

    def go(self):
        if self.thread is not None:
            return
        ids = [i for i in self.tree.selection() if not self.items[i]["done"]] or self.todo_ids()
        if not ids:
            messagebox.showinfo("Compress games", "Nothing left to compress.", parent=self.win)
            return
        if self.delete.get() and not messagebox.askyesno(
                "Compress games", f"Each of the {len(ids)} ISO(s) is deleted for good once its ZSO "
                "has been checked.\n\nGo ahead?", parent=self.win):
            return
        self.cancel.clear()
        self.go_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        jobs = [(i, self.items[i]["path"], self.items[i]["size"]) for i in ids]
        self.thread = threading.Thread(target=self.work, args=(jobs, self.delete.get()), daemon=True)
        self.thread.start()

    def stop(self):
        self.cancel.set()
        self.stop_btn.configure(state="disabled")
        self.now.configure(text="Stopping after this block...")

    def work(self, jobs, delete):
        total = sum(j[2] for j in jobs) or 1
        before = 0
        for iid, path, size in jobs:
            if self.cancel.is_set():
                break
            self.q.put(("status", iid, "working..."))
            if self.free() < size + (64 << 20):
                self.q.put(("status", iid, "not enough free space"))
                self.q.put(("msg", "Not enough free space for the next ZSO. Free some space, or tick "
                                   "'Delete each ISO' so each ISO makes room for the next one."))
                break
            name = os.path.basename(path)

            def prog(done, sz, phase, base=before):
                # compress counts as 80% of a file's time, the check 20%
                part = done / sz * (0.8 if phase == "compress" else 0.2) + (0.8 if phase == "verify" else 0)
                self.q.put(("progress", name, phase, part, (base + part * size) / total))

            try:
                try:
                    isz, zsz = self.zso.compress_iso(path, progress=prog, cancel=self.cancel)
                except self.zso.NotWorthIt:
                    self.q.put(("done", iid, "kept ISO (does not compress)"))
                    before += size
                    continue
                if True:
                    note = f"{human(zsz)} ({100 * zsz // isz}%)"
                    if delete:
                        try:
                            os.remove(path)
                            self.q.put(("saved", isz - zsz))
                            note += ", ISO deleted"
                        except OSError:
                            note += ", ISO in use - not deleted"
                    else:
                        self.q.put(("saved", isz - zsz))
                    self.q.put(("done", iid, note))
            except self.zso.Cancelled:
                self.q.put(("status", iid, "stopped"))
                break
            except Exception as e:
                self.q.put(("status", iid, f"failed: {e}"))
            before += size
        self.q.put(("finished",))

    def pump(self):
        if not self.win.winfo_exists():
            return
        try:
            while True:
                m = self.q.get_nowait()
                kind = m[0]
                if kind == "status":
                    self._set_status(m[1], m[2])
                elif kind == "done":
                    self.items[m[1]]["done"] = True
                    self._set_status(m[1], m[2])
                elif kind == "progress":
                    _, name, phase, part, overall = m
                    self.now.configure(text=f"{'Compressing' if phase == 'compress' else 'Checking'} {name}")
                    self.bar["value"] = part * 1000
                    self.total_bar["value"] = overall * 1000
                elif kind == "saved":
                    self.saved += m[1]
                elif kind == "msg":
                    messagebox.showwarning("Compress games", m[1], parent=self.win)
                elif kind == "finished":
                    self.thread = None
                    self.go_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.bar["value"] = 0
                    self.now.configure(text=f"Done. Saved {human(self.saved)} so far." if self.saved
                                       else "Done.")
                    self.summary.configure(text=f"Free on this drive: {human(self.free())}.")
                    self._label_go()
        except queue.Empty:
            pass
        self.win.after(150, self.pump)

    def _set_status(self, iid, text):
        if self.tree.exists(iid):
            vals = list(self.tree.item(iid, "values"))
            vals[2] = text
            self.tree.item(iid, values=vals)
            self.tree.see(iid)

    def on_close(self):
        if self.thread is not None:
            if not messagebox.askyesno("Compress games", "Stop compressing and close?\n\n"
                                       "The game being compressed keeps its ISO.", parent=self.win):
                return
            self.cancel.set()
        self.win.destroy()


def main():
    if IS_WINDOWS:
        # Its own taskbar button and icon rather than Python's.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UDPFS.Server")
        except Exception:
            pass
    root = tk.Tk()
    icon = os.path.join(HERE, "icon.png")
    if os.path.isfile(icon):
        try:
            root._icon = tk.PhotoImage(file=icon)
            root.iconphoto(True, root._icon)
        except Exception:
            pass
    try:
        ttk.Style().theme_use("vista" if IS_WINDOWS else ("aqua" if IS_MAC else "clam"))
    except Exception:
        pass
    App(root, sys.argv[1:])
    root.mainloop()


if __name__ == "__main__":
    main()
