from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"


def test_streamlit_chat_smoke():
    app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()
    assert not app.exception
    assert app.title[0].value == "Trinity RAG Assistant"
    assert len(app.chat_input) == 1

    app.chat_input[0].set_value("미분계수를 쉽게 설명해 주세요.").run()
    assert not app.exception
    assert len(app.chat_message) >= 2
    assert "Feynman 설명" in app.chat_message[-1].markdown[0].value
