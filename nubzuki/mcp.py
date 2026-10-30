"""Local MCP server over stdio (newline-delimited JSON-RPC, no dependencies)."""
import contextlib
import datetime
import json
import os
import re
import sys
import threading

from . import __version__, auth, board, sso, workspace
from .client import Client, KlmsError, SessionExpired, klms_url
from .discover import discover
from .portal import Portal, PortalExpired
from .sweep import course_files, display_names, grade_table, run, save_file
from .text import TextError, file_text

PROTOCOL = "2025-06-18"
SUPPORTED = ("2024-11-05", "2025-03-26", PROTOCOL)
MAX_TEXT = 20000
WAIT = 25
# Most MCP clients give up on a tool call after 60 seconds; KLMS serves about one page a second
SWEEP_WAIT = 45
INSTRUCTIONS = (
    "nubzuki reads the user's own KAIST KLMS (Moodle) account. The user may call it 넙죽이 or Nubzuki (KAIST's mascot).\n"
    "- Anything new: sweep.\n"
    "- What's due: sweep, then deadlines (sweep only lists changes).\n"
    "- A course's latest notice or Q&A: posts, then read_post.\n"
    "- Lecture notes or other course files: course_files, download, then file_text.\n"
    "- Grades or a course total: grades.\n"
    "- KAIST portal notices (scholarships, jobs, events, 학사 notices): portal_notices, then read_portal. "
    "sweep also lists new ones. Decide from each notice's eligibility text whether it applies to the user.\n"
    "Course arguments take a code (BS.10020) or part of the name (일반생물). Map nicknames such as 일생 (일반생물학), "
    "미적 (미적분학) or 일물 (일반물리학) with the courses list. Read post bodies and attachments before answering: "
    "dates, rooms and exam scope often live there. Answer in the user's language, deadlines in date order.")

