# PaperSpark 参考研究

核查日期：2026-09-25。项目：https://github.com/zongxi1115/PaperSpark 。固定版本：`8703a784e0668a96649300b935caf5fa97150fcd`。

## 许可证决定本轮复用方式

该版本 LICENSE 为 CC BY-NC 4.0（署名、标注修改、非商业使用），不是无非商用限制的 MIT 或 Apache-2.0。许可证：https://github.com/zongxi1115/PaperSpark/blob/8703a784e0668a96649300b935caf5fa97150fcd/LICENSE 。条款：https://creativecommons.org/licenses/by-nc/4.0/ 。

本轮仅研究产品和功能设计，不把其源码、提示词、图像或素材复制到 PaperMind 发行包，也不改写其代码后宣称独立授权。检查用的仓库快照单独放在开发工作区外侧。未来直接复用时，先明确使用与分发方式是否满足非商业条件，或者取得额外许可。

2026-09-25 补充核对：用户说明项目意图也是非商业使用，允许在遵守协议的前提下直接复用优秀实现。但当前工作仓库 `LICENSE` 为 GNU GPL v3，README 的徽章和许可声明同样为 GPL-3.0；没有找到本仓库的非商业许可文本。GPL 允许商业使用，不能将其视为 CC BY-NC 的同类许可。此处记录的是现有文件与用户意图的差异，尚未改动主许可证，也未把 CC BY-NC 代码合并到 GPL 源码中。具体复用需要对应真实许可证及代码权利范围；功能研究和独立实现继续推进。参考：[GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.en.html)、[CC BY-NC 4.0 条款](https://creativecommons.org/licenses/by-nc/4.0/legalcode.en)。

## 真正值得借鉴的实现方向

| 方向 | 读到的实现 | 对 PaperMind 的价值和取舍 |
| --- | --- | --- |
| 文稿操作有明确目标 | `lib/agentTooling.ts` 区分读取文稿、添加批注、编辑文稿，编辑操作绑定具体块 | 优先发展局部修订与预览；避免用户只要求改一段却被整篇重写。具体实现应使用 PaperMind 的文稿和版本模型 |
| 批注能够回到原句 | `lib/agentToolRuntime.ts` 将意见关联选文、块和严重程度；`lib/comments/commentAnchors.ts` 解析位置 | 用“问题片段—原因—建议”代替整篇宽泛评分，定位失败时保留可阅读意见，不清空草稿 |
| 版本是独立持久数据 | `lib/documentVersionStore.ts` 使用 IndexedDB 保存文稿版本，并处理旧数据迁移 | PaperMind 已有 SQLite 综述版本；应继续增加局部修改预览和恢复能力，不需要为了模仿而更换存储栈 |
| 引用既能识别也能回查 | `lib/citationLinks.ts` 区分标识符链接、原有 URL 与标题搜索 | 可以扩充 DOI/arXiv 等入口，但搜索链接不能冒充已核验文献。现有 [P编号] 原文侧栏继续保留 |
| 按研究任务提供工具 | `lib/agentTooling.ts` 和审稿接口按能力定义输入和结果 | 本轮完整技能库采用“发现技能—按任务加载—读引用资源”，使技能能使用真实工具，而不是只显示名字 |
| 导出可继续写作 | README 与 `lib/latexExporter.ts` 提供 Markdown、TeX、LaTeX Zip 路线 | 当前先确保综述 Markdown、引用与版本可用；LaTeX/BibTeX 可作为后续独立交付目标 |

以上是源码结构和产品思路研究，不代表其所有功能已在 PaperMind 实现。当前版本没有移植 PaperSpark 的富文本编辑器、块级审稿批注或 Zotero 同步。

## 不照搬的部分

- 不把其 JSON 审稿输出约束扩展成“综述必须通过审稿才能显示”。
- 不采用通过冗余化、拉长句子来降低 AI 检测概率的写作目标；正文质量仍以论证、准确和可读性为准。
- 不导入另一套大型前端和存储系统来替换当前应用；优先复用已经可用的论文、证据和版本数据。

## 建议优先级

首先做段落级修改预览与来源定位，然后完善结构化引用与写作导出，再评估更复杂的富文本编辑和多智能体交互。每项改进都应通过一个真实研究任务验证，不以功能数量作为目标。

## 按段修改与版本恢复（0.6.3）

已独立实现段落定位、AI 修改预览、局部应用、草稿保存和恢复历史版本。恢复操作生成新版本，保留中间修改。浏览器实测覆盖刷新恢复草稿、模型未配置时保留手工编辑、仅替换目标段落和版本恢复；真实 AI 段落修改效果仍待评审。

综述材料选择改为覆盖研究问题、方法机制、结果条件与讨论。章节写作合并索引召回和逐篇原文快照，即使索引尚未建立也能选取相关方法原文。来源选择、综述流程、编辑、技能及模型调用相关 39 项测试通过；三篇公开论文的原文抽样已补回此前遗漏的 RAG 模型机制、DPR 方法和 ColBERT 架构。该结果证明材料覆盖改善，尚不能作为最终综述质量通过的结论。

## 第二轮研究（2026-09-29）：数据桥、解析架构与其余子系统

复查确认远程 HEAD 仍为 `8703a784`（v1.3.1，2026-05-13），无新提交；许可证结论不变，继续仅作设计参考。检查快照位于 `D:/tmp/paperspark-20260929`（工作区外侧）。本轮覆盖首轮未研究的子系统：外部工具数据技能包、模块化解析引擎、OpenAlex 检索管线、自动知识图谱、论文生成网页、画布与代码执行。

### 最值得吸收：面向外部 AI 工具的数据技能包

PaperSpark 把浏览器工作区数据经本地服务暴露给 Claude Code、Codex 等外部 CLI 工具：写入点发事件、防抖后全量快照 POST 到 `/api/workspace-cli/snapshot` 落地 JSON（`lib/workspaceSnapshotClient.ts`、`lib/server/workspaceBridge.ts`）；CLI（`scripts/paperspark-data-cli.mjs`）经 `POST /api/workspace-cli/query` 执行 `summary/list/get/dump/search` 五个命令；`skills/paperspark-workspace-data/SKILL.md` 是给外部 agent 的操作手册（先 summary 探活、list 发现 id、get 取全文、search 兜底，含服务未启动时的恢复话术），另有 `agents/openai.yaml` 供不同工具发现。响应自带 `exportedAt` 新鲜度，设置脱敏只导出 `hasApiKey` 布尔。

这个方向与本项目用户的真实工作方式直接吻合：用户同时使用 GPT、ZCode、Codex 处理同一研究项目（0.6.22 交付即由多工具接续完成），目前外部工具查 PaperMind 资料库没有稳定入口，只能靠人工导出复制。PaperMind 具备比 PaperSpark 更好的实现条件：数据本就在后端 SQLite，有 `X-Local-Token` 鉴权和混合检索，不需要"浏览器→快照文件→HTTP"中继，也不必接受它无鉴权、子串搜索、每次变更 O(全库) 重建快照的缺陷。落地方式应是：挑选只读查询子集（检索论文、取全文片段、列文档与笔记，复用现有 API 与混合检索），配一份可放入外部工具技能目录的 SKILL 文档；验收用外部 CLI 工具实际完成一次"库内找论文并取方法段"的任务，同时核对密钥不外泄、写操作不可达。

### 值得吸收：模块化解析引擎的接入设计

PaperSpark 的解析架构是"默认 pdfjs + 可选高级引擎（本地 Surya / Modal 云 Surya / MinerU 云 API）"：`lib/types.ts` 定义引擎/运行时/提供方三类标识，`lib/documentParseProviders.ts` 静态注册并允许用户选择；各引擎结果归一为同一中间格式（按页 `layout_regions[]`，含 label、confidence、bbox、text，`lib/suryaParser.ts`），页码坐标全保留，下游翻译/RAG/批注引擎无关；本地服务与云端共用三段式任务协议（submit→poll→result）；服务端用 sha256 指纹做解析幂等去重；缓存引擎无关（`lib/pdfCache.ts`）。缺陷：无自动引擎回退、pdfjs 兼容路径实际未接线、表格仍只输出拼接文本。

对 PaperMind 的意义对准两个已知弱点：`backend/app/ingestion/pdf_parser.py` 用 PyMuPDF 提取原生文本，扫描件置信度接近 0 而无出路；长表格理解是检索与比较的既知错误来源。接入点就是现有 `parse_confidence` 判定：低置信度时允许用户选择把该文档交给外部高级引擎（作为独立可选服务调用，不并入主程序），结果写回现有页面/全文与索引结构，页码来源回查不破；引擎不可用或失败时保留原生文本并明示。这样默认路径零新依赖，与"纯本地不要求部署服务器"的产品定义不冲突（可选引擎由用户自行启用）。

引擎许可证已核实（2026-09-29）：[Surya](https://github.com/datalab-to/surya) 代码 Apache-2.0、模型权重为修改版 OpenRAIL-M（研究与个人使用免费）；[MinerU](https://github.com/opendatalab/mineru) 3.0.9 及之前为 AGPL-3.0，之后改为基于 Apache-2.0 附加条件的 MinerU Open Source License（[许可说明](https://github.com/opendatalab/MinerU/discussions/2863)）。以独立进程/云 API 方式调用属聚合使用，不把其代码并入本仓库即可；直接引入源码前需再核对当期版本条款。

### 部分吸收：OpenAlex 工具化与多阶段检索管线

PaperSpark 的检索页用五阶段 LLM 管线（意图→查询扩展→并行检索→分析→汇总，`lib/literatureSearchService.ts`），并把 OpenAlex 封装为 6 个 agent 工具（searchWorks、getRelatedWorks、filterWorks 等，`lib/openalexTools.ts`），结果稀疏时自动分级放宽过滤条件。教训同样有用：这条管线只属于独立检索页，对话 agent 的检索能力仅"预留"未打通——PaperMind 若引入 OpenAlex，应直接挂进现有对话 agent 工具体系（与 `paper_acquisition` 并列），让"库外找材料→入库→带入研究"走同一条路径，而不是再造一个独立检索页。OpenAlex API 免费无需密钥（礼貌池填 mailto）。验收以一次真实"库外找材料"任务为准：检索结果能直接入库并带入对话，引用信息可回查。

### 暂缓与不采纳

自动知识图谱（首 3000 字抽概念、置信度阈值增量 upsert、localStorage 单图）设计上有可取的增量构建模式，PaperMind 的 `graph_api` 已有论文/概念/主张三种图数据；按既有产品排序，图谱仍排在研究主线之后，本轮不投入。论文生成单文件交互网页（截 10000 字符一次 LLM 生成、iframe 渲染）质量不可控且无研究流程位置，不采纳。编辑器内画布（Excalidraw 快照作为文档块）与聊天内 python 执行（本机 spawn、结果不回填对话）暂无对应研究任务，观察即可。降 AI 率改写此前已明确不采用，维持不变。

### 本轮结论

按项目判据（服务哪一步研究工作、接入哪里、怎样验收）排序：先做外部工具只读查询技能包（消除外部 agent 与资料库之间的人工搬运，验收即用真实多工具工作流），其次在 `parse_confidence` 低分处接入可选高级解析引擎（消除扫描件与复杂表格的人工重读），再评估 OpenAlex 工具化（扩展找材料的边界）。三者在 PaperSpark 中均有对应实现可对照设计，但按许可证结论只参考设计、独立实现，不移植其代码。

### 三项落地记录（2026-09-29，0.6.23 开发）

上述三项已按该排序实现，均为独立实现、未复制 PaperSpark 代码：外部工具查询面与技能文件见 [外部工具查询](external-agent-query.md)（未采用其浏览器快照中继与无鉴权设计，改为后端直查 + token）；可选高级解析引擎见 [高级解析引擎](advanced-parse-providers.md)（自定三段式任务协议，引擎不随包分发）；OpenAlex 工具见 [OpenAlex 工具](openalex-tools.md)（直接挂进对话，不做独立检索页）。知识图谱、网页生成、画布与降 AI 率维持"暂缓/不采纳"。真实引擎转换质量与外部工具实测节省工时仍未验证，随发布验证记录更新。
