import argparse
import getpass
import json
import os
import sys

from . import __version__, auth, board, sso, workspace
from .client import Client, KlmsError, SessionExpired, filename_of
from .discover import SEMESTER_NAME, discover
from .sweep import run
from .text import TextError, file_text


def need_ws():
    ws = workspace.find()
    if not ws:
        sys.exit("No workspace found. Run `nubzuki init` first.")
    return ws


def show_number(n):
    if n:
        print(f"\n  → Open the KAIST app on your phone and tap  {n}\n")
    else:
        print("\n  → Approve the request in the KAIST app on your phone.\n")
    print("Waiting for approval (up to 3 minutes)...", flush=True)


def phone_login(user_id):
    cookie = sso.login(user_id, on_number=show_number)
    auth.save_cookie(cookie)
    cfg = workspace.load_config()
    if cfg.get("kaist_id") != user_id:
        cfg["kaist_id"] = user_id
        workspace.save_config(cfg)
    print("Logged in.")
    return Client(cookie=cookie)


def connect():
    for cookie in auth.cookie_candidates():
        cl = Client(cookie=cookie)
        try:
            cl.check()
            return cl
        except SessionExpired:
            continue
    kid = workspace.load_config().get("kaist_id")
    if kid and sys.stdin.isatty():
        print("No live KLMS session. Sending a login request to your phone.")
        return phone_login(kid)
    if kid:
        raise SessionExpired("KLMS session expired. Run `nubzuki login` and tap the number on your phone.")
    raise auth.AuthError("No live KLMS session. Run `nubzuki login` to log in with the KAIST app.")


def cmd_login(a):
    if a.cookie:
        print("Copy the MoodleSession value from your browser: DevTools > Application > Cookies > klms.kaist.ac.kr")
        v = getpass.getpass("MoodleSession: ").strip()
        if not v:
            sys.exit("Empty input.")
        if "=" not in v:
            v = f"MoodleSession={v}"
        auth.save_cookie(v)
        Client(cookie=v).check()
        print(f"Logged in. Saved to {auth.COOKIE_FILE} (mode 600)")
        return
    kid = a.id or workspace.load_config().get("kaist_id") or input("KAIST ID: ").strip()
    if not kid:
        sys.exit("Empty KAIST ID.")
    phone_login(kid)


def cmd_init(a):
    root = a.root or workspace.load_config().get("root")
    if not root:
        default = os.path.join(os.path.expanduser("~"), "KAIST")
        root = input(f"Where should semester folders live? [{default}]: ").strip() or default
    sem, courses = discover(connect())
    ws, created = workspace.init(root, sem, courses)
    y, s = sem[:4], sem[4:]
    print(f"\n{SEMESTER_NAME.get(s, s)} {y} workspace: {ws.path}")
    for c in courses:
        mark = "+" if c["folder"] in created else " "
        sec = f"({c['section']})" if c["section"] else ""
        print(f"  {mark} {c['folder']:<12} {c['code']}{sec} {c['name']}")
    print(f"\n{len(courses)} courses, {len(created)} new folders. Each course folder has files/ and notices/.")


def cmd_courses(a):
    ws = need_ws()
    if a.json:
        print(json.dumps(ws.courses, ensure_ascii=False, indent=2))
        return
    print(ws.info.get("semester", ""), ws.path)
    for c in ws.courses:
        b = c.get("boards", {})
        print(f"  {c['code']:<10} {c['section']:<5} id={c['id']:<7} "
              f"notice={b.get('notice', '-')} qna={b.get('qna', '-')} free={b.get('free', '-')}  {c['name']}")


def cmd_sweep(a):
    ws = need_ws()
    rep = run(connect(), ws, since=a.since, download=a.download, show_all=a.all,
              out=(lambda *_: None) if a.json else print)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))


