# Session Handoff — LangGraph QnA Tutor Agent

## 2026-07-09 Mission Core Feature Follow-up

- Repo: `/Users/sungminkim/Desktop/langgraph-qna-tutor-agent`
- Remote: `https://github.com/twsftrp-arch/langgraph-qna-tutor-agent.git`
- Branch: `main`
- Base commit: `512a2ea init: Add LangGraph QnA Tutor Agent for demo day`
- Dirty status after work:
  - `README.md`
  - `qna_tutor_agent.ipynb`
  - `docs/SESSION-HANDOFF.md`

### What changed

- Added a real custom Tool integration to `qna_tutor_agent.ipynb`:
  - `search_math_resources` uses `@tool` from `langchain_core.tools`.
  - `premium_rag_node` calls the tool with `source_type="premium"`.
  - `public_rag_node` calls the tool with `source_type="public"`.
  - Tool results are printed and stored as `retrieved_context`.
- Updated `README.md` with mission requirement mapping:
  - 3+ nodes
  - conditional edges
  - custom tool integration
  - human-in-the-loop review/revise flow

### Verification

- `jq empty qna_tutor_agent.ipynb` passed.
- `bash -n init_and_push.sh` passed.
- `git diff --check` passed.
- `uv run --with-requirements requirements.txt python - ...` executed all notebook code successfully.
- Runtime evidence:
  - enrolled student path used `premium_rag_node` and printed `Tool 검색 결과`.
  - non-enrolled path used `public_rag_node`, teacher feedback, `revise_draft_node`, then `publish_node`.

### Gated actions not performed

- No commit.
- No push.
- No deployment.
- No GitHub account switch.
- No secret inspection.

### Next safe step

- Review the diff.
- If 성민님 gives explicit GO, commit and push these local changes to `twsftrp-arch/langgraph-qna-tutor-agent`.

---

## 2026-07-09 Optional Features + File RAG Upgrade

- Branch: `main`
- Base commit remains: `512a2ea init: Add LangGraph QnA Tutor Agent for demo day`
- Dirty status after work:
  - `.gitignore`
  - `README.md`
  - `agent.py`
  - `qna_tutor_agent.ipynb`
  - `data/*.md`
  - `data/student_profiles.json`
  - `docs/SESSION-HANDOFF.md`

### What changed

- Moved the main implementation into `agent.py`.
- Reworked `qna_tutor_agent.ipynb` into a thin notebook entrypoint that imports `app` and `run_demo` from `agent.py`.
- Replaced fixed-string mock RAG with repo-local file RAG:
  - `data/premium_lecture_transcripts.md`
  - `data/premium_textbook_metadata.md`
  - `data/public_exam_solutions.md`
  - `data/public_concept_notes.md`
  - `data/curriculum_standards.md`
  - `data/student_profiles.json`
- Implemented all optional features:
  - Send API parallel fan-out from Premium/Public plan nodes to `retrieve_context_node`.
  - `MemorySaver` checkpoint memory with same-thread question history.
  - Multiple tools: file corpus search, curriculum lookup, student profile loading, answer structure formatting.
- Updated `README.md` with required and optional mission mapping.
- Added `.gitignore` to keep Python cache, notebook checkpoints, virtualenvs, and local env files out of commits.

### Verification

- `uv run --with-requirements requirements.txt python agent.py` passed.
- `python3 -m py_compile agent.py` passed.
- `jq empty qna_tutor_agent.ipynb` passed.
- `bash -n init_and_push.sh` passed.
- `git diff --check` passed.
- Runtime evidence:
  - Premium path sent 3 retrieval tasks via Send API.
  - Public path sent 3 retrieval tasks via Send API.
  - File RAG read Markdown corpus snippets from `data/`.
  - Teacher feedback path revised and then published.
  - Same `student-minji` thread retained exactly 2 questions after the follow-up memory test.

### Gated actions not performed

- No commit.
- No push.
- No deployment.
- No GitHub account switch.
- No secret inspection.

### Next safe step

- Review the diff.
- If 성민님 gives explicit GO, commit and push to the existing submission repo and report the commit link.
