"""HITL Streamlit 对话内审批卡片交互测试。"""

import copy
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from unittest import mock

_TMP_DIR = tempfile.mkdtemp(prefix="supportpilot_hitl_ui_test_")
os.environ["SUPPORTPILOT_AGENT_DB"] = os.path.join(_TMP_DIR, "agent.db")
os.environ["SUPPORTPILOT_LOG_LEVEL"] = "ERROR"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import ui.components as components  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402
from ui.copy import LANG_CODES, T  # noqa: E402

_SEND_KEY = "FormSubmitter:ai_composer_form-Send"
_QUESTION = "ORD-1001 商家一直失联，我要投诉并申请平台介入"


def _resume_result(approved=True):
    status = "approved" if approved else "rejected"
    return {
        "answer": "平台升级工单已创建。" if approved else "已取消本次升级操作。",
        "sources": [{"title": "平台争议处理规则", "source": "test-kb"}],
        "needs_approval": False,
        "network_error": False,
        "hitl": {
            "status": status,
            "summary": "工单写入成功" if approved else "人工审批未通过，未执行写操作",
        },
    }


@contextmanager
def app_context(result=None, state=None):
    history_file = os.path.join(tempfile.mkdtemp(dir=_TMP_DIR), "history.json")
    state_result = state or {"pending": False, "hitl": {}, "answer": "", "sources": []}

    def fake_stream(**kwargs):
        request = {
            "thread_id": kwargs["thread_id"],
            "tool": "create_escalation",
            "order_id": "ORD-1001",
            "case_type": "product",
            "priority": "high",
            "reason": "商家持续失联，需要平台介入。",
        }
        yield "node", "plan"
        yield "final", {
            "answer": "该操作已暂停，等待人工确认。",
            "needs_approval": True,
            "approval": request,
            "sources": [],
            "network_error": False,
        }

    with mock.patch.object(components, "HISTORY_FILE", history_file), \
            mock.patch("app.after_sales_agent.chat_stream", side_effect=fake_stream) as stream_mock, \
            mock.patch("app.after_sales_agent.resume") as resume_mock, \
            mock.patch("app.after_sales_agent.approval_state",
                       side_effect=lambda *args, **kwargs: copy.deepcopy(state_result)):
        resume_mock.side_effect = lambda **kwargs: copy.deepcopy(
            result(kwargs) if callable(result) else (result or _resume_result(kwargs["approved"]))
        )
        at = AppTest.from_file(os.path.join(ROOT, "streamlit_app.py"), default_timeout=180)
        at.session_state["has_booted"] = True
        at.session_state["lang"] = "zh"
        at.run()
        _assert_clean(at)
        yield at, stream_mock, resume_mock, history_file


def _assert_clean(at):
    assert not at.exception, [str(e.value) for e in at.exception]


def _run(at):
    at.run()
    _assert_clean(at)


def _send_pending(at):
    at.text_input(key="ai_text").set_value(_QUESTION)
    at.button(key=_SEND_KEY).click()
    _run(at)
    message = next(
        m for m in reversed(at.session_state.ai_messages) if m.get("approval")
    )
    return message


def _click_decision(at, message, approve=True):
    approval = message["approval"]
    at.text_input(key=f"hitl_reviewer_{approval['id']}").set_value("reviewer-a")
    at.text_area(key=f"hitl_note_{approval['id']}").set_value("已核对订单与沟通记录")
    key = f"hitl_{'approve' if approve else 'reject'}_{approval['id']}"
    at.button(key=key).click()
    _run(at)


def test_approve_and_persist():
    with app_context() as (at, stream_mock, resume_mock, history_file):
        message = _send_pending(at)
        request = message["approval"]["request"]
        assert request["order_id"] == "ORD-1001"
        assert request["priority"] == "high"
        assert at.text_input(key="ai_text").disabled
        assert stream_mock.call_count == 1

        _click_decision(at, message, approve=True)
        resume_mock.assert_called_once_with(
            thread_id=request["thread_id"],
            approved=True,
            reviewer="reviewer-a",
            note="已核对订单与沟通记录",
        )
        assert message["approval"]["status"] == "approved"
        assert "平台升级工单已创建" in message["content"]
        assert message["sources"][0]["source"] == "test-kb"
        assert not at.text_input(key="ai_text").disabled

        _run(at)
        assert resume_mock.call_count == 1
        with open(history_file, encoding="utf-8") as f:
            saved = json.load(f)
        saved_message = next(
            m for s in saved["sessions"] for m in s["messages"] if m.get("approval")
        )
        assert saved_message["approval"]["status"] == "approved"
    print("STREAMLIT_HITL_APPROVE_OK")


