<h1 align="center">nubzuki</h1>

<p align="center">An unofficial CLI that tells you <b>only what changed</b> on KAIST KLMS since you last looked,<br>and keeps a tidy folder for every course you take.</p>

---

Named after Nubzuki, KAIST's mascot.

> This is an **unofficial** tool with no affiliation to KAIST. Use it with your own account, for personal use only.
> It never sends more than two requests at a time. Please don't run it in a tight loop.

## What it does

- **Boards**: new posts on each course's Notices, Q&A and free board
- **Assignments and quizzes**: courses whose deadline table changed
- **Course files**: newly uploaded files, optionally downloaded straight into the course folder
- **Grades**: new rows on your grade report
- **Folders**: creates a layout like `~/KAIST/2026F/CS.10001/{files,notices}` for you

You never type a course ID or board ID. nubzuki reads the current semester and your enrolled courses
from the KLMS dashboard and finds each course's boards on its page.

## Install

Python 3.9+, no required dependencies.

```sh
pipx install git+https://github.com/Koooon-and-meemee/nubzuki
# or
pip install git+https://github.com/Koooon-and-meemee/nubzuki
# to read browser cookies through browser_cookie3
pip install "nubzuki[browser] @ git+https://github.com/Koooon-and-meemee/nubzuki"
```

`nubzuki text` needs `pdftotext` for PDFs (`brew install poppler` or `apt install poppler-utils`).

## Getting started

1. Log in to https://klms.kaist.ac.kr in your browser.
2. Create your semester folder:

```sh
nubzuki init                  # defaults to ~/KAIST (asks once)
nubzuki init --root ~/school  # somewhere else
```

```
~/KAIST/2026F/
├── .nubzuki/          # course list and last sweep state (do not share)
├── CS.10001/
│   ├── files/         # course files
│   └── notices/       # saved posts
├── MAS.10001/
└── ...
```

When a new semester starts, run `nubzuki init` again and you get a new folder such as `2027S/`.
Running it again in the same semester keeps existing folders and only adds new courses.
Semester suffixes: `S` Spring, `U` Summer, `F` Fall, `W` Winter.

## Usage

```sh
nubzuki sweep                   # only what changed since the last run
nubzuki sweep --download        # also download new course files into <course>/files
nubzuki sweep --since 2026-10-01
nubzuki sweep --json            # for scripts and agents

nubzuki read <board> <bwid> [<board> <bwid> ...]   # post body + attachment links
nubzuki read <board> <bwid> --save                 # save to <course>/notices/<bwid>.md
nubzuki dl <url> [...] --to CS.10001/files         # download attachments
nubzuki text lecture.pptx                          # slide text + speaker notes
nubzuki text lecture.pdf
nubzuki courses                                    # course IDs and board IDs
nubzuki login                                      # paste your cookie manually
```

Inside a semester folder, nubzuki uses that semester. Anywhere else, it uses the semester you last ran `init` for.
The first `sweep` has nothing to compare against, so everything shows up as new. After that, only changes appear.

## Logging in (cookies)

nubzuki looks in this order and uses the first cookie it finds. It never prints the cookie.

1. The `NUBZUKI_COOKIE` environment variable (e.g. `MoodleSession=...`)
2. `~/.config/nubzuki/cookie`, written by `nubzuki login` with mode 600
3. Chrome, Edge, Brave, Firefox or Safari through `browser_cookie3`, if installed
4. macOS + Chrome: decrypted with the "Chrome Safe Storage" Keychain entry (macOS asks for permission the first time)

For `nubzuki login`, copy the `MoodleSession` value from DevTools → Application → Cookies → `klms.kaist.ac.kr`.

## No false "nothing new"

Two traps came up while scraping KLMS (Moodle), and nubzuki guards against both.

- **Expired session**: KLMS still answers with HTTP 200 and a login page, which reads like "0 new posts".
  nubzuki stops as soon as it sees a page that isn't logged in, and **does not overwrite your saved state**.
  Log in again and rerun; anything you missed still shows up.
- **Session lock**: Moodle serializes requests per session. Too many at once and you get an
  `Unable to obtain session lock` page, which also looks like "0 new posts".
  nubzuki caps concurrency at two and waits and retries on a lock. Your session is still valid, so there is no need to log in again.

## Claude Code skill

Ask Claude Code to "check KLMS" and it will sweep, read new posts, extract attachment text and summarize.

```sh
git clone https://github.com/Koooon-and-meemee/nubzuki
cp -r nubzuki/skills/nubzuki ~/.claude/skills/
```

## Notes

- `.nubzuki/state.json` contains your grades. Leave it out when you share a semester folder or put it in git.
- If the KLMS layout changes, parsing may break. Please open an issue.

## License

MIT

---

<sub>This project is not affiliated with or endorsed by KAIST.</sub>
