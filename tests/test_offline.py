import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from unittest import mock

from nubzuki import auth, discover, seed, sso, workspace
from nubzuki.sweep import display_names
from nubzuki.text import table_rows

DASH = """
<select name="year"><option value="2026" selected>2026</option></select>
<select name="semester"><option value="10">봄</option><option value="20" selected>가을</option></select>
<li><div class="course_li"><div class="course_li_fullname">
<div class="course_cd"><span class="text-grey">CS.10001(A)</span></div>
<a href="https://klms.kaist.ac.kr/course/view.php?id=111" class="fullname"> Intro to Programming </a>
</div><div class="course_li_info"><div><span class="text-grey">3.0</span> <span class="text-grey">학점</span></div></div>
<div class="teacher"><span class="text-grey">교수자</span> <span class="">Kim</span></div></div></li>
<li><div class="course_li"><div class="course_li_fullname">
<div class="course_cd"><span class="text-grey">MAS.10002_(AP)</span></div>
<a href="https://klms.kaist.ac.kr/course/view.php?id=222" class="fullname"> Calculus II </a>
</div></div></li>
<a href="https://klms.kaist.ac.kr/mod/courseboard/view.php?id=9">공지사항</a>
"""

COURSE = """
<a href="https://klms.kaist.ac.kr/mod/courseboard/view.php?id=9">공지사항</a>
<a href="https://klms.kaist.ac.kr/mod/courseboard/view.php?id=500">강의 공지사항</a>
<a href="https://klms.kaist.ac.kr/mod/courseboard/view.php?id=501">강의 Q&amp;A</a>
<a href="https://klms.kaist.ac.kr/mod/courseboard/view.php?id=502">자유게시판</a>
"""


class Discover(unittest.TestCase):
    def test_semester(self):
        self.assertEqual(discover.semester_of(DASH), "2026F")

    def test_courses(self):
        cs = discover.courses_of(DASH)
        self.assertEqual([(c["id"], c["code"], c["section"]) for c in cs],
                         [(111, "CS.10001", "A"), (222, "MAS.10002", "AP")])
        self.assertEqual(cs[0]["credit"], 3.0)

    def test_boards_skip_sitewide(self):
        self.assertEqual(discover.boards_of(COURSE, {9}), {"notice": 500, "qna": 501, "free": 502})


class Parsing(unittest.TestCase):
    def test_table_rows(self):
        html = "<table><tr><th>No</th><th>Title</th></tr><tr><td>1</td><td>HW &amp; 1</td></tr></table>"
        self.assertEqual(table_rows(html), [["No", "Title"], ["1", "HW & 1"]])

    def test_duplicate_names(self):
        urls = ["a/x/notes.pdf", "a/y/notes.pdf", "a/z/other.pdf"]
        self.assertEqual(display_names(urls), ["notes.pdf", "notes (2).pdf", "other.pdf"])


