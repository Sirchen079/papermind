# 基于 AI Agent 的论文管理系统 — 设计文档（Spec）

- **日期**：2026-06-28
- **状态**：Draft（待用户审阅）
- **作者**：设计协作产出
- **产品代号**：PaperMind（暂定）

---

## 1. 概述（Vision）

一个**本地单用户 Web 应用**，以 AI agent 为核心驱动论文管理的全部操作：用户把论文交给 AI，AI 自动完成 **解析 → 分析归纳 → 概念抽取 → 索引编排 → 构建知识网状图**，并能与用户进行科研对话、主动提示关联论文、推荐相关研究。

核心理念：**"AI 负责各项操作"** —— 用户是指导者与消费者，AI 是执行者。

### 1.1 核心能力

1. **多源入库**：PDF 上传、ArXiv 抓取、BibTeX 批量导入。
2. **AI 全自动处理流水线**：入库即自动跑完整流水线（摘要 → 抽概念 → 嵌入 → 建图连接），无需手动点击。
3. **双网状图可视化**：论文图谱 + 概念/知识图谱，用户可自主切换。
4. **科研对话**：对话是万能入口，agent 可多步操作（搜库、查图、找相关、激活技能、写综述）。
5. **主动提示**：AI 发现库内关联（方法冲突、可结合、引用关系）时主动推送。
6. **相关论文推荐**：库内语义检索 + 库外（OpenAlex/Semantic Scholar）发现。
7. **多 Provider 支持**：OpenAI Chat Completions、OpenAI Responses、Anthropic Messages、任意 OpenAI 兼容（自定义 base_url），自动拉取模型列表。
8. **自定义技能系统**：四种类型（指令/模板/工具/角色），自动 + 手动激活。
9. **Token 用量统计**：观测每次调用消耗，前端用量面板。
10. **生产级高水准前端**：可视化 + 交互达到交付水准。

### 1.2 非目标（Non-goals，v1 不做）

- 多用户 / 账号体系 / 权限隔离（单用户本地应用）。
- 成本控制 / 预算拦截（仅做 Token 用量观测）。
- 移动端原生 App。
- 代码型技能（type C）的完整沙箱执行（v1 提供 A/B/D，C 作为后续阶段加沙箱）。
- 全文 PDF 编辑/标注（聚焦管理与知识结构）。

### 1.3 设计原则：优先使用模型原生能力，不重复造轮子

凡 LLM provider 已提供原生能力的（web 搜索、代码执行、文件检索、computer use 等），**优先让模型直接使用其原生工具**，而非自建等价实现。自建工具仅用于原生能力覆盖不到的领域（论文库语义检索、图查询、OpenAlex/Semantic Scholar 论文发现）。agent 工具层区分两类：
- **原生工具（pass-through）**：经 LiteLLM 透传给 provider，由模型内置实现（如 Anthropic web search、OpenAI web_search / code_interpreter）。
- **自定义工具**：我们的领域工具（库检索/图/标签等），需自建。

---

## 2. 使用形态与技术栈

- **形态**：本地单用户 Web 应用。后端起服务，浏览器访问。无登录。数据存本地。
- **后端**：Python 3.11+ / FastAPI（异步、SSE 流式）。
- **前端**：React 18 + TypeScript + Vite。开发期独立 dev server，生产构建后由后端托管静态文件，用户只需一条命令启动。
- **AI Provider 统一**：LiteLLM（统一 100+ provider，原生支持 OpenAI 双格式 + Anthropic + 兼容 base_url + 模型列表拉取）。
- **数据库**：SQLite（WAL 模式）+ sqlite-vec（向量）。
- **PDF 解析**：PyMuPDF（正文 + 版面）+ OCR 兜底（Tesseract/PaddleOCR）。GROBID 降级为可选插件。
- **检索/图**：ArXiv 用 `arxiv` 库；BibTeX 用 `bibtexparser`；外部论文元数据用 OpenAlex/CrossRef/Semantic Scholar。
- **图可视化**：Cytoscape.js（双图统一，支持力导向 + 结构化布局）。
- **迁移**：Alembic。
- **加密**：cryptography（Fernet，API Key 加密落盘）。

---

## 3. 整体架构

### 3.1 双进程模型

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend (React/TS, Vite)                                    │
│  Library · PaperGraph · ConceptGraph · Chat · Skills · Settings│
└──────────────────────────────────────────────────────────────┘
              │ REST + SSE（生产期同源托管）
