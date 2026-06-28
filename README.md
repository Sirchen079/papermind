# PaperMind

基于 AI agent 的论文管理系统 —— 本地单用户 Web 应用。AI 自动解析、分析归纳、
抽取概念并构建**论文图谱 + 概念图谱**（可切换），支持科研对话、多 LLM provider。

## 架构

- **后端**（`backend/`）：Python 3.11+ / FastAPI / SQLModel / SQLite(WAL) / Alembic /
  LiteLLM / Fernet。详见 `backend/README.md`。
- **前端**（`frontend/`）：React 18 + TypeScript + Vite + Tailwind + Cytoscape.js。
- 生产模式下后端托管前端构建产物，**一条命令启动整个应用**。

## 快速启动（推荐）

项目根目录提供了一键脚本（Windows / PowerShell）：

```powershell
.\start.ps1            # 首次会自动建 venv、装依赖、构建前端，然后启动
.\start.bat            # 等价：双击即可
.\start.ps1 -Rebuild   # 强制重建前端
.\dev.ps1              # 开发模式：后端 --reload + 前端 vite 热更新（各开一个窗口）
```

启动后自动打开 http://127.0.0.1:4278 。脚本幂等：venv / 依赖 / `frontend/dist`
已就绪时会跳过，直接启动。可选环境变量：`PAPERMIND_PORT`、`PAPERMIND_NPM_REGISTRY`
（默认 npmmirror）、`PAPERMIND_PIP_INDEX`（国内可设清华源）。

> 首次进入后，到 **Settings** 添加一个 LLM provider（OpenAI / Anthropic / 任意 OpenAI
> 兼容如 DeepSeek、智谱），刷新模型并给模型设置 `summary` / `chat` 角色，之后入库论文
> 即自动 AI 分析。

## 手动步骤（等价于脚本所做的事）

```bash
# 1. 后端
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"      # Windows
# (国内网络慢时)加 -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv/Scripts/python -m alembic upgrade head          # 建表（启动时也会自动跑）

# 2. 前端构建（生产）
cd ../frontend
npm install --registry=https://registry.npmmirror.com   # 国内用镜像
npm run build                                            # 产物在 frontend/dist

# 3. 启动（后端会托管 frontend/dist）
cd ../backend
.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 4278
```

打开 http://127.0.0.1:4278 。先在 **Settings** 添加一个 LLM provider（OpenAI / Anthropic /
任意 OpenAI 兼容如 DeepSeek、智谱），刷新模型并给一个模型设置 `summary` / `chat` 角色，
之后入库论文即自动 AI 分析。

## 开发模式（前后端分离热更新）

```bash
# 终端 A：后端
cd backend && .venv/Scripts/python -m uvicorn app.main:create_app --factory --port 4278 --reload
# 终端 B：前端 dev server（代理 /api -> 4278）
cd frontend && npm run dev   # http://127.0.0.1:5173
```

## 测试

```bash
cd backend && .venv/Scripts/python -m pytest      # 后端单元/集成测试
cd frontend && npm run build                       # 前端类型检查 + 构建
```

## 配置（环境变量）

| 变量 | 默认 | 用途 |
|---|---|---|
| `PAPERMIND_DATA_DIR` | `data` | SQLite 与 master key 所在 |
| `PAPERMIND_DB_PATH` | `<data_dir>/papermind.sqlite` | 数据库路径 |
| `PAPERMIND_MASTER_KEY_PATH` | `<data_dir>/master.key` | Fernet 主密钥（自动生成） |

API Key 经 Fernet 加密落盘；主密钥存本地、不入版本库。

## 主要 API

`/api/health` · `/api/providers`(+`/models/refresh`) · `/api/models` · `/api/settings` ·
`/api/papers/{arxiv,bibtex,pdf}` · `/api/graph/{paper,concept}` · `/api/chat/conversations` · `/api/usage`

## 文档

- 设计 spec：`docs/superpowers/specs/2026-06-28-paper-management-agent-design.md`
- 实施计划：`docs/superpowers/plans/2026-06-28-p0a-backend-foundation.md`
