"""离线评测：长期记忆命中率 + 摘要压缩保真度。

两类指标都不调用模型、不访问网络，可直接作为 CI 门禁：

1. 记忆命中率：给定用户长期记忆集合与问题，检查
   - HitRate：期望注入的记忆是否全部注入；
   - Recall：期望记忆被注入的比例；
   - Precision：注入内容中相关记忆的比例（越低说明噪声越多）。
2. 摘要保真度：把长对话交给摘要节点（无模型时走机械摘要），检查
   - Fidelity：期望保留的关键事实是否仍在摘要里；
   - Compression：压缩后 token 占原文比例。

用法：
    python tests/memory_eval.py
    python tests/memory_eval.py --min-hit-rate 0.9 --min-fidelity 0.85 --max-compression 0.75
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SUPPORTPILOT_AGENT_DB", os.path.join(tempfile.mkdtemp(prefix="mem_eval_"), "eval.db"))
os.environ.setdefault("SUPPORTPILOT_LOG_LEVEL", "ERROR")

import app.after_sales_agent as agent  # noqa: E402
from app.agent_observability import estimate_tokens  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent / "memory_cases.json"


def _record(text: str, weight: float = 0.6, age_days: int = 0, expired: bool = False) -> dict:
    """构造与长期记忆存储一致的 record，age_days 用于模拟老化。"""
    ts = (datetime.now(timezone.utc) - timedelta(days=int(age_days))).isoformat(timespec="seconds")
    return {
        "text": text,
        "weight": float(weight),
        "created_at": ts,
        "last_seen": ts,
        "hits": 0,
        "expired": bool(expired),
        "source": "eval",
    }


def _match(text: str, targets: list[str]) -> bool:
    return any(target in text for target in targets)


def eval_memory(cases: list[dict]) -> dict:
    rows = []
    hits = 0
    expected_total = 0
    matched_total = 0
    injected_total = 0
    relevant_injected_total = 0

    for case in cases:
        records = [_record(**item) for item in case.get("records", [])]
        injected = agent.select_relevant_memories(
            records,
            case.get("query", ""),
            case.get("intent", "refund"),
        )
        expected = case.get("expect_injected") or []
        forbidden = case.get("expect_not_injected") or []

        missing = [t for t in expected if not _match(" ".join(injected), [t])]
        leaked = [t for t in forbidden if _match(" ".join(injected), [t])]
        ok = not missing and not leaked

        whole_hit = ok
        hits += 1 if whole_hit else 0
        expected_total += len(expected)
        matched_total += len(expected) - len(missing)
        injected_total += len(injected)
        relevant_injected_total += sum(1 for text in injected if _match(text, expected))

        rows.append({
            "id": case.get("id", ""),
            "ok": ok,
            "missing": missing,
            "leaked": leaked,
            "injected": injected,
        })

    total = len(cases) or 1
    return {
        "cases": rows,
        "hit_rate": round(hits / total, 3),
        "recall": round(matched_total / expected_total, 3) if expected_total else 1.0,
        "precision": round(relevant_injected_total / injected_total, 3) if injected_total else 1.0,
        "leak_cases": sum(1 for r in rows if r["leaked"]),
    }


def eval_summary(cases: list[dict]) -> dict:
    original_has_llm = agent.has_llm
    agent.has_llm = lambda: False  # 强制走确定性机械摘要，保证离线可复现
    rows = []
    fidelity_sum = 0.0
    compression_sum = 0.0
    try:
        for case in cases:
            history = [m for m in case.get("history", []) if m.get("content")]
            state = {
                "history": history,
                "summary": "",
                "summarized_upto": 0,
                "errors": [],
            }
            update = agent.summarize_node(state)
            summary = update.get("summary") or ""
            keep = case.get("expect_keep") or []
            retained = [t for t in keep if t in summary]
            fidelity = len(retained) / len(keep) if keep else 1.0
            # 压缩率只针对被摘要的历史前缀，最近若干轮原文仍保留在上下文里
            chunk = history[: max(1, len(history) - agent.KEEP_RECENT_MESSAGES)]
            source_tokens = max(1, estimate_tokens("\n".join(m["content"] for m in chunk)))
            compression = round(estimate_tokens(summary) / source_tokens, 3)
            fidelity_sum += fidelity
            compression_sum += compression
            rows.append({
                "id": case.get("id", ""),
                "fidelity": round(fidelity, 3),
                "compression": compression,
                "missing": [t for t in keep if t not in summary],
                "triggered": bool(update.get("summary_triggered")),
            })
    finally:
        agent.has_llm = original_has_llm

    total = len(cases) or 1
    return {
        "cases": rows,
        "fidelity": round(fidelity_sum / total, 3),
        "compression": round(compression_sum / total, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="记忆命中率与摘要保真度离线评测")
    parser.add_argument("--min-hit-rate", type=float, default=0.9, help="期望记忆全部注入的用例占比下限")
    parser.add_argument("--min-recall", type=float, default=0.9, help="期望记忆召回率下限")
    parser.add_argument("--min-fidelity", type=float, default=0.85, help="摘要关键事实保留率下限")
    parser.add_argument("--max-compression", type=float, default=0.75, help="摘要 token 占原文比例上限")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args()

    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    memory = eval_memory(payload.get("memory_cases") or [])
    summary = eval_summary(payload.get("summary_cases") or [])

    if args.json:
        print(json.dumps({"memory": memory, "summary": summary}, ensure_ascii=False, indent=2))
    else:
        for row in memory["cases"]:
            flag = "PASS" if row["ok"] else "FAIL"
            print(f"{flag} {row['id']}: injected={row['injected']} missing={row['missing']} leaked={row['leaked']}")
        for row in summary["cases"]:
            print(
                f"SUMMARY {row['id']}: fidelity={row['fidelity']} "
                f"compression={row['compression']} missing={row['missing']}"
            )
        print(f"\nMEMORY hit_rate={memory['hit_rate']} recall={memory['recall']} "
              f"precision={memory['precision']} leak_cases={memory['leak_cases']}")
        print(f"SUMMARY fidelity={summary['fidelity']} compression={summary['compression']}")

    failures = []
    if memory["hit_rate"] < args.min_hit_rate:
        failures.append(f"hit_rate {memory['hit_rate']} < {args.min_hit_rate}")
    if memory["recall"] < args.min_recall:
        failures.append(f"recall {memory['recall']} < {args.min_recall}")
    if summary["fidelity"] < args.min_fidelity:
        failures.append(f"fidelity {summary['fidelity']} < {args.min_fidelity}")
    if summary["compression"] > args.max_compression:
        failures.append(f"compression {summary['compression']} > {args.max_compression}")

    if failures:
        print("\nGATE_FAILED: " + "; ".join(failures))
        return 1
    print("\nMEMORY_SUMMARY_EVAL_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
