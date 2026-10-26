import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .auth import cookie_header

HOST = "klms.kaist.ac.kr"
BASE = f"https://{HOST}"
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


class _KeepCookieOnHost(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).hostname != HOST:
            new.remove_header("Cookie")
        return new


_opener = urllib.request.build_opener(_KeepCookieOnHost)


def klms_url(path):
    """Absolute KLMS URL for a path. Refuses other hosts so the session cookie never leaves KLMS."""
    if not path.startswith("http"):
        return f"{BASE}/{path.lstrip('/')}"
    u = urllib.parse.urlsplit(path)
    if u.scheme != "https" or u.hostname != HOST:
        raise KlmsError(f"Refusing to send the KLMS session to {u.scheme}://{u.hostname}")
    return path


class Client:
    def __init__(self, cookie=None, strict=True):
        self.cookie = cookie or cookie_header()
        self.strict = strict

    def url(self, path):
        return klms_url(path)

    def _open(self, url, timeout=60):
        req = urllib.request.Request(url, headers={"Cookie": self.cookie, "User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
        return _opener.open(req, timeout=timeout)

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
                raise SessionLocked(f"Moodle session lock did not clear, try again shortly: {url}")
            raise SessionExpired(f"Not logged in: {url}")
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
            raise SessionExpired("No KLMS session. Log in again in your browser.")
        return h


def filename_of(url):
    name = urllib.parse.unquote(url.split("?")[0].rsplit("/", 1)[-1])
    name = re.sub(r"[\\/]", "_", name)
    return "_" if name in ("", ".", "..") else name
