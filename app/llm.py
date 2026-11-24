"""模型调用：DeepSeek 负责维权策略，SiliconFlow Qwen3-VL 负责读图。"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_COUNTRY_KEYWORDS = [
    ("中国", "CN"), ("china", "CN"), ("beijing", "CN"), ("shanghai", "CN"),
    ("guangzhou", "CN"), ("shenzhen", "CN"), ("chengdu", "CN"),
    ("美国", "US"), ("usa", "US"), ("u.s.a", "US"), ("new york", "US"),
    ("los angeles", "US"), ("california", "US"),
    ("英国", "GB"), (" uk", "GB"), ("united kingdom", "GB"), ("london", "GB"),
    ("日本", "JP"), ("japan", "JP"), ("tokyo", "JP"),
    ("韩国", "KR"), ("korea", "KR"), ("seoul", "KR"),
    ("法国", "FR"), ("france", "FR"), ("paris", "FR"),
    ("德国", "DE"), ("germany", "DE"), ("berlin", "DE"),
    ("泰国", "TH"), ("thailand", "TH"), ("bangkok", "TH"),
]


def _country_code_from_address(address):
    if not address:
        return ""
    a = address.lower()
    for kw, code in _COUNTRY_KEYWORDS:
        if kw in a:
            return code
    return ""


# 美国州全称 → 两字母代码（小写）
_US_STATES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca",
    "colorado": "co", "connecticut": "ct", "delaware": "de", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia",
    "kansas": "ks", "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms", "missouri": "mo",
    "montana": "mt", "nebraska": "ne", "nevada": "nv", "new hampshire": "nh", "new jersey": "nj",
    "new mexico": "nm", "new york": "ny", "north carolina": "nc", "north dakota": "nd", "ohio": "oh",
    "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa", "rhode island": "ri",
    "south carolina": "sc", "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa", "west virginia": "wv",
    "wisconsin": "wi", "wyoming": "wy", "district of columbia": "dc",
    "washington d.c.": "dc", "washington dc": "dc",
}
# 常见中文州名别名 → 代码
_US_STATE_CN = {
    "加州": "ca", "加利福尼亚": "ca", "纽约州": "ny", "纽约": "ny",
    "德州": "tx", "得州": "tx", "得克萨斯": "tx", "华盛顿州": "wa",
    "佛州": "fl", "佛罗里达": "fl", "伊利诺伊": "il", "宾州": "pa",
    "马萨诸塞": "ma", "麻省": "ma",
}


def _us_state_from_text(text):
    """从地址或用户文本中识别美国州，返回小写两字母代码；识别不到返回空串。"""
    if not text:
        return ""
    # 1) 中文别名（在原文上匹配）
    for cn, code in _US_STATE_CN.items():
        if cn in text:
            return code
    low = text.lower()
    # 2) 州全称（无歧义）
    for name, code in _US_STATES.items():
        if name in low:
            return code
    # 3) 两字母缩写：", ST ZIP" 是美国特有地址格式，直接匹配（已校验为合法州代码，不会误伤 in/or 等常用词）；", ST, USA" 需有美国语境
    m = re.search(r",\s*([A-Z]{2})\s+\d{4,5}", text)  # "..., CA 90001"
    if m and m.group(1).lower() in set(_US_STATES.values()):
        return m.group(1).lower()
    if any(k in low for k in ("usa", "united states", "u.s.", "u.s.a", "美国")):
        m = re.search(r",\s*([A-Z]{2})\s*,?\s*(?:USA|United States)", text, re.I)  # "..., CA, USA"
        if m and m.group(1).lower() in set(_US_STATES.values()):
            return m.group(1).lower()
    return ""

def buyer_region(address):
    """从收货地址推断买家所在国家（两字母）与美国州代码，供 RAG 按属地召回法规。"""
    return _country_code_from_address(address), _us_state_from_text(address)


DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
SILICONFLOW_URL = "https://api.siliconflow.cn/v1/chat/completions"
VISION_MODEL = os.environ.get("VISION_MODEL") or "Qwen/Qwen3-VL-8B-Instruct"
TEXT_MODEL = os.environ.get("TEXT_MODEL") or "deepseek-chat"


def _env(name):
    value = os.environ.get(name)
    if value:
        return value.strip()
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                if key.strip() == name:
                    return val.strip()
    return None


DEEPSEEK_KEY = _env("DEEPSEEK_API_KEY")
SILICONFLOW_KEY = _env("SILICONFLOW_API_KEY")


def has_llm():
    return bool(DEEPSEEK_KEY)


def has_vision():
    return bool(SILICONFLOW_KEY)


_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}

# 传输层熔断：断网时单次 TCP 连接要等约 21 秒，一轮对话若有 4 次模型调用
# 就会卡好几分钟且期间界面毫无反馈。首次连不上后短时间内直接快速失败。
_BREAKER_UNTIL = 0.0
_BREAKER_SECONDS = 20.0


def reset_network_breaker():
    """手动清除熔断状态（网络恢复或需要立即重试时调用）。"""
    global _BREAKER_UNTIL
    _BREAKER_UNTIL = 0.0


def is_network_down() -> bool:
    """当前是否处于传输层熔断中（最近刚发生过连接失败）。"""
    return time.time() < _BREAKER_UNTIL


def _post(url, key, payload, timeout=90, retries=2):
    """POST JSON；网络错误与 408/429/5xx 做指数退避重试，4xx 业务错误直接抛出。

    传输层失败（连不上/超时）不重试并开启短暂熔断，避免一轮对话被多次
    连接超时拖到几分钟：后续调用立即失败，由上层快速降级。
    """
    global _BREAKER_UNTIL
    if is_network_down():
        raise urllib.error.URLError("网络暂不可用（连接熔断中），请稍后重试")

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            # HTTPError 是 URLError 子类，必须先捕获：4xx 属于业务错误，不熔断
            last_error = exc
            if exc.code not in _RETRYABLE_STATUS:
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            _BREAKER_UNTIL = time.time() + _BREAKER_SECONDS
            break  # 连不上时重试同样连不上，直接失败交给上层降级
        if attempt < retries:
            time.sleep(0.8 * (2 ** attempt))
    raise last_error


def _chat(messages, tools=None, timeout=90):
    payload = {
        "model": TEXT_MODEL,
        "messages": messages,
        "temperature": 0.4,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    data = _post(DEEPSEEK_URL, DEEPSEEK_KEY, payload, timeout=timeout)
    return data["choices"][0]["message"]


def chat_completion_detailed(messages, temperature=0.3, timeout=90):
    """通用对话补全，额外返回 token 用量，供 Agent 埋点统计。"""
    if not DEEPSEEK_KEY:
        raise RuntimeError("DeepSeek 未配置")
    payload = {
        "model": TEXT_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    data = _post(DEEPSEEK_URL, DEEPSEEK_KEY, payload, timeout=timeout)
    content = (data["choices"][0]["message"].get("content") or "").strip()
    usage = data.get("usage") or {}
    return {
        "content": content,
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def chat_completion_with_tools(messages, tools, temperature=0.2, timeout=30, tool_choice="auto"):
    """带 function calling 的对话补全：返回模型 message（可能含 tool_calls）与 token 用量。

    与 chat_completion_detailed 的区别：保留完整 message（含 tool_calls），
    由调用方决定执行哪些工具；这里不做任何工具执行。
    """
    if not DEEPSEEK_KEY:
        raise RuntimeError("DeepSeek 未配置")
    payload = {
        "model": TEXT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "tools": tools,
        "tool_choice": tool_choice,
    }
    data = _post(DEEPSEEK_URL, DEEPSEEK_KEY, payload, timeout=timeout)
    message = data["choices"][0]["message"] or {}
    usage = data.get("usage") or {}
    return {
        "message": message,
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


REVIEW_PROMPT = """你是内容校验器，审核即将发给买家的维权回复，检查下面规则，输出审核结果：
检查项：
1. 是否存在没有来源支撑的法规、税费、售后权利描述？
2. 是否和订单详情里标注的包税/包邮/7天无理由规则冲突？
3. 是否做出"保证退款"这类无法兑现承诺？
4. 是否遗漏了对应的跨境风险提示？

