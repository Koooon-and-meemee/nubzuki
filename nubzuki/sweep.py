import datetime
import html as H
import os
import re
import urllib.parse
from collections import Counter

from . import board, workspace
from .client import KlmsError, filename_of
from .discover import semester_of
from .portal import Portal, PortalExpired
from .text import table_rows

GRADE_SKIP = ("성적 항목", "합계", "Grade item", "Course total")
TABLE_HEAD = ("No", "번호", "주차", "Topic", "Week")
RECENT_DAYS = 7
PORTAL_KEEP = 300
BOARD_LABEL = {"notice": "Notices", "qna": "Q&A", "free": "Board"}


def course_files(client, cid):
    h = H.unescape(client.get(f"/course/view.php?id={cid}"))
    found = re.findall(r'pluginfile\.php/\d+/mod_resource[^"\'<>\s]*', h)
    return sorted({urllib.parse.unquote(u).split("?")[0] for u in found})


def module_table(client, mod, cid):
    h = client.get(f"/mod/{mod}/index.php?id={cid}")
    rows = []
    for t in re.findall(r'(?is)<table[^>]*>.*?</table>', h):
        if f"/mod/{mod}/view.php" not in t:
            continue
        for cells in table_rows(t):
            if cells[0] in TABLE_HEAD:
                continue
            cells = [c for c in cells if c]
            if cells and cells[0].isdigit():
                cells = cells[1:]
            if cells:
                rows.append(" | ".join(cells))
    return rows


def grade_rows(client, cid):
    h = client.get(f"/grade/report/user/index.php?id={cid}")
    rows = []
    for cells in table_rows(h):
        if len(cells) < 2 or not cells[0]:
            continue
        line = " | ".join(cells)
        if not any(k in line for k in GRADE_SKIP):
            rows.append(line[:200])
    return rows


def grade_table(client, cid):
    h = client.get(f"/grade/report/user/index.php?id={cid}")
    columns, rows = [], []
    for cells in table_rows(h):
        if not cells or not cells[0]:
            continue
        if cells[0] in GRADE_SKIP[::2]:
            columns = cells
        elif len(cells) > 1:
            rows.append(cells)
        else:
            rows.append([cells[0]])
    return columns, rows


def display_names(urls):
    seen = Counter()
    out = []
    for u in urls:
        name = filename_of(u)
        seen[name] += 1
        if seen[name] > 1:
            base, ext = os.path.splitext(name)
            name = f"{base} ({seen[name]}){ext}"
        out.append(name)
    return out


def unique(path):
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(path):
        path = f"{base} ({i}){ext}"
        i += 1
    return path


def save_file(client, ws, course, url):
    """Download a course file into <course>/files/, or return where it was saved before."""
    rel = ws.saved_path(url)
    if rel:
        return os.path.join(ws.path, rel)
    d = os.path.join(ws.folder(course), "files")
    os.makedirs(d, exist_ok=True)
    plain = os.path.join(d, workspace.safe(filename_of(url)))
    # a same-named file from before the download index existed is reused when its size matches
    dest = client.download(url, unique(plain), same_as=plain if os.path.exists(plain) else None)
    ws.remember_download(url, dest)
    return dest


def new_semester(dash, ws):
    """The semester the dashboard shows, if it differs from the workspace's (time to run `nubzuki init`)."""
    try:
        sem = semester_of(dash)
    except KlmsError:
        return None
    return sem if ws.info.get("semester") and sem != ws.info["semester"] else None


def portal_changes(old, new, report, portal):
    pc = portal or Portal()
    if "portal" not in old:
        rows = pc.recents()
        new["portal"] = [r["id"] for r in rows]
        report["portal_note"] = f"Started following portal notices: {len(rows)} recent ones saved as already seen."
        return []
    fresh = pc.since(set(old["portal"]))
    new["portal"] = ([r["id"] for r in fresh] + old["portal"])[:PORTAL_KEEP]
    report["portal"] = fresh
    return fresh


