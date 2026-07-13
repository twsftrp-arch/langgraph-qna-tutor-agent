from __future__ import annotations

import json
import operator
import os
import re
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, Send, interrupt
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

AgentName = Literal["tutor", "quiz", "researcher"]
RequestedMode = Literal["auto", "tutor", "quiz", "researcher"]
JudgeMode = Literal["local", "ai", "local-fallback"]


class RetrievalTask(TypedDict):
    turn_id: str
    tool_name: str
    query: str
    source_file: str


class RetrievalResult(TypedDict):
    turn_id: str
    source: str
    content: str


class JudgeEvaluation(TypedDict):
    score: int
    passed: bool
    feedback: str
    strengths: list[str]
    mode: JudgeMode


class JudgeResponse(BaseModel):
    score: int = Field(ge=0, le=10)
    passed: bool
    feedback: str
    strengths: list[str] = Field(default_factory=list)


class QnAState(TypedDict, total=False):
    question: str
    requested_mode: RequestedMode
    selected_agent: AgentName
    is_enrolled: bool
    student_id: str
    require_teacher_review: bool
    use_ai_judge: bool
    teacher_feedback: str
    turn_id: str
    access_track: Literal["premium", "public"]
    question_history: list[str]
    student_memory: str
    memory_summary: str
    retrieval_tasks: list[RetrievalTask]
    retrieval_task: RetrievalTask
    retrieval_results: Annotated[list[RetrievalResult], operator.add]
    research_context: str
    selected_sources: list[str]
    draft_answer: str
    final_answer: str
    judge_evaluation: JudgeEvaluation
    status: Literal["pending", "approved", "rejected"]
    active_quiz_question: str
    active_quiz_answer: str
    active_quiz_explanation: str


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[^0-9A-Za-z가-힣']+", text.lower()) if len(token) >= 2]


def _search_text_file(source_file: str, query: str, limit: int = 3) -> str:
    allowed_files = {
        "curriculum_standards.md",
        "premium_lecture_transcripts.md",
        "premium_textbook_metadata.md",
        "public_concept_notes.md",
        "public_exam_solutions.md",
    }
    if source_file not in allowed_files:
        raise ValueError(f"허용되지 않은 RAG source_file입니다: {source_file}")

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
    """검색 컨텍스트와 학생 메모리를 바탕으로 Feynman식 설명 구조를 만듭니다."""
    return (
        f"질문: {question}\n"
        "1. 쉬운 말로 핵심 개념을 먼저 설명합니다.\n"
        "2. 그래프나 일상적인 비유와 연결합니다.\n"
        "3. 검색 근거를 이용해 식과 풀이 흐름을 정리합니다.\n"
        "4. 마지막에 학생이 스스로 확인할 질문을 제시합니다.\n\n"
        f"학생 메모리:\n{memory_summary}\n\n"
        f"검색 컨텍스트:\n{context}"
    )


def external_judge_configured() -> bool:
    """외부 AI judge 설정 여부만 반환하며 값은 노출하지 않습니다."""
    return bool(os.environ.get("OPENAI_API_KEY") and os.environ.get("EDUCATION_AGENT_JUDGE_MODEL"))


def check_auth_node(state: QnAState) -> QnAState:
    history = state.get("question_history", [])
    turn_id = f"turn-{len(history) + 1}"
    access_track = "premium" if state.get("is_enrolled") else "public"
    print(f"[Check Auth] 질문: {state['question']}")
    print(f"-> 라우팅 트랙: {access_track}")
    return {
        "turn_id": turn_id,
        "access_track": access_track,
        "question_history": [*history, state["question"]],
        "teacher_feedback": "",
        "final_answer": "",
        "draft_answer": "",
        "research_context": "",
        "selected_sources": [],
        "judge_evaluation": {
            "score": 0,
            "passed": False,
            "feedback": "평가 전",
            "strengths": [],
            "mode": "local",
        },
        "status": "pending",
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
    print(f"[Memory] student_id={student_id}, 이전 질문 수={len(previous_questions)}")
    return {"student_memory": profile, "memory_summary": memory_summary}


def _normalize_quiz_answer(text: str) -> str | None:
    normalized = text.strip().replace("번", "")
    mapping = {"①": "1", "②": "2", "③": "3", "④": "4"}
    normalized = mapping.get(normalized, normalized)
    return normalized if normalized in {"1", "2", "3", "4"} else None


def _resolve_agent(state: QnAState) -> AgentName:
    requested_mode = state.get("requested_mode", "auto")
    if requested_mode != "auto":
        return requested_mode

    question = state["question"].lower()
    if _normalize_quiz_answer(question) and state.get("active_quiz_answer"):
        return "quiz"
    if any(keyword in question for keyword in ("퀴즈", "문제 내", "테스트", "확인 문제")):
        return "quiz"
    if any(keyword in question for keyword in ("자료", "근거", "출처", "찾아", "검색")):
        return "researcher"
    return "tutor"


def _plan_source_files(state: QnAState, selected_agent: AgentName) -> list[str]:
    question = state["question"].lower()
    access_track = state["access_track"]
    is_quiz_answer = bool(_normalize_quiz_answer(question) and state.get("active_quiz_answer"))

    if access_track == "premium":
        primary = "premium_lecture_transcripts.md"
        secondary = "premium_textbook_metadata.md"
    else:
        primary = "public_concept_notes.md"
        secondary = "public_exam_solutions.md"

    selected = ["curriculum_standards.md"]
    if is_quiz_answer:
        return selected

    if selected_agent == "researcher":
        selected.extend([primary, secondary])
    elif selected_agent == "quiz":
        selected.extend([primary, secondary])
    else:
        selected.append(primary)
        if any(keyword in question for keyword in ("교재", "공식", "기출", "모평", "수능", "문제")):
            selected.append(secondary)

    return list(dict.fromkeys(selected))


def supervisor_agent_node(state: QnAState) -> QnAState:
    selected_agent = _resolve_agent(state)
    source_files = _plan_source_files(state, selected_agent)
    tasks: list[RetrievalTask] = []
    for source_file in source_files:
        tasks.append(
            {
                "turn_id": state["turn_id"],
                "tool_name": (
                    "lookup_curriculum_standard"
                    if source_file == "curriculum_standards.md"
                    else "search_file_corpus"
                ),
                "query": state["question"],
                "source_file": source_file,
            }
        )

    print(
        f"[Supervisor] selected_agent={selected_agent}, "
        f"workers={len(tasks)}, access={state['access_track']}"
    )
    return {"selected_agent": selected_agent, "retrieval_tasks": tasks}


def dispatch_research_workers(state: QnAState) -> list[Send]:
    sends = [
        Send(
            "research_worker_node",
            {
                "question": state["question"],
                "turn_id": state["turn_id"],
                "retrieval_task": task,
            },
        )
        for task in state["retrieval_tasks"]
    ]
    print(f"[Orchestrator-Workers] 동적 검색 worker {len(sends)}개 전송")
    return sends


def research_worker_node(state: QnAState) -> QnAState:
    task = state["retrieval_task"]
    if task["tool_name"] == "lookup_curriculum_standard":
        content = lookup_curriculum_standard.invoke({"query": task["query"]})
    else:
        content = search_file_corpus.invoke(
            {"query": task["query"], "source_file": task["source_file"]}
        )
    print(f"[Research Worker] {task['source_file']} 검색 완료")
    return {
        "retrieval_results": [
            {
                "turn_id": task["turn_id"],
                "source": task["source_file"],
                "content": content,
            }
        ]
    }


def research_synthesis_node(state: QnAState) -> QnAState:
    current_results = [
        result
        for result in state.get("retrieval_results", [])
        if result["turn_id"] == state["turn_id"]
    ]
    context = "\n\n".join(
        f"### {result['source']}\n{result['content']}" for result in current_results
    )
    sources = [result["source"] for result in current_results]
    print(f"[Research Synthesis] 검색 결과 {len(current_results)}개 병합")
    return {"research_context": context, "selected_sources": sources}


def route_to_specialist(
    state: QnAState,
) -> Literal["tutor_agent_node", "quiz_agent_node", "researcher_agent_node"]:
    return {
        "tutor": "tutor_agent_node",
        "quiz": "quiz_agent_node",
        "researcher": "researcher_agent_node",
    }[state["selected_agent"]]


def _profile_from_state(state: QnAState) -> dict[str, Any]:
    try:
        return json.loads(state.get("student_memory", "{}"))
    except json.JSONDecodeError:
        return {}


def _result_excerpts(state: QnAState, max_chars: int = 360) -> list[tuple[str, str]]:
    excerpts: list[tuple[str, str]] = []
    for result in state.get("retrieval_results", []):
        if result["turn_id"] != state["turn_id"]:
            continue
        text = re.sub(r"\[file:[^\]]+\]\n?", "", result["content"])
        text = re.sub(r"\n---\n", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        excerpts.append((result["source"], text[:max_chars]))
    return excerpts


def tutor_agent_node(state: QnAState) -> QnAState:
    profile = _profile_from_state(state)
    excerpts = _result_excerpts(state, max_chars=260)
    evidence = "\n".join(f"- {source}: {excerpt}" for source, excerpt in excerpts)
    preferred_style = profile.get("preferred_style", "개념을 먼저 설명한 뒤 식으로 정리")
    weak_points = ", ".join(profile.get("weak_points", [])) or "아직 기록 없음"

    if "미분계수" in state["question"] or "평균변화율" in state["question"]:
        easy_explanation = (
            "평균변화율은 서로 떨어진 두 점을 잇는 선의 기울기이고, "
            "미분계수는 두 점의 간격을 0에 가깝게 줄였을 때 얻는 한 점에서의 기울기입니다."
        )
        check_question = "두 점 사이의 간격을 줄일수록 할선의 기울기는 무엇에 가까워질까요?"
    else:
        easy_explanation = (
            "질문 속 핵심 조건을 먼저 한 문장으로 바꾼 뒤, 검색 근거와 연결해 단계별로 이해하면 됩니다."
        )
        check_question = "지금 설명에서 가장 중요한 조건을 한 문장으로 다시 말해 볼 수 있나요?"

    draft = (
        "[Tutor Agent - Feynman 설명]\n\n"
        f"질문: {state['question']}\n\n"
        f"쉽게 말하면\n{easy_explanation}\n\n"
        "단계별로 보면\n"
        "1. 문제에서 무엇이 변하는지 찾습니다.\n"
        "2. 두 값의 관계를 그래프나 식으로 표현합니다.\n"
        "3. 검색된 근거와 연결해 계산 또는 설명을 완성합니다.\n\n"
        f"학생 맞춤 포인트\n- 선호 방식: {preferred_style}\n- 주의할 부분: {weak_points}\n\n"
        f"근거 요약\n{evidence}\n\n"
        f"확인 질문\n{check_question}\n\n"
        f"출처: {', '.join(state.get('selected_sources', []))}"
    )
    print("[Tutor Agent] Feynman식 설명 초안 생성")
    return {"draft_answer": draft}


def _quiz_template(question: str) -> tuple[str, list[str], str, str]:
    if "도함수" in question:
        return (
            "도함수의 활용으로 가장 적절한 것은 무엇인가요?",
            [
                "함수의 정의역만 확인한다.",
                "함수의 증가·감소와 극값을 판단한다.",
                "두 점 사이의 거리만 계산한다.",
                "확률의 합을 계산한다.",
            ],
            "2",
            "도함수의 부호를 이용하면 함수의 증가·감소와 극값을 판단할 수 있습니다.",
        )
    if "평균변화율" in question:
        return (
            "평균변화율의 그래프 의미는 무엇인가요?",
            [
                "한 점에서의 접선 기울기",
                "두 점을 잇는 직선의 기울기",
                "함수값의 최댓값",
                "x절편의 개수",
            ],
            "2",
            "평균변화율은 두 점을 잇는 할선의 기울기입니다.",
        )
    return (
        "미분계수에 대한 설명으로 가장 적절한 것은 무엇인가요?",
        [
            "항상 함수의 최댓값을 뜻한다.",
            "두 점 사이의 평균변화율 그 자체다.",
            "두 점이 한 점으로 가까워질 때 평균변화율의 극한이다.",
            "함수의 정의역 길이를 뜻한다.",
        ],
        "3",
        "미분계수는 평균변화율에서 두 점의 간격을 0에 가깝게 줄였을 때의 극한입니다.",
    )


def quiz_agent_node(state: QnAState) -> QnAState:
    submitted_answer = _normalize_quiz_answer(state["question"])
    expected_answer = state.get("active_quiz_answer", "")
    if submitted_answer and expected_answer:
        is_correct = submitted_answer == expected_answer
        result_label = "정답입니다." if is_correct else f"아쉽지만 정답은 {expected_answer}번입니다."
        draft = (
            "[Quiz Agent - 채점 결과]\n\n"
            f"{result_label}\n\n"
            f"해설: {state.get('active_quiz_explanation', '')}\n\n"
            "다음에는 정답만 외우기보다 각 선택지가 왜 맞거나 틀린지도 설명해 보세요."
        )
        print(f"[Quiz Agent] 제출 답안 {submitted_answer}번 채점")
        return {
            "draft_answer": draft,
            "active_quiz_question": "",
            "active_quiz_answer": "",
            "active_quiz_explanation": "",
        }

    quiz_question, options, answer, explanation = _quiz_template(state["question"])
    options_text = "\n".join(f"{index}. {option}" for index, option in enumerate(options, start=1))
    draft = (
        "[Quiz Agent - 개념 확인]\n\n"
        f"{quiz_question}\n\n"
        f"{options_text}\n\n"
        "답은 1~4 중 하나로 보내주세요. 다음 메시지에서 바로 채점해 드립니다.\n\n"
        f"참고한 자료: {', '.join(state.get('selected_sources', []))}"
    )
    print("[Quiz Agent] 새 객관식 퀴즈 생성")
    return {
        "draft_answer": draft,
        "active_quiz_question": quiz_question,
        "active_quiz_answer": answer,
        "active_quiz_explanation": explanation,
    }


def researcher_agent_node(state: QnAState) -> QnAState:
    excerpts = _result_excerpts(state, max_chars=520)
    findings = "\n\n".join(
        f"{index}. {source}\n{excerpt}" for index, (source, excerpt) in enumerate(excerpts, start=1)
    )
    track_label = "수강생 자료" if state["access_track"] == "premium" else "공개 자료"
    draft = (
        "[Researcher Agent - 자료 조사]\n\n"
        f"질문: {state['question']}\n"
        f"검색 범위: {track_label}\n\n"
        f"찾은 내용\n{findings}\n\n"
        "정리: 여러 자료에서 공통으로 강조하는 정의와 풀이 조건을 먼저 확인한 뒤 답변에 사용하면 됩니다."
    )
    print("[Researcher Agent] 검색 근거 정리")
    return {"draft_answer": draft}


def _local_judge(state: QnAState, mode: JudgeMode = "local") -> JudgeEvaluation:
    answer = state.get("draft_answer", "")
    score = 0
    strengths: list[str] = []

    if len(answer) >= 180 or "채점 결과" in answer:
        score += 2
        strengths.append("충분한 설명 길이")
    if state.get("selected_sources"):
        score += 2
        strengths.append("검색 근거 포함")
    if any(marker in answer for marker in ("단계", "1.", "쉽게 말하면", "찾은 내용")):
        score += 2
        strengths.append("구조화된 설명")
    if state.get("selected_agent") == "quiz" or "확인 질문" in answer:
        score += 2
        strengths.append("학습 확인 활동")
    access_safe = not (state.get("access_track") == "public" and "premium_" in answer)
    if not access_safe:
        feedback = "공개 답변에 Premium source가 포함되어 접근 경계를 확인해야 합니다."
    else:
        score += 2
        strengths.append("접근 범위 준수")
        feedback = "핵심 구조와 근거가 포함되었습니다. 실제 사용자 피드백으로 표현을 더 다듬어 보세요."

    score = min(score, 10)
    return {
        "score": score,
        "passed": score >= 7 and access_safe,
        "feedback": feedback,
        "strengths": strengths,
        "mode": mode,
    }


def _ai_judge(state: QnAState) -> JudgeEvaluation | None:
    if not external_judge_configured():
        return None

    try:
        from langchain_openai import ChatOpenAI

        model_name = os.environ["EDUCATION_AGENT_JUDGE_MODEL"]
        model = ChatOpenAI(model=model_name, temperature=0).with_structured_output(JudgeResponse)
        response = model.invoke(
            [
                SystemMessage(
                    content=(
                        "수학 Education Agent의 답변을 0~10점으로 평가하세요. "
                        "정확성, 질문 관련성, 학습자 적합성, 근거 사용, 접근 범위 준수를 평가하고 "
                        "7점 이상이면 passed=true로 반환하세요."
                    )
                ),
                HumanMessage(
                    content=(
                        f"질문: {state['question']}\n"
                        f"접근 트랙: {state['access_track']}\n"
                        f"선택된 에이전트: {state['selected_agent']}\n"
                        f"답변:\n{state['draft_answer']}"
                    )
                ),
            ]
        )
        return {
            "score": response.score,
            "passed": response.passed,
            "feedback": response.feedback,
            "strengths": response.strengths,
            "mode": "ai",
        }
    except Exception as exc:
        print(f"[Judge Agent] 외부 AI judge 실패({type(exc).__name__}), local rubric으로 전환")
        return None


def judge_agent_node(state: QnAState) -> QnAState:
    evaluation: JudgeEvaluation
    if state.get("use_ai_judge"):
        evaluation = _ai_judge(state) or _local_judge(state, mode="local-fallback")
    else:
        evaluation = _local_judge(state)
    print(
        f"[Judge Agent] mode={evaluation['mode']}, "
        f"score={evaluation['score']}, passed={evaluation['passed']}"
    )
    return {"judge_evaluation": evaluation}


def route_after_judge(state: QnAState) -> Literal["teacher_review_node", "auto_publish_node"]:
    if state.get("require_teacher_review", False):
        return "teacher_review_node"
    return "auto_publish_node"


def auto_publish_node(state: QnAState) -> QnAState:
    print("[Auto Publish] 교사 검토 비활성 모드로 답변 완료")
    return {
        "status": "approved",
        "teacher_feedback": "",
        "final_answer": state["draft_answer"],
    }


def teacher_review_node(state: QnAState) -> QnAState:
    print(f"\n[Teacher Review] 현재 초안:\n{state['draft_answer']}")
    review = interrupt(
        {
            "type": "teacher_review",
            "question": state["question"],
            "draft_answer": state["draft_answer"],
            "judge_evaluation": state.get("judge_evaluation", {}),
            "instruction": (
                "승인하려면 approved=true, 수정하려면 approved=false와 feedback을 전달하세요."
            ),
        }
    )

    if not isinstance(review, dict) or not isinstance(review.get("approved"), bool):
        raise ValueError("교사 검토 응답에는 boolean approved 값이 필요합니다.")

    approved = review["approved"]
    feedback = str(review.get("feedback", "")).strip()
    if approved:
        print("-> 선생님 승인 완료")
        return {
            "status": "approved",
            "teacher_feedback": "",
            "final_answer": state["draft_answer"],
        }
    if not feedback:
        raise ValueError("수정 요청에는 비어 있지 않은 feedback이 필요합니다.")

    print(f"-> 선생님 피드백: {feedback}")
    return {"status": "rejected", "teacher_feedback": feedback}


def revise_draft_node(state: QnAState) -> QnAState:
    print("[Revise Draft] 교사 피드백 반영")
    revised = (
        f"{state['draft_answer']}\n\n"
        "[교사 피드백 반영]\n"
        f"{state.get('teacher_feedback', '')}"
    )
    return {"draft_answer": revised, "teacher_feedback": ""}


def publish_node(state: QnAState) -> QnAState:
    print(f"\n[Publish] 최종 답변:\n{state['final_answer']}")
    return state


def route_review(state: QnAState) -> Literal["publish_node", "revise_draft_node"]:
    if state["status"] == "approved":
        return "publish_node"
    return "revise_draft_node"


def build_app():
    workflow = StateGraph(QnAState)

    workflow.add_node("check_auth_node", check_auth_node)
    workflow.add_node("load_memory_node", load_memory_node)
    workflow.add_node("supervisor_agent_node", supervisor_agent_node)
    workflow.add_node("research_worker_node", research_worker_node)
    workflow.add_node("research_synthesis_node", research_synthesis_node)
    workflow.add_node("tutor_agent_node", tutor_agent_node)
    workflow.add_node("quiz_agent_node", quiz_agent_node)
    workflow.add_node("researcher_agent_node", researcher_agent_node)
    workflow.add_node("judge_agent_node", judge_agent_node)
    workflow.add_node("auto_publish_node", auto_publish_node)
    workflow.add_node("teacher_review_node", teacher_review_node)
    workflow.add_node("revise_draft_node", revise_draft_node)
    workflow.add_node("publish_node", publish_node)

    workflow.set_entry_point("check_auth_node")
    workflow.add_edge("check_auth_node", "load_memory_node")
    workflow.add_edge("load_memory_node", "supervisor_agent_node")
    workflow.add_conditional_edges("supervisor_agent_node", dispatch_research_workers)
    workflow.add_edge("research_worker_node", "research_synthesis_node")
    workflow.add_conditional_edges(
        "research_synthesis_node",
        route_to_specialist,
        {
            "tutor_agent_node": "tutor_agent_node",
            "quiz_agent_node": "quiz_agent_node",
            "researcher_agent_node": "researcher_agent_node",
        },
    )
    workflow.add_edge("tutor_agent_node", "judge_agent_node")
    workflow.add_edge("quiz_agent_node", "judge_agent_node")
    workflow.add_edge("researcher_agent_node", "judge_agent_node")
    workflow.add_conditional_edges(
        "judge_agent_node",
        route_after_judge,
        {
            "teacher_review_node": "teacher_review_node",
            "auto_publish_node": "auto_publish_node",
        },
    )
    workflow.add_edge("auto_publish_node", "publish_node")
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


def _run_with_teacher_reviews(
    inputs: QnAState,
    config: dict[str, Any],
    reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = app.invoke(inputs, config=config)
    for review_index, review in enumerate(reviews, start=1):
        pending_interrupts = result.get("__interrupt__", ())
        if len(pending_interrupts) != 1:
            raise RuntimeError(
                f"교사 검토 {review_index} 전에 interrupt 1개가 필요하지만 "
                f"{len(pending_interrupts)}개를 받았습니다."
            )
        result = app.invoke(Command(resume=review), config=config)

    if result.get("__interrupt__"):
        raise RuntimeError("처리되지 않은 교사 검토 interrupt가 남아 있습니다.")
    return result


def run_demo() -> None:
    tutor_config = {"configurable": {"thread_id": "demo-tutor"}}
    quiz_config = {"configurable": {"thread_id": "demo-quiz"}}
    research_config = {"configurable": {"thread_id": "demo-research"}}

    print("=== [데모 1] Supervisor -> Research Workers -> Tutor -> Judge ===")
    tutor_result = app.invoke(
        {
            "question": "미분계수와 평균변화율을 쉽게 설명해 주세요.",
            "requested_mode": "tutor",
            "is_enrolled": True,
            "student_id": "student-minji",
            "require_teacher_review": False,
            "use_ai_judge": False,
        },
        config=tutor_config,
    )
    print(tutor_result["final_answer"])

    print("\n=== [데모 2] Quiz Agent 생성 및 같은 thread 채점 ===")
    quiz_result = app.invoke(
        {
            "question": "미분계수 퀴즈를 내 주세요.",
            "requested_mode": "quiz",
            "is_enrolled": False,
            "student_id": "guest",
            "require_teacher_review": False,
            "use_ai_judge": False,
        },
        config=quiz_config,
    )
    print(quiz_result["final_answer"])
    graded_result = app.invoke(
        {
            "question": "3",
            "requested_mode": "quiz",
            "is_enrolled": False,
            "student_id": "guest",
            "require_teacher_review": False,
            "use_ai_judge": False,
        },
        config=quiz_config,
    )
    print(graded_result["final_answer"])

    print("\n=== [데모 3] Researcher + 실제 교사 HITL ===")
    research_result = _run_with_teacher_reviews(
        {
            "question": "미분계수 관련 학습자료와 근거를 찾아 주세요.",
            "requested_mode": "researcher",
            "is_enrolled": True,
            "student_id": "student-minji",
            "require_teacher_review": True,
            "use_ai_judge": False,
        },
        research_config,
        [{"approved": True, "feedback": ""}],
    )
    print(research_result["final_answer"])


if __name__ == "__main__":
    run_demo()
