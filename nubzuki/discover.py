import re

from .client import KlmsError
from .text import strip


SEMESTER_SUFFIX = {"10": "S", "11": "U", "20": "F", "21": "W"}
SEMESTER_NAME = {"S": "Spring", "U": "Summer", "F": "Fall", "W": "Winter"}

_COURSE_LI = re.compile(
    r'<div class="course_li">.*?<div class="course_cd">(.*?)</div>\s*'
    r'<a href="[^"]*course/view\.php\?id=(\d+)"[^>]*class="fullname">(.*?)</a>(.*?)</li>',
    re.S)
_BOARD = re.compile(r'mod/courseboard/view\.php\?id=(\d+)[^>]*>(.*?)</a>', re.S)


def semester_of(dash_html):
    y = re.search(r'name="year">.*?<option value="(\d{4})"[^>]*selected', dash_html, re.S)
    s = re.search(r'name="semester">.*?<option value="(\d+)"[^>]*selected', dash_html, re.S)
    if not (y and s):
        raise KlmsError("Could not find the year/semester on the dashboard (did the KLMS layout change?).")
    return y.group(1) + SEMESTER_SUFFIX.get(s.group(1), s.group(1))


def split_code(raw):
    raw = strip(raw)
    m = re.match(r"([A-Z]{2,4}\.\d{5})[_\s]*\(?([^)]*)\)?", raw)
    if m:
        return m.group(1), m.group(2).strip()
    return raw, ""


def courses_of(dash_html):
    out, seen = [], set()
    for cd, cid, name, rest in _COURSE_LI.findall(dash_html):
        if cid in seen:
            continue
        seen.add(cid)
        code, section = split_code(cd)
        credit = re.search(r'([\d.]+)</span>\s*<span[^>]*>학점', rest)
        prof = re.search(r'교수자</span>\s*<span[^>]*>(.*?)</span>', rest, re.S)
        out.append({
            "id": int(cid),
            "code": code or f"COURSE{cid}",
            "section": section,
            "name": strip(name),
            "credit": float(credit.group(1)) if credit else None,
            "professor": strip(prof.group(1)) if prof else "",
        })
    return out


def _kind(label):
    l = label.lower()
    if "q&a" in l or "질문" in l:
        return "qna"
    if "공지" in l or "notice" in l:
        return "notice"
    if "자유" in l or "board" in l:
        return "free"
    return None


def boards_of(course_html, sitewide):
    boards = {}
    for bid, label in _BOARD.findall(course_html):
        bid = int(bid)
        if bid in sitewide:
            continue
        k = _kind(strip(label))
        if k:
            boards.setdefault(k, bid)
    return boards


def discover(client):
    dash = client.check()
    sem = semester_of(dash)
    courses = courses_of(dash)
    sitewide = {int(b) for b, _ in _BOARD.findall(dash)}
    for c in courses:
        c["boards"] = boards_of(client.get(f"/course/view.php?id={c['id']}"), sitewide)
    return sem, courses
