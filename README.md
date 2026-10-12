# PaperMind

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6.svg)]()

PaperMind 是在 Windows 本机运行的科研辅助工具，可以用来：

- 管理论文；
- 为一批论文生成精读卡片和文献地图；
- 带着问题与 AI 一起读论文、比较方法；
- 把研究判断、笔记和文稿保存下来，继续使用。

资料保存在本机。模型由使用者自行配置，可以是云端 API，也可以是本机模型。

当前源码版本为 0.6.30（Windows 本地候选）。各版本的变化、验证范围和已知限制见[版本变化](CHANGELOG.md)和[发布说明](docs/releases/)。

> PaperMind 用来减少研究中的重复劳动，不替代研究者的判断。AI 生成的内容可能有错误或遗漏，引用、数值和结论在使用前请对照原文核实。详见下文“使用须知”。

## 能省掉哪些工作

| 研究工作 | PaperMind 做什么 | 留给研究者的部分 |
|---|---|---|
| 逐篇精读、写笔记 | 为每篇论文生成精读卡片，字段包括：研究问题、方法机制、数据条件、主要贡献、判断边界。每个字段附原文引文，由程序核对引文是否出自原文、数字是否一致，并标出页码 | 抽查标为“需核对”的字段 |
| 梳理研究路线 | 生成文献地图：提出研究主题并归类论文。每个主题给出趋势、值得研究的问题、方法组合机会和代表论文，最后汇总总体判断和阅读路线。年份分布等统计数字由程序计算 | 按自己的口径改名、合并、拆分或删除主题；只重跑受影响的部分 |
| 从文献走向选题 | 地图中的每个“值得研究的问题”和“方法组合机会”，都可以一键带上相关论文进入研究对话，继续核对原文，设计最小验证方案 | 判断方向是否值得投入 |
| 带着问题读论文、比较方法 | 研究对话可以：检索本地论文库；按章节或页码读全文；查询 OpenAlex、Crossref、arXiv 和网页；保存笔记与文稿。回答附来源，可回到 PDF 原页 | 提出问题，修订文稿 |
| 写综述正文 | 专题综述按“逐篇分析 → 分批综合 → 提纲 → 分章写作 → 整篇修订”进行。可以暂停续跑，可以加入新论文增量更新，历史版本都会保留 | 审阅和修改正文 |
| 交付与汇报 | 文献地图可导出为单文件 HTML、Excel、Word、CSV、BibTeX；研究汇报可导出 PPTX | — |

专题综述最多支持 1000 篇论文。文献地图目前在约 100 篇的真实文献集上做过完整运行。逐篇结果会缓存，新增论文或修改主题时只处理变化的部分。

## 其他功能

- **研究项目**：按项目分开保存论文、对话、专题知识和研究任务。跨项目复用资料需要显式复制，并保留来源。
- **资料管理**：
  - 可导入 PDF、BibTeX、RIS、arXiv，或手工录入；
  - 从 Zotero 迁移：在 Zotero 中选中文献导出 BibTeX（条目含 DOI）后导入；再把对应 PDF 一起选中上传，系统会按 DOI 自动并入已有记录，不产生重复；缺书目的条目在论文列表选中后点“补全书目信息”，按 DOI 补齐作者、年份与摘要。
  - 按 DOI 补全书目信息和摘要，获取开放获取全文；
  - 内置阅读器，支持摘录、笔记和审阅矩阵。
- **文档转换**：PDF 通过文字层或 OCR 转为 Markdown，可对照原页，供检索和阅读使用。
- **翻译与重排序**：支持划词翻译。翻译、OCR 和重排序可以在项目内各自选用模型。
- **本机模型**：
  - 可导入单文件 GGUF，由内置 llama.cpp 在 CPU 上推理；
  - 也可以连接 Ollama、LM Studio 或 llama.cpp 服务。
