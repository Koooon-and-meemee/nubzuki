import html as H
import os
import re
import shutil
import subprocess
import sys
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
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class TextError(RuntimeError):
    pass


def pptx_text(path):
    num = lambda n: int(re.search(r"(\d+)\.xml$", n).group(1))
    out = []
    with zipfile.ZipFile(path) as z:
        for kind, pat in (("", r"ppt/slides/slide\d+\.xml$"),
                          ("NOTE ", r"ppt/notesSlides/notesSlide\d+\.xml$")):
            for n in sorted((x for x in z.namelist() if re.match(pat, x)), key=num):
                root = ET.fromstring(z.read(n))
                s = re.sub(r"\s+", " ", " ".join(t.text for t in root.iter(_A) if t.text)).strip()
                if s and (not kind or len(s) > 10):
                    out.append(f"[{kind}{num(n)}] {s}")
    return "\n".join(out)


def docx_text(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    paras = ("".join(t.text or "" for t in p.iter(_W + "t")) for p in root.iter(_W + "p"))
    return "\n".join(p for p in paras if p.strip())


# GUI apps (the Claude app, Codex) start the MCP server without Homebrew on PATH
_BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")

_PDFKIT = """function run(argv) {
  ObjC.import("PDFKit");
  var d = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(argv[0]));
  if (!d || d.isNil()) return "";
  var out = [];
  for (var i = 0; i < d.pageCount; i++) {
    var s = d.pageAtIndex(i).string;
    out.push("[page " + (i + 1) + "]\\n" + (s.isNil() ? "" : s.js));
  }
  return out.join("\\n\\n");
}"""


def _pdftotext():
    return shutil.which("pdftotext") or next(
        (p for p in (os.path.join(d, "pdftotext") for d in _BIN_DIRS) if os.access(p, os.X_OK)), None)


def pdf_text(path):
    name = os.path.basename(path)
    exe = _pdftotext()
    if exe:
        r = subprocess.run([exe, "-layout", path, "-"], capture_output=True)
        if r.returncode:
            raise TextError(f"pdftotext could not read {name}: " + r.stderr.decode("utf8", "replace").strip())
        pages = r.stdout.decode("utf8", "replace").split("\f")
        out = "\n\n".join(f"[page {i}]\n{p.strip()}" for i, p in enumerate(pages, 1) if p.strip())
    elif sys.platform == "darwin":
        r = subprocess.run(["osascript", "-l", "JavaScript", "-e", _PDFKIT, path], capture_output=True)
        if r.returncode:
            raise TextError(f"macOS could not read {name}: " + r.stderr.decode("utf8", "replace").strip())
        out = r.stdout.decode("utf8", "replace").strip()
    else:
        raise TextError("Reading PDFs needs pdftotext: `apt install poppler-utils`, or on Windows `choco install poppler`.")
    if not re.sub(r"\[page \d+\]", "", out).strip():
        raise TextError(f"{name} has no text to extract. It is probably scanned pages; open it to read it.")
    return out


def file_text(path):
    low = path.lower()
    try:
        if low.endswith(".pptx"):
            return pptx_text(path)
        if low.endswith(".docx"):
            return docx_text(path)
        if low.endswith(".pdf"):
            return pdf_text(path)
        if low.endswith((".txt", ".md")):
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise TextError(f"{os.path.basename(path)} looks damaged or isn't really a {low.rsplit('.', 1)[-1]} file ({e}).")
    raise TextError("Only .pdf, .pptx, .docx, .txt and .md are supported.")
