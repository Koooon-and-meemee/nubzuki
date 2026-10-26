import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

DOMAIN = "klms.kaist.ac.kr"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "nubzuki")
COOKIE_FILE = os.path.join(CONFIG_DIR, "cookie")


class AuthError(RuntimeError):
    pass


def save_cookie(value):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd = os.open(COOKIE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value.strip() + "\n")


def _from_env_or_file():
    v = os.environ.get("NUBZUKI_COOKIE", "").strip()
    if v:
        return v, "env"
    if os.path.exists(COOKIE_FILE):
        v = open(COOKIE_FILE).read().strip()
        if v:
            return v, "file"
    return None, None


def _from_browser_cookie3():
    try:
        import browser_cookie3
    except ImportError:
        return None
    for loader in ("chrome", "edge", "brave", "firefox", "safari"):
        fn = getattr(browser_cookie3, loader, None)
        if not fn:
            continue
        try:
            jar = fn(domain_name=DOMAIN)
        except Exception:
            continue
        parts = [f"{c.name}={c.value}" for c in jar if c.domain.lstrip(".") == DOMAIN]
        if any(p.startswith("MoodleSession=") for p in parts):
            return "; ".join(parts)
    return None


_CHROME_ROOT = os.path.expanduser("~/Library/Application Support/Google/Chrome")


def _chrome_key():
    p = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
        capture_output=True, text=True)
    if p.returncode != 0 or not p.stdout.strip():
        raise AuthError("키체인에서 Chrome Safe Storage 키를 읽지 못했습니다 (승인 거부?).")
    return hashlib.pbkdf2_hmac("sha1", p.stdout.strip().encode(), b"saltysalt", 1003, 16)


def _decrypt(blob, key):
    if not blob or blob[:3] not in (b"v10", b"v11"):
        return blob.decode("utf8", "replace") if blob else ""
    p = subprocess.run(
        ["openssl", "enc", "-d", "-aes-128-cbc", "-nopad", "-K", key.hex(), "-iv", "20" * 16],
        input=blob[3:], capture_output=True)
    pt = p.stdout
    if not pt:
        return ""
    pad = pt[-1]
    if 1 <= pad <= 16:
        pt = pt[:-pad]

    try:
        s = pt.decode("utf8")
        if not s.isprintable():
            raise ValueError
        return s
    except ValueError:
        return pt[32:].decode("utf8", "replace")


def _chrome_profiles():
    if not os.path.isdir(_CHROME_ROOT):
        return []
    out = []
    for d in sorted(os.listdir(_CHROME_ROOT)):
        db = os.path.join(_CHROME_ROOT, d, "Cookies")
        if (d == "Default" or d.startswith("Profile")) and os.path.exists(db):
            out.append((d, db))
    return out


def _from_macos_chrome():
    if sys.platform != "darwin":
        return None
    profiles = _chrome_profiles()
    if not profiles:
        return None
    key = _chrome_key()
    best = None
    for name, db in profiles:
        with tempfile.TemporaryDirectory() as td:
            tmp = os.path.join(td, "Cookies")
            shutil.copy2(db, tmp)
            con = sqlite3.connect(tmp)
            rows = con.execute(
                "select name, encrypted_value, last_access_utc from cookies where host_key=?",
                (DOMAIN,)).fetchall()
            con.close()
        parts, last = [], 0
        for n, ev, la in rows:
            v = _decrypt(ev, key)
            if v:
                parts.append(f"{n}={v}")
                last = max(last, la or 0)
        if any(p.startswith("MoodleSession=") for p in parts):
            if not best or last > best[0]:
                best = (last, "; ".join(parts))
    return best[1] if best else None


def cookie_header():
    v, _ = _from_env_or_file()
    if v:
        return v
    for fn in (_from_browser_cookie3, _from_macos_chrome):
        v = fn()
        if v:
            return v
    raise AuthError(
        "KLMS 쿠키를 찾지 못했습니다.\n"
        "  - 브라우저에서 klms.kaist.ac.kr 에 로그인한 뒤 다시 실행하거나\n"
        "  - `nubzuki login` 으로 MoodleSession 값을 직접 저장하세요.")
