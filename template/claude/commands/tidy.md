---
description: 야간 위키 정리 — 새 노트에 머리말 붙이고 색인 갱신
---

볼트를 정리합니다. 오늘은 $ARGUMENTS 입니다.

1. `vault/company/` 와 `vault/lessons/` 에서 YAML 머리말(`---` 블록)이 없는 `.md` 를 찾습니다.
2. 각 파일에 머리말을 붙입니다: `type`(company-context | lesson), `status: current`, `updated: {오늘}`, `tags: []`. **본문은 한 글자도 바꾸지 않습니다.**
3. `vault/company/_index.md` 를 다시 씁니다: 파일별 한 줄(제목 — 첫 문단 요약 20자). 색인 파일만 통째로 새로 씁니다.
4. `vault/journal/` 에 오늘 날짜 파일이 없으면 `# {오늘}` 한 줄로 만듭니다.

출력은 평문 3줄 이내: 머리말 붙인 파일 수, 색인 항목 수, 이상한 점(중복 제목·빈 파일)이 있으면 한 줄. 이상이 없으면 "정리 완료, 특이사항 없음".