def run(client, ws, since=None, download=False, show_all=False, save=True, out=print, progress=None, portal=None):
    """Compare KLMS with the last saved state. Requests go one at a time:
    Moodle locks the session per request, so running two at once is no faster."""
    step = progress or (lambda *_: None)
    dash = client.check()
    old = ws.load_state()
    first = not old and not show_all
    if first and not since:
        since = (datetime.date.today() - datetime.timedelta(days=RECENT_DAYS)).isoformat()
    say = (lambda *_: None) if first else out
    counts = Counter()
    new = {}
    report = {"posts": [], "files": [], "grades": [], "deadlines": [], "portal": []}

    jobs = [(c, kind, bid) for c in ws.courses for kind, bid in c.get("boards", {}).items()]
    results = []
    for i, (_, kind, bid) in enumerate(jobs, 1):
        step(f"boards {i}/{len(jobs)}")
        results.append(board.posts(client, bid, hide_authors=kind in board.STUDENT_BOARDS))

    head = {"boards": False, "rest": False, "portal": False}

    def section(name, title):
        if not head[name]:
            out(("\n" if name != "boards" else "") + "=" * 72 + f"\n■ {title}\n" + "=" * 72)
            head[name] = True
    for (c, kind, bid), rows in zip(jobs, results):
        key = f"board:{bid}"
        seen = set(old.get(key, []))
        new[key] = [r["bwid"] for r in rows]
        counts["posts"] += len(rows)
        fresh = [r for r in rows if r["bwid"] not in seen and (not since or r["date"] >= since)]
        if not fresh:
            continue
        section("boards", "Boards")
        out(f"\n[{c['code']} {c['name']}] {BOARD_LABEL.get(kind, kind)} (board={bid})")
        for r in fresh:
            out(f"   NEW [{r['date']}] bwid={r['bwid']}  {r['title']}")
            report["posts"].append({**r, "course": c["code"], "course_name": c["name"], "board": bid, "kind": kind})

    for n, c in enumerate(ws.courses, 1):
        step(f"courses {n}/{len(ws.courses)}")
        cid = c["id"]
        chunks = []
        for mod in ("assign", "quiz"):
            t = module_table(client, mod, cid)
            key = f"{mod}:{cid}"
            prev = old.get(key) if isinstance(old.get(key), list) else []
            new[key] = t
            counts[mod] += len(t)
            changed = [r for r in t if r not in prev]
            if changed:
                chunks.append(f"  <{mod}>\n    " + "\n    ".join(changed))
                report["deadlines"] += [{"course": c["code"], "course_name": c["name"], "module": mod, "row": r}
                                        for r in changed]

        files = course_files(client, cid)
        key = f"files:{cid}"
        names = dict(zip(files, display_names(files)))
        newf = [f for f in files if f not in old.get(key, [])]
        new[key] = files
        counts["files"] += len(files)
        if newf and not first:
            lines = []
            for f in newf:
                item = {"course": c["code"], "course_name": c["name"], "url": f, "name": names[f]}
                if download:
                    item["path"] = os.path.relpath(save_file(client, ws, c, f), ws.path)
                    lines.append(f"{item['name']}  → {item['path']}")
                else:
                    lines.append(item["name"])
                report["files"].append(item)
            chunks.append("  <new files>\n    " + "\n    ".join(lines))

        g = grade_rows(client, cid)
        key = f"grades:{cid}"
        newg = [x for x in g if x not in old.get(key, [])]
        new[key] = g
        counts["grades"] += len(g)
        if newg:
            chunks.append("  <grade changes>\n    " + "\n    ".join(newg))
            report["grades"] += [{"course": c["code"], "course_name": c["name"], "row": x} for x in newg]

        if chunks and not first:
            section("rest", "Assignments, quizzes, files, grades")
            say(f"\n[{c['code']} {c['name']}] course={cid}")
            say("\n".join(chunks))

    if portal is not False:
        step("portal")
        try:
            fresh = portal_changes(old, new, report, portal)
        except (PortalExpired, KlmsError) as e:
            if "portal" in old:
                new["portal"] = old["portal"]
            fresh = []
            report["portal_error"] = (f"{e} Portal notices were not checked. "
                                      "Log in again: one phone login covers KLMS and the portal.")
        if fresh and not first:
            section("portal", "KAIST portal")
            out("\n".join(f"   NEW [{r['date']}] id={r['id']}  [{r['board']}] {r['title']}" for r in fresh))
        if report.get("portal_error"):
            out("\n" + report["portal_error"])

    if not first and not any(report[k] for k in ("posts", "files", "grades", "deadlines", "portal")):
        out("Nothing new since the last run.")
    sem = new_semester(dash, ws)
    if sem:
        out(f"\nKLMS has moved on to {sem}. Run `nubzuki init` to start following it.")
    if first:
        out(f"\nFirst run: saved a baseline of {counts['posts']} posts, {counts['assign'] + counts['quiz']} "
            f"assignments/quizzes, {counts['files']} files and {counts['grades']} grade rows "
            f"across {len(ws.courses)} courses.")
        out(f"Only posts from the last {RECENT_DAYS} days are shown above. "
            "From now on, `nubzuki sweep` shows only what changed. Use `--all` to see everything.")
    if save:
        ws.save_state(new)
        out(f"\n(state saved: {ws.state_file})")
    if sem:
        report["new_semester"] = sem
    return report
