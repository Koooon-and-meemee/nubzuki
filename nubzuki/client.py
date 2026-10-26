import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .auth import cookie_header

BASE = "https://klms.kaist.ac.kr"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")


class KlmsError(RuntimeError):
    pass


class SessionExpired(KlmsError):
    pass


class SessionLocked(KlmsError):
    pass


def logged_in(html):
    return "로그아웃" in html or re.search(r"login/logout\.php", html) is not None


class Client:
    def __init__(self, cookie=None, strict=True):
        self.cookie = cookie or cookie_header()
        self.strict = strict

    def url(self, path):
        return path if path.startswith("http") else f"{BASE}/{path.lstrip('/')}"

    def _open(self, url, timeout=60):
        req = urllib.request.Request(url, headers={"Cookie": self.cookie, "User-Agent": UA})
        return urllib.request.urlopen(req, timeout=timeout)

    def get(self, path, tries=4):
        url = self.url(path)
        html = ""
        for i in range(tries):
            try:
                with self._open(url) as r:
                    html = r.read().decode("utf8", "replace")
            except (urllib.error.URLError, TimeoutError):
                time.sleep(3 * (i + 1))
                continue
            if "session lock" in html:
                time.sleep(3 * (i + 1))
                continue
            break
        if self.strict and not logged_in(html):
            if "session lock" in html:
                raise SessionLocked(f"세션 잠금이 풀리지 않았습니다 (잠시 뒤 재시도): {url}")
            raise SessionExpired(f"로그인되지 않은 응답: {url}")
        return html

    def download(self, path, dest):
        url = urllib.parse.quote(self.url(path), safe=":/?=&%")
        with self._open(url, timeout=300) as r, open(dest, "wb") as f:
            while True:
                b = r.read(1 << 16)
                if not b:
                    break
                f.write(b)
        return dest

    def check(self):
        h = self.get("/my/")
        if not logged_in(h):
            raise SessionExpired("KLMS 세션이 없습니다. 브라우저에서 다시 로그인하세요.")
        return h


def filename_of(url):
    return urllib.parse.unquote(url.split("?")[0].rsplit("/", 1)[-1])
