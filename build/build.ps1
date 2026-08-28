# PaperMind 打包脚本（Windows / PowerShell）
# --------------------------------------------------------------
# 流程：构建前端 dist -> PyInstaller onedir 打包后端 -> dist/PaperMind/PaperMind.exe
# 用法：
#   .\build\build.ps1            # 完整构建
#   .\build\build.ps1 -NoFrontend# 已有 frontend/dist 时跳过前端
#   .\build\build.ps1 -Clean     # 清掉旧打包产物后重建
# 可选环境变量同 start.ps1（PAPERMIND_NPM_REGISTRY 等）。
param(
  [switch]$NoFrontend,
  [switch]$Installer,
  [switch]$Clean
)

$ErrorActionPreference = "Stop"
$env:LITELLM_LOCAL_MODEL_COST_MAP = "True"
$Build    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root     = Split-Path -Parent $Build
$Backend  = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPy   = Join-Path $Backend ".venv\Scripts\python.exe"
$NpmCmd   = "npm.cmd"
$NpmReg   = if ($env:PAPERMIND_NPM_REGISTRY) { $env:PAPERMIND_NPM_REGISTRY } else { "https://registry.npmmirror.com" }

function Section($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }

if (-not (Test-Path $VenvPy)) { throw "未找到后端 venv：$VenvPy。请先运行 .\start.ps1 建立环境。" }

# ---------- 1. 前端 ----------
if (-not $NoFrontend) {
  Section "构建前端"
  $distIndex = Join-Path $Frontend "dist\index.html"
  if ($Clean -or -not (Test-Path $distIndex)) {
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
    Write-Host "frontend/dist 已存在，跳过（用 -Clean 强制重建）。" -ForegroundColor Green
  }
} else {
  if (-not (Test-Path (Join-Path $Frontend "dist\index.html"))) {
    throw "-NoFrontend 但 frontend/dist 不存在；请去掉该参数或先构建前端。"
  }
}

# ---------- 2. PyInstaller ----------
Section "PyInstaller 打包"
$pyiDist = Join-Path $Build "dist"
$pyiWork = Join-Path $Build "build_artifacts"
if ($Clean) {
  if (Test-Path $pyiDist) { Remove-Item -Recurse -Force $pyiDist }
  if (Test-Path $pyiWork) { Remove-Item -Recurse -Force $pyiWork }
}
Push-Location $Build
try {
  & $VenvPy -m PyInstaller papermind.spec --noconfirm --distpath "$pyiDist" --workpath "$pyiWork"
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }
} finally { Pop-Location }

# ---------- 3. 校验 ----------
Section "完成"
$exe = Join-Path $pyiDist "PaperMind\PaperMind.exe"
if (-not (Test-Path $exe)) { throw "未找到产物：$exe" }
Write-Host "打包成功：$exe" -ForegroundColor Green
Write-Host "运行测试：& '$exe'   （Ctrl+C 退出，浏览器自动打开 http://127.0.0.1:4278）" -ForegroundColor Cyan

# ---------- 4. 安装程序（可选）----------
if ($Installer) {
  Section "编译安装程序（Inno Setup）"
  function Find-ISCC {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in @(
      'D:\Inno Setup 6\ISCC.exe',
      (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
      (Join-Path $env:LOCALAPPDATA 'Programs\Inno\ISCC.exe'),
      'C:\Program Files\Inno Setup 6\ISCC.exe',
      'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
    )) { if (Test-Path $c) { return $c } }
    return $null
  }
  $iscc = Find-ISCC
  if (-not $iscc) {
    Write-Host "未找到 ISCC.exe —— 跳过安装程序编译。请安装 Inno Setup 6 后重试。" -ForegroundColor Yellow
    Write-Host "下载：https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
  } else {
    Write-Host "使用 ISCC：$iscc" -ForegroundColor Green
    $iss = Join-Path $Build "installer.iss"
    & $iscc $iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup 编译失败" }
    $setup = Join-Path $Build "installer_output\PaperMind-Setup-0.1.0.exe"
    if (Test-Path $setup) {
      $mb = [math]::Round((Get-Item $setup).Length / 1MB, 2)
      Write-Host "安装程序生成成功：$setup  ($mb MB)" -ForegroundColor Green
    }
  }
}
