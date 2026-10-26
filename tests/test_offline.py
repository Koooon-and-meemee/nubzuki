import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from nubzuki import auth, discover, workspace
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


class Cli(unittest.TestCase):
    def test_help(self):
        r = subprocess.run([sys.executable, "-m", "nubzuki", "--help"], capture_output=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0)
        self.assertIn("sweep", r.stdout)


if __name__ == "__main__":
    unittest.main()