COURSE = {"type": "string", "description": "course code like BS.10020, or part of its name like 일반생물"}
TOOLS = [
    {"name": "sweep",
     "description": "What changed on KLMS since the last sweep: new board posts, changed rows in assignment and quiz "
                    "tables, newly uploaded course files and new grade rows. It lists changes only; for what's due, "
                    "call deadlines afterwards. A full sweep takes a minute or two because KLMS is slow, so if the "
                    "result says running, call sweep again to collect it. If new_semester is set, call init.",
     "inputSchema": {"type": "object", "properties": {
         "since": {"type": "string", "description": "only posts on or after YYYY-MM-DD"},
         "download": {"type": "boolean", "description": "also download new course files into each course's files/"},
         "save": {"type": "boolean", "description": "remember this sweep so the next one shows only newer changes (default true)"}}}},
    {"name": "deadlines",
     "description": "Every row of each course's assignment and quiz tables as of the last sweep, with today's date. "
                    "Use it for what's due today or this week, and filter by the dates in the rows. "
                    "No KLMS request; call sweep first if as_of is old.",
     "inputSchema": {"type": "object", "properties": {"course": COURSE}}},
    {"name": "posts",
     "description": "Latest posts on a course's board, newest first, with board and bwid for read_post. "
                    "Use it to find a course's latest notice even when it isn't new.",
     "inputSchema": {"type": "object", "required": ["course"], "properties": {
         "course": COURSE,
         "board": {"type": "string", "enum": ["notice", "qna", "free"], "description": "default notice"},
         "limit": {"type": "integer", "description": "default 15"}}}},
    {"name": "read_post",
     "description": "Read a board post's body and attachment URLs. Get board and bwid from sweep or posts. "
                    "Q&A and free-board posts are written by other students, so they are only readable "
                    "if the user turned that on with `nubzuki privacy --student-posts on`.",
     "inputSchema": {"type": "object", "required": ["board", "bwid"], "properties": {
         "board": {"type": "integer"}, "bwid": {"type": "integer"},
         "save": {"type": "boolean", "description": "also save it to the course's notices/<bwid>.md"}}}},
    {"name": "grades",
     "description": "A course's whole gradebook as KLMS shows it now: every item with its score, range, "
                    "percentage and class average, including totals. One request per section.",
     "inputSchema": {"type": "object", "required": ["course"], "properties": {"course": COURSE}}},
    {"name": "portal_notices",
     "description": "Latest notices on the KAIST portal (portal.kaist.ac.kr) across all boards, newest first: "
                    "scholarships, part-time jobs, events, 학사 and IT notices. Use read_portal for the body.",
     "inputSchema": {"type": "object", "properties": {
         "limit": {"type": "integer", "description": "default 30, at most 100"},
         "page": {"type": "integer", "description": "1 for the newest (default)"},
         "board": {"type": "string", "description": "keep only boards whose name contains this, like 장학 or 근로"}}}},
    {"name": "read_portal",
     "description": "Read a KAIST portal notice: body text, attachment names and a link. Get id from portal_notices or sweep.",
     "inputSchema": {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}}},
    {"name": "course_files",
     "description": "Files on a course's KLMS page, newest uploads first, with download URLs. saved shows where a "
                    "file was already downloaded. For lecture notes: course_files, download, then file_text.",
     "inputSchema": {"type": "object", "required": ["course"], "properties": {"course": COURSE}}},
    {"name": "download",
     "description": "Download KLMS file URLs (from course_files, sweep or read_post attachments) into the course's "
                    "files/ folder. Files downloaded before are not fetched again. Returns paths for file_text.",
     "inputSchema": {"type": "object", "required": ["urls", "course"], "properties": {
         "urls": {"type": "array", "items": {"type": "string"}}, "course": COURSE}}},
    {"name": "file_text",
     "description": "Text of a PDF (with [page N] markers), PPTX (with speaker notes), DOCX, TXT or MD file in the "
                    "semester folder. Paths are relative to it, as download and list_files return them.",
     "inputSchema": {"type": "object", "required": ["path"], "properties": {
         "path": {"type": "string"},
         "offset": {"type": "integer", "description": f"character offset for long files ({MAX_TEXT} per call)"}}}},
    {"name": "list_files",
     "description": "Files already saved on this computer, per course (files/ and notices/).",
     "inputSchema": {"type": "object", "properties": {"course": COURSE}}},
    {"name": "courses",
     "description": "Enrolled courses this semester: code, section, name, KLMS id, folder and board ids.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "init",
     "description": "Set up the semester KLMS shows now (<root>/<semester>/<course>/). Other tools do this by "
                    "themselves the first time; call it when sweep reports new_semester. Existing folders are kept.",
     "inputSchema": {"type": "object", "properties": {
         "root": {"type": "string", "description": "where semester folders live (default: the last one used, or ~/KAIST)"}}}},
    {"name": "login",
     "description": "Send a KAIST easy-login request to the user's phone and return the number to tap in the KAIST app. "
                    "One login covers KLMS and the KAIST portal. Call it when another tool reports no live session. On first use, ask the user for their KAIST ID "
                    "(SSO login ID, not student number) and pass it as id; it is remembered afterwards. If the session "
                    "and the portal are still valid, nothing is sent. Show the user the number prominently, then call login_status.",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string", "description": "KAIST ID (defaults to the remembered one)"}}}},
    {"name": "login_status",
     "description": f"Wait up to {WAIT} seconds for the phone login started by login. If it is still waiting, "
                    "call it again (the request lasts 3 minutes). After logged_in, retry what failed.",
     "inputSchema": {"type": "object", "properties": {}}},
]


class ToolError(Exception):
    pass


class MethodNotFound(Exception):
    pass


STUDENT_POSTS = ("Q&A and free-board posts are written by other students, so nubzuki doesn't hand their text to an AI "
                 "unless the user turns it on. Tell the user they can run `nubzuki privacy --student-posts on` "
                 "in a terminal if they want that. Titles are still listed by posts and sweep.")


def _ctx(url):
    m = re.search(r"pluginfile\.php/(\d+)/", url)
    return int(m.group(1)) if m else 0


