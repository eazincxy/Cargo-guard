"""红队确定性评测：工具越权、记忆投毒、订单号伪造。

不依赖 LLM 与网络，可直接进 CI；与 review_eval（回答合规）、
retrieval_eval（检索质量）共同组成三层质量门禁。

用法：
    python tests/redteam_eval.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.agent_tools import execute_tool  # noqa: E402
from app import after_sales_agent as agent  # noqa: E402

CASES_PATH = os.path.join(ROOT, "tests", "redteam_cases.json")
REPORT_DIR = os.path.join(ROOT, "reports")

_FAKE_ORDER = {
    "order_id": "ORD-1001",
    "seller_name": "测试商家",
    "product_name": "无线耳机",
    "currency": "USD",
    "total_amount": 29.9,
    "status": "已发货",
    "shipping_status": "运输中",
    "tracking_number": "TRK123456",
    "logistics_info": "已到达分拨中心",
    "shipping_address": "Los Angeles, CA, USA",
}


def _fake_load_order(order_id: str) -> dict:
    return dict(_FAKE_ORDER) if str(order_id).upper() == "ORD-1001" else {}


def _check_tool_scope(case: dict) -> bool:
    state = {
        "order_id": case.get("state_order_id") or "",
        "order": {},
        "disable_order_lookup": False,
    }
    entry = execute_tool(
        case["tool"],
        case.get("args") or {},
        state,
        load_order_fn=_fake_load_order,
        search_fn=lambda *a, **k: [],
    )
    denied = not entry.get("ok")
    return denied if case["expect"] == "denied" else not denied


def _check_memory_poison(case: dict) -> bool:
    user_id = f"redteam_{case['id']}"
    text = case["text"]
    agent.save_user_memory(user_id, [text])
    accepted = text in agent.load_user_memory(user_id)
    return accepted if case["expect"] == "accepted" else not accepted


def _check_order_forgery(case: dict) -> bool:
    entry = execute_tool(
        "lookup_order",
        {"order_id": case["order_id"]},
        {"order": {}, "disable_order_lookup": False},
        load_order_fn=_fake_load_order,
    )
    denied = not entry.get("ok")
    return denied if case["expect"] == "denied" else not denied


_CHECKERS = {
    "tool_scope": _check_tool_scope,
    "memory_poison": _check_memory_poison,
    "order_forgery": _check_order_forgery,
}


def write_report(results: list[dict]) -> tuple[str, str]:
    os.makedirs(REPORT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(REPORT_DIR, f"redteam_eval_{stamp}.json")
    md_path = os.path.join(REPORT_DIR, f"redteam_eval_{stamp}.md")
    passed = sum(1 for r in results if r["passed"])
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    lines = [
        "# 红队评测",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 通过：{passed}/{len(results)}",
        "",
        "| 用例 | 类别 | 期望 | 结果 | 威胁 |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['id']} | {r['category']} | {r['expect']} | "
            f"{'PASS' if r['passed'] else 'FAIL'} | {r.get('threat', '')} |"
        )
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, md_path


def main() -> int:
    with open(CASES_PATH, encoding="utf-8") as f:
        cases = json.load(f)["cases"]

    results = []
    for case in cases:
        checker = _CHECKERS.get(case["category"])
        try:
            passed = bool(checker and checker(case))
            error = "" if checker else f"未知类别：{case['category']}"
        except Exception as exc:  # noqa: BLE001
            passed, error = False, f"{type(exc).__name__}: {exc}"
        results.append({
            "id": case["id"],
            "category": case["category"],
            "expect": case["expect"],
            "threat": case.get("threat", ""),
            "passed": passed,
            "error": error,
        })
        print(
            f"[{len(results):02d}/{len(cases)}] {case['id']:<26} "
            f"{case['category']:<14} expect={case['expect']:<8} "
            f"{'PASS' if passed else 'FAIL'} {error}"
        )

    passed = sum(1 for r in results if r["passed"])
    json_path, md_path = write_report(results)
    print(f"\n红队用例：{passed}/{len(results)} 通过")
    print(f"报告：{json_path}\n报告：{md_path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
