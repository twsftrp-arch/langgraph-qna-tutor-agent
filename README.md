# Trinity RAG Assistant

Nomad Coders AI Agents SDK & LangGraph 퀴즈 과제 제출용 리포지토리입니다.

## 1. 목적
수학 질문을 받아 학생의 권한(수강생 vs 비수강생)에 따라 Two-track RAG(Premium/Public)를 수행하고, 선생님(Human-in-the-loop)의 검토와 피드백을 거쳐 최종 답변을 생성하는 에이전트입니다.

## 2. 그래프 구조
- **Check Auth Node**: 질문자의 수강 여부를 확인합니다.
- **Premium RAG Node**: 강의 타임스탬프 및 교재(LaTeX) 기반 프리미엄 해설 초안 생성
- **Public RAG Node**: 기출 해설 기반 일반 해설 초안 생성
- **Teacher Review Node**: 선생님의 승인 또는 피드백 대기
- **Revise Draft Node**: 선생님의 피드백을 반영하여 초안 수정
- **Publish Node**: 최종 승인된 답변 발행

## 3. 실행 방법
```bash
pip install -r requirements.txt
jupyter notebook qna_tutor_agent.ipynb
```
노트북 셀을 순서대로 실행하여 테스트 코드가 작동하는 것을 확인할 수 있습니다.