┌─────────────┴─────────────────────────────────────────────────┐
│  API Layer (FastAPI routers)                                   │
│  papers · graph · chat · skills · providers · models ·         │
│  ingest · search · suggestions · usage                         │
├────────────────────────────────────────────────────────────────┤
│  Agent Runtime             │  Ingestion Pipeline                │
│  · Provider 抽象(LiteLLM)   │  · 源适配器(PDF/ArXiv/BibTeX)       │
│  · 工具协议归一化层         │  · 统一解析器(OCR 兜底)              │
│  · agent 循环 + 工具注册    │  · 四阶段状态机(幂等/可恢复)         │
│  · 技能加载器               │  · 概念抽取 + 消解 + 嵌入分块        │
│  · Token 记账               │  · 增量建图                          │
├────────────────────────────────────────────────────────────────┤
│  AI Operations Service（共享，打破 agent↔ingestion 循环依赖）   │
│  summarize · extract_concepts · embed · analyze · resolve…     │
├────────────────────────────────────────────────────────────────┤
│  Knowledge/Graph Layer     │  Chat/RAG Layer                     │
│  · 论文图 + 概念图构建      │  · 检索 · 对话 · 工具增强 · 推荐      │
│  · 增量更新 · 图查询        │                                     │
├────────────────────────────────────────────────────────────────┤
│  Data Layer                                                    │
│  SQLite(WAL) 关系 · sqlite-vec 向量 · 物化图表(节点/边)          │
│  Alembic 迁移 · Fernet 加密                                    │
└────────────────────────────────────────────────────────────────┘
```

### 3.2 关键架构原则

- **洁净分层**：每层职责单一，通过明确接口通信，可独立测试。
- **AI Operations Service 解耦（F11）**：所有"调用 LLM 完成某个原子任务"的能力（摘要、抽概念、嵌入、分析）集中在此服务。Agent Runtime 和 Ingestion Pipeline 都依赖它，**不互相依赖**，消除循环依赖。
- **派生数据为缓存**：图谱边、共现关系等派生数据以原始关系（PaperLink、PaperConcept）为唯一真相，物化表仅作查询缓存，通过失效协议保持一致。

### 3.3 核心数据流

**入库流**：
```
用户加论文(PDF/ArXiv/BibTeX)
  → 源适配器(抓取/解析)
  → 去重 upsert(G2)
  → [parse] 统一解析器(OCR 兜底) → parse_confidence
  → [analyze] AI Operations: 结构化摘要 + 抽概念(带佐证)
  → [concept] 概念归一化 + 消解(合并/新建) (G1)
  → [embed] 分块 + 嵌入(带模型指纹) (G6/F7)
  → [link] 建立 PaperLink(内部+外部) → 增量更新 GraphEdge (F6/G7)
  → 落库 → SSE 通知前端刷新图谱
  → agent 评估与库内关联 → 写 Suggestion(F10) → 主动提示
```

**对话流**：
```
用户消息
  → RAG 检索(chunk 级向量 + 图上下文：相关概念/论文)
  → agent 循环：组装上下文(系统提示 + 激活技能 + 工具)
              → LLM 流式调用(经 Provider 抽象)
              → 若 tool_call → 工具协议归一化 → 执行工具 → 回填 → 继续循环
  → 流式回复(SSE) + 引用芯片(可点击跳转论文)
  → Token 记账
