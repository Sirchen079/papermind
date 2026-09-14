# PaperMind

PaperMind 是本地运行的论文阅读与研究资料管理应用，支持多个研究项目、论文问答、专题知识、笔记和研究成果导出。当前版本为 **0.5.0**。

## 功能

- 按研究项目组织论文、会话、专题知识和研究任务。跨项目复用资料时显式复制，并保留来源。
- 导入 PDF、BibTeX、RIS、arXiv 或手工记录；阅读原文，保存摘录、笔记和审阅矩阵。
- 围绕选定论文提出问题，保存和修订研究判断，对照证据核对内容。
- 将资料与判断积累为专题知识，保留候选版本、采用版本和引用来源。
- 连接 OpenAI、Anthropic 或兼容接口；连接配置可共享，各项目独立选择模型。
- 管理研究想法、实验记录和写作材料，导出 Markdown、BibTeX 或组会 PPTX。
- 创建项目备份或整应用备份，校验后离线恢复。

论文整理、阅读与人工编辑可以独立使用。AI 生成和问答需要配置模型；向量检索另需配置 embedding 模型。

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
