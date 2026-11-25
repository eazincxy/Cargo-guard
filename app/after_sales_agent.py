"""基于 LangGraph 的跨境电商售后 RAG Agent。

本文件是对外入口与图编排层，具体职责拆分为：
- agent_plan：意图识别、ReAct 工具规划与观察循环；
- agent_act：订单读取、RAG 检索、长期记忆存储与写入；
- agent_answer：上下文摘要、回答提示词、模型回答与降级文案；
- agent_review：规则与模型合规复核。

短期会话记忆由 SqliteSaver 按 thread_id 持久化；长期用户记忆由 SqliteStore 按 user_id
持久化。默认数据库为项目根目录 agent_memory.db，可用 SUPPORTPILOT_AGENT_DB 覆盖。

工作流：
    START → intent → load_memory → (超预算? summarize) → plan → retrieve
          → answer → review → extract_memory → END

对外入口保持 chat(user_id, message, order_id, thread_id) 不变。
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app import capability as cap
from app import tracing
from app import agent_act as act
from app import agent_answer as answer_stage
from app import agent_hitl as hitl_stage
from app import agent_plan as plan_stage
from app import agent_review as review_stage
from app.agent_config import CONFIG
from app.agent_intents import CHITCHAT, detect_intent, intent_prompt, intent_rule_issues
from app.agent_observability import (
    estimate_messages_tokens,
    estimate_tokens,
    get_logger,
    json_fields,
    preview,
    text_terms,
)
from app.db import get_connection
from app.kb import search as kb_search
from app.llm import (
    buyer_region,
    chat_completion_detailed,
    chat_completion_with_tools,
    has_llm,
    review_answer,
)
from app.prompt_guard import detect_injection

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("SUPPORTPILOT_DB") or os.path.join(ROOT, "data.db")

# 兼容原有导入路径；实现分别位于四个阶段模块。
CUSTOMER_SERVICE_PROMPT = answer_stage.CUSTOMER_SERVICE_PROMPT
SUMMARY_PROMPT = answer_stage.SUMMARY_PROMPT
PLANNER_PROMPT = plan_stage.PLANNER_PROMPT
MEMORY_EXTRACTION_PROMPT = act.MEMORY_EXTRACTION_PROMPT
KEEP_RECENT_MESSAGES = answer_stage.KEEP_RECENT_MESSAGES
RAG_TOKEN_RESERVE = answer_stage.RAG_TOKEN_RESERVE
TOP_K = act.TOP_K
MIN_SCORE = act.MIN_SCORE
MAX_MEMORY_FACTS = act.MAX_MEMORY_FACTS
AGENT_DB_PATH = act.AGENT_DB_PATH
MEMORY_NAMESPACE = act.MEMORY_NAMESPACE
LONG_TERM_STORE = act.LONG_TERM_STORE

LOGGER = get_logger(CONFIG.log_level)
tracing.setup_tracing()


class AfterSalesState(TypedDict, total=False):
    """工作流状态。字段均为可覆盖的普通值，便于 SqliteSaver 序列化。"""

    user_id: str
    thread_id: str
    order_id: str
    query: str
    history: list[dict]
    summary: str
    summarized_upto: int
    memories: list[str]
    order: dict[str, Any]
    extra_context: str
    reply_language: str
    disable_order_lookup: bool
    retrieved: list[dict]
    citations: list[str]
    cited_titles: list[str]
    sources_explicit: bool
    answer: str
    turn: int

    # 工具规划
    tool_trace: list[dict]
    plan: dict
    planner_error: str
    react_steps: int
    react_rounds: int
    react_stop_reason: str

    # 人工审批（HITL）
    pending_action: dict[str, Any]
    hitl: dict[str, Any]
    hitl_history: list[dict]

    # 意图 / 合规 / 观测
    intent: str
    intent_confidence: float
    review_passed: bool | None
    review_note: str
    review_issues: list[str]
    summary_triggered: bool
    context_tokens: int
    context_tokens_before: int
    memory_total: int
    memory_injected: int
    memory_error: str
    rag_error: str
    injection_flags: list[str]
    llm_error: str
    llm_usage: dict[str, int]
    node_metrics: list[dict]
    errors: list[dict]


# =========================================================
# 断点存储与兼容适配
# =========================================================
# 长期记忆连接由 agent_act 持有；断点使用独立连接，避免两套事务互相干扰。
_CHECKPOINT_CONN = act._open_agent_db()
CHECKPOINTER = SqliteSaver(_CHECKPOINT_CONN)
CHECKPOINTER.setup()

# Streamlit 多标签页可能并发进入，SQLite 连接需要串行使用。
_AGENT_LOCK = threading.RLock()


def _runtime() -> Any:
    """返回入口模块自身，让阶段节点在调用时读取最新的配置与测试替身。"""
    return sys.modules[__name__]


# 以下薄包装保留原有节点/辅助函数路径；具体实现不在本文件重复维护。
def intent_node(state: AfterSalesState) -> dict[str, Any]:
    return plan_stage.intent_node(state, _runtime())


def load_memory_node(state: AfterSalesState) -> dict[str, Any]:
    return act.load_memory_node(state, _runtime())


def summarize_node(state: AfterSalesState) -> dict[str, Any]:
    return answer_stage.summarize_node(state, _runtime())


def plan_node(state: AfterSalesState) -> dict[str, Any]:
    return plan_stage.plan_node(state, _runtime())


def approval_node(state: AfterSalesState) -> dict[str, Any]:
    return hitl_stage.approval_node(state, _runtime())


def retrieve_node(state: AfterSalesState) -> dict[str, Any]:
    return act.retrieve_node(state, _runtime())


def answer_node(state: AfterSalesState) -> dict[str, Any]:
    return answer_stage.answer_node(state, _runtime())


def review_node(state: AfterSalesState) -> dict[str, Any]:
    return review_stage.review_node(state, _runtime())


def extract_memory_node(state: AfterSalesState) -> dict[str, Any]:
    return act.extract_memory_node(state, _runtime())


def load_order(order_id: str) -> dict[str, Any]:
    return act.load_order(order_id, _runtime())


def load_memory_records(user_id: str) -> list[dict[str, Any]]:
    return act.load_memory_records(user_id, _runtime())


def load_user_memory(user_id: str) -> list[str]:
    return act.load_user_memory(user_id, _runtime())


def save_user_memory(user_id: str, facts: list[str]) -> list[str]:
    return act.save_user_memory(user_id, facts, _runtime())


def select_relevant_memories(
    records: list[dict[str, Any]],
    query: str,
    intent: str,
    relax: bool = False,
) -> list[str]:
    return act.select_relevant_memories(records, query, intent, relax, runtime=_runtime())


def _estimate_context_tokens(state: AfterSalesState) -> int:
    return answer_stage._estimate_context_tokens(state, _runtime())


def _llm_answer(state: AfterSalesState) -> tuple[str, dict[str, int]]:
    return answer_stage._llm_answer(state, _runtime())


def _grounded_fallback(state: AfterSalesState, note: str) -> str:
    return answer_stage._grounded_fallback(state, note)


def _build_search_query(state: AfterSalesState) -> str:
    return act._build_search_query(state)


def _planner_context(state: AfterSalesState) -> str:
    return plan_stage._planner_context(state)


# 无额外依赖的内部辅助函数可直接复用，兼容已有调用和测试。
_memory_ns = act._memory_ns
_now = act._now
_iso = act._iso
_extract_order_id = act._extract_order_id
_format_order = act._format_order
_format_retrieved = act._format_retrieved
_trim_history = answer_stage._trim_history


# =========================================================
# 共享模型调用与路由
# =========================================================
def _accumulate_usage(state: AfterSalesState, usage: dict[str, int]) -> dict[str, int]:
    """累加本轮 LLM token 用量。"""
    merged = dict(state.get("llm_usage") or {})
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        merged[key] = int(merged.get(key, 0)) + int(usage.get(key, 0) or 0)
    merged["calls"] = int(merged.get("calls", 0)) + 1
    return merged


def _append_error(state: AfterSalesState, node: str, message: str) -> list[dict]:
    """把已捕获异常写入本轮 errors，供埋点与排查。"""
    errors = list(state.get("errors") or [])
    errors.append({"node": node, "error": message})
    return errors


def _call_llm(
    messages: list[dict],
    temperature: float,
    timeout: int,
    purpose: str,
) -> tuple[str, dict[str, int]]:
    """统一 LLM 调用入口：返回内容 + token 用量，并记录耗时日志。"""
    started = time.perf_counter()
    data = chat_completion_detailed(messages, temperature=temperature, timeout=timeout)
    content = data.get("content", "")
    prompt_tokens = int(data.get("prompt_tokens") or 0) or estimate_messages_tokens(messages)
    completion_tokens = int(data.get("completion_tokens") or 0) or estimate_tokens(content)
    total_tokens = int(data.get("total_tokens") or 0) or (prompt_tokens + completion_tokens)
    LOGGER.info(json_fields(
        event="llm_call",
        purpose=purpose,
        ms=round((time.perf_counter() - started) * 1000, 1),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    ))
    return content, {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _route_after_plan(state: AfterSalesState) -> str:
    """高风险写操作先挂起等待人工审批，其余直接进入检索阶段。"""
    return "approval" if state.get("pending_action") else "retrieve"


def _route_after_load(state: AfterSalesState) -> str:
    """意图分流 + token 预算判断：闲聊直接回答，超预算才压缩，其余先做工具规划。"""
    if state.get("intent") == CHITCHAT:
        return "answer"
    if not CONFIG.enable_summary:
        return "plan"

    history = state.get("history", [])
    summarized = state.get("summarized_upto", 0)
    estimated = _estimate_context_tokens(state)
    can_compress = len(history) - summarized > KEEP_RECENT_MESSAGES
    if can_compress and estimated > CONFIG.context_token_budget:
        LOGGER.info(json_fields(
            event="summary_budget_exceeded",
            estimated_tokens=estimated,
            budget=CONFIG.context_token_budget,
        ))
        return "summarize"
    return "plan"


def _route_after_summarize(state: AfterSalesState) -> str:
    return "answer" if state.get("intent") == CHITCHAT else "plan"


# =========================================================
# 图观测与组装
# =========================================================
def _state_token_estimate(state: AfterSalesState) -> int:
    """节点输入的 token 估算（只看关键字段，避免日志计算本身过重）。"""
    parts = [state.get("query", ""), state.get("summary", "")]
    parts += [m.get("content", "") for m in state.get("history", [])[-6:]]
    return estimate_tokens("\n".join(parts))


def _update_token_estimate(update: dict[str, Any]) -> int:
    """节点输出的 token 估算。"""
    parts = [str(update.get(key, "")) for key in ("answer", "summary")]
    parts += [str(item.get("text", ""))[:200] for item in (update.get("retrieved") or [])[:4]]
    return estimate_tokens("\n".join(parts))


def _node_input_summary(state: AfterSalesState) -> dict[str, Any]:
    return {
        "intent": state.get("intent", ""),
        "query": preview(state.get("query", "")),
        "history": len(state.get("history", [])),
        "summary_len": len(state.get("summary", "")),
        "memories": len(state.get("memories", [])),
        "retrieved": len(state.get("retrieved", [])),
    }


def _traced(name: str, fn):
    """节点通用埋点：记录输入输出、耗时、token 与异常，不让异常冒泡中断会话。"""

    def wrapper(state: AfterSalesState) -> dict[str, Any]:
        started = time.perf_counter()
        in_tokens = _state_token_estimate(state)
        LOGGER.info(json_fields(
            event="node_start",
            node=name,
            in_tokens=in_tokens,
            input=_node_input_summary(state),
        ))
        error = None
        with tracing.span(f"agent.node.{name}", node=name, in_tokens=in_tokens) as node_span:
            try:
                update = fn(state) or {}
            except GraphInterrupt:
                # interrupt 是控制流信号，必须继续向上抛给 LangGraph，不能当异常吞掉
                raise
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                node_span.set_attribute("error", error)
                LOGGER.exception(json_fields(event="node_exception", node=name, error=error))
                update = {}
            node_span.set_attribute("out_tokens", _update_token_estimate(update))

        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        metrics = list(state.get("node_metrics") or [])
        metrics.append({
            "node": name,
            "ms": elapsed_ms,
            "in_tokens": in_tokens,
            "out_tokens": _update_token_estimate(update),
            "error": error,
        })
        update["node_metrics"] = metrics
        if error:
            update["errors"] = _append_error(state, name, error)

        LOGGER.info(json_fields(
            event="node_end",
            node=name,
            ms=elapsed_ms,
            in_tokens=in_tokens,
            out_tokens=metrics[-1]["out_tokens"],
            error=error,
            output=preview({k: update.get(k) for k in (
                "intent", "answer", "summary", "summary_triggered",
                "retrieved", "review_passed", "memories", "rag_error", "llm_error",
            )}),
        ))
        return update

    wrapper.__name__ = f"traced_{name}"
    return wrapper


def build_graph():
    """构建并编译工作流；节点实现见四个阶段模块。"""
    graph = StateGraph(AfterSalesState)
    nodes = {
        "intent": intent_node,
        "load_memory": load_memory_node,
        "summarize": summarize_node,
        "plan": plan_node,
        "approval": approval_node,
        "retrieve": retrieve_node,
        "answer": answer_node,
        "review": review_node,
        "extract_memory": extract_memory_node,
    }
    for name, node_fn in nodes.items():
        graph.add_node(name, _traced(name, node_fn))

    graph.add_edge(START, "intent")
    graph.add_edge("intent", "load_memory")
    graph.add_conditional_edges(
        "load_memory",
        _route_after_load,
        {"summarize": "summarize", "plan": "plan", "answer": "answer"},
    )
    graph.add_conditional_edges(
        "summarize",
        _route_after_summarize,
        {"plan": "plan", "answer": "answer"},
    )
    graph.add_conditional_edges(
        "plan",
        _route_after_plan,
        {"approval": "approval", "retrieve": "retrieve"},
    )
    graph.add_edge("approval", "retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", "review")
    graph.add_edge("review", "extract_memory")
    graph.add_edge("extract_memory", END)
    return graph.compile(checkpointer=CHECKPOINTER, store=LONG_TERM_STORE)


GRAPH = build_graph()


# =========================================================
# 对外入口
# =========================================================
def _prepare_payload(
    user_id: str,
    message: str,
    order_id: str,
    extra_context: str,
    history: list[dict] | None,
    allow_order_lookup: bool,
    reply_language: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_id": user_id,
        "query": message,
        "extra_context": extra_context,
        "reply_language": reply_language,
        "disable_order_lookup": not allow_order_lookup,
        "injection_flags": detect_injection(f"{message}\n{extra_context or ''}"),
        # 每轮重置埋点，避免 checkpoints 里的历史指标无限增长
        "node_metrics": [],
        "errors": [],
        "llm_usage": {},
        "summary_triggered": False,
        "tool_trace": [],
        "plan": {},
        "planner_error": "",
        "react_steps": 0,
        "react_rounds": 0,
        "react_stop_reason": "",
        "pending_action": {},
        "hitl": {},
    }
    if payload["injection_flags"]:
        LOGGER.warning(json_fields(
            event="injection_detected",
            user_id=user_id,
            flags=payload["injection_flags"],
        ))
    if order_id:
        payload["order_id"] = order_id
    else:
        # 显式写入空值，避免上一轮订单残留在断点状态里被继续使用
        payload["order_id"] = ""
    return payload


def _inherited_order_id(message: str, config: dict[str, Any]) -> str:
    """沿用同一会话上一轮的订单号；但买家本轮明确说出的国家与订单国家冲突时不沿用。"""
    try:
        prev = GRAPH.get_state(config).values or {}
    except Exception:
        return ""
    prev_order_id = str(prev.get("order_id") or "").strip()
    if not prev_order_id:
        return ""
    stated = act.stated_country_iso(message)
    if stated:
        try:
            prev_order = load_order(prev_order_id) or {}
        except Exception:
            prev_order = {}
        prev_cc, _ = act.buyer_region(prev_order.get("shipping_address") or "")
        if prev_cc and prev_cc.upper() != stated:
            return ""
    return prev_order_id


def _agent_capability(metrics: dict) -> str:
    """区分正常生成、LLM 失败降级、无模型摘录三种产能来源。"""
    if any(e.get("node") == "answer" for e in metrics.get("errors") or []):
        return cap.LLM_FALLBACK
    if (metrics.get("llm") or {}).get("calls"):
        return cap.LLM
    return cap.GROUNDED


def _persist_turn(
    user_id: str,
    thread_id: str,
    order_id: str,
    capability: str,
    metrics: dict,
) -> int | None:
    """把本轮节点指标写入 data.db.agent_turns，返回行 id；任何失败都不影响主流程。"""
    try:
        conn = get_connection()
        try:
            llm = metrics.get("llm") or {}
            review_passed = metrics.get("review_passed")
            cur = conn.execute(
                """
                INSERT INTO agent_turns
                    (user_id, thread_id, order_id, intent, total_ms,
                     llm_prompt_tokens, llm_completion_tokens, llm_total_tokens, llm_calls,
                     summary_triggered, review_mode, review_passed, error_count,
                     capability, nodes_json, errors_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    thread_id,
                    order_id,
                    metrics.get("intent", ""),
                    metrics.get("total_ms", 0),
                    int(llm.get("prompt_tokens") or 0),
                    int(llm.get("completion_tokens") or 0),
                    int(llm.get("total_tokens") or 0),
                    int(llm.get("calls") or 0),
                    1 if metrics.get("summary_triggered") else 0,
                    metrics.get("review_mode", ""),
                    None if review_passed is None else (1 if review_passed else 0),
                    len(metrics.get("errors") or []),
                    capability,
                    json.dumps(metrics.get("nodes") or [], ensure_ascii=False),
                    json.dumps(metrics.get("errors") or [], ensure_ascii=False),
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            json_fields(event="turn_persist_failed", error=f"{type(exc).__name__}: {exc}")
        )
        return None