```

---

## 4. 数据模型

存储分三部分：**SQLite（关系）+ sqlite-vec（向量）+ 物化图表（在 SQLite 内）**。所有时间戳存 UTC ISO。以下实体按领域分组，已合并 G1–G14 的修订。

### 4.1 论文与内容

- **Paper**
  - `id`, `source`(pdf/arxiv/bibtex/manual), `source_ref`(arxiv_id/doi/文件路径), `title`, `authors`(字符串数组，v1 不归一化, G10), `abstract`, `year`, `venue`, `doi`(unique, nullable), `arxiv_id`(unique, nullable), `pdf_path`, `full_text`, `parse_confidence`(float, F4), `title_norm`(归一化标题，用于模糊去重, G2), `is_deleted`(软删除, G3), `created_at`, `updated_at`
  - 去重键：`doi` / `arxiv_id` / `title_norm` 模糊匹配（入库 upsert, G2）
- **PaperSection**（可选，结构化章节）：`id`, `paper_id`, `kind`(intro/method/results/...), `content`, `order`
- **Chunk**（G6 分块）：`id`, `paper_id`, `section_id`(nullable), `ordinal`, `text`, `token_count`
  - 嵌入以 chunk 为单位，检索 chunk 级再回聚论文

### 4.2 AI 分析产物

- **AnalysisRun**（G5 版本）：`id`, `paper_id`, `model`, `provider_id`, `started_at`, `finished_at`, `status`, `is_current`(当前生效)
  - 重跑时旧 run 的 `is_current=false`，默认保留历史
- **Summary**：`id`, `paper_id`, `run_id`, `content`(JSON：问题/方法/数据集/结果/局限), `created_at`
- **Concept**：`id`, `name`, `normalized_key`(unique, G1 归一化), `type`(method/dataset/problem/domain), `description`, `parent_concept_id`(nullable, G11 层级), `created_at`
- **PaperConcept**：`paper_id`, `concept_id`, `weight`, `evidence`(论文原文佐证), `run_id`
  - 主键 (`paper_id`, `concept_id`)
- **PaperLink**（G4 拆列）：`id`, `source_paper_id`, `target_paper_id`(nullable, 库内), `target_external_ref`(nullable, 外部引用如 DOI/标题), `type`(cites/related/contradicts/builds_on), `confidence`, `source`(extracted/ai/user), `run_id`, `created_at`
  - 外部论文后续导入时，扫描 `target_external_ref` 回填 `target_paper_id`（G4）
  - `ON DELETE`：源论文删除 → 级联删除其发出的 link（G3）

### 4.3 图（物化缓存，F6/G7）

- **GraphEdge**：`id`, `graph_type`(paper/concept), `source_id`, `target_id`, `edge_type`, `weight`, `dirty`(bool), `computed_at`
  - 论文图边 = PaperLink + 共享概念共现（派生）
  - 概念图边 = 同篇论文共现 + parent_concept 层级
  - **一致性协议**：派生源（PaperLink/PaperConcept）变更 → 标记相关 GraphEdge `dirty=true` → 后台重算 → `dirty=false`。查询可选"容忍脏读"或"触发即时重算"。
  - 增量更新：新增论文只影响其自身节点 + 其涉及的边，不全量重算（F6）

### 4.4 流水线与任务（F2/F3）

- **Job**：`id`, `type`(ingest/reanalyze/reindex/rebuild_vectors), `target_type`(paper/all), `target_id`(nullable, 多态注明 G13), `status`(queued/running/succeeded/failed/partial), `stage`, `progress`(0–1), `error`, `attempts`, `created_at`, `started_at`, `finished_at`
- **PaperPipelineState**：`paper_id`(PK), `parse_status`, `analyze_status`, `embed_status`, `link_status`（各 pending/running/done/failed）, `updated_at`
  - 四阶段状态机，幂等可恢复；启动时扫描 `*_status != done` 的 paper 续跑（F2）

### 4.5 技能

- **Skill**：`id`, `name`(unique), `description`, `type`(instruction/template/tool/persona), `trigger`(auto/keyword/manual/pipeline), `keywords`(JSON，与 frontmatter 一致), `model_role`(nullable，建议路由角色 §5.4), `body`(Markdown 或模块描述), `enabled`, `source`(builtin/user), `file_path`(用户技能源文件), `version`, `updated_at`
  - 用户技能从 `user_skills/` 目录实时读取 + DB 缓存元数据；启用文件监听自动重载

### 4.6 Provider 与模型

- **Provider**：`id`, `name`, `type`(openai_chat/openai_responses/anthropic/openai_compat), `base_url`, `api_key_encrypted`(F12), `extra_headers`(JSON), `enabled`, `created_at`
- **Model**：`id`, `provider_id`, `model_id`, `display_name`, `context_window`, `supports_tools`, `supports_streaming`, `role_default`(nullable：summary/extraction/chat/deep), `fetched_at`, `is_manual`(bool)
  - 自动拉取：调用各 provider 的 `/models` 端点填充；无该端点的 provider 支持手动录入（`is_manual`）
- **Setting**（key-value）：应用级配置，如 `current_embedding_model_fingerprint`（F7 向量失效检测）、默认模型路由、并发上限等

### 4.7 对话与主动提示（F10）

- **Conversation**：`id`, `title`, `active_skills`(JSON), `active_persona`(nullable), `created_at`, `updated_at`
- **Message**：`id`, `conversation_id`, `role`(user/assistant/tool), `content`, `tool_calls`(JSON), `tool_results`(JSON), `model`, `tokens_used`, `created_at`
- **Suggestion**：`id`, `type`(connection/related/contradiction), `from_paper_id`, `to_paper_id`(nullable), `to_external_ref`(nullable), `message`, `status`(unread/read/dismissed), `run_id`, `created_at`
  - 持久化 + 已读状态，SSE 仅作实时推送通道，断连不丢（F10）

### 4.8 用户组织（G12，纳入）

- **Tag**：`id`, `name`, `color`(nullable), `user_created`(bool), `created_at`
- **PaperTag**：`paper_id`, `tag_id`, `created_at`（用户手动标签，独立于 AI Concept）
- **Collection**：`id`, `name`, `description`, `created_at`（用户合集/收藏夹）
- **CollectionPaper**：`collection_id`, `paper_id`, `added_at`

### 4.9 向量与 Token 统计

- **sqlite-vec 虚表**：`(id, owner_id, owner_kind(chunk/paper_summary/concept), embedding, embedding_model_fingerprint)`
  - `owner_kind` 区分嵌入对象：chunk（章节/语义块，主力检索）、paper_summary（论文级摘要向量）、concept（概念向量，用于概念相似推荐）
  - `embedding_model_fingerprint` 用于检测嵌入模型切换导致的向量失效（F7）：切换模型时比对 Setting 中的当前指纹，不一致则提示"重建索引"
- **TokenUsage**：`id`, `provider_id`, `model`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `request_kind`(ingest/chat/skill/embed), `ref_id`(nullable), `created_at`, `day`(日期，便于 rollup, G8)
  - 按日聚合 rollup + 原始行保留期清理（可配，默认 90 天）
- **TokenUsageDaily**（rollup, G8）：`day`, `provider_id`, `model`, `request_kind`, `total_tokens`, `call_count`

### 4.10 索引计划（G9）

- 所有外键加索引
- `Concept.normalized_key`：unique 索引（消解/去重关键）
- `GraphEdge (graph_type, source_id)`、`GraphEdge (graph_type, target_id)`：图邻居查询
- `PaperConcept (concept_id)`、`PaperConcept (paper_id)`：共现计算
- `Paper.title_norm`、`Paper.doi`、`Paper.arxiv_id`：去重
- `Suggestion (status, created_at)`：通知中心
- sqlite-vec：目标规模（几百~几千篇）够用；注明未来可切 ANN（HNSW）（G14）

### 4.11 数据完整性（G3）

- 论文软删除（`is_deleted`）；级联清理 Summary/PaperConcept/Chunk/向量/PaperLink/GraphEdge/Suggestion 引用
- 各表 `ON DELETE CASCADE` / 应用层级联，删除前校验图影响
- 引用完整性由外键约束 + 应用层软删除协议共同保证

---

## 5. 多 Provider 与模型层

### 5.1 Provider 类型与 OpenAI"两种格式"

支持四种 provider 类型（对应 LiteLLM 的不同路由）：

| type | 含义 | 端点 |
|---|---|---|
| `openai_chat` | OpenAI Chat Completions 格式 | `/v1/chat/completions` |
| `openai_responses` | OpenAI Responses API 格式（新） | `/v1/responses` |
| `anthropic` | Anthropic Messages 格式 | `/v1/messages` |
| `openai_compat` | OpenAI 兼容（自定义 base_url：DeepSeek/智谱/Moonshot/SiliconFlow/Ollama 等） | `/v1/chat/completions` |

> "OpenAI 两种格式"覆盖 `openai_chat` + `openai_responses`；兼容第三方走 `openai_compat`。

### 5.2 LiteLLM 封装

- 统一调用接口：`complete(provider, model, messages, tools, stream)` → 归一化的 `Response`（content + tool_calls + usage）。
- 流式：统一 `async for delta in stream_complete(...)`，delta 归一化为 `{content?, tool_call_delta?}`。
- 失败处理：超时重试、限流退避、provider 不可达降级。
- **原生工具透传**：`tools` 同时支持自定义工具与 provider 原生工具（web 搜索、代码执行等），原生工具经 LiteLLM 直接透传，不自建等价实现（§1.3）。

### 5.3 模型列表自动拉取

- 每个 provider 提供"刷新模型"操作：调用对应 `/models` 端点（OpenAI/Anthropic/兼容均有），结果写入 `Model` 表，记 `fetched_at`。
- 无 `/models` 端点的 provider：手动录入（`is_manual=true`）。
- 前端设置页展示已拉取模型，可标记某模型的默认用途（role_default）。

### 5.4 模型路由（按任务）

- 不同任务可用不同模型，用户在设置中配置默认路由：
  - `summary`（摘要，可用便宜模型）
  - `extraction`（概念抽取，需结构化输出能力）
  - `chat`（对话，需强模型）
  - `deep`（深度评审/综述，用最强模型）
  - `embedding`（嵌入，本地或 API）
- **任务→角色映射**：入库摘要=summary、概念抽取=extraction、对话=chat、深度评审/综述=deep、向量化=embedding。
- Agent/流水线按任务类型取对应模型；未配置则用 provider 默认模型。

### 5.5 Token 记账（F8 → 观测）

- 每次 LLM 调用在 Provider 封装层统一记录 `TokenUsage`（provider/model/kind/tokens/ref_id）。
- 不做预算拦截；前端用量面板按 时间/provider/模型/用途 聚合展示（来自 `TokenUsageDaily` rollup）。

---

## 6. Agent 运行时与技能系统

### 6.1 Agent 循环

```
输入：任务/消息 + 上下文
 1. 组装上下文：系统提示 + 激活技能(persona/template/instruction) + 可用工具描述
 2. 调用 LLM（Provider 抽象，流式）
 3. 若返回 tool_calls：
      → 工具协议归一化（F5）
      → 执行工具（经 Tools Registry）
      → 把结果作为 tool message 回填
      → 回到步骤 2
 4. 流式输出最终回复（SSE）+ 引用芯片
 5. 记账 TokenUsage
