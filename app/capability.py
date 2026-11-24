"""回复产能来源（capability）的唯一枚举定义。

Agent 层与 API 层共用同一套取值，避免"名字相近、含义不同"：
- LLM：模型正常生成；
- LLM_FALLBACK：模型调用失败，降级为知识库/订单摘录；
- GROUNDED：未配置模型，仅拼装订单与知识库原文；
- TEMPLATE：Agent 不可用，API 层关键词模板兜底。
"""

LLM = "llm"
LLM_FALLBACK = "llm_fallback"
GROUNDED = "grounded"
TEMPLATE = "template"

ALL = (LLM, LLM_FALLBACK, GROUNDED, TEMPLATE)
