import html as H
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from . import board
from .client import filename_of
from .text import totext

GRADE_SKIP = ("성적 항목", "합계", "Grade item", "Course total")
BOARD_LABEL = {"notice": "Notices", "qna": "Q&A", "free": "Board"}


def course_files(client, cid):
    h = H.unescape(client.get(f"/course/view.php?id={cid}"))
    found = re.findall(r'pluginfile\.php/\d+/mod_resource[^"\'<>\s]*', h)
    return sorted({urllib.parse.unquote(u).split("?")[0] for u in found})


def module_table(client, mod, cid):
    h = client.get(f"/mod/{mod}/index.php?id={cid}")
    keep = [t for t in re.findall(r'(?is)<table[^>]*>.*?</table>', h) if f"/mod/{mod}/view.php" in t]
    return "\n".join(totext(t) for t in keep)


def grade_rows(client, cid):
    h = client.get(f"/grade/report/user/index.php?id={cid}")
    rows = []
    for r in re.findall(r'(?is)<tr[^>]*>(.*?)</tr>', h):
        cells = [re.sub(r"\s+", " ", H.unescape(re.sub(r"(?s)<[^>]+>", "", c))).strip()
                 for c in re.findall(r'(?is)<t[dh][^>]*>(.*?)</t[dh]>', r)]
        line = " | ".join(cells)
        if line.strip(" |") and not any(k in line for k in GRADE_SKIP):
            rows.append(line[:200])
    return rows


def unique(path):
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(path):
        path = f"{base} ({i}){ext}"
        i += 1
    return path


def run(client, ws, since=None, download=False, out=print):
    client.check()
    old = ws.load_state()
    new = {}
    report = {"posts": [], "files": [], "grades": [], "deadlines": []}

    jobs = [(c, kind, bid) for c in ws.courses for kind, bid in c.get("boards", {}).items()]
    with ThreadPoolExecutor(2) as ex:
        results = list(ex.map(lambda j: board.posts(client, j[2]), jobs))

    out("=" * 72 + "\n■ Boards\n" + "=" * 72)
    for (c, kind, bid), rows in zip(jobs, results):
        key = f"board:{bid}"
        seen = set(old.get(key, []))
        new[key] = [r["bwid"] for r in rows]
        fresh = [r for r in rows if r["bwid"] not in seen and (not since or r["date"] >= since)]
        if not fresh:
            continue
        out(f"\n[{c['code']} {c['name']}] {BOARD_LABEL.get(kind, kind)} (board={bid})")
        for r in fresh:
            out(f"   NEW [{r['date']}] bwid={r['bwid']}  {r['title']}")
            report["posts"].append({**r, "course": c["code"], "board": bid, "kind": kind})

    out("\n" + "=" * 72 + "\n■ Assignments, quizzes, files, grades\n" + "=" * 72)
    for c in ws.courses:
        cid = c["id"]
        chunks = []
        for mod in ("assign", "quiz"):
            t = module_table(client, mod, cid)
            key = f"{mod}:{cid}"
            new[key] = t
            if t.strip() and t != old.get(key):
                chunks.append(f"  <{mod}>\n    " + t.replace("\n", "\n    "))
                report["deadlines"].append({"course": c["code"], "module": mod, "table": t})

        files = course_files(client, cid)
        key = f"files:{cid}"
        newf = [f for f in files if f not in old.get(key, [])]
        new[key] = files
        if newf:
            lines = []
            for f in newf:
                name = filename_of(f)
                if download:
                    dest = unique(os.path.join(ws.folder(c), "files", name))
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
        if newg:
            chunks.append("  <grade changes>\n    " + "\n    ".join(newg))
            report["grades"] += [{"course": c["code"], "row": x} for x in newg]

        if chunks:
            out(f"\n[{c['code']} {c['name']}] course={cid}")
            out("\n".join(chunks))

    ws.save_state(new)
    out(f"\n(state saved: {ws.state_file})")
    return report
