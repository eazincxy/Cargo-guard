"""轻量链路追踪：本地结构化 span + 可选 OpenTelemetry/OTLP 导出。

默认零额外依赖：每个 span 以 JSON 写入现有 logger，字段包括
trace_id / span_id / parent_span_id / 耗时 / 状态 / 业务属性，可直接被
Loki、ELK 或 `jq` 关联成一次请求的完整调用链。

启用真实 OTLP 导出（需安装 requirements-observability.txt）：
    SUPPORTPILOT_OTEL_ENABLED=true
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
仅打印到控制台调试：
    SUPPORTPILOT_OTEL_ENABLED=true
    SUPPORTPILOT_OTEL_CONSOLE=true

LangSmith 由 LangGraph/LangChain 原生支持，设置 LANGSMITH_TRACING=true
与 LANGSMITH_API_KEY 即可，本模块只做状态展示。
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import secrets
import time
from typing import Any, Callable, Iterator

_TRUE = {"1", "true", "yes", "on"}

_OTEL = False
_TRACER = None
_SPAN_SINK: Callable[[dict], None] | None = None
_STACK: contextvars.ContextVar[tuple] = contextvars.ContextVar("supportpilot_spans", default=())


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in _TRUE


def _new_id(nbytes: int) -> str:
    return secrets.token_hex(nbytes)


def _logger():
    # 延迟导入，避免 tracing 与日志模块互相初始化
    from app.agent_observability import get_logger

    return get_logger()


def setup_tracing(service_name: str = "cargoguard-agent") -> dict[str, Any]:
    """按环境变量初始化 OTel；失败或未开启时保持仅本地 span。"""
    global _OTEL, _TRACER
    if _OTEL or not _env_flag("SUPPORTPILOT_OTEL_ENABLED"):
        return tracing_status()
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        exporter = None
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=endpoint)
        elif _env_flag("SUPPORTPILOT_OTEL_CONSOLE"):
            exporter = ConsoleSpanExporter()
        if exporter is None:
            return tracing_status()

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _TRACER = trace.get_tracer(service_name)
        _OTEL = True
    except Exception as exc:  # noqa: BLE001 —— 追踪失败不影响业务
        _logger().warning(json.dumps(
            {"event": "otel_init_failed", "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        ))
        _OTEL = False
    return tracing_status()


def tracing_status() -> dict[str, Any]:
    return {
        "local_spans": True,
        "otel": _OTEL,
        "otel_enabled": _env_flag("SUPPORTPILOT_OTEL_ENABLED"),
        "langsmith": _env_flag("LANGSMITH_TRACING") or _env_flag("LANGCHAIN_TRACING_V2"),
    }


def set_span_sink(sink: Callable[[dict], None] | None) -> None:
    """测试钩子：span 结束时回调，默认同时写日志。"""
    global _SPAN_SINK
    _SPAN_SINK = sink


def current_trace_id() -> str:
    stack = _STACK.get()
    return stack[-1]["trace_id"] if stack else ""


def current_span_id() -> str:
    stack = _STACK.get()
    return stack[-1]["span_id"] if stack else ""


def _short(value: Any, limit: int = 200) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


class SpanHandle:
    """span 句柄：业务代码可补充属性，结束后统一落日志/上报。"""

    def __init__(self, payload: dict, attributes: dict, otel_span=None):
        self._payload = payload
        self._attributes = attributes
        self._otel_span = otel_span

    def set_attribute(self, key: str, value: Any) -> None:
        self._attributes[key] = _short(value)
        if self._otel_span is not None:
            self._otel_span.set_attribute(key, value if isinstance(value, (int, float, bool)) else str(value))


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[SpanHandle]:
    """创建一个 span：自动继承父级 trace_id，结束时记录耗时与状态。"""
    stack = _STACK.get()
    parent = stack[-1] if stack else None
    trace_id = parent["trace_id"] if parent else _new_id(16)
    span_id = _new_id(8)
    parent_span_id = parent["span_id"] if parent else ""

    started = time.perf_counter()
    otel_cm = None
    otel_span = None
    if _OTEL and _TRACER is not None:
        try:
            otel_cm = _TRACER.start_as_current_span(name)
            otel_span = otel_cm.__enter__()
            ctx = otel_span.get_span_context()
            if ctx and ctx.trace_id:
                # 复用 OTel 的真实 id，保证本地日志与 Jaeger/Tempo 里的链路可对照
                trace_id = f"{ctx.trace_id:032x}"
                span_id = f"{ctx.span_id:016x}"
            for key, value in attributes.items():
                otel_span.set_attribute(key, value if isinstance(value, (int, float, bool)) else str(value))
        except Exception:  # noqa: BLE001
            otel_cm = None

    span_token = _STACK.set(stack + ({"trace_id": trace_id, "span_id": span_id},))

    attrs = {key: _short(value) for key, value in attributes.items()}
    handle = SpanHandle({}, attrs, otel_span)
    status = "ok"
    error = ""
    try:
        yield handle
    except Exception as exc:
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
        if otel_cm is not None:
            try:
                otel_cm.__exit__(type(exc), exc, exc.__traceback__)
            except Exception:  # noqa: BLE001
                pass
        raise
    else:
        if otel_cm is not None:
            try:
                otel_cm.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
    finally:
        _STACK.reset(span_token)
        payload = {
            "event": "span_end",
            "name": name,
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "ms": round((time.perf_counter() - started) * 1000, 1),
            "status": status,
            **({"error": error} if error else {}),
            **attrs,
        }
        try:
            if _SPAN_SINK is not None:
                _SPAN_SINK(payload)
            _logger().info(json.dumps(payload, ensure_ascii=False, default=str))
        except Exception:  # noqa: BLE001 —— 日志失败不影响业务
            pass