def cmd_read(a):
    if len(a.ids) % 2:
        sys.exit("usage: nubzuki read <board> <bwid> [<board> <bwid> ...]")
    ws = workspace.find()
    by_board = {b: c for c in (ws.courses if ws else []) for b in c.get("boards", {}).values()}
    cl = connect()
    for bid, bwid in zip(a.ids[0::2], a.ids[1::2]):
        text, files = board.article(cl, bid, bwid)
        print(f"\n{'=' * 70}\n### board={bid} bwid={bwid}\n{'=' * 70}\n{text[:6000]}")
        if files:
            print("\n[attachments]\n" + "\n".join(f"  {f}" for f in files))
        c = by_board.get(int(bid))
        if a.save and c:
            p = os.path.join(ws.folder(c), "notices", f"{bwid}.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(text + ("\n\n" + "\n".join(files) if files else "") + "\n")
            print(f"\n(saved: {p})")


def cmd_dl(a):
    cl = Client(strict=False)
    os.makedirs(a.to, exist_ok=True)
    for u in a.urls:
        dest = os.path.join(a.to, workspace.safe(filename_of(u)))
        cl.download(u, dest)
        print(os.path.getsize(dest), dest)


def cmd_text(a):
    try:
        print(file_text(a.file))
    except TextError as e:
        sys.exit(str(e))


def cmd_remote(a):
    import shutil
    import subprocess
    from . import install
    claude = shutil.which("claude")
    if not claude:
        sys.exit("Claude Code is not installed: https://claude.com/claude-code")
    ws = need_ws()
    if not install.claude_code_has_server():
        install.add_to_claude_code(*install.server_command())
        print("Connected nubzuki to Claude Code.")
    install.allow_tools(ws.path)
    print(f"Starting a Remote Control session in {ws.path}\n"
          "Open the Claude app on your phone (or claude.ai/code) and pick this session.\n"
          "Login requests go to the KAIST app on the same phone. Keep this terminal open; Ctrl+C to stop.\n", flush=True)
    sys.exit(subprocess.run([claude, "remote-control", "--name", a.name], cwd=ws.path).returncode)


def cmd_mcp(a):
    if a.action == "install":
        from .install import install
        install(a.only)
        return
    from .mcp import serve
    serve()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="nubzuki", description="Sweep KAIST KLMS for what changed and keep per-semester course folders")
    p.add_argument("--version", action="version", version=__version__)
    sp = p.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("login", help="log in by tapping a number in the KAIST app (or paste a cookie)")
    s.add_argument("--id", help="your KAIST ID (remembered after the first login)")
    s.add_argument("--cookie", action="store_true", help="paste a MoodleSession cookie instead")
    s.set_defaults(fn=cmd_login)

    s = sp.add_parser("init", help="create the current semester folder (e.g. 2026F) with one folder per course")
    s.add_argument("--root", help="where semester folders live (default: ~/KAIST)")
    s.set_defaults(fn=cmd_init)

    s = sp.add_parser("courses", help="list enrolled courses and their board IDs")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_courses)

    s = sp.add_parser("sweep", help="show only new posts, deadlines, files and grades since the last run")
    s.add_argument("--since", metavar="YYYY-MM-DD")
    s.add_argument("--download", action="store_true", help="download new course files into each course's files/ folder")
    s.add_argument("--all", action="store_true", help="on the first run, print everything instead of a summary")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_sweep)

    s = sp.add_parser("read", help="print a post and its attachment links")
    s.add_argument("ids", nargs="+", metavar="ID")
    s.add_argument("--save", action="store_true", help="also save it to the course's notices/ folder")
    s.set_defaults(fn=cmd_read)

    s = sp.add_parser("dl", help="download attachments")
    s.add_argument("urls", nargs="+")
    s.add_argument("--to", default=".")
    s.set_defaults(fn=cmd_dl)

    s = sp.add_parser("text", help="extract text from a .pptx or .pdf")
    s.add_argument("file")
    s.set_defaults(fn=cmd_text)

    s = sp.add_parser("remote", help="use KLMS from your phone: start a Claude Code Remote Control session in the semester folder")
    s.add_argument("--name", default="KLMS", help="session name shown in the Claude app (default: KLMS)")
    s.set_defaults(fn=cmd_remote)

    s = sp.add_parser("mcp", help="run the local MCP server, or `mcp install` to add it to Claude Code, the Claude app and Cursor")
    s.add_argument("action", nargs="?", choices=("serve", "install"), default="serve")
    s.add_argument("--only", nargs="+", choices=("claude-code", "claude-app", "cursor"),
                   help="with install: only these apps (default: every one found)")
    s.set_defaults(fn=cmd_mcp)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (KlmsError, auth.AuthError, sso.SSOError) as e:
        sys.exit(f"error: {e}\n(state file left untouched)")


if __name__ == "__main__":
    main()
