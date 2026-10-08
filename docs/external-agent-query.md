# 外部 AI 工具的资料库查询

2026-09-29，随 0.6.23 开发。来源：[PaperSpark 参考研究](paperspark-reference.md)第二轮结论中优先级最高的一项。设计动机：用户的真实工作流是多工具协作（GPT、ZCode、Codex 接力处理同一研究项目），此前外部工具查 PaperMind 资料库只能靠人工导出复制。

## 提供了什么

- `GET /api/agent/summary`：应用版本、论文总数、已建索引论文数、最近论文、最近保存的研究文档。供外部工具定位库的规模和最新活动。
- `GET /api/agent/search?q=&top_k=&paper_ids=`：调用与对话助手完全相同的 `search_paper_text`（混合检索 + 关键词降级），返回论文编号、原文片段与页码。
- 两个端点都要求 `X-Local-Token`（同安装版 `api_token` 文件）。现有面向自带前端的只读 API 行为不变。
- `<数据目录>/agent_access.json`：服务绑定端口时写入实际端口、进程号和启动时间（桌面版 4278 被占用会换随机端口，外部工具以此文件发现端口）。文件仅作提示，存活以 `/api/health` 为准。
- `skills/papermind-library/SKILL.md`：给外部 CLI 工具（Claude Code、Codex、ZCode 等）的技能文件，说明服务发现、token 获取、查询流程与失败处理。用户可将其放入所用工具的技能目录。

## 复用与边界

- 检索实现直接复用 `app/agent/paper_search.py`，不另建检索面；语义检索依赖已配置的向量模型，不可用时按既有行为降级为关键词结果，响应中 `retrieval_mode` 如实标注。
- 没有引入 PaperSpark 的"浏览器快照中继"设计：PaperMind 数据本在后端 SQLite，不需要快照文件；也不接受其无鉴权本地接口的做法，新端点一律带 token。
- 端点只读，不提供任何写操作；多项目通过现有 `/api/w/{workspace_id}` 前缀访问，`GET /api/workspaces` 列出项目。
- `agent_access.json` 在进程异常退出后可能残留旧端口；技能文件指引外部工具以 health 检查为准，不把文件当权威。

## 验证状态

`tests/test_agent_query_api.py` 覆盖：无 token 403、summary 字段、检索在无向量模型时降级为关键词并返回正确页码、paper_ids 参数与非法参数 422。真实外部工具的端到端使用（发现端口→取 token→查库→取方法段落）随 0.6.23 发布验证记录。未验证：token 轮换后外部工具的自动恢复、非默认数据目录的发现。
