<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo-light.svg" alt="NUBZUKI" width="420">
  </picture>
</p>

<p align="center"><b>KAIST KLMS for you and your AI.</b><br>
Ask Claude what's due today, or have it read this morning's lecture notes.<br>
<sub>넙죽이한테 물어보세요: 오늘 마감, 새 공지, 렉노 요약까지.</sub></p>

<p align="center">
  <a href="https://github.com/Koooon-and-meemee/nubzuki/actions/workflows/test.yml"><img src="https://github.com/Koooon-and-meemee/nubzuki/actions/workflows/test.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-0B3D91" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/dependencies-0-0B3D91" alt="no dependencies">
  <img src="https://img.shields.io/badge/MCP-Claude%20%C2%B7%20Cursor-0B3D91" alt="MCP">
  <img src="https://img.shields.io/badge/license-MIT-0B3D91" alt="MIT">
</p>

<p align="center"><img src="assets/demo-due.svg" alt="Asking Claude which assignments are due today. Claude logs in through the KAIST app, sweeps KLMS and lists today's deadlines." width="760"></p>

## Start in a minute

```sh
pipx install git+https://github.com/Koooon-and-meemee/nubzuki

nubzuki login --id <your KAIST ID>   # tap the number in the KAIST app
nubzuki init                         # ~/KAIST/2026F/<course>/{files,notices}
nubzuki mcp install                  # connects the Claude app, Claude Code and Cursor
```

Restart the Claude app (⌘Q, then open it again) and ask:

> 넙죽이한테 물어봐서 오늘 마무리 해야하는 과제 있는지 알려줘

That's it. The app starts nubzuki by itself whenever it needs it. There is nothing to keep running.
If the KLMS session has expired, Claude sends a login request to your phone and shows the number to tap right in the chat.

<sub>No `pipx`? `brew install pipx` on macOS, `pip install --user pipx` elsewhere. Requires the KAIST login app registered for your account (sso.kaist.ac.kr → 로그인 앱 등록).</sub>

## Ask it like a classmate

<p align="center"><img src="assets/demo-notes.svg" alt="Asking Claude to fetch General Biology lecture notes and summarize today's lecture" width="760"></p>

| Ask | What happens |
|---|---|
| 넙죽이한테 물어봐서 오늘 마무리 해야하는 과제 있는지 알려줘 | Sweeps every course, reads related Q&A posts, lists what's due today in time order |
| 넙죽이한테 일생 렉노 받아와서 오늘 무슨 강의 하는지 정리해줘 | Downloads the new lecture file, extracts the slides and summarizes them |
| 이번 주 마감 전부 날짜순으로 | Assignments and quizzes from every course in one list |
| 미적 최신 공지 읽고 클레임 언제 어디서 하는지 알려줘 | Opens the post and its attachments, since rooms and times often live there |
| 새로 올라온 파일 다 받아서 요약해줘 | Saves files into each course's `files/` folder, then reads them |

Claude understands "넙죽이" as nubzuki, and course nicknames like 일생, 미적 and 일물 work because it matches them against your course list.

## From your phone

Keep your Mac on and run this once:

```sh
nubzuki remote
```

```
Starting a Remote Control session in ~/KAIST/2026F
Open the Claude app on your phone (or claude.ai/code) and pick this session.
Login requests go to the KAIST app on the same phone. Keep this terminal open; Ctrl+C to stop.
```

Open the **Claude app on your phone → Code → KLMS** and ask anything above, on the bus or between classes.
Everything still runs on your Mac. Your phone only shows the chat, and the KAIST login push lands on the same phone,
so a login is two taps without leaving the app.

`nubzuki remote` uses Claude Code's Remote Control (`claude remote-control`). It connects nubzuki to Claude Code if needed
and lets that session call nubzuki tools without asking each time. `--name` changes the session name.

## In the terminal

<p align="center"><img src="assets/demo-sweep.svg" alt="nubzuki sweep output: new posts, a new lecture file and a changed assignment" width="760"></p>

```sh
nubzuki sweep               # only what changed since last time
nubzuki sweep --download    # and download new course files
```

The first `sweep` saves a baseline and shows posts from the last 7 days. After that, only changes appear.

## What it watches

| | |
|---|---|
| 📌 **Boards** | New posts on each course's Notices, Q&A and free board |
| ⏰ **Assignments and quizzes** | New or changed rows in each course's deadline table |
| 📄 **Course files** | Newly uploaded files, optionally downloaded into the course folder |
| 🅰️ **Grades** | New rows on your grade report |
| 🗂 **Folders** | One folder per semester and course, built from your dashboard |

You never type a course ID or board ID. nubzuki reads the current semester and your courses from the dashboard
and finds each course's boards by itself. Run `nubzuki init` again when a new semester starts.

## Safe by design

- **Runs on your computer.** It talks only to `klms.kaist.ac.kr` and `sso.kaist.ac.kr`. No server, no analytics, no telemetry.
- **No password.** Login is KAIST's own easy login: nubzuki sends your ID, you tap a number on your phone.
- **The session cookie never leaves KLMS.** It is saved with mode 600 and never printed. Requests to any other host are refused,
  and the cookie is dropped on redirects to other hosts, so a link planted in a post can't leak it.
- **Your AI stays in its lane.** MCP tools can only read and write inside your semester folder.
- **Gentle on KLMS.** At most two requests at a time, with retries when Moodle's session lock is busy.
- **No false "nothing new".** An expired session or a session lock looks like an empty page to a naive scraper.
  nubzuki detects both, stops, and leaves your saved state untouched.