- **技能**：
  - 完整内置 Nature Skills 和 Oh My Paper 两个技能库，可在技能页浏览原文，在对话中按任务加载；专题综述按写作阶段调用这些技能。
  - 可以从 GitHub 地址、本机文件夹或 zip 导入现成的 Agent Skills 技能包（`SKILL.md` 加 references、scripts 等目录的格式）。大仓库可以只导入某个技能目录，例如 `https://github.com/<owner>/<repo>/tree/main/skills/<技能名>`。导入的技能和内置技能一样由对话助手按需加载，技能页会显示来源、版本和许可证。技能包里的脚本只作为参考资料读取，不会被执行。从 GitHub 导入会用到 GitHub API，未登录时每小时 60 次、按出口 IP 计算，多人共用代理时可能很快用完；可以设置环境变量 `GITHUB_TOKEN` 后重启 PaperMind，或者下载技能目录后用文件夹导入。
  - 也可以导入单个 Markdown 文件作为自定义技能。
- **外部 agent 接口**：Claude Code、Codex 等支持 MCP 的工具可以直接连接 PaperMind，检索和阅读论文库、精读卡片与文献地图，也可以把笔记、研究想法和文档写回。配置方法见下文“接入外部 AI 工具”。
- **数据安全**：API 密钥加密保存；支持项目备份和整应用备份。

## 安装与首次配置

- **安装版**：
  - 首次安装默认装给当前用户，不需要管理员权限；
  - 数据保存在 `%LOCALAPPDATA%\PaperMind\data`；
  - 静默卸载会保留资料；
  - 升级前建议先创建整应用备份。
- **便携版**：解压后运行 `start-portable.cmd`，数据保存在解压目录下。
- **模型配置**：
  - 在设置中添加模型连接，把文本模型指定为 `chat`、向量模型指定为 `embedding`；
  - 思考等级在模型设置中选择，未设置时默认 high；
  - 效果基准是 glm-5.3（max 思考等级），能力更弱的模型或更低的思考等级也能用，但效果不作保证；
  - 文献地图和专题综述建议使用上下文不少于 64K 的模型，并在模型设置中填写实际上下文长度。

## 接入外部 AI 工具

PaperMind 运行时，在本机提供 MCP 接口（Streamable HTTP），需要本机令牌才能访问：

- 地址：`http://127.0.0.1:<端口>/api/w/<项目 id>/mcp`。端口默认 4278，实际端口写在数据目录的 `agent_access.json` 中；项目 id 可以从 `GET /api/workspaces` 获得，默认项目是 `legacy`。
- 令牌：数据目录下 `api_token` 文件的内容，放在 `X-Local-Token` 请求头中（也可以用 `Authorization: Bearer <令牌>`）。

以 Claude Code 为例：

```powershell
claude mcp add --transport http papermind http://127.0.0.1:4278/api/w/legacy/mcp --header "X-Local-Token: <api_token 的内容>"
```

接口提供的工具与应用内对话助手相同：检索论文库和正文、读论文详情与全文、读精读卡片和文献地图、读研究笔记和已保存文档、加载内置或导入的技能；写入只限保存论文笔记、研究想法和 Markdown 文档。读取本机任意文件、联网检索和下载 PDF 等工具不通过这个接口提供。不支持 MCP 的工具，可以按 [skills/papermind-library/SKILL.md](skills/papermind-library/SKILL.md) 使用只读 HTTP 查询接口。

## 从源码运行

需要 Python 3.11+ 和 Node.js。

```powershell
.\start.ps1           # 准备依赖、构建前端并启动，默认地址 http://127.0.0.1:4278
.\start.ps1 -Rebuild  # 重新构建前端后启动
.\dev.ps1             # 开发模式
```

可以用 `PAPERMIND_DATA_DIR` 设置数据目录，用 `PAPERMIND_PORT` 设置端口。完整配置见[后端说明](backend/README.md)。

## 测试与构建

```powershell
cd backend
python -m pip install -e ".[dev]"
python -m pytest --basetemp=C:\pmt   # 仓库在较深的路径下时，指定短的临时目录可避免 Windows 路径过长
cd ../frontend
npm ci
npm test
npm run build
```

Windows 桌面程序用 PyInstaller 打包，安装程序用 Inno Setup 构建。依赖与命令见[打包说明](build/README.md)。

## 数据、网络与费用

