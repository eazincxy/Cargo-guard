"""售后回答的合规审核节点。"""

from __future__ import annotations

from typing import Any

from app.agent_intents import CHITCHAT, intent_rule_issues
from app.agent_observability import json_fields, preview


def _order_rule_for_review(order: dict[str, Any]) -> dict[str, Any] | None:
    """把订单关键字段整理成审核用的硬约束，避免审核模型凭空判断。"""
    if not order:
        return None
    return {
        "order_id": order.get("order_id"),
        "currency": order.get("currency"),
        "total_amount": order.get("total_amount"),
        "status": order.get("status"),
        "shipping_status": order.get("shipping_status"),
    }


def review_node(state: dict[str, Any], runtime: Any) -> dict[str, Any]:
    """合规审核节点：off 关闭 / soft 只标记 / hard 拦截改写。"""
    mode = runtime.CONFIG.review_mode
    answer = state.get("answer", "")
    intent = state.get("intent", "")
    flags = state.get("injection_flags") or []

    # 命中注入特征时，即使关闭审核也强制走 soft 复核
    if mode == "off" and flags:
        mode = "soft"
        runtime.LOGGER.warning(json_fields(
            event="review_escalated", reason="injection_flags", flags=flags
        ))

    if mode == "off":
        runtime.LOGGER.info(json_fields(event="review_skipped", mode=mode))
        return {"review_passed": None, "review_note": "review_off", "review_issues": []}

    issues = intent_rule_issues(answer, intent)
    passed = True
    note = ""
    errors = list(state.get("errors") or [])

    # 闲聊不做模型审核；审核模型异常不阻断主链路
    if runtime.has_llm() and intent != CHITCHAT:
        try:
            passed, note = runtime.review_answer(
                answer,
                state.get("citations") or [],
                _order_rule_for_review(state.get("order") or {}),
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            runtime.LOGGER.warning(json_fields(event="review_failed", error=message))
            errors.append({"node": "review", "error": message})
            passed, note = True, "review_error"

    final_passed = bool(passed and not issues)
    update: dict[str, Any] = {
        "review_passed": final_passed,
        "review_note": note,
        "review_issues": issues,
        "errors": errors,
    }

    if mode == "hard" and not final_passed:
        update["answer"] = runtime._grounded_fallback(state, note="合规复核未通过，已切换为知识库摘录")
        runtime.LOGGER.warning(json_fields(
            event="review_blocked",
            intent=intent,
            issues=issues,
            note=note,
        ))
    else:
        runtime.LOGGER.info(json_fields(
            event="review_done",
            mode=mode,
            intent=intent,
            passed=final_passed,
            issues=issues,
            note=preview(note),
        ))
    return update
