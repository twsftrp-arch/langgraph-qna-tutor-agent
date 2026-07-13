from __future__ import annotations

from uuid import uuid4

import pytest
from langgraph.types import Command

from agent import (
    _local_judge,
    build_app,
    judge_agent_node,
    supervisor_agent_node,
)


@pytest.mark.parametrize(
    ("question", "requested_mode", "expected_agent"),
    [
        ("미분계수를 쉽게 설명해 주세요.", "auto", "tutor"),
        ("미분계수 퀴즈를 내 주세요.", "auto", "quiz"),
        ("관련 자료와 출처를 찾아 주세요.", "auto", "researcher"),
        ("어떤 질문이든 퀴즈로 처리", "quiz", "quiz"),
    ],
)
def test_supervisor_selects_specialist(question, requested_mode, expected_agent):
    result = supervisor_agent_node(
        {
            "question": question,
            "requested_mode": requested_mode,
            "turn_id": "turn-1",
            "access_track": "public",
        }
    )
    assert result["selected_agent"] == expected_agent


def test_orchestrator_plans_dynamic_workers_and_preserves_access_boundary():
    tutor_plan = supervisor_agent_node(
        {
            "question": "미분계수를 쉽게 설명해 주세요.",
            "requested_mode": "tutor",
            "turn_id": "turn-1",
            "access_track": "public",
        }
    )
    research_plan = supervisor_agent_node(
        {
            "question": "미분계수 관련 자료와 근거를 모두 찾아 주세요.",
            "requested_mode": "researcher",
            "turn_id": "turn-1",
            "access_track": "public",
        }
    )

    tutor_sources = {task["source_file"] for task in tutor_plan["retrieval_tasks"]}
    research_sources = {task["source_file"] for task in research_plan["retrieval_tasks"]}

    assert len(tutor_plan["retrieval_tasks"]) == 2
    assert len(research_plan["retrieval_tasks"]) == 3
    assert not any(source.startswith("premium_") for source in tutor_sources | research_sources)


def test_tutor_flow_runs_end_to_end_without_teacher_review():
    app = build_app()
    config = {"configurable": {"thread_id": f"tutor-{uuid4()}"}}
    result = app.invoke(
        {
            "question": "미분계수와 평균변화율을 쉽게 설명해 주세요.",
            "requested_mode": "tutor",
            "is_enrolled": False,
            "student_id": "guest",
            "require_teacher_review": False,
            "use_ai_judge": False,
        },
        config=config,
    )

    assert "__interrupt__" not in result
    assert result["status"] == "approved"
    assert result["selected_agent"] == "tutor"
    assert "Feynman 설명" in result["final_answer"]
    assert result["judge_evaluation"]["passed"] is True
    assert not any(source.startswith("premium_") for source in result["selected_sources"])


def test_quiz_agent_generates_and_grades_in_same_thread():
    app = build_app()
    config = {"configurable": {"thread_id": f"quiz-{uuid4()}"}}
    quiz = app.invoke(
        {
            "question": "미분계수 퀴즈를 내 주세요.",
            "requested_mode": "quiz",
            "is_enrolled": False,
            "student_id": "guest",
            "require_teacher_review": False,
            "use_ai_judge": False,
        },
        config=config,
    )
    assert quiz["active_quiz_answer"] == "3"
    assert "1~4" in quiz["final_answer"]

    graded = app.invoke(
        {
            "question": "3",
            "requested_mode": "quiz",
            "is_enrolled": False,
            "student_id": "guest",
            "require_teacher_review": False,
            "use_ai_judge": False,
        },
        config=config,
    )
    assert "정답입니다" in graded["final_answer"]
    assert graded["active_quiz_answer"] == ""
    assert graded["judge_evaluation"]["passed"] is True


def test_teacher_interrupt_revise_and_approve():
    app = build_app()
    config = {"configurable": {"thread_id": f"hitl-{uuid4()}"}}
    paused = app.invoke(
        {
            "question": "미분계수 자료와 근거를 찾아 주세요.",
            "requested_mode": "researcher",
            "is_enrolled": True,
            "student_id": "student-minji",
            "require_teacher_review": True,
            "use_ai_judge": False,
        },
        config=config,
    )
    assert len(paused["__interrupt__"]) == 1
    assert paused["status"] == "pending"

    revised_pause = app.invoke(
        Command(resume={"approved": False, "feedback": "정의를 먼저 배치해 주세요."}),
        config=config,
    )
    assert len(revised_pause["__interrupt__"]) == 1
    assert "교사 피드백 반영" in revised_pause["draft_answer"]

    completed = app.invoke(
        Command(resume={"approved": True, "feedback": ""}),
        config=config,
    )
    assert "__interrupt__" not in completed
    assert completed["status"] == "approved"
    assert completed["final_answer"] == completed["draft_answer"]


def test_ai_judge_falls_back_without_secret_configuration(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("EDUCATION_AGENT_JUDGE_MODEL", raising=False)
    state = {
        "question": "미분계수를 설명해 주세요.",
        "selected_agent": "tutor",
        "access_track": "public",
        "selected_sources": ["public_concept_notes.md"],
        "draft_answer": (
            "[Tutor Agent] 쉽게 말하면 미분계수는 순간변화율입니다. "
            "1. 평균변화율을 구합니다. 2. 두 점을 한 점으로 가까이 보냅니다. "
            "3. 극한값을 접선의 기울기로 해석합니다. 확인 질문도 함께 제공합니다."
        ),
        "use_ai_judge": True,
    }
    result = judge_agent_node(state)
    assert result["judge_evaluation"]["mode"] == "local-fallback"


def test_local_judge_fails_closed_on_public_premium_leak():
    evaluation = _local_judge(
        {
            "selected_agent": "researcher",
            "access_track": "public",
            "selected_sources": ["public_concept_notes.md"],
            "draft_answer": "1. 충분한 설명 " * 30 + " premium_textbook_metadata.md",
        }
    )
    assert evaluation["passed"] is False
    assert "Premium" in evaluation["feedback"]
