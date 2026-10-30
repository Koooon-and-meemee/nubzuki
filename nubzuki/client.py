import http.client
import os
import re
import shutil
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
        u = urllib.parse.urlsplit(newurl)
        if new is not None and (u.hostname != urllib.parse.urlsplit(req.full_url).hostname or u.scheme != "https"):
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
        self._dash = None

    def url(self, path):
        return klms_url(path)

    def _open(self, url, timeout=60):
        req = urllib.request.Request(url, headers={"Cookie": self.cookie, "User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
        return _opener.open(req, timeout=timeout)

    def get(self, path, tries=4):
        url = self.url(path)
        html, err = "", None
        for i in range(tries):
            if i:
                time.sleep(3 * i)
            try:
                with self._open(url) as r:
                    html, err = r.read().decode("utf8", "replace"), None
            except urllib.error.HTTPError as e:
                e.close()
                if e.code < 500:
                    raise KlmsError(f"KLMS returned HTTP {e.code} for {url}")
                html, err = "", e
                continue
            except (OSError, http.client.HTTPException) as e:
                html, err = "", e
                continue
            if "session lock" not in html:
                break
        if err is not None:
            raise KlmsError(f"Could not reach KLMS ({getattr(err, 'reason', err)}). Check your connection and try again.")
        if self.strict and not logged_in(html):
            if "session lock" in html:
                raise SessionLocked(f"Moodle session lock did not clear, try again shortly: {url}")
            raise SessionExpired(f"Not logged in: {url}")
        return html

    def download(self, path, dest, same_as=None):
        """Save a file to dest. Writes to dest.part first, so a failed download never leaves a broken file behind.
        If same_as is an existing file of exactly the size KLMS reports, return it instead of downloading again."""
        url = urllib.parse.quote(self.url(path), safe=":/?=&%")
        part = dest + ".part"
        try:
            with self._open(url, timeout=300) as r:
                final = urllib.parse.urlsplit(r.geturl())
                if final.hostname != HOST or final.path.startswith("/login/"):
                    raise SessionExpired(f"Not logged in: {url}")
                size = r.headers.get("Content-Length")
                if same_as and size and size.isdigit() and int(size) == os.path.getsize(same_as):
                    return same_as
                with open(part, "wb") as f:
                    shutil.copyfileobj(r, f, 1 << 16)
            os.replace(part, dest)
        finally:
            if os.path.exists(part):
                os.remove(part)
        return dest

    def check(self, max_age=60):
        """The dashboard page, which also proves the session is alive. Reused for a minute to save a request."""
        if self._dash and time.time() - self._dash[0] < max_age:
            return self._dash[1]
        h = self.get("/my/")
        if not logged_in(h):
            raise SessionExpired("No live KLMS session.")
        self._dash = (time.time(), h)
        return h


def filename_of(url):
    name = urllib.parse.unquote(url.split("?")[0].rsplit("/", 1)[-1])
    name = re.sub(r"[\\/]", "_", name)
    return "_" if name in ("", ".", "..") else name
