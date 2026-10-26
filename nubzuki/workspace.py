import json
import os
import re
import shutil
import time
import urllib.parse

from .auth import CONFIG_DIR

CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
META = ".nubzuki"


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data, **kw):
    """Write through a temp file, so a crash or full disk never leaves half a JSON file behind."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, **kw)
    os.replace(tmp, path)


def load_config():
    if os.path.exists(CONFIG_FILE):
        return read_json(CONFIG_FILE)
    return {}


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    write_json(CONFIG_FILE, cfg, indent=2)


def safe(name):
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "_"


class Workspace:
    def __init__(self, path):
        self.path = path
        self.meta = os.path.join(path, META)
        self.info_file = os.path.join(self.meta, "workspace.json")
        self.state_file = os.path.join(self.meta, "state.json")
        self.downloads_file = os.path.join(self.meta, "downloads.json")
        self.info = read_json(self.info_file) if os.path.exists(self.info_file) else {}

    @property
    def courses(self):
        return self.info.get("courses", [])

    def folder(self, course):
        return os.path.join(self.path, course["folder"])

    def save(self):
        os.makedirs(self.meta, exist_ok=True)
        write_json(self.info_file, self.info, indent=2)

    def load_state(self):
        for p in (self.state_file, self.state_file + ".bak"):
            if os.path.exists(p):
                try:
                    return read_json(p)
                except ValueError:
                    continue
        return {}

    def state_time(self):
        """When the last sweep saved its state, as local ISO time, or None."""
        if not os.path.exists(self.state_file):
            return None
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(self.state_file)))

    def save_state(self, state):
        os.makedirs(self.meta, exist_ok=True)
        if os.path.exists(self.state_file):
            shutil.copy2(self.state_file, self.state_file + ".bak")
        write_json(self.state_file, state)

    def match(self, key):
        """Courses matching a code, folder, KLMS id or part of the name.
        Sections of one course (e.g. lecture and recitation) share a code, so this can return several."""
        k = str(key).replace(" ", "").upper()
        exact = [c for c in self.courses if k in (c["code"].upper(), c["folder"].upper(), str(c["id"]))]
        return exact or [c for c in self.courses if k and k in c["name"].replace(" ", "").upper()]

    def saved_path(self, url):
        """Where a KLMS file URL was downloaded before, if the file is still there."""
        try:
            rel = read_json(self.downloads_file).get(file_key(url))
        except (OSError, ValueError):
            return None
        return rel if rel and os.path.exists(os.path.join(self.path, rel)) else None

    def remember_download(self, url, dest):
        try:
            seen = read_json(self.downloads_file)
        except (OSError, ValueError):
            seen = {}
        seen[file_key(url)] = os.path.relpath(dest, self.path)
        os.makedirs(self.meta, exist_ok=True)
        write_json(self.downloads_file, seen, indent=1)


def file_key(url):
    """The same file can come as an absolute, relative or %-encoded URL; key them all the same way."""
    i = url.find("pluginfile.php/")
    return urllib.parse.unquote((url[i:] if i >= 0 else url).split("?")[0])


def find(start=None):
    p = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isdir(os.path.join(p, META)):
            return Workspace(p)
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    cfg = load_config()
    if cfg.get("root") and cfg.get("current"):
        w = os.path.join(cfg["root"], cfg["current"])
        if os.path.isdir(os.path.join(w, META)):
            return Workspace(w)
    return None


SUBDIRS = ("files", "notices")


def init(root, semester, courses):
    root = os.path.abspath(os.path.expanduser(root))
    ws = Workspace(os.path.join(root, semester))
    os.makedirs(ws.path, exist_ok=True)

    old = {c["id"]: c for c in ws.courses}
    created = []
    for c in courses:
        c["folder"] = old.get(c["id"], {}).get("folder") or safe(c["code"])
        d = ws.folder(c)
        if not os.path.isdir(d):
            created.append(c["folder"])
        for sub in SUBDIRS:
            os.makedirs(os.path.join(d, sub), exist_ok=True)

    ws.info = {"semester": semester, "courses": courses}
    ws.save()

    cfg = load_config()
    cfg.update(root=root, current=semester)
    save_config(cfg)
    return ws, sorted(set(created))
