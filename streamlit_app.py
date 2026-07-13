from __future__ import annotations

from uuid import uuid4

import streamlit as st
from langgraph.types import Command

from agent import build_app, external_judge_configured


st.set_page_config(
    page_title="Trinity RAG Assistant",
    page_icon="📐",
    layout="centered",
)

st.markdown(
    """
    <style>
    .block-container { max-width: 860px; padding-top: 2.2rem; }
    [data-testid="stSidebar"] { border-right: 1px solid #e7e9ee; }
    .agent-note {
        border: 1px solid #dce4ef;
        border-radius: 12px;
        padding: 0.8rem 1rem;
        background: #f7f9fc;
        color: #39465a;
        margin-bottom: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_agent_app():
    return build_app()


def initialize_session() -> None:
    defaults = {
        "thread_id": str(uuid4()),
        "messages": [],
        "pending_review": False,
        "pending_draft": "",
        "pending_judge": {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_session() -> None:
    st.session_state.thread_id = str(uuid4())
    st.session_state.messages = []
    st.session_state.pending_review = False
    st.session_state.pending_draft = ""
    st.session_state.pending_judge = {}


def graph_config() -> dict:
    return {"configurable": {"thread_id": st.session_state.thread_id}}


def judge_caption(result: dict) -> str:
    judge = result.get("judge_evaluation", {})
    if not judge:
        return ""
    mode_label = {
        "local": "local rubric",
        "ai": "AI judge",
        "local-fallback": "local fallback",
    }.get(judge.get("mode"), "judge")
    return f"{mode_label} · {judge.get('score', 0)}/10 · {result.get('selected_agent', '')} agent"


def store_result(result: dict) -> None:
    pending = bool(result.get("__interrupt__"))
    content = result.get("draft_answer", "") if pending else result.get("final_answer", "")
    message = {
        "role": "assistant",
        "content": content,
        "caption": judge_caption(result),
        "pending": pending,
    }

    if st.session_state.messages and st.session_state.messages[-1].get("pending"):
        st.session_state.messages[-1] = message
    else:
        st.session_state.messages.append(message)

    st.session_state.pending_review = pending
    st.session_state.pending_draft = content if pending else ""
    st.session_state.pending_judge = result.get("judge_evaluation", {}) if pending else {}


def resume_teacher_review(approved: bool, feedback: str = "") -> None:
    result = get_agent_app().invoke(
        Command(resume={"approved": approved, "feedback": feedback}),
        config=graph_config(),
    )
    store_result(result)


initialize_session()
agent_app = get_agent_app()

with st.sidebar:
    st.subheader("학습 설정")
    is_enrolled = st.toggle("수강생 자료 사용", value=True)
    student_id = st.selectbox(
        "학생 프로필",
        options=["student-minji", "guest"],
        format_func=lambda value: "민지" if value == "student-minji" else "게스트",
    )
    mode_label = st.selectbox(
        "에이전트 모드",
        options=["자동", "튜터", "퀴즈", "자료 조사"],
    )
    requested_mode = {
        "자동": "auto",
        "튜터": "tutor",
        "퀴즈": "quiz",
        "자료 조사": "researcher",
    }[mode_label]
    require_teacher_review = st.toggle("교사 검토 후 발행", value=False)

    judge_ready = external_judge_configured()
    use_ai_judge = st.toggle(
        "외부 AI judge 사용",
        value=False,
        disabled=not judge_ready,
        help=(
            "OPENAI_API_KEY와 EDUCATION_AGENT_JUDGE_MODEL이 모두 설정된 경우에만 활성화됩니다."
        ),
    )
    st.caption(f"외부 AI judge 설정: {'configured' if judge_ready else 'missing'}")

    st.divider()
    if st.button("새 대화", use_container_width=True):
        reset_session()
        st.rerun()

st.title("Trinity RAG Assistant")
st.caption("Supervisor가 Quiz · Tutor · Researcher를 선택하고, repo-local 자료로 답합니다.")
st.markdown(
    """
    <div class="agent-note">
    자동 모드에서는 질문 의도에 맞는 전문 에이전트를 고릅니다. 퀴즈 모드에서 문제를 받은 뒤
    1~4 중 하나를 보내면 같은 대화에서 바로 채점합니다.
    </div>
    """,
    unsafe_allow_html=True,
)

if not st.session_state.messages:
    st.info("예: ‘미분계수를 쉽게 설명해 줘’, ‘미분계수 퀴즈를 내 줘’, ‘관련 자료를 찾아 줘’")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("caption"):
            st.caption(message["caption"])
        if message.get("pending"):
            st.warning("교사 검토 대기 중")

if st.session_state.pending_review:
    st.subheader("교사 검토")
    judge = st.session_state.pending_judge
    if judge:
        st.caption(
            f"Judge: {judge.get('score', 0)}/10 · {judge.get('mode', 'local')} · "
            f"{judge.get('feedback', '')}"
        )
    teacher_feedback = st.text_area(
        "수정 요청",
        placeholder="수정이 필요한 이유와 방향을 입력하세요.",
    )
    approve_col, revise_col = st.columns(2)
    with approve_col:
        if st.button("승인하고 발행", type="primary", use_container_width=True):
            resume_teacher_review(approved=True)
            st.rerun()
    with revise_col:
        if st.button("수정 요청", use_container_width=True):
            if not teacher_feedback.strip():
                st.error("수정 요청 내용을 입력해 주세요.")
            else:
                resume_teacher_review(approved=False, feedback=teacher_feedback.strip())
                st.rerun()

prompt = st.chat_input(
    "수학 질문을 입력하세요",
    disabled=st.session_state.pending_review,
)
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt, "pending": False})
    with st.spinner("전문 에이전트가 자료를 확인하고 있습니다..."):
        result = agent_app.invoke(
            {
                "question": prompt,
                "requested_mode": requested_mode,
                "is_enrolled": is_enrolled,
                "student_id": student_id,
                "require_teacher_review": require_teacher_review,
                "use_ai_judge": use_ai_judge,
            },
            config=graph_config(),
        )
    store_result(result)
    st.rerun()
