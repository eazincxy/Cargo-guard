# CargoGuard · 跨境售后 RAG Agent

面向跨境电商消费者的售后维权参谋。基于「意图分类 → 工具/RAG 检索 → LLM 生成 → 合规校验」的 Agent 链路，为物流异常、清关滞留、商品破损、商家失联、税费争议等跨境售后场景提供合规维权指引，同时内置严格的安全边界：不编造法条、不承诺退款结果、不协助恶意申诉。

## 功能特性

- **智能路由分流**：轻量意图分类器区分售后维权 / 订单查询 / 闲聊越界请求，避免不必要的 RAG 与 LLM 调用，控制成本
- **ReAct 工具循环**：规划器可多轮调用只读工具（订单 / 物流 / 知识库），观察结果后再决策；带重复调用、全失败、最大轮数三类停止条件
- **人工审批（HITL）**：创建升级工单属于高风险写操作，规划阶段只挂起不执行，必须经 `interrupt` → 人工确认 → `Command(resume)` 恢复后才落库
- **可量化评测**：22 项 Agent 特性测试 + 合规规则门禁（FP=0）+ 22 条检索 gold set（HitRate@4 / MRR / Coverage）+ 记忆命中率与摘要保真度评测 + 20 条回归用例
- **运行指标**：`/metrics` 暴露轮次、降级率、工具成功率、token 成本与 p50/p95 延迟
- **多客服通道**：AI 客服、商家客服、平台客服三个界面表现完全一致，支持订单号、商家、商品、日期区间多维检索
- **订单全链路**：订单列表 → 订单详情 → 商品详情 → 物流动态时间轴，清关异常状态可跳转独立物流页面
- **多语言**：界面文案覆盖中 / 英 / 日 / 韩 / 法五种语言，状态与物流信息随语言模式联动
- **合规知识库**：法规条目双人审核入库（`review_status: passed` 方可检索），按国家分文件存储，带复核周期与废弃标记
- **可观测性**：每轮对话埋点记录工具调用、检索文档、LLM 输入输出与校验结果；token 预算使用 tiktoken 真实分词（cl100k_base），依赖缺失或离线时自动回退字符启发式

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

## Docker 部署

```bash
docker build -t cargoguard .
# 需要 OTLP 导出时：docker build --build-arg INSTALL_OBSERVABILITY=true -t cargoguard .
docker run --rm -p 8501:8501 --env-file .env cargoguard
```

镜像构建时自动执行 `init_db` 并写入演示订单；`data.db`、`agent_memory.db` 不进入镜像。API 模式：

```bash
docker run --rm -p 8000:8000 --env-file .env cargoguard \
  uvicorn app.api:app --host 0.0.0.0 --port 8000
```

## 链路追踪

默认零依赖：每轮请求会生成 `agent.turn` → `agent.node.*` → `agent.tool` 的嵌套 span，以结构化 JSON 写入日志，字段包含 `trace_id` / `span_id` / `parent_span_id` / `ms` / `status` / 业务属性；`turn_end` 日志带同一个 `trace_id`，可直接按链路聚合。

接真实 OpenTelemetry（可选）：

```bash
pip install -r requirements-observability.txt
export SUPPORTPILOT_OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
```

LangSmith 由 LangGraph 原生支持，设置 `LANGSMITH_TRACING=true` 与 `LANGSMITH_API_KEY` 即可；当前追踪状态可通过 `GET /metrics` 的 `tracing` 字段查看。

## 红队评测

确定性防线检查，不依赖模型与网络：

```bash
python tests/redteam_eval.py
```

覆盖三类攻击：工具越权（跨订单读取、伪造高权限工具）、记忆投毒（权限冒充、指令覆盖、批量导出个人信息）、订单号伪造（不存在/非法格式），并包含正常偏好的正向对照。

## 人工审批（HITL）

`create_escalation`（创建升级工单并转平台介入）是唯一的高风险写操作。工作流保证它在人工确认前不会落库：

```
plan 发现写操作 → pending_action → approval 节点 interrupt（图挂起）
      → POST /approval {approved: true}  → Command(resume) → 执行落库
      → POST /approval {approved: false} → 仅记录拒绝，不产生写操作
```

```bash
# 1) 第一次对话：返回 needs_approval=true 和待审批动作，不写库
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"order_id":"ORD-1004","message":"商家失联，帮我升级投诉","thread_id":"demo-1"}'

# 2) 人工确认后恢复
curl -X POST http://localhost:8000/approval -H "Content-Type: application/json" \
  -d '{"thread_id":"demo-1","approved":true,"reviewer":"alice","note":"核实属实"}'
```

恢复结果里的 `hitl` 字段记录 `status`（approved / rejected / failed）、审批人与备注；被拒绝时 `work_orders` 不会新增记录。

## 自动回归测试

`auto_regress.py` 循环执行 `test_cases.json` 中的全部用例：调用 Agent 获取回答后，由独立 LLM Judge 依据每条用例的 `must_have` / `must_not` 判定是否合格；存在失败时自动改写主 system prompt 并重新回归，最多迭代 3 轮，最终输出 Markdown + JSON 报告到 `reports/`。

检索质量单独评测（不调用模型，无网络也可跑）：

```bash
python tests/retrieval_eval.py                       # HitRate@K / MRR / Coverage
python tests/retrieval_eval.py --min-hit-rate 0.9    # CI 门禁
```

记忆与摘要质量评测（离线、无模型依赖，可作为门禁）：

```bash
python tests/memory_eval.py
# HitRate / Recall / Precision（记忆注入）+ Fidelity / Compression（摘要压缩）
python tests/memory_eval.py --min-hit-rate 0.9 --min-fidelity 0.85 --max-compression 0.75
```

```bash
python auto_regress.py              # 完整回归（需要 API Key）
python auto_regress.py --dry-run    # 仅校验用例结构
```

环境变量：`OPENAI_API_KEY`（必填）、`OPENAI_BASE_URL` / `AGENT_MODEL` / `JUDGE_MODEL`（可选，默认 DeepSeek）。

## GitHub Actions

| 工作流 | 触发 | 内容 |
|---|---|---|
| CI | push / PR / 手动触发 | ruff 语法检查、全量编译、Agent 单测、审核规则层门禁、检索质量门禁、红队门禁、记忆与摘要质量门禁、组件 HTML 校验、Streamlit 冒烟测试、Docker 镜像构建与 Streamlit/API 容器健康检查 |
| CI · e2e | push / PR / 手动触发 | 配置 `OPENAI_API_KEY` 时执行真实端到端回归（LLM Judge）；未配置则显式跳过，不再用 dry-run 冒充通过 |
| Regression | push（相关文件变更）/ 手动触发 | 用例校验 + 全量 Agent 回归，报告上传为 Artifact |

Regression 需在仓库 Secrets 配置 `OPENAI_API_KEY`，未配置时自动降级为 dry-run 仅校验用例结构。
