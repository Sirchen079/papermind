# PaperMind

PaperMind 是本地运行的论文阅读与研究资料管理应用，支持多个研究项目、论文问答、专题知识、笔记和研究成果导出。当前版本为 **0.5.2**。

## 功能

- 按研究项目组织论文、会话、专题知识和研究任务。跨项目复用资料时显式复制，并保留来源。
- 导入 PDF、BibTeX、RIS、arXiv 或手工记录；阅读原文，保存摘录、笔记和审阅矩阵。
- 围绕选定论文提出问题，保存和修订研究判断，对照证据核对内容。
- 将资料与判断积累为专题知识，保留候选版本、采用版本和引用来源。
- 连接 OpenAI、Anthropic 或兼容接口；连接配置可共享，各项目独立选择模型。
- 管理研究想法、实验记录和写作材料，导出 Markdown、BibTeX 或组会 PPTX。
- 创建项目备份或整应用备份，校验后离线恢复。

论文整理、阅读与人工编辑可以独立使用。AI 生成和问答需要配置模型；向量检索另需配置 embedding 模型。

## 内置科研技能与开源致谢

论文问答、研究任务和专题知识更新现共用两项内置改编技能。应用会同时加载技能入口和所需参考文件，无需另装插件或配置额外模型：

| PaperMind 技能 | 上游项目与固定版本 | 许可证 | 改编用途 |
|---|---|---|---|
| `paper-evidence` | [Nature Skills](https://github.com/Yuan1z0825/nature-skills/tree/9ea7330a17813a15421fe843778a776c258b9001)，Nature Paper Card 证据规则 | Apache-2.0 | 逐篇证据记录，区分原文、分析、假设、用户判断和材料覆盖范围 |
| `critical-comparison` | [K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills/tree/330c8e764435a731eff571e3efdda70b363d0792)，scientific-critical-thinking | MIT | 比较条件、混杂因素、统计不确定性与结论强度复核 |

上述内容于 2026-09-15 翻译、缩编并适配 PaperMind 的论文工具及输出格式，属于本项目改编版；不代表已运行上游完整精读卡或审稿流程，也不代表上游背书。维护者可在 `backend/research_skills/` 查看运行内容；用户自定义技能继续独立生效。技能组织证据检查过程，不能保证模型结论正确，科研结论仍应按原文核对。

有资料依据的问答与 Wiki 更新在生成后还会独立复核证据：审查以文本块编号定位修改，并提供原文片段；程序校验来源、定位和修改范围，再发布修订结果。全文只读到片段时，Agent 在结束前检查所问事实是否齐全，必要时继续定位章节；该检查最多触发一次，仍受工具步数上限约束。复核失败会保留原问题或失败任务，支持重试。Wiki 使用短引用编号生成正文，由程序还原稳定来源编号并计算引用列表；未提供的来源不会被补造。复核会增加真实模型调用，计入应用用量统计。

官方智谱 Chat Completion 端点上的 GLM-5.3 使用已核对的协议适配：保留工具往返所需的 `reasoning_content`（不展示为回答），普通生成使用 `low`，证据复核使用 `high`；明确设置推理参数，不依赖旧 SDK 模型表猜测能力。未手动填写上下文窗口时，GLM-5.3 使用官方说明的 1M 上限；用户填写值优先。其他兼容端点继续使用其自身配置，不套用智谱参数。依据：[GLM-5.3 模型说明](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3)、[思考模式协议](https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode)（2026-09-15 核对）。

模型网络等待有明确上限：每次 Agent 生成或 Wiki 生成最多 180 秒，独立证据复核最多 300 秒，原有研究提取任务为 90 秒；这些步骤不进行 SDK 隐式重试。超时会显示失败并保留问题或任务，可由用户重试；多个工具步骤和格式校正的总时长可能超过一次调用的上限。

感谢 Nature Skills 贡献者及 K-Dense Inc.。完整上游版本、原始文件、改动说明和协议见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、[Nature Apache-2.0 协议](third_party/research_skills/nature/LICENSE) 与 [K-Dense MIT 协议及版权声明](third_party/research_skills/kdense/LICENSE.md)。源码和 Windows 便携包均附带这些文件；再分发相应组件时应保留许可证和归属说明。

相关项目论文：Kassis, T., Agarwal, V., He, Y., Patel, D., & Brueckner, A. M. (2026). [Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents](https://doi.org/10.48550/arXiv.2609.00065)。书目信息于 2026-09-15 核对。

## Windows 使用

安装版默认把数据保存在 `%LOCALAPPDATA%/PaperMind/data`。便携版解压后通过 `start-portable.cmd` 启动，数据保存在解压目录下。升级前建议创建整应用备份。

首次进入应用后，在设置中添加模型连接，并为文本模型指定 `chat` 角色。使用向量检索时，再为向量模型指定 `embedding` 角色。发送给模型的内容由所选资料和当前功能决定，请按资料的保密要求选择模型服务。

## 从源码启动

需要 Python 3.11+ 和 Node.js。

```powershell
.\start.ps1
```

脚本会准备依赖、构建前端并启动应用。默认地址为 `http://127.0.0.1:4278`。

```powershell
.\start.ps1 -Rebuild  # 重新构建前端后启动
.\dev.ps1            # 开发模式
```

可通过 `PAPERMIND_DATA_DIR` 设置数据目录，通过 `PAPERMIND_PORT` 设置端口。完整后端配置见 [后端说明](backend/README.md)。

## 验证与构建

```powershell
cd backend
python -m pip install -e ".[dev]"
python -m pytest
cd ../frontend
npm ci
npm test
npm run build
```

Windows 桌面程序使用 PyInstaller 打包，安装程序使用 Inno Setup 构建。依赖及命令见 [打包说明](build/README.md)。

## 公开仓库范围

仓库保留产品源码、必要的维护文档和合成测试资料。个人资料、会话记录、开发计划、内部评估、运行日志、数据库、备份及模型凭据应放在仓库外。提交前运行 `python tools/check_public_tree.py`，检查待提交文件；运行 `git config core.hooksPath .githooks` 可启用自动提交检查。自动规则用于拦截常见风险，发布前仍需检查新增资料的内容。

## 文档

- [版本变化](CHANGELOG.md)
- [后端配置](backend/README.md)
- [Windows 打包](build/README.md)
