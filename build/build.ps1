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
  [switch]$Clean,
  [string]$PythonPath
)

$ErrorActionPreference = "Stop"
$env:LITELLM_LOCAL_MODEL_COST_MAP = "True"
$Build    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root     = Split-Path -Parent $Build
$Backend  = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPy   = if ($PythonPath) { $PythonPath } else { Join-Path $Backend ".venv\Scripts\python.exe" }
$VenvPy   = [IO.Path]::GetFullPath($VenvPy)
$Version  = (Get-Content -LiteralPath (Join-Path $Frontend 'package.json') -Raw | ConvertFrom-Json).version
$NpmCmd   = "npm.cmd"
$NpmReg   = if ($env:PAPERMIND_NPM_REGISTRY) { $env:PAPERMIND_NPM_REGISTRY } else { "https://registry.npmmirror.com" }

function Section($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }

if (-not (Test-Path $VenvPy)) { throw "未找到后端 venv：$VenvPy。请先运行 .\start.ps1 建立环境。" }
if (-not (Test-Path -LiteralPath (Join-Path $Build 'vendor\webview2\msedgewebview2.exe'))) {
  throw "缺少离线桌面运行时。请先准备 build\vendor\webview2（包含 msedgewebview2.exe），再运行打包脚本。此资源目录由 Git 忽略。"
}

# ---------- 1. 前端 ----------
if (-not $NoFrontend) {
  Section "构建前端"
  if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
    Write-Host "安装前端依赖（镜像 $NpmReg）…" -ForegroundColor Yellow
    Push-Location $Frontend
    try { & $NpmCmd ci --registry=$NpmReg; if ($LASTEXITCODE -ne 0) { throw "npm ci 失败" } }
    finally { Pop-Location }
  }
  Write-Host "构建前端…" -ForegroundColor Yellow
  Push-Location $Frontend
  try { & $NpmCmd run build; if ($LASTEXITCODE -ne 0) { throw "前端构建失败" } }
  finally { Pop-Location }
} else {
  if (-not (Test-Path (Join-Path $Frontend "dist\index.html"))) {
    throw "-NoFrontend 但 frontend/dist 不存在；请去掉该参数或先构建前端。"
  }
}

# ---------- 2. PyInstaller ----------
Section "准备离线分词资源"
& $VenvPy (Join-Path $Build 'prepare_tokenizers.py')
if ($LASTEXITCODE -ne 0) { throw "分词资源准备失败。首次构建需要下载并校验公共分词文件，完成后可离线构建。" }

Section "PyInstaller 打包"
$pyiDist = Join-Path $Build "dist"
$pyiWork = Join-Path $Build "build_artifacts"
if ($Clean) {
  foreach ($target in @($pyiDist, $pyiWork)) {
    $resolved = [IO.Path]::GetFullPath($target)
    $buildPrefix = [IO.Path]::GetFullPath($Build).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($buildPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "拒绝清理构建目录外的路径：$resolved" }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
  }
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
Copy-Item -LiteralPath (Join-Path $Root 'restore.ps1') -Destination (Join-Path (Split-Path -Parent $exe) 'restore.ps1') -Force
Copy-Item -LiteralPath (Join-Path $Root 'restore-all.ps1') -Destination (Join-Path (Split-Path -Parent $exe) 'restore-all.ps1') -Force
foreach ($notice in @('README.md', 'THIRD_PARTY_NOTICES.md')) {
  Copy-Item -LiteralPath (Join-Path $Root $notice) -Destination (Join-Path (Split-Path -Parent $exe) $notice) -Force
}
Copy-Item -LiteralPath (Join-Path $Root 'third_party') -Destination (Split-Path -Parent $exe) -Recurse -Force
Write-Host "打包成功：$exe" -ForegroundColor Green
Write-Host "运行测试：& '$exe'   （直接打开桌面窗口，关闭窗口退出）" -ForegroundColor Cyan

# ---------- 4. 安装程序（可选）----------
if ($Installer) {
  Section "编译安装程序（Inno Setup）"
  function Find-ISCC {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in @(
      (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
      (Join-Path $env:LOCALAPPDATA 'Programs\Inno\ISCC.exe'),
      'C:\Program Files\Inno Setup 6\ISCC.exe',
      'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
    )) { if (Test-Path $c) { return $c } }
    return $null
  }
  $iscc = Find-ISCC
  if (-not $iscc) {
    throw "请求了安装包，但未找到 Inno Setup 6 的 ISCC.exe。"
  } else {
    Write-Host "使用 ISCC：$iscc" -ForegroundColor Green
    $iss = Join-Path $Build "installer.iss"
    $compileLog = Join-Path $pyiWork 'installer-stdout.log'
    $compileError = Join-Path $pyiWork 'installer-stderr.log'
    $compiler = Start-Process -FilePath $iscc -ArgumentList @("/DMyAppVersion=$Version", ('"' + $iss + '"')) -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $compileLog -RedirectStandardError $compileError
    Get-Content -LiteralPath $compileLog
    Get-Content -LiteralPath $compileError
    if ($compiler.ExitCode -ne 0) { throw "Inno Setup 编译失败，详见 $compileLog 和 $compileError" }
    $setup = Join-Path $Build "installer_output\PaperMind-Setup-$Version.exe"
    if (-not (Test-Path -LiteralPath $setup)) { throw "未找到安装包：$setup" }
    if (Test-Path $setup) {
      $mb = [math]::Round((Get-Item $setup).Length / 1MB, 2)
      Write-Host "安装程序生成成功：$setup  ($mb MB)" -ForegroundColor Green
    }
  }
}
