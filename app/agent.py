"""API 兜底模板回复。

仅在 Agent 抛异常时使用。意图定义与主 Agent 共用 app.agent_intents，
避免 API 层再维护一套意图词表；模板只做信息收集与路径指引，不承诺结果。
"""

from __future__ import annotations

from app.agent_intents import (
    CHITCHAT,
    COMPLAINT,
    LOGISTICS,
    PRODUCT,
    REFUND,
    detect_intent,
)

_TEMPLATES = {
    LOGISTICS: (
        "已收到您对订单 {order_id} 的物流咨询。请提供物流单号或签收凭证，"
        "我们会协助您核实物流状态与清关进度。"
    ),
    REFUND: (
        "已收到订单 {order_id} 的退款/退货申请。请准备商品照片、物流单号与订单截图，"
        "我们会协助您向平台提交；最终结果以平台审核为准。"
    ),
    PRODUCT: "已收到您关于商品的咨询。请补充具体型号或使用场景，我会依据商品页与知识库为您说明。",
    COMPLAINT: (
        "已收到您对商家服务的反馈。建议通过平台投诉入口提交，"
        "并保留聊天截图、订单截图与时间线，平台会介入核实。"
    ),
    CHITCHAT: "你好，我是 CargoGuard 售后助手。有订单、物流或退款问题，把订单号发给我就行。",
}

__all__ = ["build_reply", "detect_intent"]


def build_reply(user_text: str, order_info: dict | None = None) -> str:
    """按统一意图返回一段安全、可执行的兜底话术。"""
    order_info = order_info or {}
    intent, _ = detect_intent(user_text)
    order_id = order_info.get("order_id") or "您的订单"
    template = _TEMPLATES.get(intent, _TEMPLATES[PRODUCT])
    return template.format(order_id=order_id)
