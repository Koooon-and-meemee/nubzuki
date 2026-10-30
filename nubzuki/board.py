import html as H
import re

from .text import strip, totext

ROW = re.compile(r'bwid=(\d+)[^>]*>(.*?)</a>(.*?)(\d{4}-\d{2}-\d{2})', re.S)
STUDENT_BOARDS = ("qna", "free")
AUTHOR_LINE = re.compile(r"((?:작성자|Author)\s*:\s*)([^\n]+)")


def mask(name):
    name = name.strip()
    if not name:
        return name
    if re.fullmatch(r"[가-힣]{2,5}", name):
        return name[0] + "O" * max(1, len(name) - 2) + (name[-1] if len(name) > 2 else "")
    return " ".join(w[0] + "*" * (len(w) - 1) for w in name.split())


def mask_authors(text):
    return AUTHOR_LINE.sub(lambda m: m.group(1) + mask(m.group(2)), text)


def posts(client, bid, hide_authors=False):
    h = client.get(f"/mod/courseboard/view.php?id={bid}&perpage=50")
    out, seen = [], set()
    for bwid, title, mid, date in ROW.findall(h):
        t = strip(title)
        if not t or bwid in seen:
            continue
        seen.add(bwid)
        author = strip(mid).strip("|").strip()[-20:]
        out.append({"bwid": int(bwid), "title": t,
                    "author": mask(author) if hide_authors else author, "date": date})
    return out


def article(client, bid, bwid):
    h = client.get(f"/mod/courseboard/article.php?id={bid}&bwid={bwid}")
    i = h.find("courseboard_view")
    body = h[i:] if i > 0 else h
    for mark in ('id="page-footer"', 'class="prev_next"', "이전글", "다음글"):
        j = body.find(mark)
        if j > 0:
            body = body[:j]
    text = totext(body.split(">", 1)[-1], cell_sep="\t")
    files = list(dict.fromkeys(
        f for f in re.findall(r'pluginfile\.php[^"\'<>\s]*', H.unescape(body))
        if "forcedownload" not in f))
    return text, files