_SOURCE_TRANSLATE_PROMPT = """你是翻译器。把给定的来源条目翻译成目标语言：{lang}。
要求：
1. 翻译 title、desc、country 三个字段；
2. 规则/法案标识里的英文 tag（如 runaway、damage、law-us-01）保留原文，只翻译中文部分；
3. 订单号、商品名保持原文；
4. 严格输出 JSON 数组，每项包含 title、desc、country 三个字符串，顺序与输入一致；
不要 Markdown、不要解释。"""


def _localize_sources(sources: list[dict], lang: str) -> list[dict]:
    """把来源明细翻译成当前界面语言；中文界面或翻译失败时保持原文。"""
    if not sources or not lang:
        return sources
    if "中" in lang or lang.strip().lower() in {"zh", "chinese"}:
        return sources
    runtime = _runtime()
    if not runtime.has_llm():
        return sources
    payload = [
        {"title": s.get("title", ""), "desc": s.get("desc", ""), "country": s.get("country", "")}
        for s in sources
    ]
    try:
        content, _ = runtime._call_llm(
            [
                {"role": "system", "content": _SOURCE_TRANSLATE_PROMPT.format(lang=lang)},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            timeout=30,
            purpose="sources_translate",
        )
        text = (content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("["):] if "[" in text else text
        data = json.loads(text)
        if not isinstance(data, list) or len(data) != len(sources):
            return sources
        localized = []
        for raw, item in zip(data, sources):
            merged = dict(item)
            if isinstance(raw, dict):
                for key in ("title", "desc", "country"):
                    value = raw.get(key)
                    if isinstance(value, str) and value.strip():
                        merged[key] = value.strip()
            localized.append(merged)
        return localized
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(json_fields(
            event="sources_translate_failed", error=f"{type(exc).__name__}: {exc}"
        ))
        return sources


def _finalize(
    user_id: str,
    thread_id: str,
    order_id: str,
    result: dict,
    total_ms: float,
) -> dict[str, Any]:
    """把图执行结果整理成对外响应，并完成埋点日志与落库。"""
    trace = result.get("tool_trace") or []
    metrics = {
        "total_ms": total_ms,
        "intent": result.get("intent", ""),
        "intent_confidence": result.get("intent_confidence", 0),
        "nodes": result.get("node_metrics", []),
        "llm": result.get("llm_usage", {}),
        "summary_triggered": bool(result.get("summary_triggered")),
        "context_tokens": result.get("context_tokens", 0),
        "memory_total": result.get("memory_total", 0),
        "memory_injected": result.get("memory_injected", 0),
        "review_mode": CONFIG.review_mode,
        "review_passed": result.get("review_passed"),
        "review_issues": result.get("review_issues", []),
        "injection_flags": result.get("injection_flags", []),
        "tool_calls": [
            {"name": t.get("name", ""), "ok": bool(t.get("ok")), "ms": t.get("ms", 0)}
            for t in trace
        ],
        "planner_error": result.get("planner_error", ""),
        "react": {
            "steps": result.get("react_steps", 0),
            "rounds": result.get("react_rounds", 0),
            "stop_reason": result.get("react_stop_reason", ""),
            "tool_calls": len(trace),
            "tool_failures": sum(1 for t in trace if not t.get("ok")),
        },
        "hitl": result.get("hitl") or {},
        "errors": result.get("errors", []),
    }
    LOGGER.info(json_fields(
        event="turn_end",
        trace_id=tracing.current_trace_id(),
        user_id=user_id,
        thread_id=thread_id,
        total_ms=total_ms,
        intent=metrics["intent"],
        nodes=[m.get("node") for m in metrics["nodes"]],
        llm=metrics["llm"],
        summary_triggered=metrics["summary_triggered"],
        review_passed=metrics["review_passed"],
        react=metrics["react"],
        error_count=len(metrics["errors"]),
    ))

    capability = _agent_capability(metrics)
    resolved_order_id = order_id or (result.get("order") or {}).get("order_id") or ""
    turn_id = _persist_turn(user_id, thread_id, resolved_order_id, capability, metrics)
    all_sources = act.format_sources(result.get("retrieved") or [])
    order = result.get("order") or {}
    answer_text = (result.get("answer") or "").lower()
    external_order = ("不在本系统" in answer_text) or ("not in our system" in answer_text)
    merchant_country = ""
    if order.get("origin_address"):
        code, _ = buyer_region(order["origin_address"])
        merchant_country = act.country_name(code)
    if external_order or not merchant_country:
        # 外平台订单但买家在消息里点明了国家/地区：按该地区标注并保留法条来源
        msg_code, _ = buyer_region(result.get("query") or "")
        msg_country = act.country_name(msg_code) if msg_code else ""
        for item in all_sources:
            if msg_country and not item.get("country"):
                item["country"] = msg_country
            elif not msg_country:
                item["country"] = ""
    else:
        # 规则类来源没有地区时，用商家所在地补齐；已有的地区信息保留
        for item in all_sources:
            if not item.get("country"):
                item["country"] = merchant_country

    # 只展示模型声明实际引用的条目；模型未给标记时退回前 3 条
    cited = [t.lstrip("\ufeff") for t in (result.get("cited_titles") or [])]
    explicit = bool(result.get("sources_explicit"))
    if explicit:
        sources = [
            s for s in all_sources
            if s.get("title", "").lstrip("\ufeff") in cited
            or s.get("source", "").lstrip("\ufeff") in cited
        ]
    else:
        sources = all_sources[:3]

    # 外平台订单不补订单来源；其余情况仅当正文确实引用了本单号时才补
    order_cited = (not external_order) and bool(resolved_order_id) and (
        (not explicit) or (resolved_order_id.lower() in answer_text)
    )
    if order and order_cited:
        sources.append({
            "source": "订单信息",
            "title": f"订单 {resolved_order_id}",
            "desc": "状态、物流单号与最新轨迹",
            "country": "",
        })
    # 来源明细也跟随当前界面语言
    sources = _localize_sources(sources, result.get("reply_language") or "")
    return {
        "answer": result.get("answer", ""),
        "memories": result.get("memories", []),
        "citations": result.get("citations", []),
        "summary": result.get("summary", ""),
        "turn": result.get("turn", 0),
        "order": result.get("order", {}),
        "retrieved": result.get("retrieved", []),
        "sources": sources,
        "intent": result.get("intent", ""),
        "review_passed": result.get("review_passed"),
        "review_note": result.get("review_note", ""),
        "tool_calls": [t.get("name", "") for t in trace],
        "tool_trace": trace,
        "capability": capability,
        "turn_id": turn_id,
        "metrics": metrics,
        "network_error": bool(result.get("network_error")),
        "needs_approval": False,
        "hitl": result.get("hitl") or {},
    }


_PENDING_ANSWERS = {
    "zh": "该操作会写入工单并转平台介入，已暂停等待人工确认；确认后再继续。",
    "en": "This action will open a ticket and escalate to platform support. It has been paused for human confirmation and will continue once approved.",
    "ja": "この操作はチケットを作成しプラットフォーム対応にエスカレーションします。人による確認待ちのため一時停止しています。確認後に続行します。",
    "ko": "이 작업은 티켓을 생성하고 플랫폼 지원으로 이관합니다. 담당자 확인 대기 중이며, 확인 후 계속됩니다.",
    "fr": "Cette action créera un ticket et transférera le dossier au support de la plateforme. Elle est en pause dans l'attente d'une confirmation humaine ; elle se poursuivra après validation.",
}


def _pending_answer(lang: str) -> str:
    """待人工确认的提示跟随当前界面语言。"""
    low = (lang or "").strip().lower()
    if "english" in low:
        return _PENDING_ANSWERS["en"]
    if "日本語" in (lang or "") or "japanese" in low:
        return _PENDING_ANSWERS["ja"]
    if "한국" in (lang or "") or "korean" in low:
        return _PENDING_ANSWERS["ko"]
    if "français" in low or "french" in low:
        return _PENDING_ANSWERS["fr"]
    return _PENDING_ANSWERS["zh"]


def _pending_response(thread_id: str, result: dict) -> dict[str, Any]:
    """有待审批动作时的对外响应：不落库、不给最终回答，只返回审批请求。"""
    action = result.get("pending_action") or {}
    approval = {
        "thread_id": thread_id,
        "tool": action.get("tool", ""),
        "order_id": action.get("order_id", ""),
        "case_type": action.get("case_type", ""),
        "priority": action.get("priority", ""),
        "reason": action.get("reason", ""),
    }
    LOGGER.info(json_fields(
        event="turn_pending_approval",
        trace_id=tracing.current_trace_id(),
        thread_id=thread_id,
        tool=approval["tool"],
        order_id=approval["order_id"],
    ))
    return {
        "answer": _pending_answer(result.get("reply_language") or ""),
        "needs_approval": True,
        "approval": approval,
        "memories": result.get("memories") or [],
        "citations": [],
        "summary": result.get("summary", ""),
        "turn": result.get("turn", 0),
        "order": result.get("order", {}),
        "retrieved": result.get("retrieved") or [],
        "intent": result.get("intent", ""),
        "review_passed": None,
        "review_note": "",
        "tool_calls": [t.get("name", "") for t in result.get("tool_trace") or []],
        "tool_trace": result.get("tool_trace") or [],
        "capability": cap.GROUNDED,
        "turn_id": None,
        "metrics": {},
        "network_error": False,
        "hitl": {},
    }


def chat(
    user_id: str,
    message: str,
    order_id: str = "",
    thread_id: str = "",
    extra_context: str = "",
    history: list[dict] | None = None,
    allow_order_lookup: bool = True,
    reply_language: str = "",
) -> dict[str, Any]:
    """执行一次售后对话；接口参数与返回结构保持兼容。"""
    thread_id = thread_id or f"{user_id}:default"
    config = {"configurable": {"thread_id": thread_id}}
    effective_order_id = order_id or _inherited_order_id(message, config)
    payload = _prepare_payload(
        user_id, message, effective_order_id, extra_context, history, allow_order_lookup, reply_language
    )

    started = time.perf_counter()
    with tracing.span(
        "agent.turn",
        user_id=user_id,
        thread_id=thread_id,
        order_id=order_id,
    ) as turn_span:
        with _AGENT_LOCK:
            # 断点为空时，用界面历史补齐上下文。
            if history and not GRAPH.get_state(config).values.get("history"):
                payload["history"] = [m for m in history if m.get("content")]
            result = GRAPH.invoke(payload, config)
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        turn_span.set_attribute("intent", result.get("intent", ""))
        turn_span.set_attribute("react_stop_reason", result.get("react_stop_reason", ""))
        if result.get("pending_action"):
            turn_span.set_attribute("pending_approval", True)
            return _pending_response(thread_id, result)
        return _finalize(user_id, thread_id, order_id, result, total_ms)


def resume(
    thread_id: str,
    approved: bool,
    reviewer: str = "operator",
    note: str = "",
    timeout: float | None = None,
) -> dict[str, Any]:
    """人工审批后恢复被挂起的会话：批准则执行写操作，拒绝则仅记录。

    恢复过程可能包含 LLM 调用，超过时限就返回 failed，避免界面一直停在提交中。
    """
    config = {"configurable": {"thread_id": thread_id}}
    with _AGENT_LOCK:
        snapshot = GRAPH.get_state(config)
    values = dict(snapshot.values or {})
    if not values.get("pending_action"):
        return {
            "answer": "当前会话没有待审批的操作。",
            "needs_approval": False,
            "error": "no_pending_action",
        }

    limit = timeout if timeout is not None else float(
        os.environ.get("SUPPORTPILOT_HITL_TIMEOUT", "120")
    )
    user_id = values.get("user_id", "")
    order_id = values.get("order_id", "")
    started = time.perf_counter()
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            with _AGENT_LOCK:
                box["result"] = GRAPH.invoke(
                    Command(resume={
                        "approved": bool(approved),
                        "reviewer": reviewer,
                        "note": note,
                    }),
                    config,
                )
        except Exception as exc:  # noqa: BLE001 - 需要对所有失败给出确定状态
            box["error"] = exc

    with tracing.span("agent.hitl", thread_id=thread_id, approved=bool(approved)) as span:
        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        worker.join(limit)
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        span.set_attribute("ms", total_ms)
        if worker.is_alive():
            span.set_attribute("status", "timeout")
            LOGGER.warning(json_fields(
                event="hitl_timeout",
                thread_id=thread_id,
                seconds=limit,
            ))
            return {
                "answer": "",
                "needs_approval": False,
                "error": "approval_timeout",
                "hitl": {
                    "status": "failed",
                    "summary": f"审批执行超过 {int(limit)} 秒仍未完成，已停止等待。",
                },
            }
        if "error" in box:
            exc = box["error"]
            span.set_attribute("status", "failed")
            LOGGER.warning(json_fields(
                event="hitl_failed",
                thread_id=thread_id,
                error=type(exc).__name__,
            ))
            return {
                "answer": "",
                "needs_approval": False,
                "error": "approval_failed",
                "hitl": {
                    "status": "failed",
                    "summary": f"审批执行失败：{type(exc).__name__}",
                },
            }
        result = box.get("result") or {}
        span.set_attribute("status", "approved" if approved else "rejected")
    if result.get("pending_action"):
        return _pending_response(thread_id, result)
    return _finalize(user_id, thread_id, order_id, result, total_ms)


def approval_state(thread_id: str) -> dict[str, Any]:
    """读取会话的审批状态；界面提交中断后用它区分“已执行”和“仍待审批”。"""
    config = {"configurable": {"thread_id": thread_id}}
    with _AGENT_LOCK:
        snapshot = GRAPH.get_state(config)
    values = dict(snapshot.values or {})
    return {
        "pending": bool(values.get("pending_action")),
        "hitl": values.get("hitl") or {},
        "answer": values.get("answer") or "",
        "sources": act.format_sources(values.get("retrieved") or []),
    }


def chat_stream(
    user_id: str,
    message: str,
    order_id: str = "",
    thread_id: str = "",
    extra_context: str = "",
    history: list[dict] | None = None,
    allow_order_lookup: bool = True,
    reply_language: str = "",
):
    """按节点流式返回进度，最后返回与 chat() 一致的完整结果。"""
    thread_id = thread_id or f"{user_id}:default"
    config = {"configurable": {"thread_id": thread_id}}
    payload = _prepare_payload(
        user_id, message, order_id, extra_context, history, allow_order_lookup, reply_language
    )
    events: queue.Queue = queue.Queue()

    def worker() -> None:
        started = time.perf_counter()
        accumulated: dict[str, Any] = {}
        try:
            with tracing.span(
                "agent.turn",
                user_id=user_id,
                thread_id=thread_id,
                order_id=order_id,
                stream=True,
            ) as turn_span:
                # 工作线程独占并释放 RLock，避免生成器跨线程 next() 导致锁释放异常。
                with _AGENT_LOCK:
                    if history and not GRAPH.get_state(config).values.get("history"):
                        payload["history"] = [m for m in history if m.get("content")]
                    for chunk in GRAPH.stream(payload, config, stream_mode="updates"):
                        for node, update in (chunk or {}).items():
                            if node == "__interrupt__":
                                continue
                            safe_update = update if isinstance(update, dict) else {}
                            accumulated.update(safe_update)
                            events.put(("node", node, safe_update))
                total_ms = round((time.perf_counter() - started) * 1000, 1)
                # stream_mode="updates" 只汇总节点输出，输入态字段不会回流，
                # 这里补回 reply_language，供来源明细按界面语言翻译
                accumulated.setdefault("reply_language", reply_language)
                turn_span.set_attribute("intent", accumulated.get("intent", ""))
                turn_span.set_attribute("react_stop_reason", accumulated.get("react_stop_reason", ""))
                if accumulated.get("pending_action"):
                    events.put(("final", _pending_response(thread_id, accumulated)))
                else:
                    events.put(("final", _finalize(user_id, thread_id, order_id, accumulated, total_ms)))
        except Exception as exc:  # noqa: BLE001
            events.put(("error", exc))

    threading.Thread(target=worker, daemon=True).start()
    while True:
        kind, *rest = events.get()
        if kind == "error":
            raise rest[0]
        if kind == "final":
            yield ("final", rest[0])
            return
        yield ("node", rest[0], rest[1])


def get_thread_state(thread_id: str) -> dict[str, Any]:
    """读取某个会话的断点状态，用于续聊排查或演示。"""
    with _AGENT_LOCK:
        snapshot = GRAPH.get_state({"configurable": {"thread_id": thread_id}})
    return dict(snapshot.values)


if __name__ == "__main__":
    demo_user = "buyer_demo_001"
    thread_a = "demo-conversation-a"
    thread_b = "demo-conversation-b"

    print("=" * 70)
    print("会话 A · 第 1 轮：咨询订单（新建会话）")
    print("=" * 70)
    r1 = chat(demo_user, "你好，我的订单 ORD-1004 到哪了？", thread_id=thread_a)
    print(r1["answer"][:800])
    print("\n本轮记忆：", r1["memories"])

    print("\n" + "=" * 70)
    print("会话 A · 第 2 轮：买家说明币种偏好（同一 thread_id，断点续聊）")
    print("=" * 70)
    r2 = chat(
        demo_user,
        "我习惯用 USD 结算，以后涉及金额都按 USD 告诉我。",
        thread_id=thread_a,
    )
    print(r2["answer"][:800])
    print("\n写入后的长期记忆：", r2["memories"])

    print("\n" + "=" * 70)
    print("会话 B · 同一客户新开对话（新 thread_id，验证长期记忆跨会话读取）")
    print("=" * 70)
    r3 = chat(demo_user, "我之前说习惯用什么币种结算？金额也按那个币种告诉我。", thread_id=thread_b)
    print(r3["answer"][:800])
    print("\n本轮意图：", r3["intent"], "｜合规审核：", r3["review_passed"])
    print("会话 B 读取到的长期记忆：", r3["memories"])

    assert any("USD" in m for m in r3["memories"]), "新会话未读取到长期记忆"
    print("\nDEMO_PASS：同一客户在全新会话中成功读取长期记忆")
