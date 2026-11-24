"""Agent 观测工具：结构化日志、token 估算、节点埋点辅助。"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from logging.handlers import RotatingFileHandler

try:  # 真实分词优先；依赖缺失或加载失败时退回字符启发式
    import tiktoken
except ImportError:  # pragma: no cover - 可选依赖
    tiktoken = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "logs")

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_ASCII_WORD_RE = re.compile(r"[a-zA-Z]{2,}")
_configured = False

# DeepSeek 未公开官方 tokenizer；cl100k_base 是与其词表规模接近的通用近似。
# 可通过 SUPPORTPILOT_TOKENIZER 指定其他 tiktoken encoding（如 o200k_base）。
_TOKENIZER_NAME = (os.environ.get("SUPPORTPILOT_TOKENIZER") or "cl100k_base").strip()
_ENCODER = None
if tiktoken is not None:
    try:
        _ENCODER = tiktoken.get_encoding(_TOKENIZER_NAME)
    except Exception:  # noqa: BLE001 —— 离线或词表不可用时保留启发式
        _ENCODER = None


def tokenizer_name() -> str:
    """当前 token 估算后端：tiktoken:<encoding> 或 heuristic。"""
    return f"tiktoken:{_TOKENIZER_NAME}" if _ENCODER is not None else "heuristic"


@lru_cache(maxsize=128)
def _encode_len(text: str) -> int:
    # disallowed_special=()：把 <|endoftext|> 等特殊串当普通文本，避免用户输入触发异常
    return len(_ENCODER.encode(text, disallowed_special=()))


def get_logger(level: str = "INFO") -> logging.Logger:
    """返回 Agent 专用 logger；同时输出到控制台与 logs/agent.log。"""
    global _configured
    logger = logging.getLogger("supportpilot.agent")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if _configured:
        return logger

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(LOG_DIR, "agent.log"),
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError:
        # 日志文件不可写时仍保留控制台输出，不影响主链路
        pass

    logger.propagate = False
    _configured = True
    return logger


def estimate_tokens(text: str) -> int:
    """估算 token 数：优先 tiktoken 真实分词，不可用时退回字符启发式。

    tiktoken 不可用（未安装/离线加载词表失败）时，中日韩字符约 1 token/字，
    其他文本约 4 字符/token，偏差通过预算阈值留余量吸收。
    """
    text = text or ""
    if not text:
        return 0
    if _ENCODER is not None:
        try:
            return _encode_len(text)
        except Exception:  # noqa: BLE001 —— 单条文本编码失败不影响整体统计
            pass
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return cjk + (other + 3) // 4


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算一组对话消息的 token，含每条消息的结构开销。"""
    total = 0
    for message in messages or []:
        total += estimate_tokens(str(message.get("content", ""))) + 4
    return total


def preview(value, limit: int = 220) -> str:
    """把任意值压成单行短文本，用于节点输入输出日志。"""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text)
    return text[:limit] + ("…" if len(text) > limit else "")


def json_fields(**fields) -> str:
    """结构化日志字段，便于后续接入 ELK / Loki 等采集。"""
    return json.dumps(fields, ensure_ascii=False, default=str)


def text_terms(text: str) -> set[str]:
    """抽取用于记忆相关性匹配的词项：中文二元组 + 英文单词。"""
    text = (text or "").lower()
    terms: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(run) == 1:
            terms.add(run)
        else:
            terms.update(run[i : i + 2] for i in range(len(run) - 1))
    terms.update(_ASCII_WORD_RE.findall(text))
    return terms
