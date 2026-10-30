import http.cookiejar
import json
import os
import re
import time
import urllib.parse
import urllib.request

from . import auth, seed
from .auth import CONFIG_DIR

SSO = "https://sso.kaist.ac.kr"
KLMS = "https://klms.kaist.ac.kr"
PORTAL = "https://portal.kaist.ac.kr"
AGENT = "kaist-prod-klms"
PORTAL_AGENT = "kaist-prod-portal"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")
LAST_PUSH = os.path.join(CONFIG_DIR, "last_push")
COOLDOWN = 60
TIMEOUT = 180

ERRORS = {
    "ESY008": "This KAIST ID has no login app registered. Register the KAIST app first "
              "(sso.kaist.ac.kr → 로그인 앱 등록).",
    "ESY021": "Too many failed approvals. KAIST blocked easy login for a while.",
    "ESY022": "Too many failed approvals. KAIST blocked easy login.",
    "ESY023": "The login request was cancelled on the phone.",
    "ESY024": "The wrong number was tapped.",
    "E004": "The login request timed out.",
}


class SSOError(RuntimeError):
    pass


def push_number(html):
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<script.*?</script>", "", html)))
    m = re.search(r"인증번호\s*(?:\d\s*)*?(\d{2})\b", text)
    return m.group(1) if m else None


def cooldown_left(now=None):
    try:
        with open(LAST_PUSH, encoding="utf-8") as f:
            last = float(f.read().strip())
    except (OSError, ValueError):
        return 0
    return max(0, int(COOLDOWN - ((now or time.time()) - last)))


def _mark_push():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(LAST_PUSH, "w", encoding="utf-8") as f:
        f.write(str(time.time()))


class _Session:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.referer = SSO

    def post(self, path, data=None, ajax=False):
        return self.request(path, data if data is not None else {}, ajax)

    def request(self, path, data=None, ajax=False):
        url = path if path.startswith("http") else SSO + path
        headers = {"User-Agent": UA, "Referer": self.referer, "Accept-Language": "ko-KR,ko;q=0.9"}
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
        body = urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None
        with self.op.open(urllib.request.Request(url, data=body, headers=headers), timeout=30) as r:
            return r.geturl(), r.read().decode("utf8", "replace")

    def json(self, path, data=None):
        _, body = self.post(path, data, ajax=True)
        try:
            return json.loads(body)
        except ValueError:
            raise SSOError(f"Unexpected response from KAIST SSO at {path}")

    def cookies_for(self, host):
        return "; ".join(f"{c.name}={c.value}" for c in self.jar if c.domain.lstrip(".") == host)

    def klms_cookie(self):
        return self.cookies_for("klms.kaist.ac.kr")


def _follow_forms(s, url, html, stop=KLMS):
    for _ in range(5):
        if url.startswith(stop):
            return url
        m = re.search(r'(?is)<form[^>]*action="(https?://[^"]+|/[^"]+)"[^>]*>(.*?)</form>', html)
        if not m:
            break
        fields = dict(re.findall(r'name="([^"]+)"[^>]*value="([^"]*)"', m.group(2)))
        url, html = s.request(urllib.parse.urljoin(url, m.group(1)), fields)
    return url


def login(user_id, on_number=print, timeout=TIMEOUT):
    wait = cooldown_left()
    if wait:
        raise SSOError(f"A login request was sent less than {COOLDOWN}s ago. Try again in {wait}s.")
    s = _Session()
    s.request(f"{KLMS}/login/ssologin.php")
    view = f"{SSO}/auth/kaist/user/login/view?agt_id={AGENT}&agt_url={KLMS}"
    s.request(view)
    s.referer = view

    key = s.json("/auth/user/login/init").get("result_data", "")
    if len(key) < 96:
        raise SSOError("KAIST SSO did not return a login key.")
    payload = json.dumps({"login_id": user_id, "agt_id": AGENT}, separators=(",", ":")).encode()
    user_data = seed.encrypt_cbc(bytes.fromhex(key[:32]), bytes.fromhex(key[64:96]), payload).hex()

    code = s.json("/auth/twofactor/mfa/init", {"user_data": user_data}).get("code", "")
    if code:
        raise SSOError(ERRORS.get(code, f"KAIST SSO refused easy login ({code})."))
    _mark_push()

    url, page = s.post("/auth/twofactor/mfa/login2Factor", {"linkUrl": "/user/login/link"})
    s.referer = url
    on_number(push_number(page))

    deadline = time.time() + timeout
    while True:
        r = s.json("/auth/twofactor/mfa/auth")
        if r.get("result"):
            break
        err = r.get("error_code", "")
        if err != "ESY020":
            raise SSOError(ERRORS.get(err, f"Easy login failed ({err})."))
        if time.time() > deadline:
            raise SSOError(ERRORS["E004"])
        time.sleep(3)

    policy = s.json("/auth/kaist/user/login/check/policy", {"device": []}).get("code", "")
    nxt = {"SS0001": "/auth/user/login/link", "SS0099": "/auth/kaist/user/device/login"}.get(policy)
    if not nxt:
        raise SSOError(f"KAIST SSO needs attention in a browser ({policy}).")
    if policy == "SS0099":
        s.request("/auth/kaist/user/device/view", {})
        url, html = s.request(nxt)
    else:
        url, html = s.post(nxt)
    _follow_forms(s, url, html)
    s.request(f"{KLMS}/my/?lang=ko")

    cookie = s.klms_cookie()
    if "MoodleSession=" not in cookie:
        raise SSOError("Logged in to KAIST SSO but KLMS did not start a session.")
    try:
        portal = portal_session(s)
    except (OSError, ValueError):
        portal = None
    if portal:
        auth.save_cookie(portal, auth.PORTAL_COOKIE_FILE)
    return cookie


def portal_session(s):
    s.referer = f"{PORTAL}/common/login/login.do"
    s.request(s.referer)
    url, html = s.post("/auth/user/login/link", {
        "user_id": "", "agt_id": PORTAL_AGENT, "agt_url": PORTAL, "lang": "ko",
        "form_type": "IDPW", "add_param": "add_param_value"})
    _follow_forms(s, url, html, stop=PORTAL)
    s.request(f"{PORTAL}/common/login/login.do?returnUrl=/")
    cookie = s.cookies_for("portal.kaist.ac.kr")
    return cookie if "JSESSIONID=" in cookie else None