```

- 最大循环深度限制，防止无限工具调用。
- 每步可中断（用户停止生成）。

### 6.2 工具协议归一化层（F5）

- **问题**：OpenAI Chat / OpenAI Responses / Anthropic 三家的 tool-call 增量 delta 拼装规则不同，流式下增量 JSON 易拼错。
- **方案**：在 LiteLLM 之上加一层归一化：
  - 统一 `Tool` 描述格式（JSON Schema）。
  - 流式 delta 累积器：按 provider 适配增量拼装，缓冲到 tool_call 完整（参数 JSON 可解析）后再派发，**不裸用流式 tool-call**。
  - 完整性校验：参数 JSON Schema 校验失败 → 回喂 LLM 修正。

### 6.3 工具注册表（Tools Registry）

agent 可调用的工具（每个是 AI Operations Service 或知识层之上的薄封装）：

| 工具 | 作用 |
|---|---|
| `search_library` | 库内语义检索（chunk 级向量） |
| `get_paper` | 取论文详情/摘要/概念 |
| `query_graph` | 查图（邻居/路径/共现） |
| `find_related_internal` | 库内相关论文（语义+图邻近） |
| `find_related_external` | 库外推荐（OpenAlex/Semantic Scholar） |
| `apply_skill` | 显式激活某技能 |
| `manage_tags` / `manage_collections` | 用户标签/合集操作 |
| `create_suggestion` | 生成主动提示记录 |
| `reanalyze_paper` | 触发某篇重新分析（经 Job） |

> **原生工具（pass-through）**：通用 web 搜索 / 代码执行等**不**自建 —— 优先透传 provider 原生工具（Anthropic web search、OpenAI web_search / code_interpreter 等，§1.3）。自定义工具仅用于领域逻辑（库检索 / 图 / 论文 API）。

### 6.4 AI Operations Service（F11 解耦）

集中所有"调用 LLM 完成原子任务"的能力，Agent 与 Ingestion 共用：

- `summarize(paper) → Summary`（结构化）
- `extract_concepts(paper) → [(name, type, evidence)]`
- `resolve_concepts(raw_concepts) → [Concept]`（归一化 + 消解, G1）
- `embed(texts) → [vector]`（本地或 API，带指纹）
- `analyze_relations(paper, library) → [PaperLink + Suggestion]`

> 对话（chat）由 Agent Runtime 编排（§6.1），**不在 AI Ops 内** —— AI Ops 只提供原子能力，agent 组合调用它们完成任务。

依赖方向：Agent Runtime → AI Ops Service ← Ingestion Pipeline（单向，无循环）。

### 6.5 技能系统（四种类型统一）

技能格式：Markdown 文件 + YAML frontmatter：

```markdown
---
name: deep-review
description: 深度评审一篇论文的结构、方法、贡献与局限
type: instruction            # instruction | template | tool | persona
trigger: manual              # auto | keyword | manual | pipeline
keywords: [评审, review, 深度分析]
applies_to: [chat]           # chat | ingest | both
model_role: deep             # 建议用哪个路由模型
---

