# PaperMind 一键启动脚本（Windows / PowerShell）
# --------------------------------------------------------------
# 幂等：venv / 依赖 / 前端构建缺失时才补，已就绪则直接启动。
# 用法：
#   .\start.ps1            生产模式（后端托管 frontend/dist）
#   .\start.ps1 -Dev       开发模式（后端 --reload + 前端 vite dev server）
#   .\start.ps1 -Rebuild   强制重新构建前端
# 环境变量（可选）：
#   $env:PAPERMIND_PORT            端口，默认 4278
#   $env:PAPERMIND_NPM_REGISTRY    npm 镜像，默认 https://registry.npmmirror.com
#   $env:PAPERMIND_PIP_INDEX       pip 镜像，默认（官方）
param(
  [switch]$Dev,
  [switch]$Rebuild,
  [int]$Port = 0
)

$ErrorActionPreference = "Stop"
# 输出统一 UTF-8：管道/子进程捕获（含测试）按 UTF-8 解码，中文不乱码
try {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }
$env:LITELLM_LOCAL_MODEL_COST_MAP = "True"
$Root      = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend   = Join-Path $Root "backend"
$Frontend  = Join-Path $Root "frontend"
$VenvPy    = Join-Path $Backend ".venv\Scripts\python.exe"
$NpmCmd    = "npm.cmd"
$NpmReg    = if ($env:PAPERMIND_NPM_REGISTRY) { $env:PAPERMIND_NPM_REGISTRY } else { "https://registry.npmmirror.com" }
if ($Port -le 0) { $Port = if ($env:PAPERMIND_PORT) { [int]$env:PAPERMIND_PORT } else { 4278 } }

function Section($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }

function Test-PaperMindHealth([int]$Port) {
  try {
    $res = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
    return ($res.StatusCode -eq 200 -and $res.Content -match '"status"\s*:\s*"ok"')
  } catch {
    return $false
  }
}

function Get-PortOwnerLabel([int]$Port) {
  try {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { return "PID $($conn.OwningProcess)" }
  } catch {
    # Older Windows/PowerShell setups may not expose Get-NetTCPConnection.
  }
  $line = netstat -ano | Select-String ":$Port\s+.*LISTENING" | Select-Object -First 1
  if ($line -and $line.Line -match "\s+(\d+)\s*$") { return "PID $($Matches[1])" }
  return "未知进程"
}

function Test-PortInUse([int]$Port) {
  $conn = $null
  try {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  } catch {
    $conn = $null
  }
  if ($conn) { return $true }
  return [bool](netstat -ano | Select-String ":$Port\s+.*LISTENING")
}

function Resolve-ExistingServer([int]$Port, [switch]$Dev, [switch]$Rebuild) {
  if (-not (Test-PortInUse $Port)) { return $false }

  $url = "http://127.0.0.1:$Port"
  if (Test-PaperMindHealth $Port) {
    if ($Rebuild) {
      $owner = Get-PortOwnerLabel $Port
      throw "PaperMind 已经在 $url 运行（$owner）。-Rebuild 需要先关闭旧服务窗口，再重新运行：.\start.ps1 -Rebuild。"
    }
    Write-Host "PaperMind 已经在 $url 运行，复用当前服务。" -ForegroundColor Green
    Write-Host "如果刚更新过后端代码，请先关闭旧服务窗口，再重新运行本脚本。" -ForegroundColor Yellow
    if (-not $Dev) { Start-Process $url }
    return $true
  }

  $owner = Get-PortOwnerLabel $Port
  throw "端口 $Port 已被占用（$owner），但不是可用的 PaperMind 服务。请关闭占用程序，或换一个端口：.\start.ps1 -Port <其他端口>。"
}

# If PaperMind is already running, do not run dependency checks or rebuilds.
# This keeps repeated starts fast and avoids noisy provider imports.
Section "启动检查"
if (Resolve-ExistingServer $Port -Dev:$Dev -Rebuild:$Rebuild) { return }

# ---------- 1. 后端 venv + 依赖 ----------
Section "检查后端环境"
$needInstall = $false
if (-not (Test-Path $VenvPy)) {
  Write-Host "未发现 venv，创建中…" -ForegroundColor Yellow
  Push-Location $Backend
  try { python -m venv .venv } finally { Pop-Location }
  $needInstall = $true
} else {
  & $VenvPy -c "import fastapi, uvicorn, litellm" 2>$null
  if ($LASTEXITCODE -ne 0) { $needInstall = $true; Write-Host "依赖缺失，安装中…" -ForegroundColor Yellow }
  else { Write-Host "venv 与依赖已就绪。" -ForegroundColor Green }
}
if ($needInstall) {
  Push-Location $Backend
  try {
    $pipArgs = @("-m", "pip", "install", "-e", ".[dev]")
    if ($env:PAPERMIND_PIP_INDEX) { $pipArgs += @("-i", $env:PAPERMIND_PIP_INDEX) }
    & $VenvPy @pipArgs
    if ($LASTEXITCODE -ne 0) { throw "后端依赖安装失败。" }
  } finally { Pop-Location }
}

# ---------- 2. 前端构建（仅生产模式需要 dist） ----------
if (-not $Dev) {
  Section "检查前端构建"
  $distIndex = Join-Path $Frontend "dist\index.html"
  if ($Rebuild -or -not (Test-Path $distIndex)) {
    if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
      Write-Host "安装前端依赖（镜像 $NpmReg）…" -ForegroundColor Yellow
      Push-Location $Frontend
      try { & $NpmCmd install --registry=$NpmReg; if ($LASTEXITCODE -ne 0) { throw "npm install 失败" } }
      finally { Pop-Location }
    }
    Write-Host "构建前端…" -ForegroundColor Yellow
    Push-Location $Frontend
    try { & $NpmCmd run build; if ($LASTEXITCODE -ne 0) { throw "前端构建失败" } }
    finally { Pop-Location }
  } else {
    Write-Host "frontend/dist 已存在，跳过构建（用 -Rebuild 强制重建）。" -ForegroundColor Green
  }
}

# ---------- 3. 启动 ----------
Section "启动 PaperMind"
Push-Location $Backend
try {
  if ($Dev) {
    Write-Host "开发模式：后端 --reload（http://127.0.0.1:$Port）" -ForegroundColor Green
    Write-Host "请另开终端运行：cd frontend; npm run dev  （http://127.0.0.1:5173）" -ForegroundColor Yellow
    & $VenvPy -m uvicorn app.main:create_app --factory --port $Port --reload
  } else {
    Write-Host "生产模式：http://127.0.0.1:$Port  （Ctrl+C 停止）" -ForegroundColor Green
    # 延迟 2.5s 打开浏览器，等 uvicorn 起来
    Start-Process powershell -ArgumentList "-WindowStyle Hidden -Command Start-Sleep -Seconds 2.5; Start-Process 'http://127.0.0.1:$Port'"
    & $VenvPy -m uvicorn app.main:create_app --factory --port $Port
  }
} finally {
  Pop-Location
}
