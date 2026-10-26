import json
import os
import re

from .auth import CONFIG_DIR

CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
META = ".nubzuki"


def load_config():
    if os.path.exists(CONFIG_FILE):
        return json.load(open(CONFIG_FILE))
    return {}


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    json.dump(cfg, open(CONFIG_FILE, "w"), ensure_ascii=False, indent=2)


def safe(name):
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "_"


class Workspace:
    def __init__(self, path):
        self.path = path
        self.meta = os.path.join(path, META)
        self.info_file = os.path.join(self.meta, "workspace.json")
        self.state_file = os.path.join(self.meta, "state.json")
        self.info = json.load(open(self.info_file)) if os.path.exists(self.info_file) else {}

    @property
    def courses(self):
        return self.info.get("courses", [])

    def folder(self, course):
        return os.path.join(self.path, course["folder"])

    def save(self):
        os.makedirs(self.meta, exist_ok=True)
        json.dump(self.info, open(self.info_file, "w"), ensure_ascii=False, indent=2)

    def load_state(self):
        if os.path.exists(self.state_file):
            return json.load(open(self.state_file))
        return {}

    def save_state(self, state):
        os.makedirs(self.meta, exist_ok=True)
        if os.path.exists(self.state_file):
            os.replace(self.state_file, self.state_file + ".bak")
        json.dump(state, open(self.state_file, "w"), ensure_ascii=False)


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
