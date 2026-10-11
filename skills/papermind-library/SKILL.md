---
name: papermind-library
description: 查询用户本机 PaperMind 论文资料库：检索论文正文、读取论文、精读卡片、文献地图和已保存研究文档，并可按用户要求写回笔记、想法与文档。当任务涉及用户已有的论文库、保存过的研究成果或需要先查本地材料再决定是否联网时使用。
---

# PaperMind 本地资料库查询

PaperMind 是运行在本机的研究工作台（论文库 + 阅读 + AI 研究对话）。有两种接入方式，都需要本机令牌：

- **MCP（优先）**：如果当前环境已配置名为 `papermind` 的 MCP 服务，直接调用它的工具（search_library、search_paper_text、get_paper、get_paper_full_text、get_paper_card、read_literature_map、read_paper_notes、search_saved_documents、save_paper_note、save_research_idea、save_document 等），不需要下面的 HTTP 步骤。配置地址为 `http://127.0.0.1:<port>/api/w/<workspace_id>/mcp`，请求头 `X-Local-Token: <token>`。
- **只读 HTTP**：未配置 MCP 时，按下文用本地 HTTP 接口查询。所有请求带 `X-Local-Token` 头。

## 1. 找到服务与凭据

1. 数据目录：桌面安装版为 `%LOCALAPPDATA%\PaperMind\data`；用户自定义时直接问用户。
2. 端口：读 `<数据目录>\agent_access.json` 的 `port`（或 `api`）。文件缺失时先试 `4278`。
3. 令牌：读 `<数据目录>\api_token` 的全部内容（单行）。
4. 探活：`GET http://127.0.0.1:<port>/api/health`。

多项目：`GET /api/workspaces` 列出项目；对非默认项目，把路径前缀 `/api` 换成 `/api/w/<workspace_id>`，其余不变。

## 2. 常用查询（均需 token 头）

| 目的 | 请求 |
|---|---|
| 总览（版本、论文数、最近论文、最近成果） | `GET /api/agent/summary` |
| 按研究问题检索正文片段（语义+关键词，返回论文 id、原文、页码） | `GET /api/agent/search?q=<问题>&top_k=6`（可加 `&paper_ids=1,2` 聚焦） |
| 按标题/作者/关键词列论文 | `GET /api/papers?q=<词>&limit=50` |
| 论文详情（摘要、标签、阅读状态） | `GET /api/papers/<id>` |
| 已转换全文 Markdown（含 `<!-- page:N -->` 页标记） | `GET /api/papers/<id>/document/markdown` |
| 已保存研究文档（含人工修订与来源） | `GET /api/chat/saved-documents?limit=50`；单篇 `GET /api/chat/saved-documents/<message_id>?filename=<名>` |

推荐流程：探活 → `summary` 了解库 → `agent/search` 或 `papers?q=` 定位 → 取 `document/markdown` 读相关页。检索无命中不代表原文没有相关内容——未建索引的论文也可直接读全文。已做过专题综述的论文，优先用 MCP 的 get_paper_card、read_literature_map 读取精读卡片和文献地图，比重读全文快。

## 3. 失败处理

- 连接被拒/超时：PaperMind 未运行。请用户启动 PaperMind 后重试，不要自行拉起服务。
- 403：token 变了，重新读 `api_token`。
- 503：目标项目未就绪；换 `workspaces` 列表里的其他项目或告知用户。
- 结果为空：换关键词或改读全文，如实说明未找到。

## 4. 边界

- HTTP 接口只读。写回（保存笔记、想法、文档）只通过 MCP 的 save_* 工具，并且在用户要求保存时才调用。不在回答中展示 token 内容。
- 这里只提供材料；研究判断、比较和结论仍需你基于原文完成并标明页码出处。
- 响应中的片段是检索候选，不是已验证结论；关键数字回到 `document/markdown` 相应页核对。