# 深度评审框架
请按以下结构评审：1. 研究问题  2. 方法论  ...
```

| 类型 | 说明 | body 内容 | v1 |
|---|---|---|---|
| instruction (A) | 改变 AI 行为的指令 | Markdown 提示框架 | ✅ |
| template (B) | 处理模板（定义抽取字段/流程） | 字段定义 + 处理步骤 | ✅ |
| persona (D) | 角色人格 | 系统提示词 | ✅ |
| tool (C) | 可执行代码扩展能力 | 模块描述 + 沙箱执行规范 | ⏳ 后续（带沙箱） |

**加载**：扫描 `user_skills/` + 内置技能 → 注册 → DB 缓存元数据；文件监听自动重载。

**激活规则**：
- `auto`：agent 根据对话上下文与技能 `description` 做相关性匹配，自动注入（轻量匹配，非 LLM 判定，控成本）。
- `keyword`：命中 `keywords` 时激活。
- `manual`：用户/agent 显式 `apply_skill`。
- `pipeline`：入库流水线阶段自动应用（如某个 template 定义入库抽取字段）。

**代码型技能（C）执行**：优先复用 provider 原生代码执行（Claude code execution、OpenAI code interpreter，§1.3）；仅当原生不可用或需特定能力时才设计独立子进程沙箱（文件/网络白名单）。v1 不启用，后续阶段实现。

---

## 7. 入库流水线（Ingestion Pipeline）

### 7.1 源适配器

- **PDF 上传**：保存到 `data/pdfs/`，交统一解析器。
- **ArXiv**：`arxiv` 库取元数据 + PDF → **PDF 交同一解析器**（F14，不重复造解析路径）。
- **BibTeX**：`bibtexparser` 解析条目 → 每条按 DOI/标题经 OpenAlex/CrossRef 补全元数据 → 可选抓全文 PDF（经 Unpaywall/OpenAlex 取 OA 全文链接）。

### 7.2 去重（G2）

入库第一步：按 `doi` → `arxiv_id` → `title_norm`（归一化标题，去空格/小写/去标点）模糊匹配查库：
- 命中 → upsert 合并（补全缺失字段），已有的分析保留。
- 未命中 → 新建 Paper。

### 7.3 统一解析器（F4/F14）

```
PDF → PyMuPDF 抽文本 + 版面检测(栏/节)
     → 若文本量过低(疑似扫描件) → OCR 兜底(Tesseract/PaddleOCR)
     → 结构化：分节(PaperSection) + 计算解析置信度(parse_confidence)
     → 抽取参考文献列表 → 候选外部 PaperLink
