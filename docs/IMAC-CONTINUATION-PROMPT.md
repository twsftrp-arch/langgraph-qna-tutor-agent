# iMac Continuation Prompt — LangGraph QnA Tutor Agent

Use this prompt in a fresh agent session on the iMac.

````text
성민님 LangGraph Education Agent 작업을 iMac에서 이어간다.

먼저 이 repo를 준비한다.

1. repo가 있으면:
   cd "/Users/sungmint/Desktop/langgraph-qna-tutor-agent"  # iMac 사용자명이 다르면 실제 Desktop 경로로 조정
   git pull origin main

2. repo가 없으면:
   cd "/Users/sungmint/Desktop"  # iMac 사용자명이 다르면 실제 Desktop 경로로 조정
   git clone https://github.com/twsftrp-arch/langgraph-qna-tutor-agent.git
   cd langgraph-qna-tutor-agent

그 다음 반드시 intake를 한다:
- repo root, current branch, `git status -sb`
- `docs/SESSION-HANDOFF.md`
- `README.md`
- `agent.py`
- `qna_tutor_agent.ipynb`
- `data/` 파일 목록

현재 기준:
- 전용 제출 repo: `https://github.com/twsftrp-arch/langgraph-qna-tutor-agent`
- 기능/검증이 완료된 기준 HEAD: `ef432e7 docs: record education agent push`
- 이 iMac handoff 문서가 추가로 push되어 있으면 `git pull origin main` 후 HEAD는 더 최신 docs 커밋일 수 있다.
- 실제 기능 구현 커밋: `5541b7927acc6ce82a75d334d065ce04dd81f560`
- 기능 구현 커밋 링크: `https://github.com/twsftrp-arch/langgraph-qna-tutor-agent/commit/5541b7927acc6ce82a75d334d065ce04dd81f560`
- 기존 `life-coach-agent` / `nomad quiz` repo는 이 LangGraph 과제의 백업/기록용이다. 새 과제는 이 전용 repo 기준으로 이어간다.

현재 구현 상태:
- 필수 요구사항 완료:
  - 3개 이상 LangGraph node
  - conditional edge
  - Tool 연동
- 선택사항 완료:
  - Send API 병렬 fan-out
  - MemorySaver 메모리
  - 여러 Tool 연동
- RAG는 고정 문자열 mock이 아니라 repo-local `data/` Markdown/JSON 파일을 Tool로 검색하는 file-RAG다.
- 주요 파일:
  - `agent.py`: 실제 LangGraph 구현 본체
  - `qna_tutor_agent.ipynb`: 제출용 notebook entrypoint
  - `README.md`: 미션 요구사항 매핑
  - `data/*.md`, `data/student_profiles.json`: RAG source
  - `docs/SESSION-HANDOFF.md`: MacBook 작업/검증/push 기록

검증 명령:
```bash
uv run --with-requirements requirements.txt python agent.py
python3 -m py_compile agent.py
jq empty qna_tutor_agent.ipynb
bash -n init_and_push.sh
git diff --check
```

권한/게이트:
- commit/push/deploy/public action은 성민님 명시 GO 전 금지.
- push가 필요하면 `gh auth switch -u twsftrp-arch` 후 push하고, 끝나면 반드시 `gh auth switch -u trinity-mathslab`로 복구한다.
- secret/token/API key 값은 절대 출력/기록하지 않는다.

새 과제를 이어받으면, 먼저 과제 요구사항을 현재 `agent.py` 구조와 비교해서 부족한 점을 판단하고, 구현/검증 후 `docs/SESSION-HANDOFF.md`를 갱신해라.

STATUS: working — iMac에서 LangGraph 전용 repo를 pull/clone한 뒤 새 과제 요구사항 기준으로 이어갈 준비.
````
