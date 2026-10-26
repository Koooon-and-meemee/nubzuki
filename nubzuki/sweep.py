import datetime
import html as H
import os
import re
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import board
from .client import filename_of
from .text import table_rows

GRADE_SKIP = ("성적 항목", "합계", "Grade item", "Course total")
TABLE_HEAD = ("No", "번호", "주차", "Topic", "Week")
RECENT_DAYS = 7
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


def run(client, ws, since=None, download=False, show_all=False, save=True, out=print):
    client.check()
    old = ws.load_state()
    first = not old and not show_all
    if first and not since:
        since = (datetime.date.today() - datetime.timedelta(days=RECENT_DAYS)).isoformat()
    say = (lambda *_: None) if first else out
    counts = Counter()
    new = {}
    report = {"posts": [], "files": [], "grades": [], "deadlines": []}

    jobs = [(c, kind, bid) for c in ws.courses for kind, bid in c.get("boards", {}).items()]
    with ThreadPoolExecutor(2) as ex:
        results = list(ex.map(lambda j: board.posts(client, j[2]), jobs))

    head = {"boards": False, "rest": False}

    def section(name, title):
        if not head[name]:
            out(("\n" if name == "rest" else "") + "=" * 72 + f"\n■ {title}\n" + "=" * 72)
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
            report["posts"].append({**r, "course": c["code"], "board": bid, "kind": kind})

    for c in ws.courses:
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
                report["deadlines"] += [{"course": c["code"], "module": mod, "row": r} for r in changed]

        files = course_files(client, cid)
        key = f"files:{cid}"
        names = dict(zip(files, display_names(files)))
        newf = [f for f in files if f not in old.get(key, [])]
        new[key] = files
        counts["files"] += len(files)
        if newf and not first:
            lines = []
            for f in newf:
                name = names[f]
                if download:
                    dest = unique(os.path.join(ws.folder(c), "files", filename_of(f)))
                    client.download(f, dest)
                    lines.append(f"{name}  → {os.path.relpath(dest, ws.path)}")
                else:
                    lines.append(name)
                report["files"].append({"course": c["code"], "url": f, "name": name})
            chunks.append("  <new files>\n    " + "\n    ".join(lines))

        g = grade_rows(client, cid)
        key = f"grades:{cid}"
        newg = [x for x in g if x not in old.get(key, [])]
        new[key] = g
        counts["grades"] += len(g)
        if newg:
            chunks.append("  <grade changes>\n    " + "\n    ".join(newg))
            report["grades"] += [{"course": c["code"], "row": x} for x in newg]

        if chunks and not first:
            section("rest", "Assignments, quizzes, files, grades")
            say(f"\n[{c['code']} {c['name']}] course={cid}")
            say("\n".join(chunks))

    if not first and not any(report.values()):
        out("Nothing new since the last run.")
    if first:
        out(f"\nFirst run: saved a baseline of {counts['posts']} posts, {counts['assign'] + counts['quiz']} "
            f"assignments/quizzes, {counts['files']} files and {counts['grades']} grade rows "
            f"across {len(ws.courses)} courses.")
        out(f"Only posts from the last {RECENT_DAYS} days are shown above. "
            "From now on, `nubzuki sweep` shows only what changed. Use `--all` to see everything.")
    if save:
        ws.save_state(new)
        out(f"\n(state saved: {ws.state_file})")
    return report