> Unofficial and not affiliated with KAIST. Use it with your own account, for personal use, and please don't run it in a tight loop.

## More

<details>
<summary><b>Commands</b></summary>

```sh
nubzuki login [--id ID]                            # phone login (ID is remembered)
nubzuki login --cookie                             # paste a MoodleSession cookie instead
nubzuki init [--root DIR]                          # semester folder + one folder per course
nubzuki courses [--json]                           # course IDs and board IDs

nubzuki sweep                                      # only what changed since the last run
nubzuki sweep --download                           # also download new course files
nubzuki sweep --since 2026-10-01
nubzuki sweep --json                               # for scripts and agents

nubzuki read <board> <bwid> [<board> <bwid> ...]   # post body + attachment links
nubzuki read <board> <bwid> --save                 # save to <course>/notices/<bwid>.md
nubzuki dl <url> [...] --to CS.10001/files         # download attachments
nubzuki text lecture.pdf                           # PDF, PPTX (with speaker notes), TXT, MD

nubzuki mcp install [--only claude-app ...]        # connect Claude Code, the Claude app, Cursor
nubzuki remote [--name KLMS]                       # use it from the Claude app on your phone
nubzuki mcp                                        # the MCP server itself (apps start it for you)
```

`nubzuki text` needs `pdftotext` for PDFs (`brew install poppler` or `apt install poppler-utils`).
</details>

<details>
<summary><b>MCP details and other AI apps</b></summary>

`nubzuki mcp install` finds Claude Code, the Claude app and Cursor and adds nubzuki to each.
It keeps your other settings, saves a `.bak` copy before changing a config file, and writes the full path to `nubzuki`,
so GUI apps find it even though they don't read your shell's PATH. `--only claude-app` (or `claude-code`, `cursor`) picks apps.

```
  ✓ Claude Code: registered for all projects. Start a new `claude` session to use it.
  ✓ Claude app: added in ~/Library/Application Support/Claude/claude_desktop_config.json (backup: .bak)
      Quit the Claude app completely (⌘Q / Exit) and reopen it.
```

Tools: `init`, `courses`, `sweep`, `read_post`, `download`, `list_files`, `file_text`, `login`, `login_status`.
`login` pushes to your phone only when the AI calls it, and at most once a minute.

Any other MCP client: run `nubzuki mcp` over stdio.

```json
{ "mcpServers": { "nubzuki": { "command": "/full/path/to/nubzuki", "args": ["mcp"] } } }
```

`which nubzuki` prints the full path. Agents without MCP (Codex, Gemini CLI, scripts) can use the CLI directly:
every command prints plain text and `sweep --json` returns structured results.

**Claude Code skill** (optional, for CLI-only use):

```sh
mkdir -p ~/.claude/skills/nubzuki
curl -fsSL https://raw.githubusercontent.com/Koooon-and-meemee/nubzuki/main/skills/nubzuki/SKILL.md \
  -o ~/.claude/skills/nubzuki/SKILL.md
```
</details>

<details>
<summary><b>Logging in</b></summary>

```
$ nubzuki login --id <your KAIST ID>

  → Open the KAIST app on your phone and tap  47

Waiting for approval (up to 3 minutes)...
Logged in.
```

This uses KAIST SSO's easy login: nubzuki sends only your ID, KAIST pushes a request to the KAIST app,
and you tap the number shown. Your ID is remembered locally, so later, when the session expires,
`nubzuki sweep` in a terminal or your AI over MCP sends a new request (at most once a minute).
KAIST may send a "new device" notice on each login, because nubzuki does not register itself as a trusted device.

Before asking your phone, nubzuki tries existing sessions in this order and uses the first one that works:

1. The `NUBZUKI_COOKIE` environment variable (e.g. `MoodleSession=...`)
2. `~/.config/nubzuki/cookie`, written by `nubzuki login` with mode 600
3. Chrome, Edge, Brave, Firefox or Safari through `browser_cookie3`, if installed
4. macOS + Chrome: decrypted with the "Chrome Safe Storage" Keychain entry (macOS asks for permission the first time)
5. Firefox on any OS: read directly from the profile's `cookies.sqlite`

On Windows, Chrome and Edge (127+) use app-bound encryption, so no other program can read their cookies.
Use phone login, Firefox, or `nubzuki login --cookie` with `MoodleSession` copied from DevTools.
</details>

<details>
<summary><b>Folder layout</b></summary>

```
~/KAIST/2026F/
├── .nubzuki/          # course list and last sweep state (contains grades, do not share)
├── .claude/           # created by `nubzuki remote`: lets Claude Code use nubzuki tools here
├── CS.10001/
│   ├── files/         # course files
│   └── notices/       # saved posts
├── MAS.10002/
└── ...
```

Inside a semester folder, nubzuki uses that semester. Anywhere else, it uses the semester you last ran `init` for.
Running `init` again keeps existing folders and only adds new courses.
Semester suffixes: `S` Spring, `U` Summer, `F` Fall, `W` Winter.
</details>

<details>
<summary><b>Install options</b></summary>

```sh
pipx install git+https://github.com/Koooon-and-meemee/nubzuki
pip install git+https://github.com/Koooon-and-meemee/nubzuki
pip install "nubzuki[browser] @ git+https://github.com/Koooon-and-meemee/nubzuki"   # browser_cookie3 support
```

Tested on macOS, Linux and Windows with Python 3.9 and 3.13.
If the KLMS layout changes and parsing breaks, please open an issue.
</details>

## License

MIT

---

<sub>Named after Nubzuki, KAIST's mascot. This project is not affiliated with or endorsed by KAIST.
Demo screens show sample data.</sub>
