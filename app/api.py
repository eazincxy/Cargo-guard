import json
import os
import threading
import time
from collections import deque

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from app import capability as cap
from app.agent import build_reply, detect_intent
from app.after_sales_agent import chat as after_sales_chat
from app.after_sales_agent import chat_stream as after_sales_chat_stream
from app.after_sales_agent import resume as resume_after_sales
from app.agent_observability import get_logger, json_fields, tokenizer_name
from app.tracing import tracing_status
from app.db import get_connection
from app.llm import buyer_region, has_llm

app = FastAPI(title="CargoGuard API")
LOGGER = get_logger()

# 跨域：生产用 CORS_ALLOW_ORIGINS 指定白名单（逗号分隔），默认 * 便于本地调试。
_CORS_ORIGINS = [
    o.strip() for o in (os.environ.get("CORS_ALLOW_ORIGINS") or "*").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

# ---------------------------------------------------------
# 访问控制：API Key + 每分钟限流
# API_KEY 未配置时视为开发模式（放行），生产务必设置。
# RATE_LIMIT_PER_MINUTE <= 0 表示关闭限流。
# ---------------------------------------------------------
API_KEY = (os.environ.get("API_KEY") or "").strip()
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE") or 60)

_rate_buckets: dict[str, deque] = {}
_rate_lock = threading.Lock()


def _client_key(request: Request, api_key: str | None) -> str:
    if api_key:
        return f"key:{api_key}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


def guard(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """认证 + 限流的统一依赖。"""
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    if RATE_LIMIT_PER_MINUTE <= 0:
        return
    key = _client_key(request, x_api_key)
    now = time.time()
    with _rate_lock:
        # 定期清理过期键，避免限流表随 IP/Key 无限增长
        if len(_rate_buckets) > 1024:
            stale = [k for k, b in _rate_buckets.items() if not b or now - b[-1] >= 60]
            for k in stale:
                _rate_buckets.pop(k, None)
        bucket = _rate_buckets.setdefault(key, deque())
        while bucket and now - bucket[0] >= 60:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_PER_MINUTE:
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        bucket.append(now)


# ---------------------------------------------------------
# 进程内指标聚合：供 /metrics 暴露轮次、降级、工具与延迟
# 轻量实现，不引入 Prometheus 依赖；重启后清零。
# ---------------------------------------------------------
_metric_lock = threading.Lock()
_metrics = {
    "turns": 0,
    "errors": 0,
    "llm_turns": 0,
    "fallback_turns": 0,
    "review_failed": 0,
    "tool_calls": 0,
    "tool_failures": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "react_stop_reasons": {},
    "latency_ms": deque(maxlen=500),
}


def _record_metrics(result: dict) -> None:
    """把一轮 Agent 结果累加进进程指标；任何异常都不影响主流程。"""
    try:
        metrics = (result or {}).get("metrics") or {}
        llm = metrics.get("llm") or {}
        tools = metrics.get("tool_calls") or []
        react = metrics.get("react") or {}
        with _metric_lock:
            _metrics["turns"] += 1
            _metrics["errors"] += len(metrics.get("errors") or [])
            if (metrics.get("llm") or {}).get("calls"):
                _metrics["llm_turns"] += 1
            capability = (result or {}).get("capability")
            if capability and capability != cap.LLM:
                _metrics["fallback_turns"] += 1
            if metrics.get("review_passed") is False:
                _metrics["review_failed"] += 1
            _metrics["tool_calls"] += len(tools)
            _metrics["tool_failures"] += sum(1 for t in tools if not t.get("ok"))
            _metrics["prompt_tokens"] += int(llm.get("prompt_tokens") or 0)
            _metrics["completion_tokens"] += int(llm.get("completion_tokens") or 0)
            _metrics["total_tokens"] += int(llm.get("total_tokens") or 0)
            reason = react.get("stop_reason") or "unknown"
            buckets = _metrics["react_stop_reasons"]
            buckets[reason] = buckets.get(reason, 0) + 1
            _metrics["latency_ms"].append(float(metrics.get("total_ms") or 0))
    except Exception as exc:  # noqa: BLE001 —— 指标失败不影响业务
        LOGGER.warning(json_fields(event="metrics_record_failed", error=str(exc)))


class ChatRequest(BaseModel):
    order_id: str
    message: str
    lang: str = "中文"
    # 多轮上下文：[{"role":"user"/"assistant","content":"..."}]
    history: List[Dict[str, Any]] = Field(default_factory=list)
    # 附件视觉识别结果（可选，由调用方预先调用视觉能力得到）
    vision_notes: Optional[str] = None
    # 可选：显式指定用户/会话。不传则按订单号派生，使同一订单的 API 对话具备跨请求持久化记忆。
    user_id: str | None = None
    thread_id: str | None = None


class ApprovalRequest(BaseModel):
    """高风险动作的人工审批结论。"""

    thread_id: str
    approved: bool
    reviewer: str = "operator"
    note: str = ""


def _require_order(order_id: str) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return dict(row)


@app.get("/health")
def health():
    """探活接口：供负载均衡、容器编排与监控使用。"""
    return {"status": "ok", "llm": has_llm()}


@app.get("/metrics")
def metrics_snapshot():
    """轻量运行指标：轮次、降级、工具调用、token 成本与延迟分位。"""
    with _metric_lock:
        latency = sorted(_metrics["latency_ms"])
        sample = len(latency)
        p50 = latency[int(sample * 0.5)] if sample else 0.0
        p95 = latency[min(sample - 1, int(sample * 0.95))] if sample else 0.0
        snapshot = {
            key: value
            for key, value in _metrics.items()
            if key not in {"latency_ms", "react_stop_reasons"}
        }
        snapshot["react_stop_reasons"] = dict(_metrics["react_stop_reasons"])
        snapshot["tokenizer"] = tokenizer_name()
        snapshot["tracing"] = tracing_status()
        snapshot["latency_ms"] = {
            "p50": round(p50, 1),
            "p95": round(p95, 1),
            "samples": sample,
        }
    return snapshot


@app.get("/orders")
def get_orders(_: None = Depends(guard)):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM orders ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/orders/{order_id}")
def get_order(order_id: str, _: None = Depends(guard)):
    return _require_order(order_id)


def _capability_from(result: dict) -> str:
    errors = (result.get("metrics") or {}).get("errors") or []
    return cap.LLM_FALLBACK if any(e.get("node") == "answer" for e in errors) else cap.LLM


def _country_state(order: dict) -> tuple[str, str]:
    return buyer_region((order or {}).get("shipping_address") or "")


def _response_from_result(req: ChatRequest, order: dict, result: dict) -> dict | None:
    """把 Agent 结果映射为 API 响应；无回答时返回 None（交给兜底）。"""
    if result.get("needs_approval"):
        # 高风险动作被挂起：返回审批请求，不落会话记录
        return {
            "order_id": req.order_id,
            "reply": result.get("answer") or "",
            "intent": result.get("intent") or "",
            "capability": cap.GROUNDED,
            "review_passed": None,
            "review_note": "pending_approval",
            "buyer_country": "",
            "buyer_state": "",
            "sources": [],
            "tool_calls": result.get("tool_calls") or [],
            "needs_approval": True,
            "approval": result.get("approval") or {},
            "status": "pending_approval",
        }
    reply = result.get("answer") or ""
    if not reply:
        return None
    order_meta = result.get("order") or {}
    country, state_code = _country_state(order_meta or order)
    return {
        "order_id": req.order_id,
        "reply": reply,
        "intent": result.get("intent") or "",
        "capability": result.get("capability") or _capability_from(result),
        "review_passed": result.get("review_passed"),
        "review_note": result.get("review_note") or "",
        "buyer_country": country or "",
        "buyer_state": state_code or "",
        "sources": result.get("citations") or [],
        "tool_calls": result.get("tool_calls") or [],
        # 内部字段：用于关联 agent_turns，不对外返回
        "turn_id": result.get("turn_id"),
        "status": "processed",
    }


def _fallback_response(req: ChatRequest, order: dict) -> dict:
    country, state_code = _country_state(order)
    return {
        "order_id": req.order_id,
        "reply": build_reply(req.message, order),
        "intent": detect_intent(req.message),
        "capability": cap.TEMPLATE,
        "review_passed": None,
        "review_note": "",
        "buyer_country": country or "",
        "buyer_state": state_code or "",
        "sources": [],
        "tool_calls": [],
        "status": "processed",
    }


def _persist_conversation(req: ChatRequest, resp: dict) -> int:
    conn = get_connection()
    try:
        cur = conn.execute("""
            INSERT INTO conversations
                (order_id, user_message, agent_response, retrieved_sources,
                 review_passed, review_note, buyer_country, buyer_state, capability)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            req.order_id, req.message, resp["reply"],
            json.dumps(resp["sources"], ensure_ascii=False),
            1 if resp["review_passed"] is True else (0 if resp["review_passed"] is False else None),
            resp.get("review_note") or "",
            resp["buyer_country"],
            resp["buyer_state"],
            resp["capability"],
        ))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _link_turn(turn_id: int | None, conversation_id: int | None) -> None:
    """把 agent_turns 行关联到 conversations 行，便于用统一视图查询。失败忽略。"""
    if not turn_id or not conversation_id:
        return
    try:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE agent_turns SET conversation_id = ? WHERE id = ?",
                (conversation_id, turn_id),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _save_conversation(req: ChatRequest, resp: dict) -> None:
    turn_id = resp.pop("turn_id", None)
    conversation_id = _persist_conversation(req, resp)
    _link_turn(turn_id, conversation_id)


def _process_chat(req: ChatRequest) -> dict:
    """同步核心逻辑：供 /chat 在线程池中调用，避免阻塞事件循环。"""
    order = _require_order(req.order_id)
    user_id = req.user_id or f"api_buyer_{req.order_id}"
    thread_id = req.thread_id or f"api:{req.order_id}"

    resp = None
    try:
        # 不按 has_llm() 短路：无密钥时 Agent 也会给出基于订单与知识库的摘录回答，
        # 比 API 层模板更有信息量，且能力来源统一由 Agent 的 capability 字段给出。
        result = after_sales_chat(
            user_id=user_id,
            message=req.message,
            order_id=req.order_id,
            thread_id=thread_id,
            extra_context=req.vision_notes or "",
            history=req.history or [],
            allow_order_lookup=True,
        )
        resp = _response_from_result(req, order, result)
        _record_metrics(result)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(json_fields(
            event="chat_failed",
            order_id=req.order_id,
            error=f"{type(exc).__name__}: {exc}",
        ))

    if resp is None:
        resp = _fallback_response(req, order)

    # 待审批的动作不写会话记录，等在 /approval 恢复后再落库
    if resp.get("status") == "pending_approval":
        return resp

    _save_conversation(req, resp)
    return resp


@app.post("/chat")
async def chat(req: ChatRequest, _: None = Depends(guard)):
    # async + 线程池：Agent 内部是同步阻塞调用，放到 worker 线程，避免占住事件循环。
    return await run_in_threadpool(_process_chat, req)


@app.post("/approval")
async def approval(req: ApprovalRequest, _: None = Depends(guard)):
    """人工审批高风险动作：批准则恢复被挂起的会话并执行写操作。"""
    result = await run_in_threadpool(
        resume_after_sales, req.thread_id, req.approved, req.reviewer, req.note
    )
    if result.get("error") == "no_pending_action":
        raise HTTPException(status_code=404, detail="no pending action for this thread")
    _record_metrics(result)
    return {
        "thread_id": req.thread_id,
        "approved": bool(req.approved),
        "needs_approval": bool(result.get("needs_approval")),
        "reply": result.get("answer") or "",
        "hitl": result.get("hitl") or {},
        "tool_calls": result.get("tool_calls") or [],
        "review_passed": result.get("review_passed"),
    }


def _sse(event: str, payload: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/chat/stream")
def chat_stream(req: ChatRequest, _: None = Depends(guard)):
    """SSE 流式：start → stage(逐节点) → delta(答案分块) → done(完整响应)。

    阶段事件反映真实工作流进度（intent/retrieve/answer/review…），
    答案正文按块下发以便前端渐进渲染。
    """
    order = _require_order(req.order_id)
    user_id = req.user_id or f"api_buyer_{req.order_id}"
    thread_id = req.thread_id or f"api:{req.order_id}"

    def gen():
        yield _sse("start", {"order_id": req.order_id})
        final = None
        try:
            for item in after_sales_chat_stream(
                user_id=user_id,
                message=req.message,
                order_id=req.order_id,
                thread_id=thread_id,
                extra_context=req.vision_notes or "",
                history=req.history or [],
                allow_order_lookup=True,
            ):
                if item[0] == "node":
                    yield _sse("stage", {"node": item[1], "status": "done"})
                else:
                    final = item[1]
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(json_fields(
                event="chat_stream_failed",
                order_id=req.order_id,
                error=f"{type(exc).__name__}: {exc}",
            ))
            yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})

        resp = _response_from_result(req, order, final) if final else None
        if final:
            _record_metrics(final)
        if resp is None:
            resp = _fallback_response(req, order)
        _save_conversation(req, resp)

        reply = resp["reply"]
        for i in range(0, len(reply), 60):
            yield _sse("delta", {"text": reply[i:i + 60]})
        yield _sse("done", resp)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.get("/work-orders")
def get_work_orders(_: None = Depends(guard)):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM work_orders ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/work-orders")
def create_work_order(
    order_id: str,
    priority: str = "Medium",
    case_type: str = "General",
    assignee: str = "Support AI",
    _: None = Depends(guard),
):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO work_orders (order_id, priority, case_type, assignee, status)
            VALUES (?, ?, ?, ?, ?)
        """, (order_id, priority, case_type, assignee, "Open"))
        conn.commit()
    finally:
        conn.close()
    return {"status": "created"}
