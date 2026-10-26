import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys

from . import __version__, auth, board, workspace
from .client import Client, KlmsError, filename_of
from .discover import SEMESTER_NAME, discover
from .sweep import run
from .text import pptx_text


def need_ws():
    ws = workspace.find()
    if not ws:
        sys.exit("워크스페이스가 없습니다. 먼저 `nubzuki init` 을 실행하세요.")
    return ws


def cmd_login(a):
    print("브라우저 개발자도구 > Application > Cookies > klms.kaist.ac.kr 에서 MoodleSession 값을 복사하세요.")
    v = getpass.getpass("MoodleSession: ").strip()
    if not v:
        sys.exit("입력이 비었습니다.")
    if "=" not in v:
        v = f"MoodleSession={v}"
    auth.save_cookie(v)
    Client(cookie=v).check()
    print(f"로그인 확인 완료. 저장 위치: {auth.COOKIE_FILE} (권한 600)")


def cmd_init(a):
    root = a.root or workspace.load_config().get("root")
    if not root:
        default = os.path.join(os.path.expanduser("~"), "KAIST")
        root = input(f"학기 폴더를 만들 기본 위치 [{default}]: ").strip() or default
    sem, courses = discover(Client())
    ws, created = workspace.init(root, sem, courses)
    y, s = sem[:4], sem[4:]
    print(f"\n{y}년 {SEMESTER_NAME.get(s, s)}학기 워크스페이스: {ws.path}")
    for c in courses:
        mark = "+" if c["folder"] in created else " "
        sec = f"({c['section']})" if c["section"] else ""
        print(f"  {mark} {c['folder']:<12} {c['code']}{sec} {c['name']}")
    print(f"\n과목 {len(courses)}개, 새 폴더 {len(created)}개. 각 과목 폴더에 files/ notices/ 가 있습니다.")


def cmd_courses(a):
    ws = need_ws()
    if a.json:
        print(json.dumps(ws.courses, ensure_ascii=False, indent=2))
        return
    print(ws.info.get("semester", ""), ws.path)
    for c in ws.courses:
        b = c.get("boards", {})
        print(f"  {c['code']:<10} {c['section']:<5} id={c['id']:<7} "
              f"공지={b.get('notice', '-')} Q&A={b.get('qna', '-')} 자유={b.get('free', '-')}  {c['name']}")


def cmd_sweep(a):
    ws = need_ws()
    rep = run(Client(), ws, since=a.since, download=a.download,
              out=(lambda *_: None) if a.json else print)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))


def cmd_read(a):
    if len(a.ids) % 2:
        sys.exit("사용: nubzuki read <board> <bwid> [<board> <bwid> ...]")
    ws = workspace.find()
    by_board = {b: c for c in (ws.courses if ws else []) for b in c.get("boards", {}).values()}
    cl = Client()
    for bid, bwid in zip(a.ids[0::2], a.ids[1::2]):
        text, files = board.article(cl, bid, bwid)
        print(f"\n{'=' * 70}\n### board={bid} bwid={bwid}\n{'=' * 70}\n{text[:6000]}")
        if files:
            print("\n[첨부]\n" + "\n".join(f"  {f}" for f in files))
        c = by_board.get(int(bid))
        if a.save and c:
            p = os.path.join(ws.folder(c), "notices", f"{bwid}.md")
            with open(p, "w") as f:
                f.write(text + ("\n\n" + "\n".join(files) if files else "") + "\n")
            print(f"\n(저장: {p})")


def cmd_dl(a):
    cl = Client(strict=False)
    os.makedirs(a.to, exist_ok=True)
    for u in a.urls:
        dest = os.path.join(a.to, filename_of(u))
        cl.download(u, dest)
        print(os.path.getsize(dest), dest)


def cmd_text(a):
    p = a.file
    if p.lower().endswith(".pptx"):
        print(pptx_text(p))
    elif p.lower().endswith(".pdf"):
        if not shutil.which("pdftotext"):
            sys.exit("pdftotext 가 필요합니다 (brew install poppler / apt install poppler-utils).")
        subprocess.run(["pdftotext", "-layout", p, "-"])
    else:
        sys.exit("pptx 또는 pdf 만 지원합니다.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="nubzuki", description="KAIST KLMS 새 소식 스윕 + 학기 폴더 정리")
    p.add_argument("--version", action="version", version=__version__)
    sp = p.add_subparsers(dest="cmd", required=True)

    sp.add_parser("login", help="MoodleSession 쿠키를 직접 저장").set_defaults(fn=cmd_login)

    s = sp.add_parser("init", help="현재 학기 폴더(예: 2026F)와 과목별 폴더 만들기")
    s.add_argument("--root", help="학기 폴더를 둘 기본 위치 (기본: ~/KAIST)")
    s.set_defaults(fn=cmd_init)

    s = sp.add_parser("courses", help="수강과목·게시판 ID 보기")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_courses)

    s = sp.add_parser("sweep", help="지난 실행 이후 새 글·과제·자료·성적만 보기")
    s.add_argument("--since", metavar="YYYY-MM-DD")
    s.add_argument("--download", action="store_true", help="새 강의자료를 과목 폴더 files/ 에 받기")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_sweep)

    s = sp.add_parser("read", help="게시글 본문과 첨부 링크 보기")
    s.add_argument("ids", nargs="+", metavar="ID")
    s.add_argument("--save", action="store_true", help="과목 폴더 notices/ 에 저장")
    s.set_defaults(fn=cmd_read)

    s = sp.add_parser("dl", help="첨부파일 받기")
    s.add_argument("urls", nargs="+")
    s.add_argument("--to", default=".")
    s.set_defaults(fn=cmd_dl)

    s = sp.add_parser("text", help="pptx/pdf 에서 텍스트 뽑기")
    s.add_argument("file")
    s.set_defaults(fn=cmd_text)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (KlmsError, auth.AuthError) as e:
        sys.exit(f"오류: {e}\n(상태 파일은 건드리지 않았습니다)")


if __name__ == "__main__":
    main()
