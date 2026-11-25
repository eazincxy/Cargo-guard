"""Agent 工具层：function calling schema 与执行器。

设计原则：
- 只读工具（知识库检索 / 订单查询 / 物流查询）可直接执行；
- 写操作（创建升级工单）标记为高风险，必须经人工审批后才会真正落库；
- 订单类工具返回脱敏字段，不含电话、邮箱与完整收货地址，只保留国家/州；
- 任何异常都收敛成 ok=False 的 trace，不向上抛出，保证规划节点不阻断主链路。
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Callable

from app.kb import search as kb_search
from app.llm import buyer_region
from app import tracing

TOP_K = 4
MIN_SCORE = 0.30

# OpenAI function calling 格式；description 写清「何时用」，模型才能正确选工具
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "检索售后知识库：平台规则、退款退货政策、物流时效、关税清关、"
                "商家责任与各国/各州法规。问题涉及规则依据时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索关键词，用中文组合，如「美国 退货 运费 商家责任」",
                    },
                    "country_code": {
                        "type": "string",
                        "description": "可选，买家所在国家两字母代码，如 US、GB；不传则按订单收货地址推断",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_order",
            "description": "按订单号读取订单快照：商品、金额、币种、订单状态、物流状态、收货国家/州。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "订单号，如 ORD-1004；必须来自买家原话或上下文，不得编造",
                    }
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_logistics",
            "description": "按订单号读取物流信息：物流单号、物流状态、最新轨迹、下单时间。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "订单号，如 ORD-1004",
                    }
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_escalation",
            "description": (
                "创建升级工单并转平台介入（写操作，需人工审批后才会生效）。"
                "仅当买家明确要求你代为提交投诉、平台仲裁或工单时使用；"
                "买家只是描述问题或询问怎么处理时不要调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "订单号，如 ORD-1004",
                    },
                    "case_type": {
                        "type": "string",
                        "enum": ["refund", "logistics", "product", "other"],
                        "description": "工单类型：退款纠纷 / 物流异常 / 商品问题 / 其他",
                    },
                    "reason": {
                        "type": "string",
                        "description": "升级原因，一句话陈述客观事实，不超过 100 字，不写主观情绪",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["normal", "high"],
                        "description": "紧急程度，默认 normal；商家失联、临期未处理用 high",
                    },
                },
                "required": ["order_id", "case_type", "reason"],
            },
        },
    },
]

# 高风险写操作：规划阶段只挂起，必须经人工审批后才执行
HIGH_RISK_TOOLS = frozenset({"create_escalation"})
_CASE_TYPES = {"refund", "logistics", "product", "other"}

# 对外可见的订单字段白名单：刻意排除 shipping_address / origin_address 等敏感列
_PUBLIC_ORDER_FIELDS = (
    "order_id", "seller_name", "product_name", "quantity", "unit_price",
    "total_amount", "currency", "shipping_fee", "shipping_status", "status",
    "tracking_number", "logistics_info", "order_time",
)

_LOGISTICS_FIELDS = (
    "order_id", "shipping_status", "tracking_number", "logistics_info", "order_time",
)


def _region(order: dict[str, Any]) -> tuple[str, str]:
    """从收货地址推断国家/州，只返回编码，不返回地址原文。"""
    return buyer_region((order or {}).get("shipping_address") or "")


def _public_order(order: dict[str, Any]) -> dict[str, Any]:
    """订单脱敏：只保留白名单字段 + 国家/州编码。"""
    country, state = _region(order)
    data = {key: order.get(key) for key in _PUBLIC_ORDER_FIELDS if order.get(key) not in (None, "")}
    data["buyer_country"] = country
    data["buyer_state"] = state
    return data


def _public_logistics(order: dict[str, Any]) -> dict[str, Any]:
    country, state = _region(order)
    data = {key: order.get(key) for key in _LOGISTICS_FIELDS if order.get(key) not in (None, "")}
    data["buyer_country"] = country
    data["buyer_state"] = state
    return data


def _resolve_order(args: dict[str, Any], state: dict[str, Any]) -> str:
    """订单号取自工具参数或本轮状态；游客态直接拒绝。"""
    if state.get("disable_order_lookup"):
        raise PermissionError("当前会话不允许读取订单数据")
    order_id = str(args.get("order_id") or state.get("order_id") or "").strip().upper()
    if not order_id:
        raise ValueError("缺少订单号")
    # 会话已绑定订单时，只允许读取该订单，防止模型/用户通过参数枚举他人订单
    scoped = str(state.get("order_id") or "").strip().upper()
    if scoped and order_id != scoped:
        raise PermissionError(f"仅可读取当前会话订单 {scoped}，拒绝访问 {order_id}")
    return order_id


def _load_order(order_id: str, load_order_fn: Callable[[str], dict] | None) -> dict[str, Any]:
    if load_order_fn is None:
        # 延迟导入，避免 agent_tools 与 after_sales_agent 循环依赖
        from app.after_sales_agent import load_order as load_order_fn  # noqa: F401
    order = load_order_fn(order_id) or {}
    if not order:
        raise LookupError(f"未找到订单 {order_id}")
    return order


def _search(args: dict[str, Any], state: dict[str, Any], search_fn) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("检索关键词不能为空")
    order = state.get("order") or {}
    # 买家本轮明确说出的国家优先于订单地址与模型推断，避免沿用上一轮订单的法域
    from app.agent_act import stated_country_iso
    stated = stated_country_iso(state.get("query") or "")
    if stated:
        country, state_code = stated, ""
    else:
        country, state_code = _region(order)
        country = str(args.get("country_code") or country or "")
    hits = search_fn(
        query,
        top_k=TOP_K,
        min_score=MIN_SCORE,
        country_code=country or None,
        state_code=state_code or None,
    ) or []
    return {"query": query, "retrieved": list(hits)}


def _write_work_order(order_id: str, case_type: str, priority: str) -> tuple[int, bool]:
    """写入升级工单，返回 (工单号, 是否新建)。

    同一订单、同一类型已有未关闭工单时直接复用，避免重复升级产生多条工单。
    并发审批同时插入时由部分唯一索引兜底，回查后复用已存在工单。
    测试可替换本函数以避免落库。
    """
    from app.db import get_connection

    normalized_case = case_type.capitalize() if case_type else "Other"
    active_sql = """
        SELECT id FROM work_orders
        WHERE order_id = ? AND case_type = ?
          AND COALESCE(status, 'Open') != 'Closed'
        ORDER BY id DESC LIMIT 1
    """
    conn = get_connection()
    try:
        existing = conn.execute(active_sql, (order_id, normalized_case)).fetchone()
        if existing:
            return int(existing[0]), False
        # 与手动建单接口保持同一套枚举写法（Open / High / Product…），避免前端展示不一致
        try:
            cur = conn.execute(
                """
                INSERT INTO work_orders (order_id, priority, case_type, assignee, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    priority.capitalize() if priority else "Normal",
                    normalized_case,
                    "Platform Review",
                    "Open",
                ),
            )
            conn.commit()
            return int(cur.lastrowid or 0), True
        except sqlite3.IntegrityError:
            # 另一个审批已抢先建单：唯一索引拦下本次插入，直接复用
            conn.rollback()
            row = conn.execute(active_sql, (order_id, normalized_case)).fetchone()
            if row:
                return int(row[0]), False
            raise
    finally:
        conn.close()


