# Trinity RAG Assistant

Nomad Coders Education Agent / LangGraph 미션 제출용 리포지토리입니다.

## 1. 목적
수학 질문을 받아 학생의 권한(수강생 vs 비수강생)에 따라 Two-track RAG(Premium/Public)를 수행하고, 선생님(Human-in-the-loop)의 검토와 피드백을 거쳐 최종 답변을 생성하는 Education Agent입니다.

RAG는 고정 문자열 mock이 아니라 repo-local `data/` 폴더의 Markdown/JSON 자료를 Tool로 읽고 검색하는 file-RAG 방식입니다.

## 2. 그래프 구조
- **Check Auth Node**: 질문자의 수강 여부를 확인합니다.
- **Load Memory Node**: `MemorySaver`와 학생 프로필 Tool을 이용해 이전 질문/학생 정보를 불러옵니다.
- **Premium Plan Node**: 강의 타임스탬프, 교재 메타데이터, 교육과정 자료 검색 작업을 계획합니다.
- **Public Plan Node**: 공개 기출 해설, 공개 개념 노트, 교육과정 자료 검색 작업을 계획합니다.
- **Retrieve Context Node**: `Send` API로 전달된 검색 작업을 병렬로 실행합니다.
- **Draft Answer Node**: 검색 결과와 메모리를 이용해 답변 초안을 작성합니다.
- **Teacher Review Node**: 선생님의 승인 또는 피드백 대기
- **Revise Draft Node**: 선생님의 피드백을 반영하여 초안 수정
- **Publish Node**: 최종 승인된 답변 발행

## 3. 미션 요구사항 매핑
- **3개 이상 노드**: `check_auth_node`, `load_memory_node`, `premium_plan_node`, `public_plan_node`, `retrieve_context_node`, `draft_answer_node`, `teacher_review_node`, `revise_draft_node`, `publish_node`
- **Conditional Edge**:
  - `load_memory_node` 이후 `is_enrolled` 값에 따라 `premium_plan_node` 또는 `public_plan_node`로 분기
  - `teacher_review_node` 이후 승인 여부에 따라 `publish_node` 또는 `revise_draft_node`로 분기
- **Tool 연동**:
  - `search_file_corpus`: `data/*.md`에서 질문 관련 문단 검색
  - `lookup_curriculum_standard`: 교육과정 성취기준 검색
  - `load_student_profile`: `data/student_profiles.json`에서 학생 프로필 로드
  - `format_solution_steps`: 검색 컨텍스트와 메모리를 답변 구조로 정리
- **Human-in-the-loop 흐름**: 선생님 피드백이 있으면 답변을 수정한 뒤 다시 리뷰 노드로 돌아갑니다.

## 4. 선택사항 구현
- **병렬 실행 (Send API)**: Premium/Public plan node가 검색 작업 3개를 만들고 `Send("retrieve_context_node", ...)`로 병렬 fan-out합니다.
- **메모리 기능**: `MemorySaver` 체크포인터를 사용합니다. 같은 `thread_id`로 후속 질문을 보내면 `question_history`가 누적됩니다.
- **여러 개 Tool 연동**: 파일 검색, 교육과정 검색, 학생 프로필 로딩, 답변 구조화 Tool을 함께 사용합니다.

## 5. 실행 방법
```bash
pip install -r requirements.txt
jupyter notebook qna_tutor_agent.ipynb
```
노트북 셀을 순서대로 실행하여 테스트 코드가 작동하는 것을 확인할 수 있습니다.

터미널에서 빠르게 검증하려면:
```bash
python agent.py
```

## 6. 포함된 RAG 자료
- `data/premium_lecture_transcripts.md`
- `data/premium_textbook_metadata.md`
- `data/public_exam_solutions.md`
- `data/public_concept_notes.md`
- `data/curriculum_standards.md`
- `data/student_profiles.json`
