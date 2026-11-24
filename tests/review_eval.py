"""第 13 项：review 误判率量化。

用带标签的样例集跑真实 review_node（规则层 + 模型层），输出混淆矩阵：
- 误拦率（FPR）：合规回答被判定不通过的比例；
- 漏放率（FNR）：违规回答被放行的比例。

用法：
    python tests/review_eval.py               # 规则 + 模型（需要 DEEPSEEK_API_KEY）
    python tests/review_eval.py --rules-only  # 只跑规则层，无网络调用
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 降低节点日志噪音，只保留错误
os.environ.setdefault("SUPPORTPILOT_LOG_LEVEL", "ERROR")

from app.agent_intents import intent_rule_issues  # noqa: E402
import app.after_sales_agent as agent  # noqa: E402

CASES_PATH = Path(__file__).with_name("review_eval_cases.json")
REPORT_DIR = ROOT / "reports"


def load_cases() -> list[dict]:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return data["cases"]


def run_case(case: dict) -> dict:
    """跑真实审核节点，并拆出规则层/模型层的判定来源。"""
    state = {
        "answer": case["answer"],
        "intent": case["intent"],
        "citations": case.get("sources") or [],
        "order": case.get("order") or {},
        "errors": [],
        "injection_flags": [],
    }
    out = agent.review_node(state)
    rule_issues = intent_rule_issues(case["answer"], case["intent"])
    note = out.get("review_note") or ""
    llm_fail = "【审核不通过】" in note
    passed = out.get("review_passed") is True
    pred = "pass" if passed else "fail"

    if pred == "pass":
        source = "none"
    elif rule_issues and llm_fail:
        source = "rule+llm"
    elif rule_issues:
        source = "rule"
    else:
        source = "llm"

    return {
        "id": case["id"],
        "category": case["category"],
        "intent": case["intent"],
        "gold": case["gold"],
        "pred": pred,
        "ok": pred == case["gold"],
        "source": source,
        "rule_issues": rule_issues,
        "llm_fail": llm_fail,
        "llm_error": note == "review_error",
        "note": note.replace("\n", " ")[:160],
    }


def summarize(results: list[dict]) -> dict:
    tp = sum(1 for r in results if r["gold"] == "fail" and r["pred"] == "fail")
    fp = sum(1 for r in results if r["gold"] == "pass" and r["pred"] == "fail")
    fn = sum(1 for r in results if r["gold"] == "fail" and r["pred"] == "pass")
    tn = sum(1 for r in results if r["gold"] == "pass" and r["pred"] == "pass")
    total = len(results)
    return {
        "total": total,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "accuracy": round((tp + tn) / total, 4) if total else 0.0,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else None,
        "false_negative_rate": round(fn / (fn + tp), 4) if fn + tp else None,
        "rule_layer_blocks": sum(1 for r in results if r["source"] in {"rule", "rule+llm"}),
        "llm_layer_blocks": sum(1 for r in results if r["source"] in {"llm", "rule+llm"}),
        "llm_errors": sum(1 for r in results if r["llm_error"]),
    }


def write_report(mode: str, results: list[dict], summary: dict) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"review_eval_{stamp}.json"
    md_path = REPORT_DIR / f"review_eval_{stamp}.md"

    json_path.write_text(
        json.dumps({"mode": mode, "summary": summary, "cases": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Review 误判率评估",
        "",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 模式：{mode}",
        f"- 用例：{summary['total']} 条（gold=fail {summary['tp'] + summary['fn']} 条，gold=pass {summary['fp'] + summary['tn']} 条）",
        "",
        "## 混淆矩阵",
        "",
        "| gold \\ pred | 不通过 | 通过 |",
        "| --- | --- | --- |",
        f"| 违规 (fail) | TP={summary['tp']} | FN={summary['fn']} |",
        f"| 合规 (pass) | FP={summary['fp']} | TN={summary['tn']} |",
        "",
        "## 指标",
        "",
        f"- 准确率：{summary['accuracy']}",
        f"- 拦截精确率：{summary['precision']}",
        f"- 拦截召回率：{summary['recall']}",
        f"- 误拦率（合规被判不通过）：{summary['false_positive_rate']}",
        f"- 漏放率（违规被判通过）：{summary['false_negative_rate']}",
        f"- 规则层拦截：{summary['rule_layer_blocks']} 条；模型层拦截：{summary['llm_layer_blocks']} 条；模型异常：{summary['llm_errors']} 条",
        "",
        "## 明细",
        "",
        "| id | gold | pred | 命中层 | 结果 | 说明 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        mark = "OK" if r["ok"] else "MISJUDGED"
        detail = "；".join(r["rule_issues"]) or r["note"] or ""
        lines.append(
            f"| {r['id']} | {r['gold']} | {r['pred']} | {r['source']} | {mark} | {detail} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="review 误判率量化")
    parser.add_argument("--rules-only", action="store_true", help="只跑规则层，不调用模型")
    parser.add_argument(
        "--fail-on-fp",
        action="store_true",
        help="仅当出现误拦（合规被判不通过）时返回非 0；适合 CI 门禁",
    )
    args = parser.parse_args()

    # 固定为 soft：只评估判定，不触发 hard 改写
    agent.CONFIG = dataclasses.replace(agent.CONFIG, review_mode="soft")

    if args.rules_only:
        agent.has_llm = lambda: False  # 关掉模型层，等价于无密钥环境
        mode = "rules-only"
    else:
        mode = "rules+llm"

    cases = load_cases()
    results = []
    for i, case in enumerate(cases, 1):
        result = run_case(case)
        results.append(result)
        print(
            f"[{i:02d}/{len(cases)}] {result['id']:<28} gold={result['gold']:<4} "
            f"pred={result['pred']:<4} {'OK' if result['ok'] else 'MISJUDGED'}"
        )

    summary = summarize(results)
    print("\n混淆矩阵：TP={tp} FP={fp} FN={fn} TN={tn}".format(**summary))
    print(
        "准确率={accuracy} 精确率={precision} 召回率={recall} "
        "误拦率={false_positive_rate} 漏放率={false_negative_rate}".format(**summary)
    )
    bad = [r for r in results if not r["ok"]]
    if bad:
        print("\n误判明细：")
        for r in bad:
            print(f"  - {r['id']} gold={r['gold']} pred={r['pred']} 来源={r['source']} "
                  f"规则={r['rule_issues']} 模型不通过={r['llm_fail']}")

    json_path, md_path = write_report(mode, results, summary)
    print(f"\n报告：{json_path}\n报告：{md_path}")
    if args.fail_on_fp:
        # 规则层门禁：语义型漏放属于预期（由模型层兜底），只卡误拦
        return 0 if summary["fp"] == 0 else 1
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