def test_reject():
    with app_context() as (at, _, resume_mock, _):
        message = _send_pending(at)
        _click_decision(at, message, approve=False)
        assert resume_mock.call_args.kwargs["approved"] is False
        assert message["approval"]["status"] == "rejected"
        assert "未执行写操作" in message["approval"]["summary"]
        assert "已取消本次升级操作" in message["content"]
        _run(at)
        assert resume_mock.call_count == 1
    print("STREAMLIT_HITL_REJECT_OK")


def test_stale_request():
    stale = {"answer": "当前会话没有待审批的操作。", "error": "no_pending_action"}
    with app_context(stale) as (at, _, resume_mock, _):
        message = _send_pending(at)
        _click_decision(at, message, approve=True)
        assert message["approval"]["status"] == "stale"
        assert message["content"] == T["zh"]["hitl_stale_message"]
        _run(at)
        assert resume_mock.call_count == 1
    print("STREAMLIT_HITL_STALE_OK")


def test_session_isolation():
    with app_context() as (at, _, resume_mock, _):
        message = _send_pending(at)
        old_id = message["approval"]["id"]
        old_session_id = at.session_state.ai_active
        old_thread_id = message["approval"]["thread_id"]
        old_messages = at.session_state.ai_messages

        at.button(key="ai_new_chat").click()
        _run(at)
        assert at.session_state.ai_active != old_session_id
        assert f"hitl_approve_{old_id}" not in {b.key for b in at.button}
        assert not at.text_input(key="ai_text").disabled
        assert resume_mock.call_count == 0

        at.session_state["ai_active"] = old_session_id
        at.session_state["ai_messages"] = old_messages
        _run(at)
        _click_decision(at, message, approve=True)
        assert resume_mock.call_args.kwargs["thread_id"] == old_thread_id
        assert resume_mock.call_count == 1
    print("STREAMLIT_HITL_SESSION_ISOLATION_OK")


def test_processing_recovery_pending():
    # 中断但仍待审批：恢复为可重试，且不自动重放写操作
    with app_context(state={"pending": True, "hitl": {}, "answer": "", "sources": []}) \
            as (at, _, resume_mock, _):
        message = _send_pending(at)
        approval = message["approval"]
        approval["status"] = "processing"
        _run(at)
        assert approval["status"] == "pending"
        assert resume_mock.call_count == 0
        assert at.text_input(key="ai_text").disabled
        _click_decision(at, message, approve=True)
        assert resume_mock.call_count == 1
    print("STREAMLIT_HITL_RECOVER_PENDING_OK")


def test_processing_recovery_executed():
    # 中断但后端已执行：回填真实结果，不再重复提交
    executed = {
        "pending": False,
        "hitl": {"status": "approved", "summary": "已创建升级工单 #2"},
        "answer": "已升级到平台客服，工单 #2 已创建。",
        "sources": [],
    }
    with app_context(state=executed) as (at, _, resume_mock, _):
        message = _send_pending(at)
        message["approval"]["status"] = "processing"
        _run(at)
        assert message["approval"]["status"] == "approved"
        assert message["approval"]["summary"] == "已创建升级工单 #2"
        assert "已升级到平台客服" in message["content"]
        assert resume_mock.call_count == 0
        assert not at.text_input(key="ai_text").disabled
    print("STREAMLIT_HITL_RECOVER_EXECUTED_OK")


def test_language_packs():
    required = {
        "hitl_title", "hitl_pending", "hitl_processing", "hitl_approved",
        "hitl_rejected", "hitl_failed", "hitl_stale", "hitl_description",
        "hitl_tool_create_escalation", "hitl_case_label", "hitl_priority_label",
        "hitl_reason_label", "hitl_reviewer_label", "hitl_note_label",
        "hitl_approve", "hitl_reject", "hitl_input_locked", "hitl_error",
    }
    for lang in LANG_CODES:
        assert not (required - set(T[lang])), (lang, required - set(T[lang]))
    print("STREAMLIT_HITL_I18N_OK")


def main():
    test_language_packs()
    test_approve_and_persist()
    test_reject()
    test_stale_request()
    test_session_isolation()
    test_processing_recovery_pending()
    test_processing_recovery_executed()
    print("STREAMLIT_HITL_ALL_PASS")


if __name__ == "__main__":
    main()
