import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import io
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from unittest import mock

from nubzuki import auth, discover, seed, sso, text, workspace
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
        self.assertTrue({"sweep", "read_post", "file_text", "login", "grades", "portal_notices", "read_portal"} <= names)
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
            save.assert_called_once_with("MoodleSession=x")
            self.assertEqual(workspace.load_config()["kaist_id"], "student")
            # a live session means no second push to the phone
            srv.connect = mock.Mock()
            srv.portal_alive = mock.Mock(return_value=True)
            self.assertEqual(srv.call("login", {})["status"], "logged_in")
            save.assert_called_once()

    def test_first_use_sets_up_the_semester_folder(self):
        from nubzuki import mcp
        courses = [{"id": 1, "code": "CS.10001", "section": "A", "name": "Intro", "boards": {"notice": 9}}]
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(workspace, "CONFIG_FILE", os.path.join(td, "cfg.json")), \
                mock.patch.object(workspace, "CONFIG_DIR", td), \
                mock.patch.object(mcp, "discover", return_value=("2026F", courses)):
            workspace.save_config({"root": td})
            srv = mcp.Server()
            srv.connect = mock.Mock()
            out = srv.call("courses", {})
            self.assertEqual(out["semester"], "2026F")
            self.assertTrue(os.path.isdir(os.path.join(td, "2026F", "CS.10001", "files")))

    def test_slow_sweep_is_collected_on_the_next_call(self):
        from nubzuki import mcp
        release = threading.Event()

        def slow_run(cl, ws, **kw):
            kw["progress"]("boards 1/3")
            release.wait(5)
            return {"posts": [], "files": [], "grades": [], "deadlines": []}
        ws = mock.Mock(courses=[])
        ws.load_state.return_value = {"board:1": []}
        srv = mcp.Server()
        srv.connect = mock.Mock()
        with mock.patch.object(workspace, "find", return_value=ws), mock.patch.object(mcp, "run", slow_run), \
                mock.patch.object(mcp, "SWEEP_WAIT", 0.2):
            first = srv.call("sweep", {})
            self.assertEqual(first["status"], "running")
            self.assertEqual(first["progress"], "boards 1/3")
            release.set()
            done = srv.call("sweep", {})
            self.assertEqual(done["posts"], [])
            self.assertFalse(done["first_run"])
            self.assertIsNone(srv.sweep_job)

    def test_deadlines_come_from_the_last_sweep(self):
        from nubzuki import mcp
        with tempfile.TemporaryDirectory() as td:
            ws = workspace.Workspace(td)
            ws.info = {"semester": "2026F", "courses": [
                {"id": 1, "code": "CS.10001", "section": "A", "name": "Intro", "folder": "CS.10001"},
                {"id": 2, "code": "MAS.10002", "section": "B", "name": "Calculus", "folder": "MAS.10002"}]}
            ws.save_state({"assign:1": ["HW 3 | 2026-10-28 23:59 | not submitted"], "quiz:1": [], "assign:2": []})
            srv = mcp.Server()
            with mock.patch.object(workspace, "find", return_value=ws):
                out = srv.call("deadlines", {})
            self.assertEqual([c["course"] for c in out["courses"]], ["CS.10001"])
            self.assertIn("HW 3", out["courses"][0]["assign"][0])
            self.assertTrue(out["today"][:4].isdigit())
            self.assertIsNotNone(out["as_of"])

    def test_courses_by_code_or_name(self):
        from nubzuki import mcp
        ws = workspace.Workspace(tempfile.gettempdir())
        ws.info = {"courses": [
            {"id": 1, "code": "MAS.10002", "section": "AP", "name": "미적분학Ⅱ", "folder": "MAS.10002"},
            {"id": 2, "code": "MAS.10002", "section": "EF", "name": "미적분학Ⅱ", "folder": "MAS.10002"},
            {"id": 3, "code": "BS.10020", "section": "I", "name": "일반생물학", "folder": "BS.10020"},
            {"id": 4, "code": "PH.10042", "section": "D", "name": "일반물리학 II", "folder": "PH.10042"}]}
        srv = mcp.Server()
        self.assertEqual([c["id"] for c in srv.courses_for(ws, "mas.10002")], [1, 2])
        self.assertEqual([c["id"] for c in srv.courses_for(ws, "미적분")], [1, 2])
        self.assertEqual([c["id"] for c in srv.courses_for(ws, "일반 물리")], [4])
        with self.assertRaises(mcp.ToolError) as e:
            srv.courses_for(ws, "일반")
        self.assertIn("BS.10020", str(e.exception))


    def test_download_once_whatever_the_url_form(self):
        from nubzuki import sweep
        with tempfile.TemporaryDirectory() as td:
            ws = workspace.Workspace(td)
            course = {"id": 1, "code": "CS.10001", "folder": "CS.10001"}
            cl = mock.Mock()
            cl.download.side_effect = lambda url, dest, same_as=None: open(dest, "wb").close() or dest
            a = sweep.save_file(cl, ws, course, "pluginfile.php/7/mod_resource/content/1/Lec 9.pdf")
            b = sweep.save_file(cl, ws, course, "https://klms.kaist.ac.kr/pluginfile.php/7/mod_resource/content/1/Lec%209.pdf")
            self.assertEqual(a, b)
            self.assertEqual(cl.download.call_count, 1)
            self.assertTrue(a.endswith(os.path.join("CS.10001", "files", "Lec 9.pdf")))

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

    def test_network_failure_is_not_an_expired_session(self):
        from nubzuki import client
        cl = client.Client(cookie="MoodleSession=s")
        with mock.patch.object(cl, "_open", side_effect=urllib.error.URLError("offline")), \
                mock.patch.object(client.time, "sleep"):
            with self.assertRaises(client.KlmsError) as e:
                cl.get("/my/")
        self.assertNotIsInstance(e.exception, client.SessionExpired)
        self.assertIn("Could not reach KLMS", str(e.exception))

    def test_404_is_not_retried(self):
        from nubzuki import client
        cl = client.Client(cookie="MoodleSession=s")
        err = urllib.error.HTTPError("https://klms.kaist.ac.kr/x", 404, "Not Found", {}, io.BytesIO())
        with mock.patch.object(cl, "_open", side_effect=err) as op, mock.patch.object(client.time, "sleep"):
            with self.assertRaises(client.KlmsError):
                cl.get("/x")
        self.assertEqual(op.call_count, 1)

    def test_download_never_saves_a_login_page(self):
        from nubzuki import client

        class Resp(io.BytesIO):
            def __init__(self, url, body):
                super().__init__(body)
                self.url = url
                self.headers = {}

            def geturl(self):
                return self.url
        cl = client.Client(cookie="MoodleSession=s")
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "Lec 9.pptx")
            with mock.patch.object(cl, "_open", return_value=Resp("https://klms.kaist.ac.kr/login/ssologin.php", b"<html>")):
                with self.assertRaises(client.SessionExpired):
                    cl.download("pluginfile.php/1/mod_resource/content/1/Lec 9.pptx", dest)
            self.assertEqual(os.listdir(td), [])
            ok = Resp("https://klms.kaist.ac.kr/pluginfile.php/1/mod_resource/content/1/Lec%209.pptx", b"PK data")
            ok.headers = {"Content-Length": "7"}
            with mock.patch.object(cl, "_open", return_value=ok):
                cl.download("pluginfile.php/1/mod_resource/content/1/Lec 9.pptx", dest)
            self.assertEqual(os.listdir(td), ["Lec 9.pptx"])
            # the same file again under another name is recognised by its size and not written twice
            again = Resp(ok.url, b"PK data")
            again.headers = {"Content-Length": "7"}
            with mock.patch.object(cl, "_open", return_value=again):
                got = cl.download("x", os.path.join(td, "Lec 9 (2).pptx"), same_as=dest)
            self.assertEqual(got, dest)
            self.assertEqual(os.listdir(td), ["Lec 9.pptx"])

    def test_filename_cannot_escape(self):
        from nubzuki.client import filename_of
        self.assertEqual(filename_of("https://klms.kaist.ac.kr/pluginfile.php/1/a/..%2F..%2Fx.pdf"), ".._.._x.pdf")
        self.assertEqual(filename_of("https://klms.kaist.ac.kr/pluginfile.php/1/a/%2E%2E"), "_")
        self.assertEqual(filename_of("https://klms.kaist.ac.kr/pluginfile.php/1/a/Lec%209.pdf?forcedownload=1"), "Lec 9.pdf")


