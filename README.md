# nubzuki (넙죽이)

KAIST KLMS에서 **지난번 확인 이후 바뀐 것만** 뽑아 주고, 학기·과목별 폴더를 자동으로 만들어 주는 CLI입니다.
이름은 KAIST 마스코트 넙죽이(Nubzuki)에서 따왔습니다.

> 학교와 무관한 **비공식 도구**입니다. 본인 계정으로, 개인 용도로만 쓰세요.
> 요청은 한 번에 최대 2개씩만 보내도록 되어 있습니다. 반복 실행 간격을 짧게 잡지 마세요.

## 하는 일

- **게시판**: 수강과목마다 공지 / Q&A / 자유게시판의 새 글
- **과제·퀴즈**: 마감 표가 바뀐 과목
- **강의자료**: 새로 올라온 파일 (원하면 과목 폴더에 바로 다운로드)
- **성적**: 성적표에 새로 찍힌 점수
- **폴더 정리**: `~/KAIST/2026F/HSS.39944/{files,notices}` 같은 구조를 자동 생성

과목 ID나 게시판 ID를 손으로 적을 필요가 없습니다. 대시보드에서 현재 학기와 수강과목을 읽고,
과목 페이지에서 게시판을 찾습니다.

## 설치

Python 3.9 이상, 외부 의존성 없음.

```sh
pipx install git+https://github.com/Koooon-and-meemee/nubzuki
# 또는
pip install git+https://github.com/Koooon-and-meemee/nubzuki
# 브라우저 쿠키를 browser_cookie3로 읽고 싶다면
pip install "nubzuki[browser] @ git+https://github.com/Koooon-and-meemee/nubzuki"
```

pdf 텍스트 추출(`nubzuki text`)에는 `pdftotext`가 필요합니다 (`brew install poppler`).

## 시작하기

1. 브라우저에서 https://klms.kaist.ac.kr 에 로그인합니다.
2. 학기 폴더를 만듭니다.

```sh
nubzuki init                 # 기본 위치 ~/KAIST (처음 한 번 물어봄)
nubzuki init --root ~/school # 다른 위치
```

```
~/KAIST/2026F/
├── .nubzuki/          # 과목 목록과 마지막 스윕 상태 (공유 금지)
├── BS.10020/
│   ├── files/         # 강의자료
│   └── notices/       # 저장한 공지 본문
├── HSS.39944/
└── ...
```

학기가 바뀌면 다시 `nubzuki init` 하면 `2027S/` 처럼 새 학기 폴더가 생깁니다.
같은 학기에 다시 실행하면 기존 폴더는 그대로 두고 새 과목만 추가합니다.

## 사용법

```sh
nubzuki sweep                   # 지난 실행 이후 바뀐 것만
nubzuki sweep --download        # + 새 강의자료를 과목폴더/files 에 다운로드
nubzuki sweep --since 2026-10-01
nubzuki sweep --json            # 스크립트·에이전트용

nubzuki read <board> <bwid> [<board> <bwid> ...]   # 글 본문 + 첨부 링크
nubzuki read <board> <bwid> --save                 # 과목폴더/notices/<bwid>.md 로 저장
nubzuki dl <url> [...] --to HSS.39944/files        # 첨부 다운로드
nubzuki text lecture.pptx                          # pptx 슬라이드 + 발표자 노트
nubzuki text lecture.pdf
nubzuki courses                                    # 과목 ID · 게시판 ID
nubzuki login                                      # 쿠키 직접 입력
```

학기 폴더 안에서 실행하면 그 학기를, 밖에서 실행하면 마지막으로 `init`한 학기를 씁니다.
첫 `sweep`은 기준이 없어서 전부 새 것으로 나옵니다. 두 번째부터 바뀐 것만 나옵니다.

## 로그인(쿠키)

아래 순서로 찾고, 처음 찾은 것을 씁니다. 쿠키는 화면에 출력하지 않습니다.

1. 환경변수 `NUBZUKI_COOKIE` (예: `MoodleSession=...`)
2. `~/.config/nubzuki/cookie` (`nubzuki login` 으로 저장, 권한 600)
3. `browser_cookie3` 가 설치돼 있으면 Chrome / Edge / Brave / Firefox / Safari
4. macOS + Chrome: 키체인의 "Chrome Safe Storage" 로 직접 복호화 (처음 한 번 macOS 승인 창이 뜹니다)

`nubzuki login` 은 브라우저 개발자도구 → Application → Cookies → `klms.kaist.ac.kr` 의 `MoodleSession` 값을 붙여 넣으면 됩니다.

## 거짓 "0건"을 막는 장치

KLMS(Moodle)를 긁을 때 실제로 겪은 함정 두 가지를 막아 두었습니다.

- **세션 만료**: 만료돼도 HTTP 200과 로그인 화면이 와서, 그대로 읽으면 "새 글 0건"처럼 보입니다.
  nubzuki는 로그인되지 않은 페이지를 받으면 바로 멈추고, **상태 파일을 덮어쓰지 않습니다.**
  브라우저에서 다시 로그인한 뒤 실행하면 놓친 것까지 그대로 나옵니다.
- **세션 잠금**: Moodle은 세션 하나에 요청을 한 줄로 세웁니다. 동시에 너무 많이 보내면
  `Unable to obtain session lock` 페이지가 오는데, 이것도 "0건"처럼 보입니다.
  동시 요청을 2개로 제한하고 잠금이 오면 기다렸다 재시도합니다. 이 경우 세션은 살아 있으니 재로그인할 필요가 없습니다.

## Claude Code 스킬

Claude Code 에서 "KLMS 확인해" 한마디로 스윕 → 새 글 본문 읽기 → 첨부 텍스트 추출 → 요약까지 하게 할 수 있습니다.

```sh
git clone https://github.com/Koooon-and-meemee/nubzuki
cp -r nubzuki/skills/nubzuki ~/.claude/skills/
```

## 주의

- `.nubzuki/state.json` 에는 성적이 들어갑니다. 학기 폴더를 공유하거나 git 에 올릴 때 빼세요.
- KLMS 화면 구조가 바뀌면 파싱이 깨질 수 있습니다. 이슈로 알려 주세요.

---

## English

**nubzuki** is an unofficial CLI for KAIST's KLMS (Moodle). It shows only what changed since your last run:
new board posts, assignment/quiz table changes, new course files, and new grades.
`nubzuki init` reads your current semester and enrolled courses from the dashboard and creates
`~/KAIST/2026F/<COURSE_CODE>/{files,notices}`. No course or board IDs to configure.

```sh
pipx install git+https://github.com/Koooon-and-meemee/nubzuki
nubzuki init
nubzuki sweep --download
nubzuki read <board> <bwid> --save
```

Cookies are taken from `NUBZUKI_COOKIE`, `~/.config/nubzuki/cookie` (`nubzuki login`), `browser_cookie3`,
or macOS Chrome via the Keychain, in that order. Expired sessions and Moodle session-lock pages are detected
and never overwrite your saved state, so you don't get a false "nothing new".
For personal use with your own account only. MIT licensed.
