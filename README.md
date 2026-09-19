# PaperMind

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6.svg)]()

PaperMind 是本地运行的论文阅读与研究资料管理应用，支持多个研究项目、论文问答、专题知识、笔记和研究成果导出。数据保存在本机，兼容多家模型服务。当前版本 0.5.3，提供 Windows 安装版与便携版。

## 功能特性

- **研究项目**：按项目组织论文、会话、专题知识和研究任务；跨项目复用资料需显式复制，并保留来源。
- **资料管理**：导入 PDF、BibTeX、RIS、arXiv 或手工记录；内置阅读器，可保存摘录、笔记和审阅矩阵。
- **论文问答**：围绕选定论文提问，保存和修订研究判断；有依据的回答标注来源，生成后独立复核证据，程序校验来源与修改范围，未提供的来源不会被补造。复核失败会保留原问题，支持重试。工具调用步数上限可在设置中调整。
- **专题知识**：将资料与判断积累为专题知识，保留候选版本、采用版本和引用来源。
- **模型接入**：支持 OpenAI、Anthropic 及任意 OpenAI 兼容接口；连接配置可共享，各项目独立选择模型，并可按模型配置上下文窗口、思考等级与图片输入能力标记。模型调用有明确超时上限，用量计入应用统计。
- **研究产出**：管理研究想法、实验记录和写作材料，导出 Markdown、BibTeX 或研究汇报 PPTX。
- **数据安全**：数据存储在本机，API 密钥加密保存；支持项目备份和整应用备份，校验后离线恢复。

论文整理、阅读与人工编辑可完全离线使用。AI 生成和问答需要配置模型；向量检索另需配置 embedding 模型。发送给模型的内容由所选资料和当前功能决定，请按资料的保密要求选择模型服务。

## Windows 安装与使用

- **安装版**：数据保存在 `%LOCALAPPDATA%\PaperMind\data`，升级前建议创建整应用备份。
- **便携版**：解压后运行 `start-portable.cmd` 启动，数据保存在解压目录下。
- **首次配置**：在设置中添加模型连接，为文本模型指定 `chat` 角色；使用向量检索时，再为向量模型指定 `embedding` 角色。

## 从源码运行

需要 Python 3.11+ 和 Node.js。

```powershell
.\start.ps1
```

脚本会准备依赖、构建前端并启动应用，默认地址为 `http://127.0.0.1:4278`。

```powershell
.\start.ps1 -Rebuild  # 重新构建前端后启动
.\dev.ps1             # 开发模式
```

可通过 `PAPERMIND_DATA_DIR` 设置数据目录，通过 `PAPERMIND_PORT` 设置端口。完整后端配置见 [后端说明](backend/README.md)。

## 测试与构建

```powershell
cd backend
python -m pip install -e ".[dev]"
python -m pytest
cd ../frontend
npm ci
npm test
npm run build
```

Windows 桌面程序使用 PyInstaller 打包，安装程序使用 Inno Setup 构建，依赖与命令见 [打包说明](build/README.md)。

## 内置研究技能与第三方组件

论文问答、研究任务和专题知识更新内置两项改编自上游开源项目的研究技能，随应用自动加载，无需额外安装或配置：

| 技能 | 上游项目 | 上游协议 | 用途 |
|---|---|---|---|
| `paper-evidence` | [Nature Skills](https://github.com/Yuan1z0825/nature-skills) | Apache-2.0 | 逐篇证据记录，区分原文、分析、假设、用户判断和材料覆盖范围 |
| `critical-comparison` | [K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills) | MIT | 比较实验条件、混杂因素、统计不确定性与结论强度 |

上述技能由本项目翻译、缩编并适配 PaperMind 的工具与输出格式，不是上游完整实现的运行，也不代表上游背书。技能用于组织证据检查过程，不能保证模型结论正确，研究结论仍应按原文核对。上游版本、原始文件、改动说明与协议全文见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，运行内容可在 `backend/research_skills/` 查看。用户自定义技能独立生效。

## 贡献

欢迎提交 Issue 和 Pull Request。提交前请运行 `python tools/check_public_tree.py`，避免把个人资料、会话记录、运行日志、数据库、备份或模型凭据带入仓库。

## 文档

- [版本变化](CHANGELOG.md)
- [后端配置](backend/README.md)
- [Windows 打包](build/README.md)
- [第三方组件声明](THIRD_PARTY_NOTICES.md)

## 许可证

本项目以 [GPL-3.0](LICENSE) 协议发布。两项内置研究技能为上游项目的改编版本，分别延续 Apache-2.0 与 MIT 协议；再分发相应组件时应保留其许可证与归属说明，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
