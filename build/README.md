# PaperMind 打包

把 PaperMind 打包成 Windows 安装程序：**PyInstaller**（后端 → `PaperMind.exe`）+ **Inno Setup**（安装程序）。

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

产物：

- `build\dist\PaperMind\PaperMind.exe` — PyInstaller onedir，可独立运行（双击即用，无需 Python）
- `build\installer_output\PaperMind-Setup-<ver>.exe` — 安装程序（约 65 MB，中文界面）

## 前置条件

- **Python venv**：`backend\.venv`（首次由 `.\start.ps1` 创建；脚本会装 PyInstaller）
- **Node.js**：构建前端 `frontend\dist`（由脚本自动 `npm run build`）
- **Inno Setup 6**：脚本按顺序探测 `iscc` —— PATH → `D:\Inno Setup 6\` → `Program Files\...` → current-user，找不到则跳过安装程序并提示

## 打包架构

| 部分 | 处理方式 |
|---|---|
| 后端（FastAPI / uvicorn / litellm / sqlite-vec / pymupdf / alembic） | PyInstaller onedir 打包成单目录 |
| 入口 | `backend\app\launcher.py`：启动 uvicorn + 端口就绪后自动开浏览器 |
| `frontend\dist`、`backend\migrations`、`backend\user_skills` | 作为数据文件随包分发，落到 `_internal\` |
| 用户数据（SQLite / `master.key` / PDF） | `%LOCALAPPDATA%\PaperMind\data`（与安装目录解耦） |
| 安装 / 卸载 / 快捷方式 / 防呆 | Inno Setup |

> 路径解析集中在 `backend\app\paths.py`：优先环境变量 → PyInstaller 冻结包布局 → 源码布局。开发模式行为不变。

## 防呆设计（`installer.iss` 的 `[Code]` 段）

- **禁止盘符根目录**：选目录页拒绝 `X:\`，强制装到子文件夹
- **降级提示**：已装更新版本时弹框确认
- **旧版数据迁移**：检测 `<旧安装目录>\data`，`robocopy` 到 `%LOCALAPPDATA%\PaperMind\data`，先备份现有目录为 `.migration-backup`
- **卸载询问**：卸载末尾询问是否删除用户数据（默认保留，便于重装恢复）
- **进程文件锁**：`CloseApplications=force` 让 RestartManager 自动关闭运行中的 `PaperMind.exe`
- **磁盘空间**：`ExtraDiskSpaceRequired` 预留 ~150 MB

## 关键文件

| 文件 | 作用 |
|---|---|
| `backend\app\paths.py` | 路径解析（开发 + 冻结模式） |
| `backend\app\launcher.py` | PyInstaller 入口 |
| `build\papermind.spec` | PyInstaller 配置（含 litellm / sqlite_vec / pymupdf 收集） |
| `build\installer.iss` | Inno Setup 脚本（含中文 + 防呆） |
| `build\ChineseSimplified.isl` | 中文安装界面语言包（6.5.0+，随仓库走以保可复现构建） |
| `build\build.ps1` | 一键构建脚本 |

## 手动分步

```powershell
.\build\build.ps1                       # 只产出裸 exe
& 'D:\Inno Setup 6\ISCC.exe' .\build\installer.iss   # 再编译安装程序
```
