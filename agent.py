from __future__ import annotations

import json
import operator
import re
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Send


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


class RetrievalTask(TypedDict):
    turn_id: str
    tool_name: str
    query: str
    source_file: str


class RetrievalResult(TypedDict):
    turn_id: str
    source: str
    content: str


class QnAState(TypedDict, total=False):
    question: str
    is_enrolled: bool
    student_id: str
    teacher_feedback: str
    turn_id: str
    access_track: Literal["premium", "public"]
    question_history: list[str]
    student_memory: str
    memory_summary: str
    retrieval_tasks: list[RetrievalTask]
    retrieval_task: RetrievalTask
    retrieval_results: Annotated[list[RetrievalResult], operator.add]
    draft_answer: str
    final_answer: str
    status: Literal["approved", "rejected"]


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[^0-9A-Za-z가-힣']+", text.lower()) if len(token) >= 2]


def _search_text_file(source_file: str, query: str, limit: int = 3) -> str:
    path = DATA_DIR / source_file
    text = path.read_text(encoding="utf-8")
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    terms = _tokenize(query)

    ranked: list[tuple[int, int, str]] = []
    for index, block in enumerate(blocks):
        lowered = block.lower()
        score = sum(lowered.count(term) for term in terms)
        ranked.append((score, -index, block))

    ranked.sort(reverse=True)
    selected = [block for score, _, block in ranked[:limit] if score > 0]
    if not selected:
        selected = blocks[:limit]

    snippets = "\n---\n".join(selected)
    return f"[file:{source_file}]\n{snippets}"


@tool
def search_file_corpus(query: str, source_file: str) -> str:
    """Repo-local Markdown corpus에서 질문과 관련 있는 문단을 검색합니다."""
    return _search_text_file(source_file=source_file, query=query)


@tool
def lookup_curriculum_standard(query: str) -> str:
    """수학 교육과정 기준 파일에서 질문과 관련 있는 성취기준을 찾습니다."""
    return _search_text_file(source_file="curriculum_standards.md", query=query, limit=2)


@tool
def load_student_profile(student_id: str) -> str:
    """학생 ID에 해당하는 로컬 학습 프로필을 불러옵니다."""
    profiles_path = DATA_DIR / "student_profiles.json"
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    profile = profiles.get(student_id) or profiles["guest"]
    return json.dumps(profile, ensure_ascii=False)


@tool
def format_solution_steps(question: str, context: str, memory_summary: str) -> str:
    """검색 컨텍스트와 학생 메모리를 바탕으로 답변 초안의 단계 구조를 만듭니다."""
    return (
        f"질문: {question}\n"
        "답변 구조:\n"
        "1. 먼저 질문이 요구하는 개념을 한 문장으로 정리합니다.\n"
        "2. 검색된 근거 자료를 이용해 핵심 정의와 풀이 흐름을 연결합니다.\n"
        "3. 학생 메모리에 맞춰 헷갈리기 쉬운 지점을 짚습니다.\n"
        "4. 마지막에 다음 학습 액션을 제안합니다.\n\n"
        f"학생 메모리:\n{memory_summary}\n\n"
        f"검색 컨텍스트:\n{context}"
    )


def check_auth_node(state: QnAState) -> QnAState:
    history = state.get("question_history", [])
    turn_id = f"turn-{len(history) + 1}"
    access_track = "premium" if state.get("is_enrolled") else "public"
    print(f"[Check Auth] 질문: {state['question']}")
    print(f"-> 수강생 여부: {state.get('is_enrolled', False)}")
    print(f"-> 라우팅 트랙: {access_track}")
    return {
        "turn_id": turn_id,
        "access_track": access_track,
        "question_history": [*history, state["question"]],
    }


def load_memory_node(state: QnAState) -> QnAState:
    student_id = state.get("student_id", "guest")
    profile = load_student_profile.invoke({"student_id": student_id})
    history = state.get("question_history", [])
    previous_questions = history[:-1] if history and history[-1] == state["question"] else history
    memory_summary = (
        f"profile={profile}\n"
        f"previous_questions={previous_questions[-3:] if previous_questions else 'none'}"
    )
    print(f"[Memory] student_id={student_id}")
    print(f"-> 이전 질문 수: {len(previous_questions)}")
    return {"student_memory": profile, "memory_summary": memory_summary}


def route_by_access(state: QnAState) -> Literal["premium_plan_node", "public_plan_node"]:
    if state.get("access_track") == "premium":
        return "premium_plan_node"
    return "public_plan_node"


def premium_plan_node(state: QnAState) -> QnAState:
    question = state["question"]
    turn_id = state["turn_id"]
    tasks: list[RetrievalTask] = [
        {
            "turn_id": turn_id,
            "tool_name": "search_file_corpus",
            "query": question,
            "source_file": "premium_lecture_transcripts.md",
        },
        {
            "turn_id": turn_id,
            "tool_name": "search_file_corpus",
            "query": question,
            "source_file": "premium_textbook_metadata.md",
        },
        {
            "turn_id": turn_id,
            "tool_name": "lookup_curriculum_standard",
            "query": question,
            "source_file": "curriculum_standards.md",
        },
    ]
    print(f"[Plan Retrieval] premium 자료 {len(tasks)}개 병렬 검색 준비")
    return {"retrieval_tasks": tasks}


def public_plan_node(state: QnAState) -> QnAState:
    question = state["question"]
    turn_id = state["turn_id"]
    tasks: list[RetrievalTask] = [
        {
            "turn_id": turn_id,
            "tool_name": "search_file_corpus",
            "query": question,
            "source_file": "public_exam_solutions.md",
        },
        {
            "turn_id": turn_id,
            "tool_name": "search_file_corpus",
            "query": question,
            "source_file": "public_concept_notes.md",
        },
        {
            "turn_id": turn_id,
            "tool_name": "lookup_curriculum_standard",
            "query": question,
            "source_file": "curriculum_standards.md",
        },
    ]
    print(f"[Plan Retrieval] public 자료 {len(tasks)}개 병렬 검색 준비")
    return {"retrieval_tasks": tasks}


def dispatch_retrieval(state: QnAState) -> list[Send]:
    sends = [
        Send(
            "retrieve_context_node",
            {
                "question": state["question"],
                "turn_id": state["turn_id"],
                "retrieval_task": task,
            },
        )
        for task in state["retrieval_tasks"]
    ]
    print(f"[Send API] 병렬 검색 작업 {len(sends)}개 전송")
    return sends


def retrieve_context_node(state: QnAState) -> QnAState:
    task = state["retrieval_task"]
    if task["tool_name"] == "lookup_curriculum_standard":
        content = lookup_curriculum_standard.invoke({"query": task["query"]})
    else:
        content = search_file_corpus.invoke(
            {"query": task["query"], "source_file": task["source_file"]}
        )
    print(f"[Retrieve] {task['source_file']} 검색 완료")
    return {
        "retrieval_results": [
            {
                "turn_id": task["turn_id"],
                "source": task["source_file"],
                "content": content,
            }
        ]
    }


def draft_answer_node(state: QnAState) -> QnAState:
    turn_id = state["turn_id"]
    current_results = [
        result for result in state.get("retrieval_results", []) if result["turn_id"] == turn_id
    ]
    context = "\n\n".join(
        f"### {result['source']}\n{result['content']}" for result in current_results
    )
    structure = format_solution_steps.invoke(
        {
            "question": state["question"],
            "context": context,
            "memory_summary": state.get("memory_summary", ""),
        }
    )
    track_label = "프리미엄 수강생" if state.get("access_track") == "premium" else "공개 질문자"
    draft = (
        f"[{track_label} 답변 초안]\n"
        f"{structure}\n\n"
        "초안 결론: 위 근거를 바탕으로 개념 정의 -> 풀이 흐름 -> 실수 포인트 순서로 설명합니다."
    )
    print(f"[Draft] 검색 결과 {len(current_results)}개로 초안 생성")
    return {"draft_answer": draft}


def teacher_review_node(state: QnAState) -> QnAState:
    print(f"\n[Teacher Review] 현재 초안:\n{state['draft_answer']}")
    if state.get("teacher_feedback"):
        print(f"-> 선생님 피드백: {state['teacher_feedback']}")
        return {"status": "rejected"}
    print("-> 선생님 승인 완료")
    return {"status": "approved", "final_answer": state["draft_answer"]}


def revise_draft_node(state: QnAState) -> QnAState:
    print("[Revise Draft] 피드백을 반영하여 초안 수정 중")
    revised = (
        f"{state['draft_answer']}\n\n"
        f"[Teacher Revision Applied]\n{state.get('teacher_feedback', '')}"
    )
    return {"draft_answer": revised, "teacher_feedback": ""}


def publish_node(state: QnAState) -> QnAState:
    print(f"\n[Publish] 학생에게 최종 답변 전송:\n{state['final_answer']}")
    return state


def route_review(state: QnAState) -> Literal["publish_node", "revise_draft_node"]:
    if state["status"] == "approved":
        return "publish_node"
    return "revise_draft_node"


def build_app():
    workflow = StateGraph(QnAState)

    workflow.add_node("check_auth_node", check_auth_node)
    workflow.add_node("load_memory_node", load_memory_node)
    workflow.add_node("premium_plan_node", premium_plan_node)
    workflow.add_node("public_plan_node", public_plan_node)
    workflow.add_node("retrieve_context_node", retrieve_context_node)
    workflow.add_node("draft_answer_node", draft_answer_node)
    workflow.add_node("teacher_review_node", teacher_review_node)
    workflow.add_node("revise_draft_node", revise_draft_node)
    workflow.add_node("publish_node", publish_node)

    workflow.set_entry_point("check_auth_node")
    workflow.add_edge("check_auth_node", "load_memory_node")
    workflow.add_conditional_edges(
        "load_memory_node",
        route_by_access,
        {
            "premium_plan_node": "premium_plan_node",
            "public_plan_node": "public_plan_node",
        },
    )
    workflow.add_conditional_edges("premium_plan_node", dispatch_retrieval)
    workflow.add_conditional_edges("public_plan_node", dispatch_retrieval)
    workflow.add_edge("retrieve_context_node", "draft_answer_node")
    workflow.add_edge("draft_answer_node", "teacher_review_node")
    workflow.add_conditional_edges(
        "teacher_review_node",
        route_review,
        {
            "publish_node": "publish_node",
            "revise_draft_node": "revise_draft_node",
        },
    )
    workflow.add_edge("revise_draft_node", "teacher_review_node")
    workflow.add_edge("publish_node", END)

    return workflow.compile(checkpointer=MemorySaver())


app = build_app()


def run_demo() -> None:
    enrolled_config = {"configurable": {"thread_id": "student-minji"}}
    public_config = {"configurable": {"thread_id": "guest-public"}}

    print("=== [테스트 1] 수강생 질문: Send API 병렬 Premium RAG ===")
    app.invoke(
        {
            "question": "수2 미분계수 정의 파트에서 f'(a)를 어떻게 이해해야 하나요?",
            "is_enrolled": True,
            "student_id": "student-minji",
            "teacher_feedback": "",
        },
        config=enrolled_config,
    )

    print("\n=== [테스트 2] 비수강생 질문: Public RAG + 교사 피드백 수정 ===")
    app.invoke(
        {
            "question": "2024년 9월 모평 22번 문제 해설 부탁드립니다.",
            "is_enrolled": False,
            "student_id": "guest",
            "teacher_feedback": "학생이 이해하기 쉽게 중간 과정을 좀 더 자세히 써주세요.",
        },
        config=public_config,
    )

    print("\n=== [테스트 3] 같은 수강생의 후속 질문: MemorySaver 메모리 확인 ===")
    app.invoke(
        {
            "question": "방금 말한 평균변화율 극한과 접선 기울기는 어떻게 이어지나요?",
            "is_enrolled": True,
            "student_id": "student-minji",
            "teacher_feedback": "",
        },
        config=enrolled_config,
    )
    memory_state = app.get_state(enrolled_config).values
    print("\n[Memory Check] 누적 질문 기록:")
    for index, question in enumerate(memory_state.get("question_history", []), start=1):
        print(f"{index}. {question}")


if __name__ == "__main__":
    run_demo()