- **本机数据**：论文、笔记、索引和研究记录都保存在本机数据目录。应用没有账号体系；PaperMind 自身不收集使用数据，也不向开发者上传任何数据。
- **发送给模型服务的内容**：调用模型时，相关的论文片段、问题和材料会发送到你配置的模型服务，适用该服务的隐私条款和计费规则。不希望外发的资料，请改用本机模型，或者不要发送。
- **联网访问**：文献调研、DOI 补全、公开全文获取、网页搜索与读取会访问 OpenAlex、Crossref、arXiv、Bing 搜索结果，以及你指定的网页；从 GitHub 导入技能包会访问 GitHub。只有使用这些功能时才会联网，arXiv 订阅除外：设置了订阅后，每次启动会自动拉取超过 24 小时未更新的订阅。
- **外部 AI 工具**：通过 MCP 接口连接的工具读到的论文内容，会按该工具自己的设置发送给它使用的模型服务，适用该服务的条款。接口只监听本机地址，并要求本机令牌；不要把令牌分享给他人，也不要写入公开的配置文件或代码仓库。
- **费用**：
  - 模型调用费用由使用者承担；
  - 应用内的用量统计按服务返回的 token 数计算，仅供参考，以服务商账单为准；
  - 文献地图和专题综述会批量调用模型，用量较大；
  - arXiv 订阅自动拉取时，会用对话模型为新论文评估相关度，也会产生少量调用。

## 使用须知

- **AI 内容需要核实。** AI 生成的卡片、地图、回答和综述可能存在事实、归因或数值错误。
  - “已核对原文”标签只表示两件事：该字段的引文能在原文或摘要中找到；引文中的数字出现在原文对应位置。它不表示模型的概括、比较或科学结论正确。
  - 拿不到全文的论文，只能依据摘要或元数据处理，界面会标出证据级别。
- **学术规范由研究者负责。** 研究者对引用、投稿和发表的内容负责，请遵守所在机构、期刊和会议关于 AI 辅助写作与披露的规定。本工具用于提升研究效率，不得用于捏造数据、伪造引用或其他学术不端行为。
- **文献获取与版权。** 全文获取只使用公开的开放获取链接，不绕过登录或付费访问控制。导入和使用文献的权利，由使用者自行确认。
- **导入的技能。** 从第三方导入的技能包按其原有许可证使用，许可证和内容是否适合你的用途由使用者自行确认；技能页显示的许可证是从技能文件或仓库许可证文件中读取的，仅供参考。导入的技能不随本程序分发，PaperMind 不对其内容负责。
- **无隶属或背书关系。** 本项目与 Springer Nature、Nature 期刊、K-Dense、Oh My Paper、OpenAlex、Crossref、arXiv、Microsoft 及各模型服务商均无隶属、合作或背书关系。“Nature Skills”是一个社区开源项目的名称，与 Nature 期刊及其出版商无关。文中出现的相关名称只用于说明来源。
- **无担保。** 软件按“现状”提供，不附带任何明示或默示的担保；责任限制见 GPL-3.0 第 15、16 条。

## 复用的开源技能与组件

PaperMind 优先复用成熟的开源技能和组件，只为实际缺口编写新代码。下列内容按各自的许可证使用。完整出处、固定版本、修改说明和许可证原文见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、`third_party/` 和 `backend/builtin_skills/`。

### 科研技能

