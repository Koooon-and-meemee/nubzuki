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
PORTAL_COOKIE_FILE = os.path.join(CONFIG_DIR, "portal_cookie")


class AuthError(RuntimeError):
    pass


def save_cookie(value, path=None):
    path = path or COOKIE_FILE
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value.strip() + "\n")
    os.chmod(path, 0o600)


def portal_cookie():
    v = os.environ.get("NUBZUKI_PORTAL_COOKIE", "").strip()
    if v:
        return v
    if os.path.exists(PORTAL_COOKIE_FILE):
        with open(PORTAL_COOKIE_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    return None


def _from_env_or_file():
    v = os.environ.get("NUBZUKI_COOKIE", "").strip()
    if v:
        return v, "env"
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, encoding="utf-8") as f:
            v = f.read().strip()
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
        raise AuthError("Could not read the Chrome Safe Storage key from the Keychain (access denied?).")
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
    found = []
    for _, db in _chrome_profiles():
        with tempfile.TemporaryDirectory() as td:
            tmp = os.path.join(td, "Cookies")
            shutil.copy2(db, tmp)
            con = sqlite3.connect(tmp)
            rows = con.execute(
                "select name, encrypted_value, last_access_utc from cookies where host_key=?",
                (DOMAIN,)).fetchall()
            con.close()
        if any(n == "MoodleSession" for n, _, _ in rows):
            found.append(rows)
    if not found:
        return None
    # Only now ask the Keychain, so people who never used KLMS in Chrome don't get a macOS password prompt
    key = _chrome_key()
    best = None
    for rows in found:
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


def _firefox_roots():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", "")
        return [os.path.join(base, "Mozilla", "Firefox", "Profiles")]
    if sys.platform == "darwin":
        return [os.path.expanduser("~/Library/Application Support/Firefox/Profiles")]
    return [os.path.expanduser("~/.mozilla/firefox"),
            os.path.expanduser("~/snap/firefox/common/.mozilla/firefox")]


def _firefox_dbs():
    out = []
    for root in _firefox_roots():
        if not os.path.isdir(root):
            continue
        for d in os.listdir(root):
            db = os.path.join(root, d, "cookies.sqlite")
            if os.path.exists(db):
                out.append(db)
    return out


def _read_firefox(db):
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.join(td, "cookies.sqlite")
        shutil.copy2(db, tmp)
        if os.path.exists(db + "-wal"):
            shutil.copy2(db + "-wal", tmp + "-wal")
        con = sqlite3.connect(tmp)
        rows = con.execute(
            "select name, value, lastAccessed from moz_cookies where host in (?, ?)",
            (DOMAIN, "." + DOMAIN)).fetchall()
        con.close()
    return rows


def _from_firefox():
    best = None
    for db in _firefox_dbs():
        try:
            rows = _read_firefox(db)
        except (sqlite3.Error, OSError):
            continue
        if not any(n == "MoodleSession" for n, _, _ in rows):
            continue
        last = max(la or 0 for _, _, la in rows)
        if not best or last > best[0]:
            best = (last, "; ".join(f"{n}={v}" for n, v, _ in rows))
    return best[1] if best else None


def _hint():
    if sys.platform == "win32":
        return ("  - On Windows, Chrome and Edge encrypt cookies so other programs cannot read them.\n"
                "    Log in to klms.kaist.ac.kr in Firefox, or\n"
                "  - copy your MoodleSession value from the browser and save it with `nubzuki login`.")
    return ("  - Log in to klms.kaist.ac.kr in Chrome or Firefox and run again, or\n"
            "  - save your MoodleSession value with `nubzuki login`.")


def cookie_candidates():
    v, _ = _from_env_or_file()
    if v:
        yield v
    for fn in (_from_browser_cookie3, _from_macos_chrome, _from_firefox):
        try:
            v = fn()
        except (AuthError, OSError, sqlite3.Error):
            v = None
        if v:
            yield v


def cookie_header():
    for v in cookie_candidates():
        return v
    raise AuthError("No KLMS cookie found.\n" + _hint())