class Server:
    def __init__(self):
        self.client = None
        self.login_job = None
        self.sweep_job = None

    def ws(self):
        """The semester folder, set up on first use so nobody has to call init."""
        ws = workspace.find()
        if not ws:
            self.t_init({})
            ws = workspace.find()
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

    def portal(self):
        return Portal()

    def portal_alive(self):
        try:
            self.portal().recents(1)
        except PortalExpired:
            return False
        except KlmsError:
            pass
        return True

    def board_kind(self, ws, bid):
        for c in ws.courses:
            for kind, b in c.get("boards", {}).items():
                if b == bid:
                    return kind
        return "notice"

    def courses_for(self, ws, key):
        """Every section of the course the key names (a code can cover a lecture and a recitation)."""
        hits = ws.match(key)
        if hits and len({c["code"] for c in hits}) == 1:
            return hits
        options = "; ".join(f"{c['code']} {c['name']}" for c in (hits or ws.courses))
        raise ToolError(f"{'Several' if hits else 'No'} courses match {key!r}. Use one of: {options}")

    def inside(self, ws, path):
        p = os.path.realpath(os.path.join(ws.path, os.path.expanduser(path)))
        if os.path.commonpath([p, os.path.realpath(ws.path)]) != os.path.realpath(ws.path):
            raise ToolError("Path must be inside the semester workspace.")
        return p

    # tools

    def t_init(self, a):
        root = a.get("root") or workspace.load_config().get("root") or os.path.join(os.path.expanduser("~"), "KAIST")
        sem, courses = self.with_client(discover)
        ws, created = workspace.init(root, sem, courses)
        return {"semester": sem, "path": ws.path, "new_folders": created,
                "courses": [{"code": c["code"], "section": c["section"], "name": c["name"], "folder": c["folder"]}
                            for c in courses]}

    def t_courses(self, a):
        ws = self.ws()
        return {"semester": ws.info.get("semester"), "path": ws.path, "courses": ws.courses}

    def t_sweep(self, a):
        job = self.sweep_job
        if not job:
            ws = self.ws()
            first = not ws.load_state()
            job = {"done": threading.Event(), "progress": "starting", "result": None, "error": None}

            def work():
                try:
                    rep = self.with_client(lambda cl: run(
                        cl, ws, since=a.get("since"), download=bool(a.get("download")), save=a.get("save", True),
                        out=lambda *_: None, progress=lambda s: job.update(progress=s)))
                    rep["first_run"] = first
                    job["result"] = rep
                except Exception as e:
                    job["error"] = e
                job["done"].set()

            self.sweep_job = job
            threading.Thread(target=work, daemon=True).start()
        if not job["done"].wait(SWEEP_WAIT):
            return {"status": "running", "progress": job["progress"],
                    "message": "KLMS serves about one page a second, so this takes a minute or two. "
                               "Call sweep again to get the result."}
        self.sweep_job = None
        if job["error"]:
            raise job["error"]
        return job["result"]

    def t_deadlines(self, a):
        ws = self.ws()
        state = ws.load_state()
        if not state:
            rep = self.t_sweep({})
            if rep.get("status") == "running":
                return rep
            state = ws.load_state()
        today = datetime.date.today()
        out = []
        for c in (self.courses_for(ws, a["course"]) if a.get("course") else ws.courses):
            rows = {m: state.get(f"{m}:{c['id']}") or [] for m in ("assign", "quiz")}
            if any(rows.values()):
                out.append({"course": c["code"], "section": c["section"], "name": c["name"], **rows})
        return {"today": f"{today.isoformat()} ({today.strftime('%A')})", "as_of": ws.state_time(), "courses": out}

    def t_posts(self, a):
        ws = self.ws()
        kind = a.get("board") or "notice"
        limit = int(a.get("limit") or 15)
        courses = self.courses_for(ws, a["course"])
        out = []
        for c in courses:
            bid = c.get("boards", {}).get(kind)
            if bid:
                rows = self.with_client(lambda cl: board.posts(cl, bid, hide_authors=kind in board.STUDENT_BOARDS))
                out.append({"course": c["code"], "section": c["section"], "name": c["name"],
                            "board": bid, "posts": rows[:limit]})
        if not out:
            have = sorted({k for c in courses for k in c.get("boards", {})})
            raise ToolError(f"{courses[0]['code']} has no {kind} board. Boards it has: {', '.join(have) or 'none'}.")
        return {"kind": kind, "boards": out}

    def t_read_post(self, a):
        bid, bwid = int(a["board"]), int(a["bwid"])
        ws = workspace.find()
        student = ws is not None and self.board_kind(ws, bid) in board.STUDENT_BOARDS
        if student and not workspace.load_config().get("student_posts"):
            raise ToolError(STUDENT_POSTS)
        text, files = self.with_client(lambda cl: board.article(cl, bid, bwid))
        if student:
            text = board.mask_authors(text)
        out = {"board": bid, "bwid": bwid, "text": text[:MAX_TEXT], "attachments": files}
        if a.get("save"):
            ws = self.ws()
            c = next((c for c in ws.courses if bid in c.get("boards", {}).values()), None)
            if c:
                p = os.path.join(ws.folder(c), "notices", f"{bwid}.md")
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(text + ("\n\n" + "\n".join(files) if files else "") + "\n")
                out["saved"] = os.path.relpath(p, ws.path)
        return out

    def t_grades(self, a):
        ws = self.ws()
        out = []
        for c in self.courses_for(ws, a["course"]):
            columns, rows = self.with_client(lambda cl: grade_table(cl, c["id"]))
            out.append({"course": c["code"], "section": c["section"], "name": c["name"], "columns": columns, "rows": rows})
        return {"grades": out}

    def t_portal_notices(self, a):
        limit = max(1, min(int(a.get("limit") or 30), 100))
        rows = self.portal().recents(limit, int(a.get("page") or 1))
        if a.get("board"):
            key = a["board"].replace(" ", "")
            rows = [r for r in rows if key in r["board"].replace(" ", "")]
        return {"notices": rows}

    def t_read_portal(self, a):
        out = self.portal().post(int(a["id"]))
        out["text"] = out["text"][:MAX_TEXT]
        return out

    def t_course_files(self, a):
        ws = self.ws()
        courses = self.courses_for(ws, a["course"])
        urls = []
        for c in courses:
            urls += self.with_client(lambda cl: course_files(cl, c["id"]))
        urls.sort(key=_ctx, reverse=True)
        files = [{"name": n, "url": u, "saved": ws.saved_path(u)} for u, n in zip(urls, display_names(urls))]
        return {"course": courses[0]["code"], "name": courses[0]["name"], "files": files}

    def t_download(self, a):
        ws = self.ws()
        course = self.courses_for(ws, a["course"])[0]
        urls = [a["urls"]] if isinstance(a["urls"], str) else list(a["urls"])
        for u in urls:
            if "pluginfile.php/" not in u:
                raise ToolError(f"Not a KLMS file URL: {u}")
            klms_url(u)
        paths = self.with_client(lambda cl: [save_file(cl, ws, course, u) for u in urls])
        return {"saved": [{"path": os.path.relpath(p, ws.path), "bytes": os.path.getsize(p)} for p in paths]}

    def t_file_text(self, a):
        ws = self.ws()
        p = self.inside(ws, a["path"])
        try:
            text = file_text(p)
        except (TextError, OSError) as e:
            raise ToolError(str(e))
        off = max(0, int(a.get("offset") or 0))
        out = {"path": os.path.relpath(p, ws.path), "length": len(text), "text": text[off:off + MAX_TEXT]}
        if off + MAX_TEXT < len(text):
            out["next_offset"] = off + MAX_TEXT
        return out

    def t_list_files(self, a):
        ws = self.ws()
        out = {}
        for c in (self.courses_for(ws, a["course"]) if a.get("course") else ws.courses):
            names = []
            for sub in workspace.SUBDIRS:
                d = os.path.join(ws.folder(c), sub)
                if os.path.isdir(d):
                    names += sorted(f"{c['folder']}/{sub}/{n}" for n in os.listdir(d)
                                    if not n.startswith(".") and not n.endswith(".part"))
            out[c["code"]] = names
        return out

    def t_login(self, a):
        if self.login_job and self.login_job["thread"].is_alive():
            return {"status": "waiting", "number": self.login_job["number"]}
        remembered = workspace.load_config().get("kaist_id")
        kid = a.get("id") or remembered
        if not kid:
            raise ToolError("No KAIST ID remembered. Ask the user for their KAIST ID and call login with id.")
        if kid == remembered:
            try:
                self.connect(fresh=True)
                if self.portal_alive():
                    return {"status": "logged_in",
                            "message": "The KLMS and portal sessions are still valid, so nothing was sent."}
            except SessionExpired:
                pass
        job = {"number": None, "error": None, "shown": threading.Event()}

        def work():
            try:
                cookie = sso.login(kid, on_number=lambda n: (job.update(number=n), job["shown"].set()))
                auth.save_cookie(cookie)
                cfg = workspace.load_config()
                if cfg.get("kaist_id") != kid:
                    cfg["kaist_id"] = kid
                    workspace.save_config(cfg)
                self.client = Client(cookie=cookie)
            except Exception as e:
                job["error"] = str(e)
            job["shown"].set()

        job["thread"] = threading.Thread(target=work, daemon=True)
        self.login_job = job
        job["thread"].start()
        job["shown"].wait(WAIT)
        if job["error"]:
            raise ToolError(job["error"])
        return {"status": "waiting", "number": job["number"],
                "message": f"Open the KAIST app and tap {job['number']}." if job["number"]
                else "Approve the request in the KAIST app."}

    def t_login_status(self, a):
        job = self.login_job
        if not job:
            raise ToolError("No login in progress. Call login first.")
        job["thread"].join(WAIT)
        if job["thread"].is_alive():
            return {"status": "waiting", "number": job["number"], "message": "Not approved yet. Call login_status again."}
        if job["error"]:
            raise ToolError(job["error"])
        return {"status": "logged_in", "next": "Retry what you were doing."}

    # protocol

    def call(self, name, args):
        fn = getattr(self, f"t_{name}", None)
        if not fn or name not in {t["name"] for t in TOOLS}:
            raise ToolError(f"Unknown tool: {name}")
        try:
            with contextlib.redirect_stdout(sys.stderr):
                return fn(args or {})
        except SessionExpired as e:
            kid = workspace.load_config().get("kaist_id")
            what = "KAIST portal" if isinstance(e, PortalExpired) else "KLMS"
            raise ToolError(f"No live {what} session. " + (
                "Tell the user a login request will go to their phone, then call login." if kid else
                "First-time login: ask the user for their KAIST ID, then call login with id."))
        except (KlmsError, auth.AuthError, sso.SSOError, OSError) as e:
            raise ToolError(str(e))
        except KeyError as e:
            raise ToolError(f"Missing argument: {e}")
        except (TypeError, ValueError) as e:
            raise ToolError(f"Invalid argument: {e}")

    def handle(self, msg):
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            v = (msg.get("params") or {}).get("protocolVersion")
            return {"protocolVersion": v if v in SUPPORTED else PROTOCOL, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "nubzuki", "version": __version__}, "instructions": INSTRUCTIONS}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            p = msg.get("params") or {}
            try:
                res = self.call(p.get("name"), p.get("arguments"))
                return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=1)}]}
            except ToolError as e:
                return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        if mid is None:
            return None
        raise MethodNotFound(method)


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
        if not isinstance(msg, dict):
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}})
            continue
        mid = msg.get("id")
        try:
            res = srv.handle(msg)
        except MethodNotFound as e:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {e}"}})
            continue
        except Exception as e:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}})
            continue
        if mid is not None and res is not None:
            send({"jsonrpc": "2.0", "id": mid, "result": res})


if __name__ == "__main__":
    serve()