class Text(unittest.TestCase):
    def office(self, path, files):
        with zipfile.ZipFile(path, "w") as z:
            for name, xml in files.items():
                z.writestr(name, xml)

    def test_pptx_and_docx(self):
        a = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "s.pptx")
            self.office(p, {"ppt/slides/slide2.xml": f'<s {a}><a:t>Krebs cycle</a:t></s>',
                            "ppt/slides/slide1.xml": f'<s {a}><a:t>Glycolysis</a:t><a:t>2 ATP</a:t></s>'})
            self.assertEqual(text.file_text(p), "[1] Glycolysis 2 ATP\n[2] Krebs cycle")
            d = os.path.join(td, "h.docx")
            self.office(d, {"word/document.xml": f'<w:document {w}><w:body><w:p><w:r><w:t>Due </w:t></w:r>'
                                                 f'<w:r><w:t>Friday</w:t></w:r></w:p><w:p/></w:body></w:document>'})
            self.assertEqual(text.file_text(d), "Due Friday")

    def test_damaged_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "bad.pptx")
            with open(p, "w") as f:
                f.write("<html>login</html>")
            with self.assertRaises(text.TextError):
                text.file_text(p)

    def test_pdf_pages(self):
        done = subprocess.CompletedProcess([], 0, stdout="첫 장\fsecond\f".encode(), stderr=b"")
        with mock.patch.object(text, "_pdftotext", return_value="/x/pdftotext"), \
                mock.patch.object(text.subprocess, "run", return_value=done):
            self.assertEqual(text.file_text("a.pdf"), "[page 1]\n첫 장\n\n[page 2]\nsecond")
        scanned = subprocess.CompletedProcess([], 0, stdout=b"\f \f", stderr=b"")
        with mock.patch.object(text, "_pdftotext", return_value="/x/pdftotext"), \
                mock.patch.object(text.subprocess, "run", return_value=scanned):
            with self.assertRaises(text.TextError):
                text.file_text("scan.pdf")