| 名称 | 上游 | 许可证 | 在 PaperMind 中的用法 |
|---|---|---|---|
| Nature Skills | [Yuan1z0825/nature-skills](https://github.com/Yuan1z0825/nature-skills) | Apache-2.0 | 20 个技能及全部资源原样内置在 `backend/builtin_skills/nature/`，对话和专题综述按任务加载。`backend/research_skills/paper-evidence/` 是 nature-paper-card 证据规则的翻译缩编版，用于研究任务和专题知识更新 |
| Oh My Paper | [LigphiDonk/Oh-my--paper](https://github.com/LigphiDonk/Oh-my--paper) | MIT | 35 个技能及资源原样内置在 `backend/builtin_skills/oh-my-paper/`，专题综述写作使用 academic-researcher 和 research-paper-handoff。PaperMind 不安装、也不运行它的 Claude Code 插件、会话钩子或远程实验组件 |
| K-Dense Scientific Agent Skills | [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | MIT | `backend/research_skills/critical-comparison/` 改编自 scientific-critical-thinking，在比较方法时检查实验条件差异 |

改编版是为 PaperMind 的工具和输出格式所做的翻译、选取和修改，不是上游的完整实现。它不代表上游作者认可本项目的使用方式或输出结果。内置技能中的脚本和外部服务说明原样保留，但它们的存在不代表相应的外部依赖或账户已经配置。

### 设计参考（未复制代码或资源）

- [PaperSpark](https://github.com/zongxi1115/PaperSpark)（CC BY-NC 4.0）：只参考了功能与交互思路，没有复制其源码、提示词、图片或其他资源。
- [PaperQA2](https://github.com/Future-House/paper-qa)（Apache-2.0）：参考了它把模型分为对话模型和向量模型两种角色的配置思路，没有复制代码。

### 随程序分发的主要运行组件

| 组件 | 许可证 | 用途 |
|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) b11146（未修改的 Windows CPU 服务与 DLL） | MIT | 本机 GGUF 模型推理。不附带模型权重，各模型遵守各自的许可证 |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | AGPL-3.0（或 Artifex 商业许可） | PDF 解析、渲染和链接提取 |
| [LiteLLM](https://github.com/BerriAI/litellm) | MIT | 接入多家模型服务 |
| FastAPI、Uvicorn、SQLModel、Alembic | MIT / BSD-3-Clause | 本机服务与数据库 |
| [sqlite-vec](https://github.com/asg017/sqlite-vec) | MIT / Apache-2.0 | 向量检索 |
| python-markdownify、Beautiful Soup、Soup Sieve | MIT | 把 OCR 得到的表格转成 Markdown |
| openpyxl、python-docx、python-pptx | MIT | Excel、Word、PPTX 导出 |
| arxiv、bibtexparser | MIT；LGPL-3.0 或 BSD | 获取 arXiv 论文、解析 BibTeX |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)（mcp） | MIT | 外部 AI 工具接入的 MCP 接口 |
| cryptography、Pillow、httpx、PyYAML | Apache-2.0 或 BSD-3-Clause、MIT-CMU、BSD-3-Clause、MIT | 加密、图像处理、网络请求、配置读取 |
| pywebview | BSD-3-Clause | 桌面窗口，使用系统已有的 Microsoft Edge WebView2 运行时 |
| React、react-markdown、unified / remark / rehype、KaTeX、Cytoscape.js | MIT | 界面、Markdown 与公式渲染、关系图 |
| PDF.js（pdfjs-dist） | Apache-2.0 | 内置 PDF 阅读器 |
| highlight.js（经 rehype-highlight 使用） | BSD-3-Clause | 代码高亮 |

打包时使用 PyInstaller（GPL-2.0-or-later，附 bootloader 例外）和 Inno Setup（Inno Setup License）。使用者自行配置的模型服务和外部数据服务都不随本程序分发，使用时遵守各自的服务条款。

## 许可证

本项目以 [GPL-3.0](LICENSE) 发布。

- PyMuPDF 以 AGPL-3.0 授权。再分发本程序，或以网络服务方式提供修改后的版本时，还需满足 AGPL-3.0 对相应部分的要求。
- 内置技能和第三方组件保留各自的许可证（Apache-2.0、MIT 等）。再分发时，请保留 THIRD_PARTY_NOTICES.md，以及 `third_party/`、`backend/builtin_skills/` 中的许可证和声明文件。

## 贡献

欢迎提交 Issue 和 Pull Request。提交前请运行 `python tools/check_public_tree.py`，避免把个人资料、会话记录、运行日志、数据库、备份或模型凭据带入仓库。

## 文档

- [版本变化](CHANGELOG.md)
- [发布说明](docs/releases/)
- [后端配置](backend/README.md)
- [Windows 打包](build/README.md)
- [第三方组件声明](THIRD_PARTY_NOTICES.md)
- [外部 agent 查询技能（MCP 与 HTTP）](skills/papermind-library/SKILL.md)