```
- `parse_confidence` 低 → 在 UI 标记"解析质量低"，AI 分析带降级提示。
- GROBID 仅作为可选插件（需 JVM/Docker），默认不启用（F9）。

### 7.4 四阶段状态机（F3）

每篇 Paper 一条 `PaperPipelineState`，四阶段：

```
parse → analyze → embed → link
```
- 每阶段：`pending / running / done / failed`。
- **analyze 阶段内部**（§3.3 流程图中的"分析"与"概念消解"两步均属此阶段，产出在同一 `AnalysisRun` 下）：结构化摘要（Summary）+ 概念抽取与消解（§7.5）。
- **幂等**：每阶段可重入，以 `AnalysisRun` 隔离历史。
- **失败**：记录 error，可重试；AI 阶段失败可降级（换便宜模型重试）。
- **可恢复（F2）**：服务启动时扫描所有 `*_status != done` 的 paper，重新入队 Job 续跑。

### 7.5 概念抽取与消解（G1）

- AI 抽出原始概念（name/type/evidence）。
- **归一化**：小写 + 词形还原 + 同义表 → `normalized_key`。
- **消解**：与库内已有 Concept 按 `normalized_key` 匹配 → 命中则合并（复用概念，新增 PaperConcept）；未命中则新建 Concept。
- **层级（is-a）**：抽取概念间上下位关系（如 "注意力机制" is-a "序列建模"），赋值 `parent_concept_id`；同一 AnalysisRun 内完成 —— 这是 §8.2 概念图层级边的来源。
- 这是概念图可用的前提（否则碎片化）。

### 7.6 分块与嵌入（G6/F7）

- 按 PaperSection / 语义切分为 Chunk。
- 嵌入每个 Chunk（+ 论文级摘要），向量带 `embedding_model_fingerprint`。
- 检索走 chunk 级，再回聚到论文。

### 7.7 建图连接与增量更新（F6/G7）

- 建立 PaperLink：内部（引用库内论文）+ 外部（参考文献指向库外）+ AI 关系判定。
- 触发 GraphEdge 增量更新：仅重算该论文涉及的节点 + 边，标记/清理 dirty。
- 不全量重算图谱（F6）。

### 7.8 并发与持久化（F1/F2）

- 入库任务进 Job 队列，worker 按并发上限（Setting 可配）处理。
- SQLite WAL + 单写者 asyncio 锁：读并发、写串行，规避锁死（F1）。
- Job 持久化，崩溃可恢复（F2）。

---

## 8. 知识图谱层

### 8.1 论文图谱（Paper Graph）

- **节点**：论文。
- **边**：引用（PaperLink:cites）、相关性（PaperLink:related/contradicts/builds_on）、共享概念共现（派生）。
- 布局：dagre（引用层次）/ cose（力导向）。

### 8.2 概念图谱（Concept Graph）

- **节点**：概念。
- **边**：同篇论文共现（权重=共现次数）、is-a 层级（parent_concept_id）。
- 布局：Cola / force-directed。

### 8.3 构建与一致性（F6/G7）

- 派生源（PaperLink / PaperConcept / Concept.parent）为唯一真相。
- `GraphEdge` 物化为查询缓存；派生源变更 → dirty → 后台重算。
- 增量更新：单篇入库只影响局部，不全量重算。
- 大图布局在前端 Web Worker 内跑，避免阻塞 UI（F6）。

### 8.4 图查询

- 邻居（一阶/多阶）、最短路径、子图提取、按概念/作者/年份过滤、聚类社区发现（可选）。
- **规模化可读性**：概念图按出现频次/权重过滤（默认仅显示出现在 ≥N 篇论文中的概念，N 可调），避免概念爆炸不可读；论文图支持聚焦子图。
- 供 Chat/RAG 与前端共用。

---

## 9. 科研对话与 RAG

### 9.1 对话即万能入口

用户在 Chat 中用自然语言下达指令，agent 经多步工具调用完成任务：搜库、查图、找相关、激活技能、改标签、写综述、生成主动提示。

### 9.2 RAG 检索

```
用户消息 → 嵌入查询
  → chunk 级向量检索(top-k)
  → 回聚到论文 + 取其 Summary/Concept
  → 图上下文：相关概念、邻近论文、引用链
  → 组装进 agent 上下文
