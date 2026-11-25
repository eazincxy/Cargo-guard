# CargoGuard · 简历与面试要点

> 本文档是个人求职材料，内容均可在仓库代码、README 与 CI 记录中核对。

## 项目一句话定位

用 LangGraph 把跨境售后这个「信息不对称 + 法域碎片化 + 结果不可承诺」的场景，做成一个**读得懂订单、找得到法条、且敢说不知道**的 RAG Agent，并配一套真实跑 LLM Judge 的回归与 CI。

## 简历项目描述（完整版，可直接粘贴）

**CargoGuard · 跨境售后 RAG Agent**（个人项目 | [GitHub](https://github.com/eazincxy/Cargo-guard) | [Live Demo](https://cargo-guard-m6sopr3tsl3q3kua3d9hmz.streamlit.app/)）
技术栈：Python · LangGraph · RAG（向量检索）· LLM · Streamlit · GitHub Actions

- 基于 LangGraph 设计 9 节点状态图（意图 → 记忆 → 规划 → 检索 → 生成 → 自检），将「写操作」用 `interrupt` 挂起接入人工审批，经 `Command(resume)` 恢复执行，实现不可逆动作的可控闭环。
- 构建 6 国消费者法规结构化知识库（42 个检索文档），按国家 tag 做检索隔离防止法条串国；自建检索评测集，HitRate@4 = 1.0、MRR@4 = 0.97，并在 CI 中固化回归。
- 设计三层防幻觉机制：无覆盖时强制回答「知识库暂无」、独立 review 节点做输出合规校验、确定性后处理剥离无出处法条编号；配套 22 个功能测试覆盖拦截规则。
- 搭建 20 条场景化 e2e 回归（含提示注入、隐私、逃税、威胁等对抗用例），以 LLM Judge 自动评分，通过率从 60% 提升至稳定 ≥95%；集成 GitHub Actions（lint / 单测 / Docker 构建 / e2e 报告归档），主分支持续可交付。
- 公开部署 Streamlit Demo，在调用链入口加 2000 字输入截断与敏感信息拒答，兼顾演示效果与 API 成本防护。

## 简历项目描述（精简版，版面紧张时用）

- 用 LangGraph 搭建 9 节点跨境售后 Agent，写操作经 `interrupt` + `Command(resume)` 走人工审批；自建 6 国法规知识库（42 文档），检索 HitRate@4 = 1.0。
- 设计三层防幻觉 + 20 条 LLM Judge e2e 回归（通过率 60%→≥95%）并接入 GitHub Actions，公开部署且带输入截断等成本防护。

## 可核对的关键数字

| 指标 | 数值 | 出处 |
|---|---|---|
| 图节点数 | 9 | `app/after_sales_agent.py` 的 `add_node` |
| 覆盖国家 | 6（US / JP / KR / TH / DE / GB） | `kb/laws/*.yaml` |
| 检索文档数 | 42 | `kb/chunks_emb.json` 构建结果 |
| HitRate@1 / @3 / @4 | 0.955 / 1.0 / 1.0 | `tests/retrieval_eval.py` |
| MRR@4 / Coverage@4 | 0.97 / 0.962 | 同上 |
| e2e 用例数 | 20 | `test_cases.json` |
| e2e 通过率 | 60% → 稳定 ≥95%（本地最优 20/20） | `reports/regression_*.md` |
| 功能测试数 | 22 | `tests/test_agent_features.py` |
| 单条输入上限 | 2000 字符 | `streamlit_app.py` 的 `MAX_INPUT_CHARS` |

## 三条最可能被追问的问题

1. **e2e 通过率为什么不是 100%？**
   LLM 输出存在非确定性，单例偶发漏要点；已定位为模型漂移而非逻辑缺陷，因此设为不阻断绿 + 报告归档人工复核，避免为了全绿去写死断言。

2. **怎么保证不编法条？**
   不是靠提示词「请勿编造」，而是三层结构：知识库无覆盖就说无覆盖、独立 review 节点复核、后处理把正文里无出处的条款号（如「第25条」）确定性地剥离。

3. **为什么写操作要人工审批？**
   升级工单是不可逆副作用，模型判断错无法回滚；用 LangGraph 的 `interrupt` 挂起 + 审批后恢复，把「模型建议」和「系统执行」解耦。

## 架构速讲（30 秒）

START → intent（意图分类）→ load_memory（注入记忆 + 读订单）→ summarize（超长才压缩）→ plan（ReAct 只读工具）→ 命中写操作则 `interrupt` 挂起等人审 → retrieve（知识库检索，按国家隔离）→ answer（生成）→ review（独立合规校验）→ extract_memory（落长期记忆）→ END。