def _escalate(args: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """校验并创建升级工单：订单作用域、类型白名单、原因必填且截断。"""
    order_id = _resolve_order(args, state)
    case_type = str(args.get("case_type") or "other").strip().lower()
    if case_type not in _CASE_TYPES:
        case_type = "other"
    priority = "high" if str(args.get("priority") or "").strip().lower() == "high" else "normal"
    reason = str(args.get("reason") or "").strip()[:100]
    if not reason:
        raise ValueError("升级原因不能为空")
    work_order_id, created = _write_work_order(order_id, case_type, priority)
    return {
        "work_order_id": work_order_id,
        "order_id": order_id,
        "case_type": case_type,
        "priority": priority,
        "reason": reason,
        "status": "open",
        "created": created,
    }


def _summarize(name: str, result: dict[str, Any]) -> str:
    if name == "search_knowledge_base":
        hits = result.get("retrieved") or []
        sources = "、".join(
            dict.fromkeys(str(h.get("source") or h.get("title", "")) for h in hits)
        )
        return f"命中 {len(hits)} 条知识库内容" + (f"（{sources}）" if sources else "")
    if name == "lookup_order":
        order = result.get("order") or {}
        amount = order.get("total_amount")
        currency = order.get("currency") or ""
        return (
            f"订单 {order.get('order_id', '')}：状态 {order.get('status') or '未知'}；"
            f"物流 {order.get('shipping_status') or '未知'}；"
            f"金额 {amount if amount not in (None, '') else '未标注'} {currency}".strip()
        )
    if name == "lookup_logistics":
        info = result.get("logistics") or {}
        return (
            f"物流单号 {info.get('tracking_number') or '无'}；"
            f"状态 {info.get('shipping_status') or '未知'}；"
            f"最新信息 {str(info.get('logistics_info') or '无')[:80]}"
        )
    if name == "create_escalation":
        prefix = "已创建升级工单" if result.get("created") else "已存在同订单同类型工单，复用"
        return (
            f"{prefix} #{result.get('work_order_id')}；"
            f"订单 {result.get('order_id')}；类型 {result.get('case_type')}；"
            f"优先级 {result.get('priority')}"
        )
    return ""


def execute_tool(
    name: str,
    args: dict[str, Any],
    state: dict[str, Any],
    *,
    search_fn: Callable | None = None,
    load_order_fn: Callable[[str], dict] | None = None,
) -> dict[str, Any]:
    """执行单个工具，返回可观测的 trace；异常一律转成 ok=False。"""
    started = time.perf_counter()
    entry: dict[str, Any] = {
        "name": name,
        "args": args or {},
        "ok": False,
        "ms": 0.0,
        "summary": "",
        "result": {},
        "error": "",
    }
    try:
        with tracing.span("agent.tool", tool=name) as tool_span:
            if name == "search_knowledge_base":
                result = _search(args or {}, state, search_fn or kb_search)
            elif name == "lookup_order":
                order_id = _resolve_order(args or {}, state)
                result = {"order": _public_order(_load_order(order_id, load_order_fn))}
            elif name == "lookup_logistics":
                order_id = _resolve_order(args or {}, state)
                result = {"logistics": _public_logistics(_load_order(order_id, load_order_fn))}
            elif name == "create_escalation":
                result = _escalate(args or {}, state)
            else:
                raise ValueError(f"未知工具：{name}")
            entry["result"] = result
            entry["ok"] = True
            entry["summary"] = _summarize(name, result)
            tool_span.set_attribute("ok", True)
            tool_span.set_attribute("summary", entry["summary"])
    except Exception as exc:  # noqa: BLE001 —— 工具失败不应中断对话
        entry["error"] = f"{type(exc).__name__}: {exc}"
    entry["ms"] = round((time.perf_counter() - started) * 1000, 1)
    return entry
