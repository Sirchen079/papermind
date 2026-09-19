# PaperMind 打包

把 PaperMind 打包成 Windows 安装程序：**PyInstaller**（后端 → `PaperMind.exe`）+ **Inno Setup**（安装程序）。

当前功能变化见 [版本记录](../CHANGELOG.md)。

## 一键打包

```powershell
.\build\build.ps1 -Installer
```

参数：

| 参数 | 作用 |
|---|---|
| `-Installer` | 末尾调用 ISCC 编译安装程序（不加则只产出裸 exe） |
| `-NoFrontend` | 跳过前端构建（`frontend\dist` 已存在时） |
| `-Clean` | 清掉旧产物重建 |
| `-PythonPath` | 指定已装齐后端依赖和 PyInstaller 的 Python 路径 |

产物：

- `build\dist\PaperMind\` — PyInstaller onedir，完整目录可独立运行（不能只复制其中的 exe；无需另装 Python）
- `build\installer_output\PaperMind-Setup-<ver>.exe` — Windows x64 安装程序，中文界面，版本取自 `frontend/package.json`

## 前置条件

- **Python venv**：`backend\.venv`（首次由 `.\start.ps1` 创建），需已安装后端依赖与 PyInstaller；可通过 `-PythonPath` 指定其他环境
- **Node.js**：构建前端 `frontend\dist`（由脚本自动 `npm run build`）
- **Inno Setup 6**：脚本探测 PATH、当前用户和 Program Files 下的常见路径；指定 `-Installer` 却找不到编译器时构建失败
- **WebView2 离线运行时**：将 Windows x64 运行时文件放到 `build\vendor\webview2`，其中应包含 `msedgewebview2.exe`。这个大体积资源目录由 Git 忽略，克隆代码后需单独准备；构建脚本会先检查它是否存在。

构建时会运行 `prepare_tokenizers.py`，将 tiktoken 的分词数据准备到模型依赖的资源目录，并按库内置的 SHA256 校验。首次准备可能需要下载公共文件；后续构建复用本地缓存，桌面包携带这些资源。建议使用单独的虚拟环境打包，记录所用依赖版本，并在无网络环境验收导入与启动。

默认每次重新构建前端，只有显式使用 `-NoFrontend` 才复用现有 dist。发布时同步更新前后端版本、`installer.iss` 默认版本及 `version_info.txt` 的 Windows 文件版本。

## 打包架构

| 部分 | 处理方式 |
|---|---|
| 后端（FastAPI / uvicorn / litellm / sqlite-vec / pymupdf / alembic） | PyInstaller onedir 打包成单目录 |
| 入口 | `backend\app\launcher.py`：启动本地后端与桌面窗口；`PAPERMIND_NO_BROWSER=1` 用于无窗口诊断 |
| `frontend\dist`、`backend\migrations`、`backend\user_skills` | 作为数据文件随包分发，落到 `_internal\` |
| 用户数据（SQLite / `master.key` / PDF） | `%LOCALAPPDATA%\PaperMind\data`（与安装目录解耦） |
| 安装 / 卸载 / 快捷方式 / 防呆 | Inno Setup |

> 路径解析集中在 `backend\app\paths.py`：优先环境变量 → PyInstaller 冻结包布局 → 源码布局。开发模式行为不变。

## 防呆设计（`installer.iss` 的 `[Code]` 段）

- **禁止盘符根目录**：选目录页拒绝 `X:\`，强制装到子文件夹
- **降级提示**：已装更新版本时弹框确认
- **旧版数据迁移**：目标用户数据目录不存在时，复制 `<旧安装目录>\data` 到 `%LOCALAPPDATA%\PaperMind\data`；目标已存在则保留，不覆盖现有数据和历史备份；旧数据始终保留
- **卸载询问**：卸载末尾询问是否删除用户数据（默认保留，便于重装恢复）
- **进程文件锁**：`CloseApplications=force` 让 RestartManager 自动关闭运行中的 `PaperMind.exe`
- **磁盘空间**：`ExtraDiskSpaceRequired` 预留 ~150 MB

## 关键文件

| 文件 | 作用 |
|---|---|
| `backend\app\paths.py` | 路径解析（开发 + 冻结模式） |
| `backend\app\launcher.py` | PyInstaller 入口 |
| `build\papermind.spec` | PyInstaller 配置（含 litellm / sqlite_vec / pymupdf 收集） |
| `build\prepare_tokenizers.py` | 准备并校验随包提供的分词数据 |
| `build\installer.iss` | Inno Setup 脚本（含中文 + 防呆） |
| `build\ChineseSimplified.isl` | 中文安装界面语言包（6.5.0+，随仓库走以保可复现构建） |
| `build\build.ps1` | 一键构建脚本 |

## 手动分步

```powershell
.\build\build.ps1                       # 只产出裸 exe
& ISCC.exe .\build\installer.iss   # 再编译安装程序
```

## 桌面发布检查

构建环境必须安装 `backend[desktop]`（例如在 backend 目录运行 `python -m pip install -e ".[desktop,dev]"`）。spec 与构建脚本均在缺少桌面依赖时终止。

`build/verify_desktop.py <PaperMind.exe>` 使用独立数据目录，连续验证首次启动和再次启动的真实 WebView2 页面挂载及正常退出。构建脚本自动执行此检查，通过后才编译安装包；发布前还需对解压的便携包及安装后的程序重复执行。后台健康检查不能替代桌面检查。
