"""售后意图识别、分支提示词与差异化合规规则。

意图使用可解释的关键词打分，不额外消耗模型调用；
新增意图时只需补充关键词、提示词与规则即可。
"""

from __future__ import annotations

import re

LOGISTICS = "logistics"
REFUND = "refund"
PRODUCT = "product"
COMPLAINT = "complaint"
CHITCHAT = "chitchat"

INTENT_LABELS = {
    LOGISTICS: "物流查询",
    REFUND: "退款申请",
    PRODUCT: "商品咨询",
    COMPLAINT: "投诉",
    CHITCHAT: "无关闲聊",
}

# 顺序即优先级：投诉 > 退款 > 物流 > 商品
INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    (COMPLAINT, [
        "投诉", "维权", "举报", "商家不理", "商家不回", "不回复", "已读不回", "敷衍", "拖延",
        "拒绝退款", "不给我退", "不退钱", "态度差", "态度恶劣", "跑路", "失联", "关店",
        "platform", "complaint", "report seller",
    ]),
    (REFUND, [
        "退款", "退货", "退钱", "退运费", "申请退", "取消订单", "返金", "返品",
        "refund", "return", "cancel order", "money back",
    ]),
    (LOGISTICS, [
        "物流", "快递", "发货", "签收", "到哪", "几天到", "运输", "清关", "海关", "包裹",
        "单号", "查件", "派送", "停运", "没收到", "未收到", "丢件",
        "tracking", "shipping", "delivery", "parcel", "customs",
    ]),
    (PRODUCT, [
        "商品", "产品", "规格", "尺寸", "尺码", "材质", "颜色", "型号", "参数", "功能",
        "配件", "保修", "真假", "正品", "适用", "说明书",
        "product", "size", "material", "warranty", "spec",
    ]),
]

CHITCHAT_WORDS = [
    "你好", "您好", "在吗", "谢谢", "多谢", "早上好", "晚上好", "再见", "拜拜",
    "hello", "hi", "thanks", "thank you", "bye", "good morning", "good evening",
]

# 各意图追加到主客服提示词后的差异化指令
INTENT_PROMPTS = {
    LOGISTICS: """【本轮意图：物流查询】
- 先核对订单物流状态、物流单号与最新节点，再给结论；
- 若只是查状态/到哪了，直接给结论与关键事实（当前状态、物流单号、最新节点）即可，不要展开步骤；
- 只有出现运输停滞、清关被扣、签收未收到等异常时，才给出对应的查件与举证步骤；
- 只引用订单字段与知识库中的物流规则，不得虚构物流节点或承诺到达日期。""",
    REFUND: """【本轮意图：退款申请】
- 先判定适用规则、责任归属（商家责任 / 买家原因）与退货运费承担方；
- 若只是查退款进度/状态，直接给结论与关键事实即可，不要展开步骤或材料；
- 只有买家要申请退款/退货或报告退款被拒时，才列出可执行步骤与需要准备的举证材料；
- 退款时效、到账时间只能引用知识库；不得承诺“一定可以退款”；信息不足时只追问一个关键问题。""",
    PRODUCT: """【本轮意图：商品咨询】
- 只依据知识库与订单字段说明商品与售后规则；
- 不得虚构商品参数、材质、认证、医疗功效或平台政策；
- 知识库没有覆盖时明确说明，并引导买家以商品页与商家公示为准。""",
    COMPLAINT: """【本轮意图：投诉】
- 先简短回应买家情绪，再给出平台介入 / 商家投诉的可执行路径与材料清单；
- 不评价商家是否违法，不承诺处罚结果或赔偿金额；
- 引导买家本人操作，客服不代发消息、不代提交申诉。""",
    CHITCHAT: """【本轮意图：无关闲聊】
- 简短、友好地回应，不要输出合规声明、免责声明或固定业务结构；
- 如果买家随后提到订单、物流、退款等问题，主动引导其提供订单号。""",
}

# 规则型合规校验：与 review_answer 的模型审核叠加，命中即标记
_FORBIDDEN = {
    REFUND: [
        (r"(一定|保证|百分百|100%)\s*(能|可以)?\s*(退款|退货|退钱)", "退款承诺过于绝对"),
    ],
    COMPLAINT: [
        (r"(一定|肯定|必然).{0,8}(处罚|封店|违法|赔偿)", "对处理结果作出绝对承诺"),
    ],
    PRODUCT: [
        (r"(治疗|治愈|药效|医疗功效|包治)", "涉及医疗功效宣称"),
    ],
    LOGISTICS: [],
    CHITCHAT: [],
}

_EVIDENCE_WORDS = ["凭证", "材料", "照片", "视频", "截图", "单号", "举证", "证明"]
# 只有给出退款行动建议（申请/提交/联系/准备等）时，才要求附带举证材料；
# 纯状态/进度播报（如“退款审核中”）不强制材料，避免把简短状态回复误判为不合规。
_REFUND_ACTION_WORDS = ["申请", "提交", "联系", "提供", "准备", "步骤", "发起", "操作"]

# 否定词窗口：命中点前 12 个字内出现这些词，视为“否定式合规表述”，不判违规
_NEGATIONS = (
    "无法", "不能", "不会", "不敢", "不再", "不保证", "不承诺", "没有", "并非",
    "不存在", "不具备", "不涉及", "不属于", "不构成", "不可",
)


def _violation_hit(pattern: str, text: str) -> bool:
    """命中违规表述；被否定词修饰时跳过，减少规则层误拦。"""
    for match in re.finditer(pattern, text):
        window = text[max(0, match.start() - 12):match.start()]
        if any(neg in window for neg in _NEGATIONS):
            continue
        return True
    return False


def detect_intent(text: str) -> tuple[str, float]:
    """返回 (意图, 置信度)。无明显业务信号时归为商品咨询，低置信度。"""
    low = (text or "").lower().strip()
    if not low:
        return CHITCHAT, 0.4

    best_intent, best_hits = PRODUCT, 0
    for intent, keywords in INTENT_KEYWORDS:
        hits = sum(1 for keyword in keywords if keyword.lower() in low)
        if hits > best_hits:
            best_intent, best_hits = intent, hits

    if best_hits == 0:
        if len(low) <= 30 and any(word in low for word in CHITCHAT_WORDS):
            return CHITCHAT, 0.6
        return PRODUCT, 0.35

    confidence = min(0.98, 0.55 + 0.12 * best_hits)
    return best_intent, round(confidence, 2)


def intent_prompt(intent: str) -> str:
    """返回该意图对应的追加提示词。"""
    return INTENT_PROMPTS.get(intent, INTENT_PROMPTS[PRODUCT])


def intent_rule_issues(answer: str, intent: str) -> list[str]:
    """按意图执行规则型合规校验，返回问题列表（空列表表示通过）。"""
    issues: list[str] = []
    text = answer or ""
    for pattern, note in _FORBIDDEN.get(intent, []):
        if _violation_hit(pattern, text):
            issues.append(note)

    if (
        intent == REFUND
        and "退款" in text
        and any(w in text for w in _REFUND_ACTION_WORDS)
        and not any(w in text for w in _EVIDENCE_WORDS)
    ):
        issues.append("退款回复缺少举证材料")
    return issues
