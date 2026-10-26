<h1 align="center">nubzuki</h1>

<p align="center"><b>KAIST KLMS for you and your AI agent.</b><br>
Tap a number on your phone once, then ask what's new, what's due, and what the lecture notes say.</p>

---

```
$ nubzuki sweep
========================================================================
■ Boards
========================================================================

[MAS.10002 미적분학Ⅱ] Notices (board=...)
   NEW [2026-10-26] bwid=...  중간고사&Part II Exam 클레임 안내

========================================================================
■ Assignments, quizzes, files, grades
========================================================================

[PH.10042 일반물리학 II] course=...
  <new files>
    Lecture Note #9 Chap29.pdf  → PH.10042/files/Lecture Note #9 Chap29.pdf
[HSS.20117 스타트업 101] course=...
  <assign>
    9주차 | 중간발표 과제물 제출 | 2026년 10월 28일(수요일) 오후 11:59 | 제출물 없음
```

nubzuki shows **only what changed** on KLMS since you last looked: new posts, deadline changes,
new course files and new grades. It finds your courses and boards by itself and keeps one folder per course,
so you, Claude Code, Cursor or any agent that can run a shell command can work from the same place.

> Unofficial, not affiliated with KAIST. Use it with your own account, for personal use.
> It never sends more than two requests at a time. Please don't run it in a tight loop.

## Quick start

Python 3.9+, no required dependencies.

```sh
pipx install git+https://github.com/Koooon-and-meemee/nubzuki

nubzuki login --id <your KAIST ID>   # tap the number shown, in the KAIST app
nubzuki init                         # creates ~/KAIST/2026F/<course>/{files,notices}
nubzuki sweep                        # what changed since last time
```

The first `sweep` saves a baseline and prints a summary plus posts from the last 7 days (`--all` prints everything).
After that, only changes appear. When the session expires, `sweep` sends a new request to your phone by itself.

## Use it with your AI

**Claude Code**: install the skill, then just say "check KLMS" or "what's due this week?".
Claude Code sweeps, reads the new posts, extracts text from attached slides and summarizes.

```sh
mkdir -p ~/.claude/skills/nubzuki
curl -fsSL https://raw.githubusercontent.com/Koooon-and-meemee/nubzuki/main/skills/nubzuki/SKILL.md \
  -o ~/.claude/skills/nubzuki/SKILL.md
```

**Any other agent** (Cursor, Codex, Gemini CLI, scripts): every command prints plain text, and `sweep --json`
returns structured results. Course files land in `<course>/files/`, and `nubzuki text` turns PDF and PPTX into text,
so an agent can read lecture notes without you attaching anything.

Things to ask:
- "Anything new on KLMS? Download new files and summarize them."
- "List every deadline in the next 7 days."
- "Read the latest Calculus notice and tell me when and where the claim session is."
- "Summarize Chapter 9 from the chemistry lecture notes."

## What it does

- **Boards**: new posts on each course's Notices, Q&A and free board
- **Assignments and quizzes**: new or changed rows in each course's deadline table
- **Course files**: newly uploaded files, optionally downloaded into the course folder
- **Grades**: new rows on your grade report
- **Folders**: one folder per semester and course, created from your KLMS dashboard

You never type a course ID or board ID. nubzuki reads the current semester and your enrolled courses
from the dashboard and finds each course's boards on its page.

## Logging in

### Phone login (recommended, any OS)

```sh
nubzuki login --id <your KAIST ID>
```

```
  → Open the KAIST app on your phone and tap  47
Waiting for approval (up to 3 minutes)...
Logged in.
```

This uses KAIST SSO's easy login: nubzuki sends only your ID, KAIST pushes a request to the KAIST app,
and you tap the number shown in the terminal. No password is sent or stored.
Your ID is remembered locally, so later, when the session expires, `nubzuki sweep` sends a new request
by itself (only in an interactive terminal, and at most once a minute).

Requirements: the KAIST login app registered for your account (sso.kaist.ac.kr → 로그인 앱 등록).
KAIST may send a "new device" notice on each login, because nubzuki does not register itself as a trusted device.

### Browser cookies

Before asking your phone, nubzuki tries existing sessions in this order and uses the first one that works.
It never prints the cookie.

1. The `NUBZUKI_COOKIE` environment variable (e.g. `MoodleSession=...`)
2. `~/.config/nubzuki/cookie`, written by `nubzuki login` with mode 600
3. Chrome, Edge, Brave, Firefox or Safari through `browser_cookie3`, if installed
4. macOS + Chrome: decrypted with the "Chrome Safe Storage" Keychain entry (macOS asks for permission the first time)
5. Firefox on any OS: read directly from the profile's `cookies.sqlite`

On Windows, Chrome and Edge (127+) use app-bound encryption, so no other program can read their cookies.
Use phone login, Firefox, or `nubzuki login --cookie` with `MoodleSession` copied from DevTools.

## Commands

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
```

`nubzuki text` needs `pdftotext` for PDFs (`brew install poppler` or `apt install poppler-utils`).

## Folder layout

```
~/KAIST/2026F/
├── .nubzuki/          # course list and last sweep state (contains grades, do not share)
├── CS.10001/
│   ├── files/         # course files
│   └── notices/       # saved posts
├── MAS.10002/
└── ...
```

Inside a semester folder, nubzuki uses that semester. Anywhere else, it uses the semester you last ran `init` for.
Run `nubzuki init` again when a new semester starts to get `2027S/` and so on.
Running it again in the same semester keeps existing folders and only adds new courses.
Semester suffixes: `S` Spring, `U` Summer, `F` Fall, `W` Winter.

## No false "nothing new"

Two traps came up while scraping KLMS (Moodle), and nubzuki guards against both.

- **Expired session**: KLMS still answers with HTTP 200 and a login page, which reads like "0 new posts".
  nubzuki stops as soon as it sees a page that isn't logged in, and **does not overwrite your saved state**.
- **Session lock**: Moodle serializes requests per session. Too many at once and you get an
  `Unable to obtain session lock` page, which also looks like "0 new posts".
  nubzuki caps concurrency at two and waits and retries on a lock.

## Privacy

- Everything runs on your machine. Nothing is sent anywhere except KLMS and KAIST SSO.
- No password is sent or stored. The session cookie is saved with mode 600 and never printed.
- `.nubzuki/state.json` contains your grades. Leave it out when you share a folder or put it in git.

## Install options

```sh
pipx install git+https://github.com/Koooon-and-meemee/nubzuki
pip install git+https://github.com/Koooon-and-meemee/nubzuki
pip install "nubzuki[browser] @ git+https://github.com/Koooon-and-meemee/nubzuki"   # browser_cookie3 support
```

Tested on macOS, Linux and Windows with Python 3.9 and 3.13.
If the KLMS layout changes and parsing breaks, please open an issue.

## License

MIT

---

<sub>Named after Nubzuki, KAIST's mascot. This project is not affiliated with or endorsed by KAIST.</sub>
