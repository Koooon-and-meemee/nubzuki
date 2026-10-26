import html as H
import re
import shutil
import subprocess
import zipfile
from xml.etree import ElementTree as ET


def strip(s):
    s = re.sub(r"(?s)<[^>]+>", "", s)
    return re.sub(r"\s+", " ", H.unescape(s)).strip()


def totext(t, cell_sep=" | "):
    t = re.sub(r"(?is)<(script|style|nav|svg)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h[1-6])>", "\n", t)
    t = re.sub(r"(?i)</t[dh]>", cell_sep, t)
    t = re.sub(r"(?s)<[^>]+>", "", t)
    t = H.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def table_rows(t):
    rows = []
    for r in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", t):
        cells = [strip(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", r)]
        if any(cells):
            rows.append(cells)
    return rows


_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"


def pptx_text(path):
    z = zipfile.ZipFile(path)
    num = lambda n: int(re.search(r"(\d+)\.xml$", n).group(1))
    out = []
    for kind, pat in (("", r"ppt/slides/slide\d+\.xml$"),
                      ("NOTE ", r"ppt/notesSlides/notesSlide\d+\.xml$")):
        for n in sorted((x for x in z.namelist() if re.match(pat, x)), key=num):
            root = ET.fromstring(z.read(n))
            s = re.sub(r"\s+", " ", " ".join(t.text for t in root.iter(_A) if t.text)).strip()
            if s and (not kind or len(s) > 10):
                out.append(f"[{kind}{num(n)}] {s}")
    return "\n".join(out)


class TextError(RuntimeError):
    pass


def file_text(path):
    low = path.lower()
    if low.endswith(".pptx"):
        return pptx_text(path)
    if low.endswith(".pdf"):
        if not shutil.which("pdftotext"):
            raise TextError("pdftotext is required (brew install poppler / apt install poppler-utils).")
        r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True)
        return r.stdout.decode("utf8", "replace")
    if low.endswith((".txt", ".md")):
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    raise TextError("Only .pptx, .pdf, .txt and .md are supported.")
