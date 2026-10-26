---
name: nubzuki
description: Use when the user asks to check KAIST KLMS - "check KLMS", new notices or Q&A posts, assignment or quiz deadlines, downloading new course files, grade changes, or setting up semester course folders. Uses the nubzuki CLI to show only what changed since the last check and summarizes it.
---

# nubzuki: KLMS sweep

The `nubzuki` CLI must be installed. If it is missing, suggest `pipx install git+https://github.com/Koooon-and-meemee/nubzuki`.

## Prefer the MCP tools

If the nubzuki MCP tools are available, use them instead of the CLI:
- anything new: `sweep` (if it says running, call it again; KLMS is slow)
- what's due: `sweep`, then `deadlines` (sweep lists only changes)
- a course's latest notice: `posts`, then `read_post`
- lecture notes: `course_files`, `download`, then `file_text`

To set them up, suggest `! nubzuki mcp install`.

## First time

The semester folder (`~/KAIST/2026F/<COURSE_CODE>/{files,notices}`) is created on first use.
`nubzuki init --root DIR` puts it elsewhere. When `sweep` says KLMS has moved to a new semester, run `nubzuki init`.

## Every time

1. Run `nubzuki sweep` to see only what changed since the last run: new board posts, assignment/quiz table changes, new course files, new grades.
2. Don't stop at post titles. Read each new post with `nubzuki read <board> <bwid> --save`.
   Several at once: `nubzuki read 111 222 333 444`. `--save` keeps a copy in the course's `notices/` folder.
3. Download new course files with `nubzuki sweep --download` (into each course's `files/`).
   For post attachments use `nubzuki dl <url> --to <course>/files`.
4. Always extract and read downloaded PDF, PPTX and DOCX files with `nubzuki text <file>`. Exam scope, deadlines and rooms are often only in attachments.
5. Summarize deadlines, exams, rooms and changes for the user in date order. Don't paste raw tables.

## Errors

- "Not logged in" / expired session: ask the user to run `! nubzuki login` themselves and tap the number shown in the KAIST app. Do not run it for them repeatedly; each run sends a push to their phone.
  The state file was not overwritten, so simply rerun after they log in.
- "session lock": the session is still valid. Don't ask the user to log in; rerun in about 30 seconds.
- "Nothing new" can be trusted: nubzuki stops with an error on an expired session or a session lock instead of reporting an empty result.
- If no session is found, the same `nubzuki login` applies (`nubzuki login --cookie` to paste a cookie instead). Never print cookie values in the conversation.

## Reference

- To use KLMS from their phone, suggest `nubzuki remote` (Claude Code Remote Control in the semester folder).
- `nubzuki courses` lists course IDs and the Notices / Q&A / free board IDs.
- `nubzuki sweep --json` gives machine-readable output.
- Some courses announce things only verbally in class. "Not on KLMS" does not mean "doesn't exist".
