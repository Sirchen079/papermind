# OpenAlex 检索工具

2026-09-29，随 0.6.23 开发。来源：[PaperSpark 参考研究](paperspark-reference.md)——把公开学术 API 直接暴露给对话 agent，并吸取其"检索页与对话未打通"的教训：这里直接挂进对话工具体系，不做独立检索页。

## 提供了什么

- `search_openalex(query, limit)`：按主题检索公开文献，返回标题、作者、年份、期刊、被引数、DOI、开放获取 PDF 链接与摘要。
- `find_related_openalex(doi | openalex_id, limit)`：给定一篇文献，取 OpenAlex 的相关工作列表。
- 两个工具注册进对话 agent（`app/agent/tools.py`），系统提示说明使用时机：查找库外文献、核实书目、追溯相关工作；拿到 OA PDF 链接后用既有 `import_paper_pdf` 入库再精读，形成"库外找材料 → 入库 → 带入研究"的同一条路径。
- 工具结果进入来源记录（`provenance.py` 的 web 类来源），模型引用可回查。
- OpenAlex 提供不用密钥的免费基础查询，服务有请求额度；免费 API 密钥可提高额度，具体以[当前官方说明](https://help.openalex.org/api/authentication/)为准。当前程序可携带 `openalex_mailto` 设置，不把它当成解除限流的保证。

## 复用与边界

- HTTP 客户端模式沿用 `research_actions.fetch_page` 的做法（httpx 同步、明确超时、UA 标识）；错误返回 JSON 错误对象交给模型处理，不抛断对话。
- 摘要从 OpenAlex 倒排索引重建并截断 1200 字符；无摘要的记录回退为一行题录，保证来源记录不空。
- 返回的是元数据不是全文；被引数是 OpenAlex 口径。没有实现 PaperSpark 的多阶段 LLM 查询扩展管线——先看直接检索是否满足任务，确有缺口再评估。

## 验证状态

`tests/test_openalex_tools.py` 覆盖：检索返回记录与 web 来源、mailto 注入、HTTP 错误与空查询处理、无摘要回退、空结果提示、find_related 两步请求、工具注册，以及网页不冒充 PDF、多个关联 ID 的合法 OR 查询。

2026-09-30，真实 API 验证旧的多个 ID 过滤式返回 400，修复后为 200；实际工具从 `W4408570670` 取回 3 篇关联工作。真实主题搜索与入库见[0.6.24 验证](releases/release-0.6.24-validation.md)。单次流程通过不代表已测得检索覆盖率或科研内容准确率。
