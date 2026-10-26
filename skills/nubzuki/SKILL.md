---
name: nubzuki
description: KAIST KLMS 확인 요청 시 사용. "KLMS 확인해", 새 공지·Q&A, 과제·퀴즈 마감, 새 강의자료 받기, 성적 변동 확인, 학기 폴더 정리. nubzuki CLI로 지난 확인 이후 바뀐 것만 뽑아 요약한다.
---

# nubzuki: KLMS 스윕

`nubzuki` CLI가 설치돼 있어야 한다. 없으면 `pipx install git+https://github.com/Koooon-and-meemee/nubzuki` 를 안내한다.

## 처음 한 번

1. `nubzuki init` 을 실행한다. 대시보드에서 현재 학기(예: `2026F`)와 수강과목을 읽어
   `~/KAIST/2026F/<과목코드>/{files,notices}` 를 만든다. 기본 위치를 바꾸려면 `--root`.
2. 학기가 바뀌면 다시 `nubzuki init`. 기존 폴더는 그대로 두고 새 과목만 추가한다.

## 평소

1. `nubzuki sweep` 으로 지난 실행 이후 바뀐 것만 본다 (게시판 새 글, 과제·퀴즈 표 변경, 새 강의자료, 새 성적).
2. 새 글은 제목만 보고 넘기지 말고 `nubzuki read <board> <bwid> --save` 로 본문을 읽는다.
   여러 개면 `nubzuki read 111 222 333 444` 처럼 이어 붙인다. `--save` 는 과목 폴더 `notices/` 에 남긴다.
3. 새 강의자료는 `nubzuki sweep --download` 로 과목 폴더 `files/` 에 받는다.
   게시글 첨부는 `nubzuki dl <url> --to <과목폴더>/files`.
4. 받은 pdf·pptx는 반드시 `nubzuki text <파일>` 로 텍스트를 뽑아 읽는다. 시험 범위·마감·장소가 첨부에만 있는 경우가 많다.
5. 사용자에게는 마감·시험·장소·변경 사항을 날짜순으로 요약한다. 표를 그대로 붙여넣지 않는다.

## 오류 대응

- `로그인되지 않은 응답` / 세션 만료: 사용자에게 브라우저에서 klms.kaist.ac.kr 에 다시 로그인해 달라고 한다.
  상태 파일은 덮이지 않았으니 로그인 후 그대로 다시 실행하면 된다.
- `세션 잠금`: 세션은 살아 있다. 재로그인시키지 말고 30초쯤 뒤 다시 실행한다.
- 결과가 "0건"인데 이상하다 싶으면 내용보다 세션부터 의심한다. `nubzuki courses` 가 정상인지 확인한다.
- 쿠키를 못 찾으면 `nubzuki login` 으로 MoodleSession 값을 직접 저장하게 안내한다. 쿠키 값을 대화에 출력하지 않는다.

## 참고

- `nubzuki courses` 로 과목 ID와 공지/Q&A/자유게시판 ID를 볼 수 있다.
- `nubzuki sweep --json` 은 기계가 읽기 좋은 결과를 낸다.
- 일부 과목은 공지를 KLMS에 올리지 않고 수업 중 말로 한다. "KLMS에 없다"가 "없다"는 뜻은 아니다.
