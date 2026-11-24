"""高风险动作的人工审批（Human-in-the-loop）。

规划节点发现高风险写操作时不会直接执行，而是写入 `pending_action` 并转入本节点。
本节点用 LangGraph `interrupt()` 挂起图，把待审批动作返回给调用方；外部通过
`Command(resume={"approved": ..., "reviewer": ..., "note": ...})` 恢复执行：

- 批准：真正执行工具（落库），并把结果并入 tool_trace；
- 拒绝：不产生任何写操作，只保留审批记录。

这样「写操作 → 人工确认 → 恢复执行」的边界由工作流本身保证，而不是靠提示词约束。
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.types import interrupt

from app.agent_observability import json_fields
from app.agent_tools import execute_tool


def approval_node(state: dict[str, Any], runtime: Any) -> dict[str, Any]:
    """挂起等待人工审批；批准后执行高风险工具。"""
    action = state.get("pending_action") or {}
    if not action:
        return {}

    request = {
        "tool": action.get("tool", ""),
        "order_id": action.get("order_id", ""),
        "case_type": action.get("case_type", ""),
        "priority": action.get("priority", ""),
        "reason": action.get("reason", ""),
        "ask": "该操作会写入工单并转平台介入，需要人工确认后才执行。",
    }
    # 图在此处暂停；恢复时本行返回外部传入的审批结论
    decision = interrupt(request)
    if not isinstance(decision, dict):
        decision = {"approved": bool(decision)}

    approved = bool(decision.get("approved"))
    reviewer = str(decision.get("reviewer") or "operator")[:40]
    note = str(decision.get("note") or "")[:200]
    started = time.perf_counter()

    trace = list(state.get("tool_trace") or [])
    # plan 阶段留下的占位 trace（error=pending_approval）用真实结果替换
    if trace and trace[-1].get("error") == "pending_approval":
        trace = trace[:-1]

    update: dict[str, Any] = {"pending_action": {}}
    if approved:
        entry = execute_tool(
            action.get("tool", ""),
            action.get("args") or {},
            {**state, "order": state.get("order") or {}},
            search_fn=runtime.kb_search,
            load_order_fn=runtime.load_order,
        )
        trace.append(entry)
        update["tool_trace"] = trace
        status = "approved" if entry.get("ok") else "failed"
        result_summary = entry.get("summary") or entry.get("error") or ""
    else:
        status = "rejected"
        result_summary = "人工审批未通过，未执行写操作"

    record = {
        "tool": action.get("tool", ""),
        "order_id": action.get("order_id", ""),
        "case_type": action.get("case_type", ""),
        "priority": action.get("priority", ""),
        "reason": action.get("reason", ""),
        "status": status,
        "reviewer": reviewer,
        "note": note,
        "summary": result_summary,
        "ms": round((time.perf_counter() - started) * 1000, 1),
    }
    history = list(state.get("hitl_history") or [])
    history.append(record)
    update["hitl"] = record
    update["hitl_history"] = history

    runtime.LOGGER.info(json_fields(
        event="hitl_decision",
        tool=record["tool"],
        order_id=record["order_id"],
        status=status,
        reviewer=reviewer,
        ms=record["ms"],
    ))
    return update
