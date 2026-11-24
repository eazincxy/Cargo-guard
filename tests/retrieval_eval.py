"""检索质量评测：Recall@K / MRR / 期望文档覆盖率。

与 review_eval（合规判定）互补，用来回答“RAG 到底召回得准不准”。
无需网络：有向量缓存且配置了硅基流动 Key 时走混合检索，否则自动退化为关键词检索。

用法：
    python tests/retrieval_eval.py
    python tests/retrieval_eval.py --min-hit-rate 0.85   # CI 门禁
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app.kb as kb  # noqa: E402

CASES_PATH = os.path.join(ROOT, "tests", "retrieval_cases.json")
REPORT_DIR = os.path.join(ROOT, "reports")


def load_cases(path: str = CASES_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_case(case: dict, top_k: int, min_score: float) -> dict:
    started = time.perf_counter()
    hits = kb.search(
        case["query"],
        top_k=top_k,
        min_score=min_score,
        country_code=case.get("country_code") or None,
        state_code=case.get("state_code") or None,
    ) or []
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    ids = [h.get("id") for h in hits]
    expected = list(dict.fromkeys(case.get("expected_ids") or []))
    matched = [doc_id for doc_id in ids if doc_id in expected]
    rank = next((i + 1 for i, doc_id in enumerate(ids) if doc_id in expected), None)
    return {
        "id": case["id"],
        "query": case["query"],
        "country_code": case.get("country_code") or "",
        "state_code": case.get("state_code") or "",
        "expected_ids": expected,
        "retrieved_ids": ids,
        "retrieved_sources": [h.get("source", "") for h in hits],
        "matched": matched,
        "rank": rank,
        "hit": rank is not None,
        "coverage": round(len(matched) / len(expected), 3) if expected else 0.0,
        "ms": elapsed,
    }


def summarize(results: list[dict], top_k: int) -> dict:
    total = len(results) or 1
    hit1 = sum(1 for r in results if r["rank"] == 1)
    hit3 = sum(1 for r in results if r["rank"] and r["rank"] <= 3)
    hitk = sum(1 for r in results if r["hit"])
    reciprocal = sum(1 / r["rank"] for r in results if r["rank"])
    return {
        "cases": len(results),
        "top_k": top_k,
        "hit_rate_at_1": round(hit1 / total, 3),
        "hit_rate_at_3": round(hit3 / total, 3),
        f"hit_rate_at_{top_k}": round(hitk / total, 3),
        f"mrr_at_{top_k}": round(reciprocal / total, 3),
        f"coverage_at_{top_k}": round(sum(r["coverage"] for r in results) / total, 3),
        "misses": [r["id"] for r in results if not r["hit"]],
        "avg_ms": round(sum(r["ms"] for r in results) / total, 1),
    }


def write_report(mode: dict, results: list[dict], summary: dict) -> tuple[str, str]:
    os.makedirs(REPORT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(REPORT_DIR, f"retrieval_eval_{stamp}.json")
    md_path = os.path.join(REPORT_DIR, f"retrieval_eval_{stamp}.md")

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "summary": summary,
        "results": results,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    lines = [
        "# 检索质量评测",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 检索模式：{mode['retrieval']}（向量缓存={mode['embeddings']}，查询向量可用={mode['query_embedding']}）",
        f"- 用例数：{summary['cases']}｜Top-K：{summary['top_k']}",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| HitRate@1 | {summary['hit_rate_at_1']} |",
        f"| HitRate@3 | {summary['hit_rate_at_3']} |",
    ]
    k = summary["top_k"]
    lines += [
        f"| HitRate@{k} | {summary['hit_rate_at_' + str(k)]} |",
        f"| MRR@{k} | {summary['mrr_at_' + str(k)]} |",
        f"| Coverage@{k} | {summary['coverage_at_' + str(k)]} |",
        "",
        "## 逐条结果",
        "",
        "| 用例 | 查询 | 期望 | 实际 Top-K | 命中排名 |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['id']} | {r['query']} | {', '.join(r['expected_ids'])} | "
            f"{', '.join(r['retrieved_ids'])} | {r['rank'] or '未命中'} |"
        )
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 检索质量评测")
    parser.add_argument("--cases", default=CASES_PATH)
    parser.add_argument("--top-k", type=int, default=0, help="覆盖用例文件中的 top_k")
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument(
        "--min-hit-rate",
        type=float,
        default=0.0,
        help="HitRate@K 低于该值时返回非 0；设为 0 表示不做门禁",
    )
    args = parser.parse_args()

    data = load_cases(args.cases)
    top_k = args.top_k or int(data.get("top_k") or 4)
    min_score = (
        args.min_score
        if args.min_score is not None
        else float(data.get("min_score") or 0.3)
    )
    mode = {
        "retrieval": "hybrid" if (kb.EMBS and kb.SILICONFLOW_KEY) else "keyword",
        "embeddings": bool(kb.EMBS),
        "query_embedding": bool(kb.SILICONFLOW_KEY),
    }

    cases = data.get("cases") or []
    results = []
    for i, case in enumerate(cases, 1):
        result = run_case(case, top_k, min_score)
        results.append(result)
        flag = "OK" if result["hit"] else "MISS"
        print(
            f"[{i:02d}/{len(cases)}] {result['id']:<28} rank={str(result['rank'] or '-'):<2} "
            f"expected={','.join(result['expected_ids']):<20} "
            f"got={','.join(result['retrieved_ids'])} {flag}"
        )

    summary = summarize(results, top_k)
    print(f"\n检索模式：{mode['retrieval']}（向量缓存={mode['embeddings']}，查询向量={mode['query_embedding']}）")
    print(
        f"HitRate@1={summary['hit_rate_at_1']} HitRate@3={summary['hit_rate_at_3']} "
        f"HitRate@{top_k}={summary[f'hit_rate_at_{top_k}']} "
        f"MRR@{top_k}={summary[f'mrr_at_{top_k}']} "
        f"Coverage@{top_k}={summary[f'coverage_at_{top_k}']}"
    )
    if summary["misses"]:
        print("未命中：" + ", ".join(summary["misses"]))

    json_path, md_path = write_report(mode, results, summary)
    print(f"\n报告：{json_path}\n报告：{md_path}")

    if args.min_hit_rate > 0:
        return 0 if summary[f"hit_rate_at_{top_k}"] >= args.min_hit_rate else 1
    return 0 if not summary["misses"] else 1


if __name__ == "__main__":
    sys.exit(main())
