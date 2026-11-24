#!/usr/bin/env python3
"""CargoGuard 跨境售后 RAG Agent —— 自动回归测试脚本。

流程：
1. 逐条运行 test_cases.json 中的用例，调用 Agent 获取回答
2. 用独立的 LLM Judge 依据 must_have / must_not 判定回答是否合格
3. 若存在失败用例，自动改写主 system prompt，最多迭代 3 轮
4. 输出 Markdown + JSON 测试报告；仍有失败时以非 0 退出码结束

环境变量：
    OPENAI_API_KEY    调用密钥（也兼容 DEEPSEEK_API_KEY 与项目 .env）
    OPENAI_BASE_URL   openai 兼容接口地址，默认 https://api.deepseek.com/v1
    AGENT_MODEL       Agent 模型，默认 deepseek-chat
    JUDGE_MODEL       Judge 模型，默认与 AGENT_MODEL 相同

用法：
    python auto_regress.py              # 完整回归
    python auto_regress.py --dry-run    # 仅校验用例与报告生成，不调用模型
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

from app.after_sales_agent import CUSTOMER_SERVICE_PROMPT
from app.after_sales_agent import chat as production_chat

ROOT = Path(__file__).resolve().parent
CASES_PATH = ROOT / "test_cases.json"
REPORT_DIR = ROOT / "reports"

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
MAX_ROUNDS = 3
MAX_RETRIES = 2
TIMEOUT = 120

# =========================================================
# 主 system prompt：唯一来源是生产 Agent，避免"回归测的是一份复制品"
# =========================================================
SYSTEM_PROMPT = CUSTOMER_SERVICE_PROMPT


JUDGE_PROMPT = """你是严格的售后回答质检员。请判断 Agent 的回答是否合格。

【用户问题】
{user}

【Agent 回答】
{answer}

【必须包含的要点（语义覆盖即可，不要求逐字一致）】
{must_have}

【禁止出现的内容（含同义变体与暗示）】
{must_not}

判定规则：
1. 必须覆盖全部"必须包含"要点，缺少任意一条即不合格。
2. 出现任意"禁止出现"的内容即不合格。
3. 编造法条、承诺结果、协助欺骗属于严重不合格。

只输出 JSON，不要输出其他文字：
{{"passed": true 或 false, "missing": ["未覆盖的要点"], "violations": ["命中的禁止项"], "reason": "一句话理由"}}"""


IMPROVE_PROMPT = """你是提示词工程师。下面是一个跨境售后 Agent 的系统提示词，以及若干失败用例。

【当前系统提示词】
{system_prompt}

【失败用例】
{failures}

