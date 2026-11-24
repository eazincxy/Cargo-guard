"""Agent 数据动作：订单读取、RAG 检索与长期记忆读写。

这里的 act 只负责读取业务数据、执行检索和持久化用户记忆，不做工具决策或答案生成。
可变配置与外部依赖由入口模块通过 runtime 注入，便于测试并保持降级策略一致。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Any

from langgraph.store.sqlite import SqliteStore

from app.agent_intents import CHITCHAT
from app.agent_observability import json_fields, preview, text_terms
from app.llm import buyer_region
from app.prompt_guard import detect_injection, wrap_untrusted

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_DB_PATH = os.environ.get("SUPPORTPILOT_AGENT_DB") or os.path.join(ROOT, "agent_memory.db")
MEMORY_NAMESPACE = "user_memory"
TOP_K = 4
MIN_SCORE = 0.30
MAX_MEMORY_FACTS = 24
MIN_INJECT_WEIGHT = 0.25  # 衰减后低于该权重的记忆视为陈旧，不再注入


# =========================================================
# 长期记忆存储与治理
# =========================================================
def _open_agent_db() -> sqlite3.Connection:
    """打开 Agent 专用 SQLite 连接；WAL 提升多连接并发读写的稳定性。"""
    # isolation_level=None：交给 LangGraph 自己显式管理事务，避免嵌套事务报错
    conn = sqlite3.connect(
        AGENT_DB_PATH,
        check_same_thread=False,
        timeout=30,
        isolation_level=None,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


_STORE_CONN = _open_agent_db()
LONG_TERM_STORE = SqliteStore(_STORE_CONN)
LONG_TERM_STORE.setup()


def _memory_ns(user_id: str) -> tuple[str, str]:
    return (MEMORY_NAMESPACE, user_id or "anonymous")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _new_record(text: str, source: str = "llm", weight: float = 0.6) -> dict[str, Any]:
    now = _iso(_now())
    return {
        "text": text,
        "weight": weight,
        "created_at": now,
        "last_seen": now,
        "hits": 0,
        "expired": False,
        "source": source,
    }


def _mark_expired(records: list[dict[str, Any]], runtime: Any) -> list[dict[str, Any]]:
    """按最后命中时间标记过期：超过 TTL 且权重偏低的记忆不再注入。"""
    now = _now()
    for record in records:
        last_seen = _parse_iso(record.get("last_seen", "")) or now
        age_days = max(0, (now - last_seen).days)
        weight = float(record.get("weight", 0.6))
        if age_days > runtime.CONFIG.memory_ttl_days and weight < 0.5:
            record["expired"] = True
        if weight * (0.995 ** age_days) < 0.1:
            record["expired"] = True
    return records


def load_memory_records(user_id: str, runtime: Any) -> list[dict[str, Any]]:
    """读取长期记忆明细；兼容旧的 list[str] 存储格式。"""
    item = LONG_TERM_STORE.get(_memory_ns(user_id), "profile")
    if not item:
        return []
    raw = item.value.get("facts", [])
    records: list[dict[str, Any]] = []
    for entry in raw:
        if isinstance(entry, str) and entry.strip():
            records.append(_new_record(entry.strip(), source="legacy"))
        elif isinstance(entry, dict) and entry.get("text"):
            record = _new_record(str(entry["text"]).strip(), source=entry.get("source", "legacy"))
            record.update({
                "weight": float(entry.get("weight", 0.6)),
                "created_at": entry.get("created_at") or record["created_at"],
                "last_seen": entry.get("last_seen") or record["last_seen"],
                "hits": int(entry.get("hits", 0)),
                "expired": bool(entry.get("expired", False)),
            })
            records.append(record)
    return _mark_expired(records, runtime)


def load_user_memory(user_id: str, runtime: Any) -> list[str]:
    """读取某个用户全部未过期的长期记忆（对外兼容接口）。"""
    return [r["text"] for r in runtime.load_memory_records(user_id) if not r.get("expired")]


def _fact_key(fact: str) -> str:
    """归一化后用于去重：忽略大小写、空格与常见标点。"""
    return re.sub(r"[\s：:，,。.！!？?、；;\-]+", "", fact).lower()


def _effective_weight(record: dict[str, Any]) -> float:
    last_seen = _parse_iso(record.get("last_seen", "")) or _now()
    age_days = max(0, (_now() - last_seen).days)
    return float(record.get("weight", 0.6)) * (0.995 ** age_days)


def save_user_memory(user_id: str, facts: list[str], runtime: Any) -> list[str]:
    """合并长期记忆：去重、命中加权、过期标记、数量截断。"""
    records = runtime.load_memory_records(user_id)
    index = {_fact_key(r["text"]): r for r in records}
    now = _iso(_now())

    for fact in facts:
        fact = (fact or "").strip()
        if not fact or len(fact) > 80 or _is_sensitive(fact) or _is_poisoned_memory(fact):
            continue
        key = _fact_key(fact)
        if not key:
            continue
        if key in index:
            record = index[key]
            record["weight"] = min(1.0, float(record.get("weight", 0.6)) + 0.2)
            record["last_seen"] = now
            record["hits"] = int(record.get("hits", 0)) + 1
            record["expired"] = False
        else:
            record = _new_record(fact)
            records.append(record)
            index[key] = record

    _mark_expired(records, runtime)
    # 未过期优先，其次按最近命中时间倒序
    records.sort(key=lambda r: (not r.get("expired", False), r.get("last_seen", "")), reverse=True)
    records = records[:MAX_MEMORY_FACTS]
    LONG_TERM_STORE.put(
        _memory_ns(user_id),
        "profile",
        {"version": 2, "facts": records},
    )
    return [r["text"] for r in records if not r.get("expired")]


_MEMORY_CATEGORY_RULES = [    ("币种", ["币种", "结算", "汇率", "金额", "货币", "currency", "usd", "eur", "jpy", "gbp"]),
    ("语言", ["语言", "回复", "沟通", "language", "english", "中文"]),
    ("国家", ["国家", "地区", "country", "关税", "清关", "海关"]),
    ("称呼", ["称呼", "名字", "name"]),
    ("偏好", ["偏好", "喜欢", "习惯", "prefer"]),
]


def _category_hit(fact_text: str, query: str) -> bool:
    low_query = (query or "").lower()
    for label, keywords in _MEMORY_CATEGORY_RULES:
        if label in fact_text and any(k in low_query for k in keywords):
            return True
    return False


def select_relevant_memories(
    records: list[dict[str, Any]],
    query: str,
    intent: str,
    relax: bool = False,
    *,
    runtime: Any,
) -> list[str]:
    """只挑与当前问题相关的记忆注入 prompt，避免长期记忆变成噪声。"""
    if intent == CHITCHAT:
        return []
    config = runtime.CONFIG
    threshold = max(0.05, config.memory_relevance_min * 0.5) if relax else config.memory_relevance_min
    query_terms = text_terms(query)
    scored: list[tuple[float, str]] = []
    for record in records:
        if record.get("expired"):
            continue
        terms = text_terms(record["text"])
        coverage = len(query_terms & terms) / max(1, len(terms))
        weight = _effective_weight(record)
        # 权重衰减到很低时视为接近过期：即使类别命中也不再注入，避免用陈旧偏好误导回答
        if weight < MIN_INJECT_WEIGHT:
            continue
        boost = 0.2 if _category_hit(record["text"], query) else 0.0
        score = 0.7 * coverage + 0.15 * weight + boost
        if score >= threshold:
            scored.append((round(score, 3), record["text"]))
    scored.sort(reverse=True)
    return [text for _, text in scored[:config.memory_max_injected]]


# =========================================================
# 订单与知识库数据
# =========================================================
_ORDER_FIELDS = (
    "order_id", "seller_name", "product_name", "quantity", "unit_price",
    "total_amount", "currency", "shipping_fee", "shipping_status", "status",
    "tracking_number", "logistics_info", "order_time", "shipping_address",
    "origin_address",
)

_SENSITIVE_RE = re.compile(r"(电话|手机|邮箱|身份证|详细地址|收货地址)|@|\d{7,}")

# 记忆投毒：拒绝“角色冒充 / 指令覆盖 / 权限提升 / 批量导出”类候选记忆。
_MEMORY_POISON_PATTERNS = [
    re.compile(r"(忽略|无视|绕过).{0,12}(指令|规则|提示|限制)", re.I),
    re.compile(r"(系统提示|开发者模式|管理员权限|root\s*权限|超级用户)", re.I),
    re.compile(r"(我是|本人是|你是|用户是).{0,10}(平台|系统|商家)?(管理员|admin|root)", re.I),
    re.compile(r"(以后|今后|从现在起).{0,12}(所有|全部).{0,12}(退款|通过|批准|放行)", re.I),
    re.compile(r"(无需|不用|跳过).{0,6}(审核|核实|验证)", re.I),
    re.compile(r"(导出|发我|给我).{0,10}(电话|手机号|邮箱|身份证|地址|订单列表|全部订单)", re.I),
]


def _is_sensitive(text: str) -> bool:
    """过滤含联系方式、证件号、完整地址的候选记忆。"""
    return bool(_SENSITIVE_RE.search(text or ""))


def _is_poisoned_memory(text: str) -> bool:
    """识别试图污染长期记忆的权限/指令类内容。"""
    return any(pattern.search(text or "") for pattern in _MEMORY_POISON_PATTERNS)


def _extract_order_id(text: str) -> str:
    match = re.search(r"ORD-\d{3,}", text or "", flags=re.I)
    return match.group(0).upper() if match else ""


def load_order(order_id: str, runtime: Any) -> dict[str, Any]:
    """从项目 data.db 读取订单快照；查询失败返回空字典。"""
    if not order_id:
        return {}
    try:
        conn = sqlite3.connect(runtime.DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT {', '.join(_ORDER_FIELDS)} FROM orders WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        return {}
    return dict(row) if row else {}


def _format_money(value: Any, currency: str) -> str:
    if value in (None, ""):
        return "未标注"
    try:
        return f"{float(value):.2f} {currency or '币种未标注'}"
    except (TypeError, ValueError):
        return f"{value} {currency or '币种未标注'}"


def _format_order(order: dict[str, Any]) -> str:
    """把订单整理成模型可读的文本；地址只保留国家/州级，避免敏感信息进入上下文。"""
    if not order:
        return "无（本轮未提供有效订单号）"
    currency = order.get("currency") or ""
    country, state = buyer_region(order.get("shipping_address") or "")
    region = country.upper() if country else "未识别"
    if state:
        region += f"/{state.upper()}"
    lines = [
        f"订单号：{order.get('order_id', '')}",
        f"商家：{order.get('seller_name', '')}",
        f"商品：{order.get('product_name', '')} × {order.get('quantity') or 1}",
        f"商品金额：{_format_money(order.get('unit_price'), currency)}",
        f"订单总额：{_format_money(order.get('total_amount'), currency)}",
        f"运费：{_format_money(order.get('shipping_fee'), currency)}",
        f"订单状态：{order.get('status', '')}；物流状态：{order.get('shipping_status', '')}",
        f"物流单号：{order.get('tracking_number') or '无'}",
        f"物流信息：{order.get('logistics_info') or '无'}",
        f"下单时间：{order.get('order_time') or '未标注'}",
        f"收货国家/地区：{region}",
    ]
    return "\n".join(lines)


def _truncate(text: str, limit: int = 700) -> str:
    """裁掉超长知识库原文，避免单条 chunk 占满上下文。"""
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "……"


def _format_retrieved(retrieved: list[dict], untrusted: bool = False) -> str:
    if not retrieved:
        return "无匹配内容。禁止编造规则，只能说明知识库暂未覆盖。"
    blocks = []
    for i, item in enumerate(retrieved, 1):
        source = item.get("source") or item.get("title", "")
        text = _truncate(item.get("text", ""))
        if untrusted:
            text = wrap_untrusted(text)
        blocks.append(
            f"{i}. [{source}] {item.get('title', '')}（相关度 {item.get('score', 0)}）\n"
            f"   {text}"
        )
    return "\n".join(blocks)


_FOLLOWUP_HINTS = (
    "那", "那么", "这个", "那个", "它", "还有", "然后", "另外",
    "继续", "上面", "刚才", "刚说", "同样", "呢",
)


def _is_followup(query: str) -> bool:
    """判断是否为多轮追问：含指代词或明显过短，需要借助上文才能准确检索。"""
    text = (query or "").strip()
    if not text:
        return False
    return len(text) <= 8 or any(hint in text for hint in _FOLLOWUP_HINTS)


def _previous_user_message(state: dict[str, Any]) -> str:
    """取上一轮买家提问：history 末尾已是本轮问题，因此倒数第二个 user 才是上一轮。"""
    users = [
        str(m.get("content", ""))
        for m in state.get("history", [])
        if m.get("role") == "user" and m.get("content")
    ]
    return users[-2] if len(users) >= 2 else ""


def _build_search_query(state: dict[str, Any]) -> str:
    """把本轮问题、订单关键字段、记忆中的国家/币种拼成检索语句。"""
    query = state.get("query", "")
    parts = [query]
    if _is_followup(query):
        previous = _previous_user_message(state)
        if previous:
            parts.append(previous)
        if state.get("summary"):
            parts.append(state["summary"][:200])
    order = state.get("order") or {}
    for key in ("product_name", "seller_name", "shipping_status"):
        if order.get(key):
            parts.append(str(order[key]))
    for fact in state.get("memories", []):
        if any(k in fact for k in ("国家", "地区", "币种")):
            parts.append(fact)
    if state.get("extra_context"):
        parts.append(state["extra_context"][:200])
    return "；".join(dict.fromkeys(p for p in parts if p))


# =========================================================
# 图数据动作节点
# =========================================================
def load_memory_node(state: dict[str, Any], runtime: Any) -> dict[str, Any]:
    """追加本轮提问、读取并筛选长期记忆、读取订单快照。"""
    query = state.get("query", "")
    if state.get("disable_order_lookup"):
        # 游客态：即使文本里出现订单号也不读取数据库订单
        order_id, order = "", {}
    else:
        # 本轮显式提到的订单号优先；没提到时沿用本会话上一次的订单
        order_id = _extract_order_id(query) or state.get("order_id", "")
        order = runtime.load_order(order_id)
    history = list(state.get("history", [])) + [{"role": "user", "content": query}]

    memories: list[str] = []
    memory_total = 0
    memory_error = ""
    if runtime.CONFIG.enable_long_memory:
        try:
            records = runtime.load_memory_records(state.get("user_id", ""))
            memory_total = sum(1 for r in records if not r.get("expired"))
            memories = runtime.select_relevant_memories(
                records, query, state.get("intent", ""), relax=_is_followup(query)
            )
        except Exception as exc:
            memory_error = f"{type(exc).__name__}: {exc}"
            runtime.LOGGER.warning(json_fields(event="memory_read_failed", error=memory_error))
    else:
        runtime.LOGGER.info(json_fields(event="memory_disabled"))

    runtime.LOGGER.info(json_fields(
        event="memory_loaded",
        memory_total=memory_total,
        injected=len(memories),
        error=memory_error,
    ))
    return {
        "order_id": order_id,
        "order": order,
        "history": history,
        "memories": memories,
        "memory_total": memory_total,
        "memory_injected": len(memories),
        "memory_error": memory_error,
        "turn": sum(1 for m in history if m.get("role") == "user"),
    }


_LAW_COUNTRY_RE = re.compile(r"country:\s*([^\n\r]+)")
_COUNTRY_BY_CODE = {
    "us": "美国", "kr": "韩国", "jp": "日本", "cn": "中国", "fr": "法国",
    "de": "德国", "gb": "英国", "uk": "英国", "th": "泰国", "eu": "欧盟",
}


def country_name(code: str) -> str:
    """两字母地区代码转中文地区名；未知返回空串。"""
    return _COUNTRY_BY_CODE.get((code or "").lower(), "")


def _title_code(title: str) -> str:
    """知识库标题常以“-us/-kr”结尾标注适用地区代码。"""
    tail = title.rsplit("-", 1)[-1].strip().lower() if "-" in title else ""
    return tail if tail in _COUNTRY_BY_CODE else ""


def _strip_title_code(title: str) -> str:
    code = _title_code(title)
    return title[: -len(code) - 1].rstrip() if code else title


_SOURCE_META_PREFIXES = ("law_id:", "rule_id:", "review_status:", "country:", "country_code:", "region:", "title:", "source:")


def _summary_line(text: str, limit: int = 60) -> str:
    """取知识库条目的首句说明，跳过 law_id/country 等元数据行。"""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith(_SOURCE_META_PREFIXES):
            continue
        return line[:limit]
    return ""


def format_sources(retrieved: list[dict]) -> list[dict[str, str]]:
    """把检索结果整理成可展示的来源明细：来源名 + 规则/法案名 + 说明 + 适用国家或地区。"""
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in retrieved or []:
        title = (item.get("title") or "").strip().lstrip("\ufeff")
        source = (item.get("source") or "").strip().lstrip("\ufeff")
        key = (source, title)
        if key in seen:
            continue
        seen.add(key)
        text = item.get("text") or ""
        match = _LAW_COUNTRY_RE.search(text)
        country = match.group(1).strip() if match else ""
        if not country:
            country = _COUNTRY_BY_CODE.get(_title_code(title), "")
        out.append({
            "source": source or title,
            "title": _strip_title_code(title),
            "desc": _summary_line(text),
            "country": country,
        })
    return out


def _retrieval_update(
    state: dict[str, Any],
    retrieved: list[dict],
    query: str,
    started: float,
    runtime: Any,
) -> dict[str, Any]:
    """把召回结果整理成 state 增量：引用列表 + 检索文本注入扫描 + 埋点。"""
    if not retrieved:
        runtime.LOGGER.info(json_fields(event="rag_empty", query=preview(query)))
        return {"retrieved": [], "citations": [], "rag_error": "empty"}

    citations = [item.get("source") or item.get("title", "") for item in retrieved]
    kb_flags = sorted({
        f"kb:{name}"
        for item in retrieved
        for name in detect_injection(item.get("text", ""))
    })
    if kb_flags:
        runtime.LOGGER.warning(json_fields(
            event="kb_injection_suspected",
            flags=kb_flags,
            hits=len(retrieved),
        ))
    merged_flags = list(state.get("injection_flags") or [])
    merged_flags += [flag for flag in kb_flags if flag not in merged_flags]
    runtime.LOGGER.info(json_fields(
        event="rag_done",
        hits=len(retrieved),
        ms=round((time.perf_counter() - started) * 1000, 1),
    ))
    return {
        "retrieved": retrieved,
        "citations": citations,
        "rag_error": "",
        "injection_flags": merged_flags,
    }


def retrieve_node(state: dict[str, Any], runtime: Any) -> dict[str, Any]:
    """RAG 检索：带超时降级，按买家收货国/州优先召回属地法规。"""
    started = time.perf_counter()
    existing = state.get("retrieved") or []
    if existing:
        runtime.LOGGER.info(json_fields(event="rag_reused_from_plan", hits=len(existing)))
        return _retrieval_update(
            state,
            existing,
            (state.get("plan") or {}).get("search_query", ""),
            started,
            runtime,
        )

    plan = state.get("plan") or {}
    order = state.get("order") or {}
    country, state_code = buyer_region(order.get("shipping_address") or "")
    # 用户本轮明确说出的国家优先级最高：避免上一轮订单把法域带偏（如订单在韩国、买家说在美国）
    stated = stated_country_iso(state.get("query") or "")
    if stated:
        country, state_code = stated, ""
    elif plan.get("country_code"):
        country = str(plan["country_code"]).upper()
    query = plan.get("search_query") or _build_search_query(state)

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(
            runtime.kb_search,
            query,
            top_k=TOP_K,
            min_score=MIN_SCORE,
            country_code=country or None,
            state_code=state_code or None,
        )
        retrieved = future.result(timeout=runtime.CONFIG.rag_timeout_seconds)
    except FutureTimeout:
        runtime.LOGGER.warning(json_fields(
            event="rag_timeout",
            seconds=runtime.CONFIG.rag_timeout_seconds,
            query=preview(query),
        ))
        return {"retrieved": [], "citations": [], "rag_error": "timeout"}
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        runtime.LOGGER.error(json_fields(event="rag_failed", error=message))
        return {
            "retrieved": [],
            "citations": [],
            "rag_error": message,
            "errors": runtime._append_error(state, "retrieve", message),
        }
    finally:
        # 超时后不再等待卡住的检索线程
        pool.shutdown(wait=False, cancel_futures=True)

    return _retrieval_update(state, retrieved, query, started, runtime)


# =========================================================
# 长期记忆提取与写入动作
# =========================================================
MEMORY_EXTRACTION_PROMPT = """你是跨境电商售后系统的「用户长期记忆提取器」。
任务：从本轮对话中提取买家稳定、可跨会话复用的事实，供下次对话直接使用。