class Privacy(unittest.TestCase):
    def test_mask(self):
        from nubzuki import board
        self.assertEqual(board.mask("김민준"), "김O준")
        self.assertEqual(board.mask("김철"), "김O")
        self.assertEqual(board.mask("남궁민수"), "남OO수")
        self.assertEqual(board.mask("Jane Doe"), "J*** D**")
        self.assertEqual(board.mask_authors("제목\n작성자\n:\n홍길동\n본문"), "제목\n작성자\n:\n홍O동\n본문")

    def test_student_board_posts_need_opt_in(self):
        from nubzuki import board, mcp
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(workspace, "CONFIG_FILE", os.path.join(td, "cfg.json")), \
                mock.patch.object(workspace, "CONFIG_DIR", td):
            ws = workspace.Workspace(td)
            ws.info = {"courses": [{"id": 1, "code": "CS.10001", "section": "A", "name": "Intro", "folder": "CS",
                                    "boards": {"notice": 10, "qna": 11}}]}
            srv = mcp.Server()
            srv.connect = mock.Mock()
            with mock.patch.object(workspace, "find", return_value=ws), \
                    mock.patch.object(board, "article", return_value=("작성자\n:\n홍길동\nQ", [])):
                self.assertIn("홍길동", srv.call("read_post", {"board": 10, "bwid": 1})["text"])
                with self.assertRaises(mcp.ToolError):
                    srv.call("read_post", {"board": 11, "bwid": 2})
                workspace.save_config({"student_posts": True})
                self.assertIn("홍O동", srv.call("read_post", {"board": 11, "bwid": 2})["text"])


class Grades(unittest.TestCase):
    def test_table(self):
        from nubzuki import sweep
        html = ("<table><tr><th>성적 항목</th><th>성적</th><th>범위</th></tr><tr><td>Part II Exam</td></tr>"
                "<tr><td>Part II 1-(a)</td><td>4.00</td><td>0–10</td></tr>"
                "<tr><td>강좌 합계</td><td>-</td><td>0–540</td></tr></table>")
        cl = mock.Mock()
        cl.get.return_value = html
        cols, rows = sweep.grade_table(cl, 1)
        self.assertEqual(cols, ["성적 항목", "성적", "범위"])
        self.assertEqual(rows, [["Part II Exam"], ["Part II 1-(a)", "4.00", "0–10"], ["강좌 합계", "-", "0–540"]])


