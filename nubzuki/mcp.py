"""Local MCP server over stdio (newline-delimited JSON-RPC, no dependencies)."""
import contextlib
import json
import os
import sys
import threading

from . import __version__, auth, board, sso, workspace
from .client import Client, KlmsError, SessionExpired, filename_of
from .sweep import run, unique
from .text import TextError, file_text

PROTOCOL = "2025-06-18"
MAX_TEXT = 50000

TOOLS = [
    {"name": "courses",
     "description": "List enrolled courses in the current semester workspace with course IDs, folders and "
                    "Notices / Q&A / free board IDs.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "sweep",
     "description": "Show only what changed on KLMS since the last sweep: new board posts, assignment/quiz "
                    "table changes, new course files and new grade rows. Saves the new state unless save=false. "
                    "Read new posts with read_post afterwards; titles alone are rarely enough.",
     "inputSchema": {"type": "object", "properties": {
         "since": {"type": "string", "description": "only posts on or after YYYY-MM-DD"},
         "download": {"type": "boolean", "description": "download new course files into each course's files/"},
         "save": {"type": "boolean", "description": "save state so the next sweep shows only newer changes (default true)"}}}},
    {"name": "read_post",
     "description": "Read a board post's body and attachment URLs. Get board and bwid from sweep or courses.",
     "inputSchema": {"type": "object", "required": ["board", "bwid"], "properties": {
         "board": {"type": "integer"}, "bwid": {"type": "integer"},
         "save": {"type": "boolean", "description": "also save it to the course's notices/<bwid>.md"}}}},
    {"name": "download",
     "description": "Download KLMS attachment URLs (pluginfile.php links) into a course's files/ folder.",
     "inputSchema": {"type": "object", "required": ["urls", "course"], "properties": {
         "urls": {"type": "array", "items": {"type": "string"}},
         "course": {"type": "string", "description": "course code or folder, e.g. CS.10001"}}}},
    {"name": "file_text",
     "description": "Extract text from a PDF, PPTX (with speaker notes), TXT or MD file inside the workspace. "
                    "Paths are relative to the semester folder, e.g. CS.10001/files/week9.pdf.",
     "inputSchema": {"type": "object", "required": ["path"], "properties": {
         "path": {"type": "string"},
         "offset": {"type": "integer", "description": f"character offset for long files ({MAX_TEXT} per call)"}}}},
    {"name": "list_files",
     "description": "List files already saved in the workspace (course files/ and notices/ folders).",
     "inputSchema": {"type": "object", "properties": {
         "course": {"type": "string", "description": "limit to one course code or folder"}}}},
    {"name": "login",
     "description": "Send a KAIST easy-login request to the user's phone and return the number to tap. "
                    "Only call this when another tool reports an expired session, and never twice in a row "
                    "without the user asking: each call pushes a notification to their phone. "
                    "Tell the user the number, then call login_status.",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string", "description": "KAIST ID (defaults to the remembered one)"}}}},
    {"name": "login_status",
     "description": "Wait up to 60 seconds for the phone login started by login to finish and report the result.",
     "inputSchema": {"type": "object", "properties": {}}},
]


class ToolError(Exception):
    pass


class Server:
    def __init__(self):
        self.client = None
        self.login_job = None

    def ws(self):
        ws = workspace.find()
        if not ws:
            raise ToolError("No workspace found. Ask the user to run `nubzuki init` once.")
        return ws

    def connect(self, fresh=False):
        if self.client and not fresh:
            return self.client
        self.client = None
        for cookie in auth.cookie_candidates():
            cl = Client(cookie=cookie)
            try:
                cl.check()
            except SessionExpired:
                continue
            self.client = cl
            return cl
        raise SessionExpired("No live KLMS session.")

    def with_client(self, fn):
        try:
            return fn(self.connect())
        except SessionExpired:
            return fn(self.connect(fresh=True))

    def course(self, ws, key):
        for c in ws.courses:
            if key.upper() in (c["code"].upper(), c["folder"].upper()) or key == str(c["id"]):
                return c
        raise ToolError(f"Unknown course {key!r}. Use the courses tool for valid codes.")

    def inside(self, ws, path):
        p = os.path.realpath(os.path.join(ws.path, os.path.expanduser(path)))
        if os.path.commonpath([p, os.path.realpath(ws.path)]) != os.path.realpath(ws.path):
            raise ToolError("Path must be inside the semester workspace.")
        return p

    # tools

    def t_courses(self, a):
        ws = self.ws()
        return {"semester": ws.info.get("semester"), "path": ws.path, "courses": ws.courses}

    def t_sweep(self, a):
        ws = self.ws()
        first = not ws.load_state()
        rep = self.with_client(lambda cl: run(cl, ws, since=a.get("since"), download=bool(a.get("download")),
                                              save=a.get("save", True), out=lambda *_: None))
        rep["first_run"] = first
        return rep

    def t_read_post(self, a):
        bid, bwid = int(a["board"]), int(a["bwid"])
        text, files = self.with_client(lambda cl: board.article(cl, bid, bwid))
        out = {"board": bid, "bwid": bwid, "text": text[:MAX_TEXT], "attachments": files}
        if a.get("save"):
            ws = self.ws()
            c = next((c for c in ws.courses if bid in c.get("boards", {}).values()), None)
            if c:
                p = os.path.join(ws.folder(c), "notices", f"{bwid}.md")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(text + ("\n\n" + "\n".join(files) if files else "") + "\n")
                out["saved"] = os.path.relpath(p, ws.path)
        return out

    def t_download(self, a):
        ws = self.ws()
        c = self.course(ws, a["course"])
        d = os.path.join(ws.folder(c), "files")
        os.makedirs(d, exist_ok=True)
        cl = self.connect()
        saved = []
        for u in a["urls"]:
            if "pluginfile.php" not in u:
                raise ToolError(f"Not a KLMS file URL: {u}")
            dest = unique(os.path.join(d, workspace.safe(filename_of(u))))
            cl.download(u, dest)
            saved.append({"path": os.path.relpath(dest, ws.path), "bytes": os.path.getsize(dest)})
        return {"saved": saved}

    def t_file_text(self, a):
        ws = self.ws()
        p = self.inside(ws, a["path"])
        try:
            text = file_text(p)
        except (TextError, OSError) as e:
            raise ToolError(str(e))
        off = int(a.get("offset") or 0)
        chunk = text[off:off + MAX_TEXT]
        out = {"path": os.path.relpath(p, ws.path), "length": len(text), "text": chunk}
        if off + MAX_TEXT < len(text):
            out["next_offset"] = off + MAX_TEXT
        return out

    def t_list_files(self, a):
        ws = self.ws()
        courses = [self.course(ws, a["course"])] if a.get("course") else ws.courses
        out = {}
        for c in courses:
            names = []
            for sub in workspace.SUBDIRS:
                d = os.path.join(ws.folder(c), sub)
                if os.path.isdir(d):
                    names += sorted(f"{c['folder']}/{sub}/{n}" for n in os.listdir(d) if not n.startswith("."))
            out[c["code"]] = names
        return out

    def t_login(self, a):
        if self.login_job and self.login_job["thread"].is_alive():
            return {"status": "waiting", "number": self.login_job["number"]}
        kid = a.get("id") or workspace.load_config().get("kaist_id")
        if not kid:
            raise ToolError("No KAIST ID remembered. Pass id, or ask the user to run `nubzuki login` once.")
        job = {"number": None, "cookie": None, "error": None, "shown": threading.Event()}

        def work():
            try:
                job["cookie"] = sso.login(kid, on_number=lambda n: (job.update(number=n), job["shown"].set()))
            except Exception as e:
                job["error"] = str(e)
            job["shown"].set()

        job["thread"] = threading.Thread(target=work, daemon=True)
        self.login_job = job
        job["thread"].start()
        job["shown"].wait(60)
        if job["error"]:
            raise ToolError(job["error"])
        return {"status": "waiting", "number": job["number"],
                "message": f"Open the KAIST app and tap {job['number']}." if job["number"]
                else "Approve the request in the KAIST app."}

    def t_login_status(self, a):
        job = self.login_job
        if not job:
            raise ToolError("No login in progress. Call login first.")
        job["thread"].join(60)
        if job["thread"].is_alive():
            return {"status": "waiting", "number": job["number"]}
        if job["error"]:
            raise ToolError(job["error"])
        if job["cookie"]:
            auth.save_cookie(job["cookie"])
            cfg = workspace.load_config()
            self.client = Client(cookie=job["cookie"])
            job["cookie"] = None
            return {"status": "logged_in", "kaist_id": cfg.get("kaist_id")}
        return {"status": "logged_in"}

    # protocol

    def call(self, name, args):
        fn = getattr(self, f"t_{name}", None)
        if not fn or name not in {t["name"] for t in TOOLS}:
            raise ToolError(f"Unknown tool: {name}")
        try:
            with contextlib.redirect_stdout(sys.stderr):
                return fn(args or {})
        except SessionExpired:
            raise ToolError("KLMS session expired. Ask the user whether to send a login request to their phone "
                            "(login tool), or have them run `nubzuki login` in a terminal.")
        except (KlmsError, auth.AuthError, sso.SSOError) as e:
            raise ToolError(str(e))

    def handle(self, msg):
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            v = msg.get("params", {}).get("protocolVersion") or PROTOCOL
            return {"protocolVersion": v, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "nubzuki", "version": __version__}}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            p = msg.get("params", {})
            try:
                res = self.call(p.get("name"), p.get("arguments"))
                return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=1)}]}
            except ToolError as e:
                return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        if mid is None:
            return None
        raise LookupError(method)


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve(stdin=None):
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    srv = Server()
    for line in stdin or sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        mid = msg.get("id")
        try:
            res = srv.handle(msg)
        except LookupError as e:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {e}"}})
            continue
        except Exception as e:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}})
            continue
        if mid is not None and res is not None:
            send({"jsonrpc": "2.0", "id": mid, "result": res})


if __name__ == "__main__":
    serve()