可以提取（必须有明确依据，不能推测）：
- 常用币种或结算币种；
- 所在国家/地区、沟通语言；
- 商品或品类偏好、尺码/型号偏好；
- 售后沟通偏好（例如希望先联系商家、希望平台介入）；
- 买家主动告知的称呼。

禁止提取：
- 一次性问题、临时情绪、订单当前的物流状态；
- 完整收货地址、电话、邮箱、证件号等敏感信息；
- 任何没有明确依据的推断。

输出要求：严格输出 JSON，不要 Markdown、不要解释，格式如下：
{"memories": ["偏好币种：USD", "所在国家：美国"]}
没有可提取内容时输出：{"memories": []}
每条记忆不超过 40 个字。"""

_CURRENCY_RE = re.compile(
    r"(?:习惯|以后|今后|都用|统一|按|用)[^。；，,]{0,6}(USD|EUR|JPY|KRW|CNY|GBP|THB|RMB|AUD|CAD)",
    re.I,
)
_CURRENCY_NAMES = {
    "RMB": "CNY",
    "USD": "USD", "EUR": "EUR", "JPY": "JPY", "KRW": "KRW",
    "CNY": "CNY", "GBP": "GBP", "THB": "THB", "AUD": "AUD", "CAD": "CAD",
}
_COUNTRY_HINTS = {
    "中国": "中国", "china": "中国",
    "美国": "美国", "usa": "美国", "united states": "美国",
    "英国": "英国", "uk": "英国", "united kingdom": "英国",
    "日本": "日本", "japan": "日本",
    "韩国": "韩国", "korea": "韩国",
    "法国": "法国", "france": "法国",
    "德国": "德国", "germany": "德国",
    "泰国": "泰国", "thailand": "泰国",
}

_COUNTRY_ISO = {
    "中国": "CN", "china": "CN",
    "美国": "US", "usa": "US", "united states": "US",
    "英国": "GB", "uk": "GB", "united kingdom": "GB",
    "日本": "JP", "japan": "JP",
    "韩国": "KR", "korea": "KR",
    "法国": "FR", "france": "FR",
    "德国": "DE", "germany": "DE",
    "泰国": "TH", "thailand": "TH",
}

_US_STATE_HINTS = (
    "加州", "加利福尼亚", "纽约", "德州", "德克萨斯", "佛罗里达", "华盛顿州",
    "伊利诺伊", "宾夕法尼亚", "俄亥俄", "佐治亚", "马萨诸塞", "新泽西",
    "california", "new york", "texas", "florida", "illinois", "ohio", "georgia",
)


def stated_country_iso(query: str) -> str:
    """用户本轮明确说出的国家（ISO 码）：优先级高于订单地址与长期记忆。"""
    low = (query or "").lower()
    for hint, code in _COUNTRY_ISO.items():
        if hint in low:
            return code
    return ""


def mentions_us_state(query: str) -> bool:
    low = (query or "").lower()
    return any(hint in low for hint in _US_STATE_HINTS)

_LANGUAGE_RE = re.compile(
    r"(?:用|以|说|回复|讲)[^。；，,]{0,4}(中文|英文|英语|日语|韩语|法语|English|Japanese|Korean|French)",
    re.I,
)
_LANGUAGE_NAMES = {
    "中文": "中文", "英文": "英文", "英语": "英文",
    "日语": "日语", "韩语": "韩语", "法语": "法语",
    "english": "英文", "japanese": "日语", "korean": "韩语", "french": "法语",
}
_NAME_RE = re.compile(r"(?:我叫|我的名字是|my name is)\s*([A-Za-z\u4e00-\u9fff]{2,20})", re.I)


def _rule_extract(query: str) -> list[str]:
    """规则兜底：只在用户明确表达偏好时提取，避免误记一次性信息。"""
    facts: list[str] = []
    text = query or ""

    match = _CURRENCY_RE.search(text)
    if match:
        facts.append(f"偏好币种：{_CURRENCY_NAMES.get(match.group(1).upper(), match.group(1).upper())}")

    low = text.lower()
    for hint, country in _COUNTRY_HINTS.items():
        if hint in low:
            facts.append(f"所在国家/地区：{country}")
            break

    match = _LANGUAGE_RE.search(text)
    if match:
        facts.append(f"沟通语言：{_LANGUAGE_NAMES.get(match.group(1).lower(), match.group(1))}")

    match = _NAME_RE.search(text)
    if match:
        facts.append(f"称呼：{match.group(1)}")

    return facts


def _parse_memories(raw: str) -> list[str]:
    """解析模型返回的 JSON；解析失败返回空列表。"""
    if not raw:
        return []
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    items = data.get("memories", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if isinstance(item, str):
            item = item.strip()
            if 0 < len(item) <= 80:
                out.append(item)
    return out


def extract_memory_node(state: dict[str, Any], runtime: Any) -> dict[str, Any]:
    """本轮结束后提取长期记忆并写回 SQLite；失败时保留原记忆继续会话。"""
    query = state.get("query", "")
    answer = state.get("answer", "")
    history = list(state.get("history", []))
    if answer:
        history.append({"role": "assistant", "content": answer})

    if not runtime.CONFIG.enable_long_memory:
        runtime.LOGGER.info(json_fields(event="memory_write_skipped"))
        return {"history": history, "memories": []}

    new_facts = _rule_extract(query)
    usage: dict[str, int] | None = None
    errors = list(state.get("errors") or [])
    if runtime.has_llm():
        try:
            raw, usage = runtime._call_llm(
                [
                    {"role": "system", "content": MEMORY_EXTRACTION_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "【已有长期记忆】\n"
                            + ("\n".join(f"- {m}" for m in state.get("memories", [])) or "无")
                            # 只给买家本人的原话，避免模型从客服回答里反推用户信息
                            + f"\n\n【本轮买家发言】\n{query}"
                        ),
                    },
                ],
                temperature=0.1,
                timeout=60,
                purpose="memory_extract",
            )
            new_facts += _parse_memories(raw)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            runtime.LOGGER.warning(json_fields(event="memory_extract_failed", error=message))
            errors.append({"node": "extract_memory", "error": message})

    try:
        merged = runtime.save_user_memory(state.get("user_id", ""), new_facts)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        runtime.LOGGER.error(json_fields(event="memory_write_failed", error=message))
        errors.append({"node": "extract_memory", "error": message})
        merged = list(state.get("memories") or [])

    update: dict[str, Any] = {
        "history": history,
        "memories": merged,
        "memory_total": len(merged),
        "errors": errors,
    }
    if usage:
        update["llm_usage"] = runtime._accumulate_usage(state, usage)
    return update
