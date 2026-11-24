"""UI 层动作识别：只保留 Agent 意图体系之外的界面专属判断。

业务意图统一由 app.agent_intents 提供；本模块只判断「是否需要走界面本地汇率计算」，
避免 Streamlit 再维护一套与 Agent 不一致的意图词表。
"""

from __future__ import annotations

import re

# 币种线索 + 汇率相关词：命中任意一个才进入汇率判断，避免无关问句误触发
_CURRENCY_OR_RATE = (
    "汇率", "换算", "兑换", "等于多少", "exchange", "rate", "currency", "convert", "how much",
    "人民币", "美元", "美金", "欧元", "英镑", "日元", "日币", "韩元", "韩币", "泰铢", "澳元", "澳币", "新币",
    "cny", "usd", "eur", "gbp", "jpy", "krw", "aud", "sgd", "thb",
)
# 明确要求换算的表达：只有出现这些词或 A to B 格式，才判定为汇率请求
_RATE_SIGNAL = ("汇率", "换算", "兑换", "等于多少", "exchange", "rate", "convert", "how much")
_RATE_FORMAT_RE = re.compile(r"[a-z]{3}\s*[=≈]\s*[a-z]{3}|[a-z]{3}\s+to\s+[a-z]{3}")


def is_exchange_rate_query(text: str) -> bool:
    """判断是否为汇率换算请求。

    必须同时出现币种/汇率线索与「问汇率」的表达（或 A to B 格式），
    否则「35 美元关税」这类只是提到币种的问句会被误判为汇率查询。
    """
    q = (text or "").lower()
    if not q or not any(k in q for k in _CURRENCY_OR_RATE):
        return False
    if _RATE_FORMAT_RE.search(q):
        return True
    return any(k in q for k in _RATE_SIGNAL)
