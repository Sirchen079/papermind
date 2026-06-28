# PaperMind 开发模式：一个脚本同时起后端(--reload) + 前端(vite dev)。
# 前端 dev server 代理 /api -> 8000。Ctrl+C 关闭两个窗口。
$ErrorActionPreference = "Stop"
$Root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend  = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPy   = Join-Path $Backend ".venv\Scripts\python.exe"
$NpmReg   = if ($env:PAPERMIND_NPM_REGISTRY) { $env:PAPERMIND_NPM_REGISTRY } else { "https://registry.npmmirror.com" }

if (-not (Test-Path $VenvPy)) { throw "未找到 backend\.venv，请先运行 .\start.ps1 完成初始化。" }
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
  Write-Host "安装前端依赖…" -ForegroundColor Yellow
  Push-Location $Frontend
  try { npm install --registry=$NpmReg } finally { Pop-Location }
}

Write-Host "启动后端(--reload) 与前端 dev server…" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$Backend'; & '$VenvPy' -m uvicorn app.main:create_app --factory --port 8000 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$Frontend'; npm run dev"
Write-Host "后端 http://127.0.0.1:8000  前端 http://127.0.0.1:5173" -ForegroundColor Green
