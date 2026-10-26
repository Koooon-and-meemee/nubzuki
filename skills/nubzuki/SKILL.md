---
name: nubzuki
description: Use when the user asks to check KAIST KLMS - "check KLMS", new notices or Q&A posts, assignment or quiz deadlines, downloading new course files, grade changes, or setting up semester course folders. Uses the nubzuki CLI to show only what changed since the last check and summarizes it.
---

# nubzuki: KLMS sweep

The `nubzuki` CLI must be installed. If it is missing, suggest `pipx install git+https://github.com/Koooon-and-meemee/nubzuki`.

## First time

1. Run `nubzuki init`. It reads the current semester (e.g. `2026F`) and enrolled courses from the dashboard
   and creates `~/KAIST/2026F/<COURSE_CODE>/{files,notices}`. Use `--root` for a different location.
2. When the semester changes, run `nubzuki init` again. Existing folders are kept; only new courses are added.

## Every time

1. Run `nubzuki sweep` to see only what changed since the last run: new board posts, assignment/quiz table changes, new course files, new grades.
2. Don't stop at post titles. Read each new post with `nubzuki read <board> <bwid> --save`.
   Several at once: `nubzuki read 111 222 333 444`. `--save` keeps a copy in the course's `notices/` folder.
3. Download new course files with `nubzuki sweep --download` (into each course's `files/`).
   For post attachments use `nubzuki dl <url> --to <course>/files`.
4. Always extract and read downloaded PDFs and PPTX files with `nubzuki text <file>`. Exam scope, deadlines and rooms are often only in attachments.
5. Summarize deadlines, exams, rooms and changes for the user in date order. Don't paste raw tables.

## Errors

- "Not logged in" / expired session: ask the user to run `! nubzuki login` themselves and tap the number shown in the KAIST app. Do not run it for them repeatedly; each run sends a push to their phone.
  The state file was not overwritten, so simply rerun after they log in.
- "session lock": the session is still valid. Don't ask the user to log in; rerun in about 30 seconds.
- If "nothing new" looks suspicious, suspect the session before the content. Check that `nubzuki courses` works.
- If no session is found, the same `nubzuki login` applies (`nubzuki login --cookie` to paste a cookie instead). Never print cookie values in the conversation.

## Reference

- `nubzuki courses` lists course IDs and the Notices / Q&A / free board IDs.
- `nubzuki sweep --json` gives machine-readable output.
- Some courses announce things only verbally in class. "Not on KLMS" does not mean "doesn't exist".
