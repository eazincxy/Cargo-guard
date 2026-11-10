# CargoGuard · 跨境售后 RAG Agent

面向跨境电商消费者的售后维权参谋。基于「意图分类 → 工具/RAG 检索 → LLM 生成 → 合规校验」的 Agent 链路，为物流异常、清关滞留、商品破损、商家失联、税费争议等跨境售后场景提供合规维权指引，同时内置严格的安全边界：不编造法条、不承诺退款结果、不协助恶意申诉。

## 功能特性

- **智能路由分流**：轻量意图分类器区分售后维权 / 订单查询 / 闲聊越界请求，避免不必要的 RAG 与 LLM 调用，控制成本
- **多客服通道**：AI 客服、商家客服、平台客服三个界面表现完全一致，支持订单号、商家、商品、日期区间多维检索
- **订单全链路**：订单列表 → 订单详情 → 商品详情 → 物流动态时间轴，清关异常状态可跳转独立物流页面
- **多语言**：界面文案覆盖中 / 英 / 日 / 韩 / 法五种语言，状态与物流信息随语言模式联动
- **合规知识库**：法规条目双人审核入库（`review_status: passed` 方可检索），按国家分文件存储，带复核周期与废弃标记
- **可观测性**：每轮对话埋点记录工具调用、检索文档、LLM 输入输出与校验结果

## 项目结构

```
├── streamlit_app.py      # Streamlit 主应用（界面 + 路由 + 会话管理）
├── app/                  # Agent 核心：意图分类、LLM 调用、RAG 检索、校验
├── components/           # 前端组件（订单详情、订单视图、物流时间轴等）
├── kb/                   # 合规知识库（按国家分文件的法规条目 + 向量索引）
├── assets/               # 商品图、商家头像等静态资源
├── test_cases.json       # 回归测试用例库（正向合规咨询 + 反向越界请求）
├── auto_regress.py       # 自动回归脚本（LLM Judge 判定 + 自动修复 system prompt）
└── .github/workflows/    # CI（语法检查/冒烟）与 Regression（Agent 回归）
```

## 快速开始

```bash
pip install -r requirements.txt

# 配置模型密钥（.env）
# DEEPSEEK_API_KEY=sk-xxx        或其他 openai 兼容接口 key

streamlit run streamlit_app.py
```

## 自动回归测试

`auto_regress.py` 循环执行 `test_cases.json` 中的全部用例：调用 Agent 获取回答后，由独立 LLM Judge 依据每条用例的 `must_have` / `must_not` 判定是否合格；存在失败时自动改写主 system prompt 并重新回归，最多迭代 3 轮，最终输出 Markdown + JSON 报告到 `reports/`。

```bash
python auto_regress.py              # 完整回归（需要 API Key）
python auto_regress.py --dry-run    # 仅校验用例结构
```

环境变量：`OPENAI_API_KEY`（必填）、`OPENAI_BASE_URL` / `AGENT_MODEL` / `JUDGE_MODEL`（可选，默认 DeepSeek）。

## GitHub Actions

| 工作流 | 触发 | 内容 |
|---|---|---|
| CI | push / PR | ruff 语法检查、全量编译、组件 HTML 校验、Streamlit 冒烟测试 |
| Regression | push（相关文件变更）/ 手动触发 | 用例校验 + 全量 Agent 回归，报告上传为 Artifact |

Regression 需在仓库 Secrets 配置 `OPENAI_API_KEY`，未配置时自动降级为 dry-run 仅校验用例结构。
