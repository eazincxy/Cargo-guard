"""SupportPilot Agent 运行配置。

全部通过环境变量（或项目根目录 .env）覆盖，多环境切换不需要改代码。

可用配置项：
    SUPPORTPILOT_REVIEW_MODE         soft | hard | off，默认 soft
    SUPPORTPILOT_ENABLE_LONG_MEMORY  true | false，默认 true
    SUPPORTPILOT_ENABLE_SUMMARY      true | false，默认 true
    SUPPORTPILOT_CONTEXT_TOKEN_BUDGET  上下文 token 预算，默认 3200
    SUPPORTPILOT_SUMMARY_TARGET_RATIO  压缩后目标占比，默认 0.7
    SUPPORTPILOT_RAG_TIMEOUT         RAG 检索超时秒数，默认 8
    SUPPORTPILOT_MEMORY_TTL_DAYS     记忆过期天数，默认 90
    SUPPORTPILOT_MEMORY_RELEVANCE_MIN  记忆相关度阈值，默认 0.15
    SUPPORTPILOT_MEMORY_MAX_INJECTED   单轮最多注入的记忆条数，默认 6
    SUPPORTPILOT_MAX_TOOL_STEPS      ReAct 工具循环最大轮数，默认 3
    SUPPORTPILOT_LOG_LEVEL           日志级别，默认 INFO
    SUPPORTPILOT_AGENT_DB            Agent SQLite 路径（由 agent 模块读取）
"""

from __future__ import annotations

import os
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_PATH = os.path.join(ROOT, ".env")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _raw(name: str) -> str | None:
    """优先读进程环境变量，其次读 .env；与 app.llm 的读取方式保持一致。"""
    value = os.environ.get(name)
    if value:
        return value.strip()
    if os.path.exists(_ENV_PATH):
        try:
            with open(_ENV_PATH, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    if key.strip() == name:
                        return val.strip()
        except OSError:
            return None
    return None


def _str(name: str, default: str) -> str:
    raw = _raw(name)
    return raw if raw else default


def _bool(name: str, default: bool) -> bool:
    raw = _raw(name)
    if raw is None:
        return default
    low = raw.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    return default


def _int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(_raw(name) or default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _float(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(_raw(name) or default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


@dataclass(frozen=True)
class AgentConfig:
    """一次进程生命周期内使用的 Agent 配置。"""

    review_mode: str = "soft"
    enable_long_memory: bool = True
    enable_summary: bool = True
    context_token_budget: int = 3200
    summary_target_ratio: float = 0.7
    rag_timeout_seconds: float = 8.0
    memory_ttl_days: int = 90
    memory_relevance_min: float = 0.15
    memory_max_injected: int = 6
    max_tool_steps: int = 3
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "AgentConfig":
        mode = _str("SUPPORTPILOT_REVIEW_MODE", "soft").lower()
        if mode not in {"soft", "hard", "off"}:
            mode = "soft"
        return cls(
            review_mode=mode,
            enable_long_memory=_bool("SUPPORTPILOT_ENABLE_LONG_MEMORY", True),
            enable_summary=_bool("SUPPORTPILOT_ENABLE_SUMMARY", True),
            context_token_budget=_int("SUPPORTPILOT_CONTEXT_TOKEN_BUDGET", 3200, 300, 64000),
            summary_target_ratio=_float("SUPPORTPILOT_SUMMARY_TARGET_RATIO", 0.7, 0.2, 0.95),
            rag_timeout_seconds=_float("SUPPORTPILOT_RAG_TIMEOUT", 8.0, 0.5, 120.0),
            memory_ttl_days=_int("SUPPORTPILOT_MEMORY_TTL_DAYS", 90, 1, 3650),
            memory_relevance_min=_float("SUPPORTPILOT_MEMORY_RELEVANCE_MIN", 0.15, 0.0, 1.0),
            memory_max_injected=_int("SUPPORTPILOT_MEMORY_MAX_INJECTED", 6, 0, 50),
            max_tool_steps=_int("SUPPORTPILOT_MAX_TOOL_STEPS", 3, 1, 8),
            log_level=_str("SUPPORTPILOT_LOG_LEVEL", "INFO").upper(),
        )


# 模块级单例；测试可用 dataclasses.replace 后重新赋值给 agent.CONFIG
CONFIG = AgentConfig.from_env()