重要对齐规则：本系统主提示词要求引用法规时只写法条名称与适用规则、不输出条款序号。因此不得仅因回复未给出条款编号或官方链接就判定为“没有来源支撑”——只要回复表述与已注入的国家/州法规硬约束、检索来源一致，即视为有来源支撑。

输出格式：
【审核通过】或者【审核不通过】
不通过的话列出问题 + 修改建议，不要直接重写全文。

待审核文本：
{agent_answer}

引用来源列表：
{source_list}

订单原始规则：
{order_rule}
"""


def review_answer(agent_answer, source_list, order_rule):
    """审核回复是否合规；返回 (是否通过, 审核意见)。"""
    if not DEEPSEEK_KEY:
        return True, ""

    sources = "\n".join(f"- {s}" for s in source_list) if source_list else "无"
    rules = json.dumps(order_rule, ensure_ascii=False, indent=2) if order_rule else "无"

    prompt = REVIEW_PROMPT.format(
        agent_answer=agent_answer,
        source_list=sources,
        order_rule=rules,
    )

    messages = [{"role": "user", "content": prompt}]
    msg = _chat(messages, timeout=60)
    reply = (msg.get("content") or "").strip()

    passed = "【审核通过】" in reply
    return passed, reply


VISION_PROMPT = (
    "这是跨境电商买家上传的售后素材。请只描述你能确认的事实，不要推测或编造：\n"
    "1) 若是商品照片：商品是什么、外观状态、有无破损/裂痕/污渍/缺件，损伤属于轻微还是严重；\n"
    "2) 若是聊天或订单截图：逐条提取可见文字要点（商家承诺、拒绝理由、模糊话术、自相矛盾处）；\n"
    "3) 若是物流截图：提取物流节点、时间、签收状态；\n"
    "4) 是否出现诱导脱离平台交易、私下转账、加微信/支付宝等风险信号。\n"
    "如果截图含时间信息，请原样提取具体日期时间，不要评价时间是否真实、是否为未来日期或示例数据。\n"
    "看不清就写“无法确认”，不要编造。"
)


def describe_attachment(att):
    """单张图片 → 事实摘要；视频暂不支持，返回提示。"""
    if att.get("kind") != "image":
        return f"[{att.get('name')}] 视频暂不支持自动识别，请截取关键帧后作为图片上传。"
    if not SILICONFLOW_KEY:
        return f"[{att.get('name')}] 视觉识别未配置，无法读取图片内容。"
    mime = att.get("mime") or "image/png"
    b64 = base64.b64encode(att["bytes"]).decode()
    payload = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": VISION_PROMPT},
            ],
        }],
    }
    try:
        data = _post(SILICONFLOW_URL, SILICONFLOW_KEY, payload, timeout=120)
        return f"[{att.get('name')}] " + data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        return f"[{att.get('name')}] 识别失败（HTTP {e.code}）"
    except Exception as e:
        return f"[{att.get('name')}] 识别失败（{type(e).__name__}）"


def describe_attachments(attachments):
    return "\n".join(describe_attachment(a) for a in attachments)