```

- **引用接地（citation grounding）**：助手回复只能引用本次检索命中的论文/chunk，引用芯片绑定检索源 ID；禁止引用未检索到的论文（系统提示约束 + 输出后校验芯片合法性），避免幻觉引用。

### 9.3 相关论文推荐

- **库内**：语义相似（向量）+ 图邻近（共享概念/引用）。
- **库外**：按概念/DOI/引用经 OpenAlex / Semantic Scholar API 发现，结果可一键入库。

### 9.4 主动提示（F10）

- 入库后 agent 评估新论文与库内既有论文的关联（方法冲突、可结合、引用）。
- 生成 `Suggestion`（持久化 + unread 状态）。
- 前端通知中心展示；若用户在线，经 SSE 实时推送。

---

## 10. 前端架构

### 10.1 技术选型

- React 18 + TypeScript + Vite。
- UI：shadcn/ui + Tailwind CSS（现代、可定制、高质感）。
- 动效：Framer Motion（微交互、过渡）。
- 状态：Zustand（客户端）+ TanStack Query（服务端状态）+ SSE hooks。
- 图可视化：Cytoscape.js（双图统一）。
- 大图布局：Web Worker（F6，不阻塞 UI）。
- Markdown：react-markdown + remark/rehype（含公式 KaTeX、引用芯片）。

### 10.2 页面/视图

| 视图 | 说明 |
|---|---|
| **Library** | 论文列表/网格，筛选（标签/合集/概念/年份/来源）、批量操作、入库入口 |
| **PaperGraph** | 论文网状图，节点=论文，交互（点开详情、过滤、布局切换） |
| **ConceptGraph** | 概念网状图，节点=概念，力导向，点概念看相关论文 |
| **Chat** | 科研对话，流式、工具调用可见、引用芯片可跳转、激活技能/角色 |
| **PaperDetail** | 论文详情抽屉/页：元数据、AI 摘要、概念、引用、用户标签、原文 |
| **Skills** | 技能管理：启用/禁用、新建/编辑（Markdown 编辑器）、查看触发规则 |
| **Settings** | Provider/模型管理、模型路由、自动拉模型、并发上限、嵌入模型、数据/迁移 |
| **Usage** | Token 用量面板（按时间/provider/模型/用途） |
| **Notifications** | 主动提示中心（Suggestion 列表，已读/忽略） |

### 10.3 图可视化交互

- 平移/缩放、节点拖拽、悬停高亮邻居、点击展开详情、框选、布局切换、按属性过滤/着色。
- 性能：Web Worker 布局 + 视口裁剪渲染（大图不卡）。

### 10.4 设计水准

- 统一设计系统（色板、字号、间距、阴影、动效曲线）。
- 暗色/亮色主题。
- 空状态、加载态、错误态、流式打字态均有打磨。
- 响应式（桌面优先，平板可用）。

---

## 11. API 设计（FastAPI）

### 11.1 REST（节选）

```
POST /api/ingest                 # 入库（PDF/ArXiv/BibTeX），返回 job_id
GET  /api/papers                 # 列表（筛选/分页）
GET  /api/papers/{id}            # 详情
PATCH/api/papers/{id}            # 改标签/合集关联
DELETE /api/papers/{id}          # 软删除
GET/POST/DELETE /api/tags             # 标签 CRUD
GET/POST/DELETE /api/collections       # 合集 CRUD
POST/DELETE  /api/collections/{id}/papers  # 合集成员管理
GET  /api/graph/{type}           # 图数据（paper/concept），支持子图/过滤
GET  /api/graph/{type}/query     # 邻居/路径查询
POST /api/chat/conversations      # 新建对话
POST /api/chat/conversations/{id}/messages   # 发消息（触发 SSE 流）
GET  /api/search                 # 语义检索
GET  /api/suggestions            # 主动提示列表
PATCH/api/suggestions/{id}       # 标记已读/忽略
GET  /api/skills                 # 技能列表
POST /api/skills                 # 新建/更新技能
GET  /api/providers              # provider 列表
POST /api/providers              # 新增 provider
POST /api/providers/{id}/models  # 刷新模型列表
GET  /api/models                 # 模型列表
PUT  /api/settings/model-routing # 模型路由配置
GET  /api/usage                  # Token 用量统计
```

### 11.2 SSE 流

```
GET /api/chat/conversations/{id}/stream   # 对话流式回复
GET /api/ingest/{job_id}/stream           # 入库流水线进度
GET /api/events                           # 全局事件（主动提示、任务完成）
```

### 11.3 鉴权

- 本地单用户，默认无鉴权。
- 若绑定非 localhost，可选简单 token（Setting 配置）。

---

## 12. 跨切面关注点

### 12.1 错误处理

- 分层处理：Provider 错误（重试/降级）→ 流水线错误（记 Job + 状态 failed + 可重试）→ API 错误（用户友好消息）。
- 解析置信度低 → UI 标记 + AI 降级提示。
- 全程结构化日志。
- **无 Provider 降级**：未配置 provider 或 API 不可用时，仍可入库/解析/手填元数据/打标签；AI 阶段入队等待，provider 恢复后自动续跑（R11）。

### 12.2 安全

- API Key：Fernet 对称加密落盘（master key 机器本地，不进 git, F12）。
- 上传 PDF 限制大小/类型；路径不穿越。
- 代码型技能沙箱（C 型）后续阶段实现（子进程 + 能力白名单）。

### 12.3 数据迁移（F13）

- Alembic 管理 schema 迁移；启动时自动 upgrade head。

### 12.4 可观测性

- TokenUsage / TokenUsageDaily（用量）。
- Job / PaperPipelineState（任务状态）。
- parse_confidence（解析质量）。
- 结构化日志（文件 + 控制台）。

### 12.5 并发控制

- 入库 worker 并发上限（Setting 可配，默认 2）。
- SQLite WAL + 单写者锁（F1）。

### 12.6 备份与导出（R7）

- 库导出：JSON（元数据/AI 产物/标签/合集）与 BibTeX（元数据）。
- DB 备份：一键复制 SQLite 文件（WAL checkpoint 后）。
- 研究者数据不可丢 —— 导出/备份为生产基本能力。

---

## 13. 测试策略

### 13.1 后端（pytest）

- 单元：每个模块（Provider 抽象、AI Ops、流水线阶段、图构建、概念消解）。
- 集成：端到端入库流水线、agent 多步对话、图增量更新。
- Provider mock：用录制好的响应夹具（cassette）做确定性测试，不依赖真实 API。
- 数据层：去重（G2）、软删除级联（G3）、概念消解（G1）专项测试。

### 13.2 前端（Vitest + React Testing Library）

- 组件单测、SSE hook 测试、图交互测试。

### 13.3 端到端（Playwright）

- 关键流：入库 → 看图 → 对话 → 推荐 → 标签。

### 13.4 LLM 行为测试

- 用固定响应验证 agent 循环、工具调用归一化（F5）、技能激活。

---

## 14. 项目结构

```
论文管理/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI routers
│   │   ├── agents/           # agent 循环、工具注册、技能加载
│   │   ├── providers/        # LiteLLM 封装、模型拉取、Token 记账
│   │   ├── ai_ops/           # AI Operations Service（共享）
│   │   ├── ingestion/        # 源适配器、统一解析器、流水线、状态机
│   │   ├── knowledge/        # 图构建、增量更新、查询、推荐
│   │   ├── chat/             # RAG、对话管理
│   │   ├── models/           # SQLModel/SQLAlchemy 实体
│   │   ├── db/               # SQLite、sqlite-vec、Alembic 迁移
│   │   ├── security/         # Fernet 加密、沙箱(后续)
│   │   ├── skills/           # 内置技能
│   │   └── config.py
│   ├── user_skills/          # 用户自定义技能（.md）
│   ├── data/                 # SQLite、向量、上传 PDF（gitignore）
│   ├── migrations/           # Alembic
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── pages/            # Library, PaperGraph, ConceptGraph, Chat, Skills, Settings, Usage, Notifications
│   │   ├── components/       # GraphCanvas, ChatPanel, PaperCard, SkillEditor, UsageChart...
│   │   ├── api/              # REST 客户端、SSE hooks
│   │   ├── store/            # Zustand stores
│   │   ├── workers/          # 图布局 Web Worker
│   │   └── styles/
│   ├── package.json
│   └── vite.config.ts
├── docs/superpowers/specs/
└── scripts/                  # 一键启动脚本（起后端 + 托管前端）
```

---

## 15. 分阶段路线图（Phasing）

| 阶段 | 交付 |
|---|---|
| **P0 脚手架** | 后端/前端骨架、SQLite+sqlite-vec、Alembic、Provider 层（LiteLLM）、设置页、加密 |
| **P1 入库与解析** | PDF/ArXiv/BibTeX 源适配器、统一解析器（OCR 兜底）、去重、Paper 存储、四阶段状态机、可恢复 Job、Token 记账（Provider 层，随首次 LLM 调用） |
| **P2 Provider 与 Agent** | 模型自动拉取、模型路由、Agent 循环、工具协议归一化、用量面板（前端） |
| **P3 概念与知识图** | 概念抽取+消解、分块嵌入、论文图+概念图构建、增量更新、双图可视化 |
| **P4 对话与推荐** | RAG 检索、对话万能入口、库内+库外推荐、主动提示中心 |
| **P5 技能系统** | instruction/template/persona 技能、加载与激活（auto/keyword/manual/pipeline）、技能管理 UI |
| **P6 前端打磨** | 设计系统、动效、暗色主题、空/加载/错误态、响应式 |
| **P7 测试与交付** | 单测/集成/E2E、Provider mock、一键启动、文档、打包 |

> 代码型技能（C 型 + 沙箱）作为 P5 之后的独立阶段。

---

## 16. 审查修订记录

本设计经两轮 `code-review` 视角自审，以下问题已折叠进对应章节：

- **架构层（F1–F14）**：见 §3、§5、§6、§7、§12。
- **数据模型（G1–G14）**：见 §4。
- **全文审查（R1–R11，成稿后第三轮）**：概念层级构建（§7.5）、AI Ops 边界（§6.4）、引用接地（§9.2）、概念图规模化过滤（§8.4）、Token 记账时序（§15）、标签/合集 CRUD（§11.1）、备份导出（§12.6）、技能字段对齐（§4.5）、模型角色映射（§5.4）、BibTeX OA 来源（§7.1）、无 Provider 降级（§12.1）。

关键决策：
- F8（成本控制）→ 用户决定改为 Token 用量统计（§5.5、§4.9）。
- G12（用户标签/合集）→ 用户确认纳入（§4.8）。
- G10（作者归一化）→ v1 只存字符串，推迟（§4.1）。
- C 型代码技能 → 后续阶段加沙箱（§6.5、§1.2）。

---

## 17. 待办与开放问题

- 产品最终命名（暂用 PaperMind）。
- C 型技能沙箱的具体技术方案（子进程 + WASM？）— 留待后续阶段细化。
- 库外推荐 API 的选择与速率限制策略（OpenAlex 免费无 key；Semantic Scholar 需考虑限频）。
- 是否需要"作者视图"（决定是否启动作者归一化）。
