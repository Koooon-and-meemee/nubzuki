import http.client
import json
import urllib.error
import urllib.parse
import urllib.request

from . import auth
from .client import UA, KlmsError, SessionExpired, _opener
from .text import totext

HOST = "portal.kaist.ac.kr"
BASE = f"https://{HOST}"
PAGE = 30
MAX_PAGES = 5
EXPIRED = "No live KAIST portal session. Run `nubzuki login` (one phone login covers KLMS and the portal)."


class PortalExpired(SessionExpired):
    pass


def link(pst):
    return f"{BASE}/kaist/portal/board/ntc/0#{pst}"


def when(s):
    return (s or "").replace(".", "-")[:16]


def summary(x):
    return {"id": x["pstNo"], "title": x.get("pstTtl", ""), "board": x.get("boardNm", ""),
            "dept": x.get("pstWrtrDeptNm") or "", "date": when(x.get("regDt")),
            "attachments": x.get("atchFileCnt", 0), "views": x.get("inqCnt", 0)}


def detail(x):
    out = summary(x)
    out["board"] = out["board"] or (x.get("board") or {}).get("boardNm", "")
    out["text"] = totext(x.get("pstCn") or "")
    out["attachments"] = [{"name": a.get("atchFileNm"), "size": a.get("atchFileSizeFormat")}
                          for a in x.get("boardAtchList") or []]
    out["url"] = link(x["pstNo"])
    return out


class Portal:
    def __init__(self, cookie=None):
        self.cookie = cookie or auth.portal_cookie()
        if not self.cookie:
            raise PortalExpired(EXPIRED)

    def get(self, path):
        req = urllib.request.Request(BASE + path, headers={
            "Cookie": self.cookie, "User-Agent": UA, "Accept": "application/json", "Accept-Language": "ko-KR,ko;q=0.9"})
        try:
            with _opener.open(req, timeout=30) as r:
                kind = r.headers.get("Content-Type", "")
                body = r.read().decode("utf8", "replace")
                final = urllib.parse.urlsplit(r.geturl())
        except urllib.error.HTTPError as e:
            e.close()
            if e.code in (401, 403):
                raise PortalExpired(EXPIRED)
            raise KlmsError(f"The portal returned HTTP {e.code} for {path}")
        except (OSError, http.client.HTTPException) as e:
            raise KlmsError(f"Could not reach the KAIST portal ({getattr(e, 'reason', e)}).")
        if final.hostname != HOST or "json" not in kind:
            raise PortalExpired(EXPIRED)
        try:
            return json.loads(body)
        except ValueError:
            raise PortalExpired(EXPIRED)

    def recents(self, n=PAGE, page=1):
        data = self.get(f"/wz/api/board/recents/?recordCountPerPage={int(n)}&pageIndex={int(page)}").get("data") or []
        return [summary(x) for x in data if x.get("delYn") != "Y"]

    def since(self, seen, pages=MAX_PAGES):
        out = []
        for p in range(1, pages + 1):
            rows = self.recents(PAGE, p)
            if not rows:
                break
            for r in rows:
                if r["id"] in seen:
                    return out
                out.append(r)
        return out

    def post(self, pst):
        return detail(self.get(f"/wz/api/board/recents/{int(pst)}"))