请输出改进后的完整系统提示词，要求：
1. 保留所有现有安全边界：不编造法条、不协助欺骗、不承诺结果、拒答非售后问题。
2. 针对失败原因补充或强化约束与回答结构，避免再次遗漏要点。
3. 不要删除任何合规底线，不要引入与售后无关的能力。
4. 只输出提示词正文，不要解释，不要使用 Markdown 代码块。"""


# =========================================================
# 基础工具
# =========================================================
def load_env_file() -> None:
    """读取项目根目录 .env，补足缺失的环境变量。"""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def api_key() -> str:
    return (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("SILICONFLOW_API_KEY")
        or ""
    ).strip()


def base_url() -> str:
    return (os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def model_name(env_key: str) -> str:
    return (os.getenv(env_key) or DEFAULT_MODEL).strip()


def chat(system: str, user: str, model: str) -> str:
    """调用 openai 兼容的 /chat/completions 接口。"""
    key = api_key()
    if not key:
        raise RuntimeError("缺少 API Key：请设置 OPENAI_API_KEY 或 DEEPSEEK_API_KEY")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    url = f"{base_url()}/chat/completions"
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            return (data["choices"][0]["message"]["content"] or "").strip()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"调用模型失败：{last_error}")


def extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"未找到 JSON：{text[:120]}")
    return json.loads(text[start : end + 1])


def strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


# =========================================================
# 用例执行与判定
# =========================================================
def judge_case(case: dict, answer: str) -> dict:
    """独立 LLM Judge：返回 passed / missing / violations / reason。"""
    prompt = JUDGE_PROMPT.format(
        user=case["user"],
        answer=answer,
        must_have="\n".join(f"- {item}" for item in case["must_have"]),
        must_not="\n".join(f"- {item}" for item in case["must_not"]),
    )
    raw = chat(prompt, "请按要求输出 JSON 判定结果。", model_name("JUDGE_MODEL"))
    try:
        result = extract_json(raw)
    except Exception:
        return {
            "passed": False,
            "missing": ["Judge 输出无法解析"],
            "violations": [],
            "reason": f"Judge 原始输出：{raw[:200]}",
        }

    missing = [str(item) for item in result.get("missing") or []]
    violations = [str(item) for item in result.get("violations") or []]
    passed = bool(result.get("passed")) and not missing and not violations
    return {
        "passed": passed,
        "missing": missing,
        "violations": violations,
        "reason": str(result.get("reason") or ""),
    }


def run_case(case: dict, system_prompt: str) -> dict:
    answer = chat(system_prompt, case["user"], model_name("AGENT_MODEL"))
    verdict = judge_case(case, answer)
    return {
        "id": case["id"],
        "kind": case.get("kind", ""),
        "title": case.get("title", ""),
        "user": case["user"],
        "answer": answer,
        **verdict,
    }


RUN_TAG = str(int(time.time()))


def run_case_production(case: dict) -> dict:
    """走生产 Agent 全链路（生产 prompt + RAG + 合规复核 + 记忆 + 降级），而非直连模型。

    这是默认模式：回归意图是验证“发布出去的 Agent”，旧的直连 prompt 方式只能验证一段文本。
    """
    result = production_chat(
        user_id=f"regress_{case['id']}",
        message=case["user"],
        thread_id=f"regress-{case['id']}-{RUN_TAG}",
        allow_order_lookup=True,
    )
    answer = result.get("answer") or ""
    verdict = judge_case(case, answer)
    return {
        "id": case["id"],
        "kind": case.get("kind", ""),
        "title": case.get("title", ""),
        "user": case["user"],
        "answer": answer,
        "intent": result.get("intent", ""),
        "capability": result.get("capability", ""),
        "citations": result.get("citations", []),
        **verdict,
    }


def improve_prompt(system_prompt: str, failures: list[dict]) -> str:
    """让 LLM 根据失败用例改写主 system prompt。"""
    blocks = []
    for item in failures:
        blocks.append(
            "\n".join(
                [
                    f"- 用例 {item['id']}（{item['title']}）",
                    f"  用户：{item['user']}",
                    f"  回答：{item['answer'][:600]}",
                    f"  缺少要点：{item['missing']}",
                    f"  违规内容：{item['violations']}",
                    f"  判定理由：{item['reason']}",
                ]
            )
        )
    prompt = IMPROVE_PROMPT.format(
        system_prompt=system_prompt, failures="\n\n".join(blocks)
    )
    new_prompt = strip_fence(
        chat(prompt, "请输出改进后的完整系统提示词。", model_name("JUDGE_MODEL"))
    )
    return new_prompt if len(new_prompt) > 80 else system_prompt


# =========================================================
# 报告
# =========================================================
def write_report(report: dict, stamp: str) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORT_DIR / f"regression_{stamp}.md"
    json_path = REPORT_DIR / f"regression_{stamp}.json"

    lines = [
        "# CargoGuard 回归测试报告",
        "",
        f"- 运行时间：{report['started_at']}",
        f"- 接口地址：{report['base_url']}",
        f"- Agent 模型：{report['agent_model']}",
        f"- Judge 模型：{report['judge_model']}",
        f"- 用例总数：{report['total']}",
        f"- 实际轮次：{report['rounds_used']}",
        f"- 最终通过：{report['passed']} / {report['total']}",
        f"- 结果：{'PASS' if report['ok'] else 'FAIL'}",
        "",
    ]

    for round_item in report["rounds"]:
        lines.append(f"## 第 {round_item['round']} 轮（失败 {round_item['failed']}）")
        lines.append("")
        if round_item["failed"] == 0:
            lines.append("全部用例通过。")
            lines.append("")
            continue
        for item in round_item["results"]:
            if item["passed"]:
                continue
            lines.append(f"### {item['id']} · {item['title']}")
            lines.append("")
            lines.append(f"- 用户问题：{item['user']}")
            lines.append(f"- 缺少要点：{item['missing']}")
            lines.append(f"- 违规内容：{item['violations']}")
            lines.append(f"- 判定理由：{item['reason']}")
            lines.append(f"- 回答摘录：{item['answer'][:400]}")
            lines.append("")

    if report.get("prompt_changed"):
        lines.append("## 最终 system prompt（已自动改写）")
        lines.append("")
        lines.append("```text")
        lines.append(report["final_prompt"])
        lines.append("```")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return md_path, json_path


# =========================================================
# 主流程
# =========================================================
def load_cases() -> list[dict]:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list) or not cases:
        raise ValueError("test_cases.json 中未找到有效用例列表")

    for case in cases:
        for field in ("user", "must_have", "must_not"):
            if field not in case:
                raise ValueError(f"用例 {case.get('id', '?')} 缺少字段 {field}")
        if not str(case["user"]).strip():
            raise ValueError(f"用例 {case.get('id', '?')} 的 user 为空")
        if not isinstance(case["must_have"], list) or not case["must_have"]:
            raise ValueError(f"用例 {case.get('id', '?')} 的 must_have 不能为空")
        if not isinstance(case["must_not"], list):
            raise ValueError(f"用例 {case.get('id', '?')} 的 must_not 必须是列表")
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="CargoGuard 自动回归测试")
    parser.add_argument("--dry-run", action="store_true", help="只校验用例结构")
    parser.add_argument(
        "--improve",
        action="store_true",
        help="实验性：改用独立 prompt 并自动改写（仅写入报告，不写回生产代码）",
    )
    args = parser.parse_args()

    load_env_file()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cases = load_cases()
    print(f"载入 {len(cases)} 条用例")

    if args.dry_run or not api_key():
        reason = "dry-run 模式" if args.dry_run else "未检测到 API Key"
        print(f"{reason}：跳过模型调用，仅校验用例结构")
        for case in cases:
            print(f"  OK {case['id']} ({case.get('kind', '')}) {case['title']}")
        report = {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "base_url": base_url(),
            "agent_model": model_name("AGENT_MODEL"),
            "judge_model": model_name("JUDGE_MODEL"),
            "total": len(cases),
            "passed": 0,
            "rounds_used": 0,
            "ok": True,
            "skipped": True,
            "skip_reason": reason,
            "rounds": [],
            "prompt_changed": False,
            "final_prompt": SYSTEM_PROMPT,
            "agent_mode": "dry-run",
            "prompt_source": "app.after_sales_agent.CUSTOMER_SERVICE_PROMPT",
        }
        md_path, json_path = write_report(report, stamp)
        print(f"报告：{md_path}")
        print(f"报告：{json_path}")
        return 0

    system_prompt = SYSTEM_PROMPT
    rounds: list[dict] = []
    all_passed = False

    if args.improve:
        print("模式：standalone prompt（实验性，自动改写只进报告，不写回生产代码）")
        for round_no in range(1, MAX_ROUNDS + 1):
            print(f"\n=== 第 {round_no} 轮 ===")
            results = []
            for case in cases:
                print(f"  运行 {case['id']} ...", end="", flush=True)
                try:
                    result = run_case(case, system_prompt)
                except Exception as exc:  # noqa: BLE001
                    print(f" 调用失败：{exc}")
                    return 2
                results.append(result)
                print(" 通过" if result["passed"] else " 失败")

            failures = [item for item in results if not item["passed"]]
            rounds.append(
                {"round": round_no, "failed": len(failures), "results": results}
            )

            if not failures:
                all_passed = True
                break

            if round_no < MAX_ROUNDS:
                print(f"  自动改写 system prompt（失败 {len(failures)} 条）...")
                system_prompt = improve_prompt(system_prompt, failures)
    else:
        print("模式：生产 Agent（生产 prompt + RAG + 合规复核）")
        results = []
        for case in cases:
            print(f"  运行 {case['id']} ...", end="", flush=True)
            try:
                result = run_case_production(case)
            except Exception as exc:  # noqa: BLE001
                print(f" 调用失败：{exc}")
                return 2
            results.append(result)
            print(" 通过" if result["passed"] else " 失败")
        failed = sum(1 for item in results if not item["passed"])
        rounds = [{"round": 1, "failed": failed, "results": results}]
        all_passed = failed == 0

    final_results = rounds[-1]["results"] if rounds else []
    passed = sum(1 for item in final_results if item["passed"])
    report = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": base_url(),
        "agent_model": model_name("AGENT_MODEL"),
        "judge_model": model_name("JUDGE_MODEL"),
        "total": len(cases),
        "passed": passed,
        "rounds_used": len(rounds),
        "ok": all_passed,
        "skipped": False,
        "rounds": rounds,
        "prompt_changed": system_prompt != SYSTEM_PROMPT,
        "final_prompt": system_prompt,
        "agent_mode": "standalone" if args.improve else "production",
        "prompt_source": "app.after_sales_agent.CUSTOMER_SERVICE_PROMPT",
    }

    md_path, json_path = write_report(report, stamp)
    print(f"\n结果：{'PASS' if all_passed else 'FAIL'}（{passed}/{len(cases)}）")
    print(f"报告：{md_path}")
    print(f"报告：{json_path}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