PORTAL_ITEM = {"pstNo": 5, "pstTtl": "근로장학생 모집", "boardNm": "근로장학생", "pstWrtrNm": "직원",
               "pstWrtrDeptNm": "예술융합센터", "regDt": "2026.10.30 15:21:49", "atchFileCnt": 1, "inqCnt": 3,
               "delYn": "N", "loginId": "me"}


class Portal(unittest.TestCase):
    def test_summary_and_detail(self):
        from nubzuki import portal
        s = portal.summary(PORTAL_ITEM)
        self.assertEqual((s["id"], s["date"], s["board"]), (5, "2026-10-30 15:21", "근로장학생"))
        self.assertNotIn("loginId", s)
        d = portal.detail({**PORTAL_ITEM, "pstCn": "<p>모집 인원 : 1명</p><p>마감 11/6</p>",
                           "boardAtchList": [{"atchFileNm": "a.docx", "atchFileSizeFormat": "18.5KB"}]})
        self.assertEqual(d["text"], "모집 인원 : 1명\n마감 11/6")
        self.assertEqual(d["attachments"], [{"name": "a.docx", "size": "18.5KB"}])

    def test_expired_session(self):
        from nubzuki import portal
        err = urllib.error.HTTPError("https://portal.kaist.ac.kr/x", 401, "", {}, io.BytesIO(b"<html>"))
        with mock.patch.object(portal._opener, "open", side_effect=err):
            with self.assertRaises(portal.PortalExpired):
                portal.Portal(cookie="JSESSIONID=x").recents()
        with mock.patch.object(portal.auth, "portal_cookie", return_value=None):
            with self.assertRaises(portal.PortalExpired):
                portal.Portal()

    def test_since_stops_at_seen(self):
        from nubzuki import portal
        pc = portal.Portal(cookie="JSESSIONID=x")
        pages = {1: [{"id": i} for i in (9, 8, 7)], 2: [{"id": i} for i in (6, 5, 4)]}
        pc.recents = lambda n, p: pages.get(p, [])
        self.assertEqual([r["id"] for r in pc.since({5})], [9, 8, 7, 6])

    def test_sweep_baseline_then_new(self):
        from nubzuki import sweep
        pc = mock.Mock()
        pc.recents.return_value = [{"id": 2}, {"id": 1}]
        new, report = {}, {"portal": []}
        self.assertEqual(sweep.portal_changes({}, new, report, pc), [])
        self.assertEqual(new["portal"], [2, 1])
        pc.since.return_value = [{"id": 3}]
        new, report = {}, {"portal": []}
        self.assertEqual(sweep.portal_changes({"portal": [2, 1]}, new, report, pc), [{"id": 3}])
        self.assertEqual(new["portal"], [3, 2, 1])


class State(unittest.TestCase):
    def test_damaged_state_falls_back_to_backup(self):
        with tempfile.TemporaryDirectory() as td:
            ws = workspace.Workspace(td)
            ws.save_state({"board:1": [1]})
            ws.save_state({"board:1": [1, 2]})
            with open(ws.state_file, "w") as f:
                f.write('{"board:1": [1, 2')
            self.assertEqual(ws.load_state(), {"board:1": [1]})


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

    def test_toml_quoted_key_is_replaced(self):
        from nubzuki import install
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "config.toml")
            with open(p, "w", encoding="utf-8") as f:
                f.write('[mcp_servers."nubzuki"]\ncommand = "old"\n')
            self.assertEqual(install.add_to_toml(p, "/bin/nubzuki", ["mcp"]), "updated")
            with open(p, encoding="utf-8") as f:
                self.assertEqual(f.read(), '[mcp_servers.nubzuki]\ncommand = "/bin/nubzuki"\nargs = ["mcp"]\n')

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_private_config_stays_private(self):
        from nubzuki import install
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "cfg.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write('{"apiKey": "secret"}')
            os.chmod(p, 0o600)
            install.add_to_json(p, "/bin/nubzuki", ["mcp"])
            self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)
            self.assertEqual(sorted(os.listdir(td)), ["cfg.json", "cfg.json.bak"])

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
        for args in (["--help"], []):
            r = subprocess.run([sys.executable, "-m", "nubzuki", *args], capture_output=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0)
            self.assertIn("sweep", r.stdout)


if __name__ == "__main__":
    unittest.main()