class Workspace(unittest.TestCase):
    def test_init_creates_folders(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(workspace, "CONFIG_FILE", os.path.join(td, "cfg.json")):
            courses = [{"id": 1, "code": "CS.10001", "section": "A", "name": "x", "boards": {}},
                       {"id": 2, "code": "CS.10001", "section": "B", "name": "x", "boards": {}}]
            ws, created = workspace.init(td, "2026F", courses)
            self.assertEqual(created, ["CS.10001"])
            for sub in ("files", "notices"):
                self.assertTrue(os.path.isdir(os.path.join(td, "2026F", "CS.10001", sub)))
            self.assertEqual(workspace.find(os.path.join(td, "2026F", "CS.10001")).path, ws.path)


class Cookies(unittest.TestCase):
    def test_env_wins(self):
        with mock.patch.dict(os.environ, {"NUBZUKI_COOKIE": "MoodleSession=abc"}):
            self.assertEqual(auth.cookie_header(), "MoodleSession=abc")

    def test_firefox_profile(self):
        with tempfile.TemporaryDirectory() as td:
            prof = os.path.join(td, "abcd.default-release")
            os.makedirs(prof)
            con = sqlite3.connect(os.path.join(prof, "cookies.sqlite"))
            con.execute("create table moz_cookies (host text, name text, value text, lastAccessed integer)")
            con.executemany("insert into moz_cookies values (?, ?, ?, ?)", [
                ("klms.kaist.ac.kr", "MoodleSession", "s3cr3t", 10),
                (".klms.kaist.ac.kr", "MOODLEID1_", "id", 5),
                ("example.com", "MoodleSession", "nope", 99)])
            con.commit()
            con.close()
            with mock.patch.object(auth, "_firefox_roots", return_value=[td]):
                v = auth._from_firefox()
            self.assertIn("MoodleSession=s3cr3t", v)
            self.assertIn("MOODLEID1_=id", v)
            self.assertNotIn("nope", v)

    def test_no_cookie_message(self):
        with mock.patch.dict(os.environ, {"NUBZUKI_COOKIE": ""}), \
                mock.patch.object(auth, "COOKIE_FILE", os.path.join(tempfile.gettempdir(), "nubzuki-none")), \
                mock.patch.object(auth, "_from_browser_cookie3", return_value=None), \
                mock.patch.object(auth, "_from_macos_chrome", return_value=None), \
                mock.patch.object(auth, "_from_firefox", return_value=None):
            with self.assertRaises(auth.AuthError) as e:
                auth.cookie_header()
            self.assertIn("nubzuki login", str(e.exception))


class Seed(unittest.TestCase):
    def test_rfc4269_vector(self):
        self.assertEqual(seed.encrypt_block(bytes(16), bytes(range(16))).hex(),
                         "5ebac6e0054e166819aff1cc6d346cdb")

    def test_cbc_matches_kaist_js(self):
        key = bytes(range(16))
        iv = bytes(range(15, -1, -1))
        data = b'{"login_id":"student","agt_id":"kaist-prod-klms"}'
        self.assertEqual(seed.encrypt_cbc(key, iv, data).hex(),
                         "b9f1e0d10123846af22019b92e96ea302c27ad374d36aaa9aed21e16799df10c"
                         "b5b631a7f3e30b114dec39fe6c65ab9bf467b1e444f1469fbe2438e7fbf64973")


class Sso(unittest.TestCase):
    def test_push_number(self):
        html = '<div>인증번호</div><span>4</span><span>7</span><p class="num">47</p><p>인증 대기 중입니다.</p>'
        self.assertEqual(sso.push_number(html), "47")

    def test_cooldown(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(sso, "LAST_PUSH", os.path.join(td, "p")), \
                mock.patch.object(sso, "CONFIG_DIR", td):
            self.assertEqual(sso.cooldown_left(), 0)
            sso._mark_push()
            self.assertGreater(sso.cooldown_left(), 50)


class Mcp(unittest.TestCase):
    def rpc(self, *msgs):
        r = subprocess.run([sys.executable, "-m", "nubzuki", "mcp"], capture_output=True, encoding="utf-8",
                           input="".join(json.dumps(m) + "\n" for m in msgs))
        return [json.loads(x) for x in r.stdout.splitlines()]

    def test_handshake_and_tools(self):
        out = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                       {"jsonrpc": "2.0", "method": "notifications/initialized"},
                       {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                       {"jsonrpc": "2.0", "id": 3, "method": "nope"})
        self.assertEqual([m["id"] for m in out], [1, 2, 3])
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "nubzuki")
        names = {t["name"] for t in out[1]["result"]["tools"]}
        self.assertTrue({"sweep", "read_post", "file_text", "login"} <= names)
        self.assertEqual(out[2]["error"]["code"], -32601)

    def test_paths_stay_in_workspace(self):
        from nubzuki import mcp
        with tempfile.TemporaryDirectory() as td:
            ws = workspace.Workspace(td)
            with self.assertRaises(mcp.ToolError):
                mcp.Server().inside(ws, "../../etc/passwd")
            self.assertTrue(mcp.Server().inside(ws, "CS/files/a.pdf").startswith(os.path.realpath(td)))


    def test_first_login_remembers_id(self):
        from nubzuki import mcp

        def fake_login(kid, on_number):
            on_number("47")
            return "MoodleSession=x"
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(workspace, "CONFIG_FILE", os.path.join(td, "cfg.json")), \
                mock.patch.object(workspace, "CONFIG_DIR", td), \
                mock.patch.object(auth, "save_cookie") as save, \
                mock.patch.object(sso, "login", fake_login), \
                mock.patch.object(workspace, "find", return_value=None):
            srv = mcp.Server()
            with self.assertRaises(mcp.ToolError) as e:
                srv.call("login", {})
            self.assertIn("KAIST ID", str(e.exception))
            self.assertEqual(srv.call("login", {"id": "student"})["number"], "47")
            st = srv.call("login_status", {})
            self.assertEqual(st["status"], "logged_in")
            self.assertIn("init", st["next"])
            save.assert_called_once_with("MoodleSession=x")
            self.assertEqual(workspace.load_config()["kaist_id"], "student")
            with self.assertRaises(mcp.ToolError) as e:
                srv.call("courses", {})
            self.assertIn("init", str(e.exception))


    def test_bad_input_is_a_tool_error(self):
        out = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "read_post", "arguments": {}}},
                       [1, 2],
                       {"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertTrue(out[0]["result"]["isError"])
        self.assertIn("Missing argument", out[0]["result"]["content"][0]["text"])
        self.assertEqual(out[1]["error"]["code"], -32600)
        self.assertEqual(out[2]["result"], {})

    def test_download_refuses_other_hosts(self):
        from nubzuki import mcp
        ws = mock.Mock(courses=[{"id": 1, "code": "CS.10001", "folder": "CS.10001"}], path=tempfile.gettempdir())
        ws.folder.return_value = tempfile.mkdtemp()
        srv = mcp.Server()
        srv.connect = mock.Mock()
        with mock.patch.object(workspace, "find", return_value=ws):
            for u in ("https://evil.example/pluginfile.php/1/x.pdf", "http://klms.kaist.ac.kr/pluginfile.php/1/x.pdf"):
                with self.assertRaises(mcp.ToolError):
                    srv.call("download", {"urls": [u], "course": "CS.10001"})
        srv.connect.assert_not_called()

    def test_login_saves_even_without_status_call(self):
        from nubzuki import mcp
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(workspace, "CONFIG_FILE", os.path.join(td, "cfg.json")), \
                mock.patch.object(workspace, "CONFIG_DIR", td), \
                mock.patch.object(auth, "save_cookie") as save, \
                mock.patch.object(sso, "login", lambda kid, on_number: (on_number("12"), "MoodleSession=y")[1]):
            srv = mcp.Server()
            srv.call("login", {"id": "student"})
            srv.login_job["thread"].join(5)
            save.assert_called_once_with("MoodleSession=y")
            self.assertEqual(srv.client.cookie, "MoodleSession=y")


class Client(unittest.TestCase):
    def test_cookie_stays_on_klms(self):
        from nubzuki import client
        self.assertEqual(client.klms_url("/my/"), "https://klms.kaist.ac.kr/my/")
        for bad in ("https://evil.example/x", "http://klms.kaist.ac.kr/x", "https://klms.kaist.ac.kr.evil.example/x"):
            with self.assertRaises(client.KlmsError):
                client.klms_url(bad)

    def test_redirect_drops_cookie_off_host(self):
        from nubzuki import client
        h = client._KeepCookieOnHost()
        req = urllib.request.Request("https://klms.kaist.ac.kr/a", headers={"Cookie": "MoodleSession=s"})
        same = h.redirect_request(req, None, 302, "", {}, "https://klms.kaist.ac.kr/b")
        other = h.redirect_request(req, None, 302, "", {}, "https://cdn.example/b")
        self.assertEqual(same.get_header("Cookie"), "MoodleSession=s")
        self.assertIsNone(other.get_header("Cookie"))

    def test_filename_cannot_escape(self):
        from nubzuki.client import filename_of
        self.assertEqual(filename_of("https://klms.kaist.ac.kr/pluginfile.php/1/a/..%2F..%2Fx.pdf"), ".._.._x.pdf")
        self.assertEqual(filename_of("https://klms.kaist.ac.kr/pluginfile.php/1/a/%2E%2E"), "_")
        self.assertEqual(filename_of("https://klms.kaist.ac.kr/pluginfile.php/1/a/Lec%209.pdf?forcedownload=1"), "Lec 9.pdf")


class Install(unittest.TestCase):
    def test_merges_and_backs_up(self):
        from nubzuki import install
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "cfg.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"preferences": {"x": 1}, "mcpServers": {"other": {"command": "o"}}}, f)
            self.assertEqual(install.add_to_json(p, "/bin/nubzuki", ["mcp"]), "added")
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
            self.assertEqual(cfg["preferences"], {"x": 1})
            self.assertEqual(set(cfg["mcpServers"]), {"other", "nubzuki"})
            self.assertTrue(os.path.exists(p + ".bak"))
            self.assertEqual(install.add_to_json(p, "/bin/nubzuki", ["mcp"]), "same")

    def test_codex_toml(self):
        from nubzuki import install
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "config.toml")
            head = 'model = "gpt-5"\n\n[mcp_servers.other]\ncommand = "o"\n\n[mcp_servers.other.env]\nK = "v"\n'
            with open(p, "w", encoding="utf-8") as f:
                f.write(head)
            self.assertEqual(install.add_to_toml(p, "/bin/nubzuki", ["mcp"]), "added")
            self.assertEqual(install.add_to_toml(p, "/bin/nubzuki", ["mcp"]), "same")
            self.assertEqual(install.add_to_toml(p, "C:\\nb\\nubzuki.exe", ["mcp"]), "updated")
            with open(p, encoding="utf-8") as f:
                text = f.read()
            self.assertTrue(text.startswith(head))
            self.assertEqual(text.count("[mcp_servers.nubzuki]"), 1)
            self.assertIn('command = "C:\\\\nb\\\\nubzuki.exe"', text)
            if sys.version_info >= (3, 11):
                import tomllib
                cfg = tomllib.loads(text)
                self.assertEqual(cfg["mcp_servers"]["nubzuki"], {"command": "C:\\nb\\nubzuki.exe", "args": ["mcp"]})
                self.assertEqual(cfg["mcp_servers"]["other"]["env"], {"K": "v"})

    def test_allow_tools_once(self):
        from nubzuki import install
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(install.allow_tools(td))
            self.assertFalse(install.allow_tools(td))
            with open(os.path.join(td, ".claude", "settings.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["permissions"]["allow"], ["mcp__nubzuki"])

    def test_new_file(self):
        from nubzuki import install
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "mcp.json")
            self.assertEqual(install.add_to_json(p, "nb", ["mcp"]), "added")
            self.assertFalse(os.path.exists(p + ".bak"))


class Cli(unittest.TestCase):
    def test_help(self):
        r = subprocess.run([sys.executable, "-m", "nubzuki", "--help"], capture_output=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0)
        self.assertIn("sweep", r.stdout)


if __name__ == "__main__":
    unittest.main()
